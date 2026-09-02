"""
Historical monthly expiry date resolution, for backtesting.

This is deliberately more conservative than app.engine.expiry's live
bootstrap inference. NSE's monthly F&O expiry weekday has changed TWICE in
the ~18 months before this was written:
  - Thursday, for a long time before that
  - Monday, briefly, from ~April 2025
  - Tuesday, from 2025-09-01 onward (SEBI circular
    SEBI/HO/MRD/TPD-1/P/CIR/2025/76), current regime as of this writing

Because of that history, computing a weekday-of-month rule backward
indefinitely is unsafe. So: this module only supports reconstructing expiry
dates within the CURRENT verified regime (Tuesday, from 2025-09-01). Asking
for an earlier month raises UnsupportedHistoricalPeriodError.

The weekday rule is only ever used as a SEARCH STARTING POINT -- the actual
answer is verified against NSE's own bhavcopy: a candidate date is only
accepted once we confirm it is genuinely the minimum listed expiry (i.e. the
nearest/current-month contract) for that symbol on that trading day. This is
a materially stronger check than "was this merely a trading day", which
would still pass on the wrong Tuesday.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.backtest import bhavcopy

CURRENT_REGIME_START = date(2025, 9, 1)  # Tuesday expiry regime begins
CURRENT_REGIME_WEEKDAY = 1  # Monday=0 ... Tuesday=1

_SEARCH_WINDOW_DAYS = 5  # candidate +/- this many days, to absorb holidays


class UnsupportedHistoricalPeriodError(RuntimeError):
    pass


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    if month == 12:
        first_of_next_month = date(year + 1, 1, 1)
    else:
        first_of_next_month = date(year, month + 1, 1)
    last_day = first_of_next_month - timedelta(days=1)
    offset = (last_day.weekday() - weekday) % 7
    return last_day - timedelta(days=offset)


@dataclass(frozen=True)
class MonthlyExpiry:
    calculation_month: str  # "YYYY-MM"
    expiry_date: str  # YYYY-MM-DD, verified as the actual min-listed expiry that day


def resolve_monthly_expiry(symbol: str, year: int, month: int) -> MonthlyExpiry:
    """
    Resolve the monthly expiry date for (year, month), verified against NSE's
    own bhavcopy (the candidate date must itself be the nearest/minimum
    listed expiry for `symbol` that day). Raises
    UnsupportedHistoricalPeriodError if (year, month) predates the verified
    Tuesday-expiry regime, or if no matching expiry day is found within the
    search window (e.g. the symbol wasn't yet F&O-eligible that month).
    """
    candidate = _last_weekday_of_month(year, month, CURRENT_REGIME_WEEKDAY)
    if candidate < CURRENT_REGIME_START:
        raise UnsupportedHistoricalPeriodError(
            f"{year}-{month:02d} predates the verified Tuesday-expiry regime "
            f"(effective {CURRENT_REGIME_START.isoformat()}). NSE's expiry weekday "
            f"changed at least twice before that date and reconstructing it via a "
            f"weekday rule alone is not safe -- this module refuses rather than guess."
        )

    for offset in range(-_SEARCH_WINDOW_DAYS, _SEARCH_WINDOW_DAYS + 1):
        probe = candidate + timedelta(days=offset)
        try:
            df = bhavcopy.get_bhavcopy(probe.isoformat())
        except bhavcopy.BhavcopyUnavailableError:
            continue
        expiries = bhavcopy.get_available_expiries(df, symbol)
        if not expiries:
            continue
        nearest_listed = min(expiries)
        if nearest_listed == probe.isoformat():
            return MonthlyExpiry(
                calculation_month=f"{year:04d}-{month:02d}",
                expiry_date=probe.isoformat(),
            )

    raise UnsupportedHistoricalPeriodError(
        f"Could not verify a monthly expiry for {symbol} in {year}-{month:02d} within "
        f"+/-{_SEARCH_WINDOW_DAYS} days of the expected date {candidate.isoformat()}."
    )


def months_between(start_year: int, start_month: int, end_year: int, end_month: int) -> list[tuple[int, int]]:
    """Inclusive list of (year, month) tuples from start to end, chronological."""
    result = []
    y, m = start_year, start_month
    while (y, m) <= (end_year, end_month):
        result.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return result
