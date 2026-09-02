"""
Monthly rollover engine.

Computes and permanently stores the fixed monthly S/R levels for one F&O
stock, following the exact procedure in spec Section 3 / Section 31:

  1. Resolve reference expiry (previous monthly expiry) and pricing expiry
     (next monthly expiry) from the exchange's own expiry list.
  2. Get the reference expiry day's EOD spot price -> SPOT_LEVEL.
  3. Select the ATM strike from the pricing expiry's option chain, nearest
     to SPOT_LEVEL.
  4. Read ATM CE / ATM PE premiums from that option chain.
  5. Compute straddle, midpoint, S1/S2/R1/R2, and +/-zone_pct zones via
     app.engine.formulas (the single source of truth for the math).
  6. Store as a new immutable monthly_levels row. Never overwrites a row
     that already exists for (symbol, calculation_month).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from app import config
from app.data.dhan_client import DhanClient, DhanApiError
from app.data.dhan_constants import EXCHANGE_SEGMENT_NSE_EQ, INSTRUMENT_EQUITY
from app.data.universe import FnoStock
from app.db import database as db
from app.engine import formulas
from app.engine.expiry import (
    ExpiryPair,
    ExpiryResolutionError,
    infer_previous_monthly_expiry,
    resolve_expiry_pair,
)


class MonthlyCalculationError(RuntimeError):
    """Raised when a stock's monthly levels cannot be computed -- callers must
    surface this as a DATA ERROR, never silently skip or substitute (Section 41)."""


@dataclass(frozen=True)
class RolloverResult:
    symbol: str
    calculation_month: str
    levels: formulas.MonthlyLevels
    reference_expiry: str
    pricing_expiry: str


def _reference_eod_spot(client: DhanClient, stock: FnoStock, reference_expiry: str) -> float:
    """
    EOD spot close on the reference expiry date. Uses the historical daily
    candle for that exact date (non-inclusive `toDate`, so we request the day
    after to include it).
    """
    ref_date = date.fromisoformat(reference_expiry)
    to_date = date.fromordinal(ref_date.toordinal() + 1).isoformat()
    hist = client.get_historical_daily(
        security_id=stock.equity_security_id,
        exchange_segment=EXCHANGE_SEGMENT_NSE_EQ,
        instrument=INSTRUMENT_EQUITY,
        from_date=reference_expiry,
        to_date=to_date,
    )
    closes = hist.get("close") or []
    if not closes:
        raise MonthlyCalculationError(
            f"{stock.symbol}: no EOD close returned for reference expiry {reference_expiry}"
        )
    return float(closes[-1])


def _calculation_month(pricing_expiry: str) -> str:
    """The monthly cycle these levels govern, labeled by the pricing expiry's
    year-month (e.g. pricing expiry 2026-08-27 -> cycle "2026-08")."""
    return pricing_expiry[:7]


def _resolve_expiry_pair_for_today(
    client: DhanClient, stock: FnoStock, today: date
) -> ExpiryPair:
    """
    If today IS the reference expiry's own trading day, expiry_list[0]/[1]
    give us reference/pricing directly (live path). Otherwise we are mid-cycle
    and the already-passed reference expiry has rolled off the live expiry
    list -- infer it from the documented NSE calendar rule, verified against
    real trading data (bootstrap path). See app.engine.expiry for details.
    """
    expiries = client.get_expiry_list(stock.equity_security_id, EXCHANGE_SEGMENT_NSE_EQ)
    if len(expiries) < 1:
        raise ExpiryResolutionError(f"No expiries returned for {stock.symbol}")

    if expiries[0] == today.isoformat():
        if len(expiries) < 2:
            raise ExpiryResolutionError(
                f"{stock.symbol}: today is expiry day but no next-month expiry is listed"
            )
        return ExpiryPair(reference_expiry=expiries[0], pricing_expiry=expiries[1])

    pricing_expiry = expiries[0]
    reference_expiry = infer_previous_monthly_expiry(
        client,
        stock.equity_security_id,
        EXCHANGE_SEGMENT_NSE_EQ,
        INSTRUMENT_EQUITY,
        pricing_expiry,
    )
    return ExpiryPair(reference_expiry=reference_expiry, pricing_expiry=pricing_expiry)


def run_monthly_rollover(
    client: DhanClient,
    stock: FnoStock,
    zone_pct: float = config.DEFAULT_ZONE_PCT,
    today: date | None = None,
) -> RolloverResult:
    today = today or datetime.now(timezone.utc).date()
    try:
        expiry_pair: ExpiryPair = _resolve_expiry_pair_for_today(client, stock, today)
    except (ExpiryResolutionError, DhanApiError) as e:
        raise MonthlyCalculationError(f"{stock.symbol}: expiry resolution failed: {e}") from e

    calculation_month = _calculation_month(expiry_pair.pricing_expiry)

    existing = db.get_monthly_levels_for_month(stock.symbol, calculation_month)
    if existing is not None:
        raise MonthlyCalculationError(
            f"{stock.symbol}: monthly levels for {calculation_month} already exist "
            f"(id={existing['id']}) -- refusing to overwrite historical levels"
        )

    try:
        spot_level = _reference_eod_spot(client, stock, expiry_pair.reference_expiry)
    except DhanApiError as e:
        raise MonthlyCalculationError(f"{stock.symbol}: failed to fetch reference EOD spot: {e}") from e

    try:
        chain = client.get_option_chain(
            stock.equity_security_id, EXCHANGE_SEGMENT_NSE_EQ, expiry_pair.pricing_expiry
        )
    except DhanApiError as e:
        raise MonthlyCalculationError(f"{stock.symbol}: failed to fetch option chain: {e}") from e

    strikes = chain.get("oc", {})
    if not strikes:
        raise MonthlyCalculationError(
            f"{stock.symbol}: option chain for pricing expiry {expiry_pair.pricing_expiry} is empty"
        )
    available_strikes = [float(k) for k in strikes.keys()]
    atm_strike = formulas.nearest_atm_strike(spot_level, available_strikes)

    # option chain keys are strike prices formatted as e.g. "1290.000000"
    strike_key = next(k for k in strikes.keys() if float(k) == atm_strike)
    strike_data = strikes[strike_key]
    ce_data = strike_data.get("ce") or {}
    pe_data = strike_data.get("pe") or {}
    atm_ce = ce_data.get("last_price")
    atm_pe = pe_data.get("last_price")
    if not atm_ce or not atm_pe:
        raise MonthlyCalculationError(
            f"{stock.symbol}: missing/zero ATM CE or PE at strike {atm_strike} "
            f"(CE={atm_ce}, PE={atm_pe})"
        )

    try:
        levels = formulas.compute_monthly_levels(
            spot_level=spot_level,
            atm_strike=atm_strike,
            atm_ce=float(atm_ce),
            atm_pe=float(atm_pe),
            zone_pct=zone_pct,
        )
    except formulas.InvalidMarketDataError as e:
        raise MonthlyCalculationError(f"{stock.symbol}: {e}") from e

    row = db.MonthlyLevelRow(
        symbol=stock.symbol,
        company_name=stock.company_name,
        calculation_month=calculation_month,
        reference_expiry_date=expiry_pair.reference_expiry,
        reference_spot_price=levels.spot_level,
        pricing_expiry_date=expiry_pair.pricing_expiry,
        atm_strike=levels.atm_strike,
        atm_ce=levels.atm_ce,
        atm_pe=levels.atm_pe,
        straddle_value=levels.straddle,
        midpoint=levels.midpoint,
        s2=levels.s2,
        s1=levels.s1,
        r1=levels.r1,
        r2=levels.r2,
        s2_lower_zone=levels.s2_zone.lower,
        s2_upper_zone=levels.s2_zone.upper,
        s1_lower_zone=levels.s1_zone.lower,
        s1_upper_zone=levels.s1_zone.upper,
        r1_lower_zone=levels.r1_zone.lower,
        r1_upper_zone=levels.r1_zone.upper,
        r2_lower_zone=levels.r2_zone.lower,
        r2_upper_zone=levels.r2_zone.upper,
        zone_pct=zone_pct,
        calculation_timestamp=db.now_iso(),
        data_source="DhanHQ",
    )
    db.insert_monthly_levels(row)

    return RolloverResult(
        symbol=stock.symbol,
        calculation_month=calculation_month,
        levels=levels,
        reference_expiry=expiry_pair.reference_expiry,
        pricing_expiry=expiry_pair.pricing_expiry,
    )


def needs_rollover(stock: FnoStock, today: date) -> bool:
    """True if there is no monthly_levels row yet covering `today`."""
    latest = db.get_latest_monthly_levels(stock.symbol)
    if latest is None:
        return True
    return today.isoformat() >= latest["pricing_expiry_date"]
