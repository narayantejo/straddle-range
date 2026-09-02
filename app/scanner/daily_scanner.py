"""
Daily proximity + reaction scanner.

For every stock with an active monthly_levels row, fetches current spot,
equity volume, and near-month futures OI/volume (two batched quote calls,
regardless of universe size), then computes per level (S2/S1/R1/R2):
  - distance (abs/signed/pct)
  - zone status (FAR/APPROACHING/VERY_CLOSE/INSIDE_ZONE/TOUCH)
  - breakout/breakdown confirmation (configurable)
  - reaction (adds BOUNCE/REJECTED/BREAKOUT/BREAKDOWN on top of zone status)
  - signal score (0-100) and signal type

Direction and "consecutive closes" confirmation use OUR OWN accumulated
daily_scans history (prior scan spot values) rather than extra per-stock
historical-data API calls -- this scales the scan to the whole 210-stock
universe in ~2 batched requests instead of 200+ throttled ones, and matches
the spec's own daily-scan-history design (Section 33). Trend/confirmation
quality improves as more days of scan history accumulate; on day one there
simply isn't history yet, so direction defaults to SIDEWAYS and
consecutive-closes confirmation can't fire (this is a data-availability
limit, not a bug -- classify_direction/evaluate_confirmation both handle it
by degrading gracefully rather than guessing).

Does NOT recompute monthly S/R levels -- those stay fixed until the next
monthly rollover (spec Rule 15/16).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from sqlite3 import Row

from app import config
from app.data.dhan_client import DhanClient, DhanApiError
from app.data.dhan_constants import EXCHANGE_SEGMENT_NSE_EQ, EXCHANGE_SEGMENT_NSE_FNO
from app.data.universe import FnoStock
from app.db import database as db
from app.engine import formulas
from app.engine.confirmation import ConfirmationConfig, ConfirmationInputs, evaluate_confirmation
from app.engine.direction import classify_direction
from app.engine.reaction import RESISTANCE_LEVELS, SUPPORT_LEVELS, classify_reaction
from app.engine.signal_scoring import compute_signal_score

_LEVEL_NAMES = ("s2", "s1", "r1", "r2")
# CE/PE watch (spec Section 28) fires on real engagement with the level, not
# merely being within the (wide, ~10%) APPROACHING band -- that band alone
# would flag nearly every stock's both sides simultaneously and add no signal.
_ENGAGED_STATUSES = frozenset(
    {
        formulas.ZONE_STATUS_VERY_CLOSE,
        formulas.ZONE_STATUS_INSIDE_ZONE,
        formulas.ZONE_STATUS_TOUCH,
        "BOUNCE",
        "REJECTED",
    }
)

SCAN_HISTORY_LOOKBACK = 10  # prior scans used for direction / consecutive-close / avg-volume


@dataclass(frozen=True)
class ScanResult:
    symbol: str
    spot: float
    nearest_support: str | None
    nearest_support_distance_pct: float | None
    nearest_resistance: str | None
    nearest_resistance_distance_pct: float | None
    absolute_nearest_level: str
    absolute_nearest_level_distance_pct: float
    signal_type: str
    signal_score: float
    signal_level: str
    ce_watch: bool
    pe_watch: bool


def _nearest(levels: dict[str, float], names: tuple[str, ...], spot: float) -> tuple[str, float]:
    best_name, best_dist = None, None
    for name in names:
        d = formulas.compute_distance(spot, levels[name])
        if best_dist is None or d.abs_distance_pct < best_dist:
            best_name, best_dist = name, d.abs_distance_pct
    return best_name, best_dist


def scan_stock(
    stock: FnoStock,
    monthly_row: Row,
    spot: float,
    confirmation_config: ConfirmationConfig,
    current_volume: float | None = None,
    current_futures_oi: float | None = None,
    prior_scans: list[Row] | None = None,
) -> tuple[ScanResult, db.DailyScanRow]:
    prior_scans = prior_scans or []  # most-recent-first, from db.get_scan_history

    levels = {
        "s2": monthly_row["s2"],
        "s1": monthly_row["s1"],
        "r1": monthly_row["r1"],
        "r2": monthly_row["r2"],
    }
    zones = {
        "s2": formulas.ZoneBand(monthly_row["s2_lower_zone"], monthly_row["s2_upper_zone"]),
        "s1": formulas.ZoneBand(monthly_row["s1_lower_zone"], monthly_row["s1_upper_zone"]),
        "r1": formulas.ZoneBand(monthly_row["r1_lower_zone"], monthly_row["r1_upper_zone"]),
        "r2": formulas.ZoneBand(monthly_row["r2_lower_zone"], monthly_row["r2_upper_zone"]),
    }

    prior_spots = [row["spot"] for row in reversed(prior_scans[:SCAN_HISTORY_LOOKBACK]) if row["spot"] is not None]
    direction = classify_direction(prior_spots, spot)

    prior_volumes = [row["volume"] for row in prior_scans[:SCAN_HISTORY_LOOKBACK] if row["volume"]]
    average_volume = (sum(prior_volumes) / len(prior_volumes)) if prior_volumes else None
    volume_ratio = (current_volume / average_volume) if (current_volume and average_volume) else None

    previous_oi = prior_scans[0]["futures_oi"] if prior_scans and prior_scans[0]["futures_oi"] else None
    oi_change_pct = None
    if current_futures_oi is not None and previous_oi:
        oi_change_pct = ((current_futures_oi - previous_oi) / previous_oi) * 100

    distances = {name: formulas.compute_distance(spot, levels[name]) for name in _LEVEL_NAMES}
    zone_status = {
        name: formulas.classify_zone_status(
            spot,
            levels[name],
            zones[name],
            approach_threshold_pct=config.DEFAULT_APPROACH_THRESHOLD_PCT,
            very_close_threshold_pct=config.DEFAULT_VERY_CLOSE_THRESHOLD_PCT,
            touch_threshold_pct=config.DEFAULT_TOUCH_THRESHOLD_PCT,
        )
        for name in _LEVEL_NAMES
    }

    reactions: dict[str, str] = {}
    scores: dict[str, tuple[float, str]] = {}
    for name in _LEVEL_NAMES:
        level_type = name.upper()
        is_resistance = level_type in RESISTANCE_LEVELS
        conf_inputs = ConfirmationInputs(
            level=levels[name],
            direction_is_up=is_resistance,
            latest_close=spot,
            recent_closes=prior_spots,
            current_volume=current_volume,
            average_volume=average_volume,
            current_oi=current_futures_oi,
            previous_oi=previous_oi,
        )
        confirmation = evaluate_confirmation(confirmation_config, conf_inputs)
        reaction = classify_reaction(level_type, zone_status[name], direction, confirmation)
        reactions[name] = reaction

        oi_confirming = None
        if confirmation_config.require_oi_confirmation and oi_change_pct is not None:
            oi_confirming = confirmation.checks.get("futures_oi")

        signal = compute_signal_score(
            level_type,
            distances[name].abs_distance_pct,
            zone_status[name],
            reaction,
            direction,
            volume_ratio=volume_ratio,
            oi_confirming=oi_confirming,
        )
        scores[name] = (signal.score, signal.signal_type)

    best_level = max(scores, key=lambda n: scores[n][0])
    best_score, best_signal_type = scores[best_level]

    nearest_support_name, nearest_support_dist = _nearest(levels, ("s1", "s2"), spot)
    nearest_resistance_name, nearest_resistance_dist = _nearest(levels, ("r1", "r2"), spot)
    abs_nearest_name, abs_nearest_dist = _nearest(levels, _LEVEL_NAMES, spot)

    ce_watch = any(reactions[n] in _ENGAGED_STATUSES for n in ("s1", "s2"))
    pe_watch = any(reactions[n] in _ENGAGED_STATUSES for n in ("r1", "r2"))

    now = datetime.now(timezone.utc)
    row = db.DailyScanRow(
        monthly_level_id=monthly_row["id"],
        symbol=stock.symbol,
        scan_date=now.date().isoformat(),
        scan_timestamp=now.isoformat(),
        spot=spot,
        futures_price=None,
        volume=current_volume,
        volume_change_pct=(
            ((current_volume - prior_scans[0]["volume"]) / prior_scans[0]["volume"] * 100)
            if current_volume and prior_scans and prior_scans[0]["volume"]
            else None
        ),
        futures_oi=current_futures_oi,
        futures_oi_change_pct=oi_change_pct,
        distance_s2=distances["s2"].signed_distance,
        distance_s1=distances["s1"].signed_distance,
        distance_r1=distances["r1"].signed_distance,
        distance_r2=distances["r2"].signed_distance,
        distance_pct_s2=distances["s2"].distance_pct,
        distance_pct_s1=distances["s1"].distance_pct,
        distance_pct_r1=distances["r1"].distance_pct,
        distance_pct_r2=distances["r2"].distance_pct,
        zone_status_s2=zone_status["s2"],
        zone_status_s1=zone_status["s1"],
        zone_status_r1=zone_status["r1"],
        zone_status_r2=zone_status["r2"],
        reaction_s2=reactions["s2"],
        reaction_s1=reactions["s1"],
        reaction_r1=reactions["r1"],
        reaction_r2=reactions["r2"],
        nearest_support=nearest_support_name.upper(),
        nearest_support_distance_pct=nearest_support_dist,
        nearest_resistance=nearest_resistance_name.upper(),
        nearest_resistance_distance_pct=nearest_resistance_dist,
        absolute_nearest_level=abs_nearest_name.upper(),
        absolute_nearest_level_distance_pct=abs_nearest_dist,
        direction=direction,
        signal_type=best_signal_type,
        signal_score=best_score,
        signal_level=best_level.upper(),
        ce_watch=1 if ce_watch else 0,
        pe_watch=1 if pe_watch else 0,
    )

    result = ScanResult(
        symbol=stock.symbol,
        spot=spot,
        nearest_support=nearest_support_name.upper(),
        nearest_support_distance_pct=nearest_support_dist,
        nearest_resistance=nearest_resistance_name.upper(),
        nearest_resistance_distance_pct=nearest_resistance_dist,
        absolute_nearest_level=abs_nearest_name.upper(),
        absolute_nearest_level_distance_pct=abs_nearest_dist,
        signal_type=best_signal_type,
        signal_score=best_score,
        signal_level=best_level.upper(),
        ce_watch=ce_watch,
        pe_watch=pe_watch,
    )
    return result, row


def scan_all(
    client: DhanClient,
    stocks: list[FnoStock],
    confirmation_config: ConfirmationConfig | None = None,
) -> tuple[list[ScanResult], list[str]]:
    """Batch-scans every stock that has an active monthly_levels row.
    Fetches equity quotes (spot+volume) and futures quotes (OI+volume) in
    batched requests (up to 1000 ids per DhanHQ limits). Returns (results, errors)."""
    confirmation_config = confirmation_config or ConfirmationConfig()
    by_symbol = {s.symbol: s for s in stocks}
    latest_levels = {row["symbol"]: row for row in db.get_all_latest_monthly_levels()}

    scoped_stocks = [s for s in stocks if s.symbol in latest_levels]
    if not scoped_stocks:
        return [], ["No stocks have monthly levels yet -- run the monthly rollover first."]

    errors: list[str] = []
    results: list[ScanResult] = []

    eq_ids = [s.equity_security_id for s in scoped_stocks]
    id_to_stock = {s.equity_security_id: s for s in scoped_stocks}

    eq_quote_data: dict[str, dict] = {}
    for batch_start in range(0, len(eq_ids), 1000):
        batch_ids = eq_ids[batch_start : batch_start + 1000]
        try:
            resp = client.get_quote({EXCHANGE_SEGMENT_NSE_EQ: batch_ids})
            eq_quote_data.update(resp.get(EXCHANGE_SEGMENT_NSE_EQ, {}))
        except DhanApiError as e:
            errors.append(f"Equity quote batch fetch failed: {e}")

    fut_ids = [s.near_future_security_id for s in scoped_stocks if s.near_future_security_id]
    fut_id_to_symbol = {
        s.near_future_security_id: s.symbol for s in scoped_stocks if s.near_future_security_id
    }
    fut_quote_data: dict[str, dict] = {}
    for batch_start in range(0, len(fut_ids), 1000):
        batch_ids = fut_ids[batch_start : batch_start + 1000]
        try:
            resp = client.get_quote({EXCHANGE_SEGMENT_NSE_FNO: batch_ids})
            fut_quote_data.update(resp.get(EXCHANGE_SEGMENT_NSE_FNO, {}))
        except DhanApiError as e:
            errors.append(f"Futures quote batch fetch failed: {e}")

    for stock in scoped_stocks:
        symbol = stock.symbol
        eq_entry = eq_quote_data.get(str(stock.equity_security_id))
        if not eq_entry or "last_price" not in eq_entry:
            errors.append(f"{symbol}: DATA ERROR -- no quote returned")
            continue
        spot = float(eq_entry["last_price"])
        if spot <= 0:
            errors.append(f"{symbol}: DATA ERROR -- non-positive spot {spot}")
            continue
        current_volume = eq_entry.get("volume")

        current_futures_oi = None
        if stock.near_future_security_id:
            fut_entry = fut_quote_data.get(str(stock.near_future_security_id))
            if fut_entry:
                current_futures_oi = fut_entry.get("oi")

        try:
            prior_scans = db.get_scan_history(symbol, limit=SCAN_HISTORY_LOOKBACK)
            result, row = scan_stock(
                by_symbol[symbol],
                latest_levels[symbol],
                spot,
                confirmation_config,
                current_volume=current_volume,
                current_futures_oi=current_futures_oi,
                prior_scans=prior_scans,
            )
            db.insert_daily_scan(row)
            results.append(result)
        except Exception as e:  # noqa: BLE001 -- surface as scan error, keep scanning others
            errors.append(f"{symbol}: scan failed: {e}")

    return results, errors
