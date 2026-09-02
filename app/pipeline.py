"""High-level orchestration used by both the CLI scripts and the Streamlit app."""
from __future__ import annotations

from datetime import date

from app import config
from app.alerts.engine import FiredAlert, evaluate_scan_rows
from app.data.dhan_client import DhanClient
from app.data.universe import FnoStock, get_fno_universe
from app.db import database as db
from app.engine.confirmation import ConfirmationConfig
from app.engine.monthly_engine import MonthlyCalculationError, needs_rollover, run_monthly_rollover
from app.scanner.daily_scanner import ScanResult, scan_all


def run_universe_rollover(
    client: DhanClient,
    stocks: list[FnoStock] | None = None,
    zone_pct: float = config.DEFAULT_ZONE_PCT,
    force_all: bool = False,
    progress_cb=None,
) -> tuple[list[str], list[str]]:
    """
    Runs the monthly rollover for every stock that needs it (or all stocks if
    force_all=True). Returns (succeeded_symbols, error_messages).
    progress_cb(done, total, symbol) is called after each stock if provided.
    """
    stocks = stocks or get_fno_universe()
    today = date.today()
    succeeded: list[str] = []
    errors: list[str] = []

    targets = stocks if force_all else [s for s in stocks if needs_rollover(s, today)]

    for i, stock in enumerate(targets, start=1):
        try:
            run_monthly_rollover(client, stock, zone_pct=zone_pct, today=today)
            succeeded.append(stock.symbol)
        except MonthlyCalculationError as e:
            errors.append(str(e))
        if progress_cb:
            progress_cb(i, len(targets), stock.symbol)

    return succeeded, errors


def run_universe_daily_scan(
    client: DhanClient,
    stocks: list[FnoStock] | None = None,
    confirmation_config: ConfirmationConfig | None = None,
) -> tuple[list[ScanResult], list[str], list[FiredAlert]]:
    """Scans the universe, persists results, then evaluates alert rules
    against what was just scanned. Returns (results, scan_errors, fired_alerts)."""
    stocks = stocks or get_fno_universe()
    results, errors = scan_all(client, stocks, confirmation_config=confirmation_config)

    scanned_symbols = {r.symbol for r in results}
    fresh_rows = [
        row for row in db.get_latest_scan_all_symbols() if row["symbol"] in scanned_symbols
    ]
    daily_scan_rows = [_row_to_dataclass(row) for row in fresh_rows]
    fired_alerts = evaluate_scan_rows(daily_scan_rows)

    return results, errors, fired_alerts


def _row_to_dataclass(row) -> db.DailyScanRow:
    keys = {k for k in row.keys() if k not in ("id",)}
    return db.DailyScanRow(**{k: row[k] for k in keys})


def get_dashboard_rows() -> list[dict]:
    """Joins the latest monthly levels with the latest daily scan per symbol
    for display in the main dashboard table."""
    monthly_by_symbol = {row["symbol"]: row for row in db.get_all_latest_monthly_levels()}
    scan_by_symbol = {row["symbol"]: row for row in db.get_latest_scan_all_symbols()}

    rows = []
    for symbol, ml in monthly_by_symbol.items():
        scan = scan_by_symbol.get(symbol)
        rows.append(
            {
                "Symbol": symbol,
                "Company": ml["company_name"],
                "Spot": scan["spot"] if scan else None,
                "S2": ml["s2"],
                "S1": ml["s1"],
                "R1": ml["r1"],
                "R2": ml["r2"],
                "Nearest Support": scan["nearest_support"] if scan else None,
                "Dist % (Support)": scan["nearest_support_distance_pct"] if scan else None,
                "Nearest Resistance": scan["nearest_resistance"] if scan else None,
                "Dist % (Resistance)": scan["nearest_resistance_distance_pct"] if scan else None,
                "Nearest Level": scan["absolute_nearest_level"] if scan else None,
                "Dist %": scan["absolute_nearest_level_distance_pct"] if scan else None,
                "Zone (Nearest)": _zone_status_for_nearest(scan) if scan else None,
                "Direction": scan["direction"] if scan else None,
                "Signal Type": scan["signal_type"] if scan else None,
                "Signal Score": scan["signal_score"] if scan else None,
                "Signal Level": scan["signal_level"] if scan else None,
                "Reaction S2": scan["reaction_s2"] if scan else None,
                "Reaction S1": scan["reaction_s1"] if scan else None,
                "Reaction R1": scan["reaction_r1"] if scan else None,
                "Reaction R2": scan["reaction_r2"] if scan else None,
                "CE Watch": bool(scan["ce_watch"]) if scan else False,
                "PE Watch": bool(scan["pe_watch"]) if scan else False,
                "Volume": scan["volume"] if scan else None,
                "Volume Chg %": scan["volume_change_pct"] if scan else None,
                "Futures OI": scan["futures_oi"] if scan else None,
                "Futures OI Chg %": scan["futures_oi_change_pct"] if scan else None,
                "Reference Expiry": ml["reference_expiry_date"],
                "Pricing Expiry": ml["pricing_expiry_date"],
                "ATM Strike": ml["atm_strike"],
                "ATM CE": ml["atm_ce"],
                "ATM PE": ml["atm_pe"],
                "Straddle": ml["straddle_value"],
                "Midpoint": ml["midpoint"],
                "Last Scan": scan["scan_timestamp"] if scan else None,
            }
        )
    return rows


def _zone_status_for_nearest(scan) -> str | None:
    nearest = scan["absolute_nearest_level"]
    if not nearest:
        return None
    return scan[f"zone_status_{nearest.lower()}"]
