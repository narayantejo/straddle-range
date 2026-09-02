"""
Reconstructs past monthly S1/S2/R1/R2 cycles for backtesting, with strict
no-look-ahead: for calculation_month M, only information dated on or before
that cycle's reference expiry is ever used (spec Section 35, Rule 19-20).

Sourced entirely from NSE's own bhavcopy (app.backtest.bhavcopy) -- chosen
over DhanHQ's /charts/rollingoption endpoint after finding that endpoint too
slow (~30s/query) and unreliable (frequent 504s/empty responses) to build a
historical dataset from. Bhavcopy gives every stock's every strike for a
whole trading day in a single ~7s download (cached after first use), plus
real volume/OI/transaction-count fields to distinguish a genuinely-traded
closing price from a stale carried-forward one.

Reuses app.engine.formulas and app.engine.formulas.nearest_atm_strike -- the
exact same calculation/selection code path as the live rollover -- so a
backtested level is computed identically to how a live one would have been,
just fed historical instead of live inputs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from app.backtest import bhavcopy
from app.backtest.expiry_calendar import (
    MonthlyExpiry,
    UnsupportedHistoricalPeriodError,
    resolve_monthly_expiry,
)
from app.engine import formulas
from app.engine.adaptive_zone import compute_adaptive_zone_pct

DEFAULT_PLAUSIBLE_STRADDLE_BAND = (0.01, 0.30)  # 1%..30% of spot, sanity net


class HistoricalDataError(RuntimeError):
    """Raised when historical inputs are missing, invalid, or fail plausibility
    checks -- callers must treat this as a DATA ERROR for that cycle, never
    silently skip or substitute (spec Section 41, extended to backtesting)."""


@dataclass(frozen=True)
class HistoricalCycle:
    symbol: str
    calculation_month: str
    reference_expiry: str
    pricing_expiry: str
    levels: formulas.MonthlyLevels
    ce_volume: int
    pe_volume: int


def reconstruct_monthly_cycle(
    symbol: str,
    year: int,
    month: int,
    zone_pct: float = 0.05,
    plausible_straddle_band: tuple[float, float] = DEFAULT_PLAUSIBLE_STRADDLE_BAND,
    require_traded_volume: bool = True,
    adaptive_zone: bool = True,
) -> HistoricalCycle:
    """
    Reconstructs the monthly S/R levels that WOULD have been calculated at
    the start of (year, month)'s cycle, using only NSE bhavcopy data dated
    on the cycle's reference expiry -- never the following month's data.

    require_traded_volume: if True (default), refuse to use an ATM CE/PE
    closing price that has zero traded volume that day -- NSE's bhavcopy
    carries forward the previous close for untraded contracts, which is not
    a fresh price and would silently corrupt the level calculation.

    zone_pct is the BASE zone% (spec Section 11's configurable default).
    adaptive_zone=True (default) scales it by this cycle's straddle relative
    to spot, matching the live rollover's methodology -- see
    app.engine.adaptive_zone. Set False to use zone_pct literally, matching
    the spec's flat definition exactly.
    """
    next_year, next_month = (year, month + 1) if month < 12 else (year + 1, 1)
    try:
        reference: MonthlyExpiry = resolve_monthly_expiry(symbol, year, month)
        pricing: MonthlyExpiry = resolve_monthly_expiry(symbol, next_year, next_month)
    except UnsupportedHistoricalPeriodError as e:
        # Most commonly: the pricing month's expiry hasn't happened yet, so no
        # bhavcopy exists for it to verify against -- that's the "not yet
        # complete" case below, just discovered a different way. Re-raise as
        # HistoricalDataError so every caller of this function only needs to
        # catch one exception type for "this cycle isn't reconstructable".
        raise HistoricalDataError(f"{symbol}: {e}") from e

    today = datetime.now(timezone.utc).date()
    if date.fromisoformat(pricing.expiry_date) >= today:
        raise HistoricalDataError(
            f"{symbol}: cycle {year}-{month:02d} is not yet complete -- its pricing "
            f"expiry {pricing.expiry_date} hasn't happened yet (today is {today.isoformat()}). "
            f"This is the currently-active live cycle, not a backtestable one."
        )

    try:
        df = bhavcopy.get_bhavcopy(reference.expiry_date)
    except bhavcopy.BhavcopyUnavailableError as e:
        raise HistoricalDataError(f"{symbol}: {e}") from e

    spot_level = bhavcopy.get_underlying_price(df, symbol)
    if not spot_level:
        raise HistoricalDataError(f"{symbol}: no underlying price in bhavcopy for {reference.expiry_date}")

    strikes = bhavcopy.get_available_strikes(df, symbol, pricing.expiry_date, "CE")
    if not strikes:
        raise HistoricalDataError(
            f"{symbol}: no strikes listed for pricing expiry {pricing.expiry_date} "
            f"in the {reference.expiry_date} bhavcopy"
        )
    atm_strike = formulas.nearest_atm_strike(spot_level, strikes)

    ce_row = bhavcopy.get_option_row(df, symbol, pricing.expiry_date, atm_strike, "CE")
    pe_row = bhavcopy.get_option_row(df, symbol, pricing.expiry_date, atm_strike, "PE")
    if not ce_row or not pe_row:
        raise HistoricalDataError(
            f"{symbol}: missing CE/PE row at strike {atm_strike}, expiry {pricing.expiry_date}"
        )

    if require_traded_volume and (not ce_row["TtlTradgVol"] or not pe_row["TtlTradgVol"]):
        raise HistoricalDataError(
            f"{symbol} {reference.expiry_date}: ATM strike {atm_strike} had zero traded "
            f"volume on CE and/or PE -- the closing price is a stale carry-forward, not a "
            f"fresh quote. Refusing to use it (require_traded_volume=True)."
        )

    atm_ce = float(ce_row["ClsPric"])
    atm_pe = float(pe_row["ClsPric"])

    straddle = atm_ce + atm_pe
    straddle_pct_of_spot = straddle / spot_level if spot_level else 0
    lo, hi = plausible_straddle_band
    if not (lo <= straddle_pct_of_spot <= hi):
        raise HistoricalDataError(
            f"{symbol} {reference.expiry_date}: straddle {straddle:.2f} is "
            f"{straddle_pct_of_spot*100:.2f}% of spot {spot_level:.2f}, outside the "
            f"plausible band [{lo*100:.0f}%, {hi*100:.0f}%]."
        )

    effective_zone_pct = zone_pct
    if adaptive_zone:
        effective_zone_pct = compute_adaptive_zone_pct(
            straddle=straddle, spot_level=spot_level, base_zone_pct=zone_pct
        )

    levels = formulas.compute_monthly_levels(
        spot_level=spot_level,
        atm_strike=atm_strike,
        atm_ce=atm_ce,
        atm_pe=atm_pe,
        zone_pct=effective_zone_pct,
    )

    return HistoricalCycle(
        symbol=symbol,
        calculation_month=f"{next_year:04d}-{next_month:02d}",
        reference_expiry=reference.expiry_date,
        pricing_expiry=pricing.expiry_date,
        levels=levels,
        ce_volume=int(ce_row["TtlTradgVol"]),
        pe_volume=int(pe_row["TtlTradgVol"]),
    )
