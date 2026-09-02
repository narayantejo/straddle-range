"""
Monthly expiry selection.

NSE stock F&O currently lists only monthly contracts (no weeklies), so the
expiry list returned by DhanHQ for a stock underlying is already a sorted
list of monthly expiry dates >= today.

On (or immediately after) a monthly expiry day, for a given stock:
    expiry_list[0] == the expiry that is/was expiring "now" -> REFERENCE expiry
        (its EOD spot becomes SPOT_LEVEL for the new monthly cycle)
    expiry_list[1] == the next monthly expiry -> PRICING expiry
        (its ATM CE/PE are used for the new monthly cycle's levels)

This module never guesses expiry dates from calendar rules (e.g. "last
Thursday") -- it always defers to the exchange-supplied expiry list, since
NSE's expiry weekday has changed by regulation before and will again.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.data.dhan_client import DhanClient, DhanApiError


class ExpiryResolutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExpiryPair:
    reference_expiry: str  # YYYY-MM-DD, source of SPOT_LEVEL
    pricing_expiry: str  # YYYY-MM-DD, source of ATM CE/PE


def resolve_expiry_pair(
    client: DhanClient, underlying_scrip: int, underlying_seg: str
) -> ExpiryPair:
    """
    Live, event-driven resolution: valid ONLY when called on (or immediately
    after) the reference expiry's own trading day, when that expiry has not
    yet rolled off the exchange's expiry list. This is how the scheduled
    monthly rollover job (Section 31) should call this function.

    Do NOT use this to resolve levels for a cycle that is already mid-month --
    the previous expiry will have already disappeared from the live list. Use
    infer_previous_monthly_expiry() for that (bootstrap-only) case.
    """
    expiries = client.get_expiry_list(underlying_scrip, underlying_seg)
    if len(expiries) < 2:
        raise ExpiryResolutionError(
            f"Need at least 2 upcoming expiries to resolve reference+pricing expiry, "
            f"got {expiries} for underlying_scrip={underlying_scrip}"
        )
    return ExpiryPair(reference_expiry=expiries[0], pricing_expiry=expiries[1])


def is_reference_expiry_today(expiry_pair: ExpiryPair, today: date) -> bool:
    return expiry_pair.reference_expiry == today.isoformat()


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    """weekday: Monday=0 ... Sunday=6. Returns the last calendar occurrence of
    that weekday in the given month (before any trading-holiday adjustment)."""
    if month == 12:
        first_of_next_month = date(year + 1, 1, 1)
    else:
        first_of_next_month = date(year, month + 1, 1)
    last_day = first_of_next_month - timedelta(days=1)
    offset = (last_day.weekday() - weekday) % 7
    return last_day - timedelta(days=offset)


def infer_previous_monthly_expiry(
    client: DhanClient,
    underlying_security_id: int,
    exchange_segment: str,
    instrument: str,
    pricing_expiry: str,
) -> str:
    """
    BOOTSTRAP-ONLY fallback: infers the already-passed monthly expiry date one
    cycle before `pricing_expiry`, using NSE's documented rule (last Tuesday
    of the month, effective 2025-09-01; SEBI circular
    SEBI/HO/MRD/TPD-1/P/CIR/2025/76). The candidate date is then verified
    against actual historical trading data -- if the exchange was closed that
    day (holiday), we walk backward to the nearest real trading day. This
    means the returned date is never a guess about the closing price itself,
    only about which calendar date to query.

    Only use this when the live expiry-list endpoint can no longer supply the
    already-passed reference expiry (i.e., any day after that expiry occurred).
    Prefer resolve_expiry_pair() during the live scheduled rollover.
    """
    pe = date.fromisoformat(pricing_expiry)
    prev_year, prev_month = (pe.year, pe.month - 1) if pe.month > 1 else (pe.year - 1, 12)
    candidate = _last_weekday_of_month(prev_year, prev_month, weekday=1)  # Tuesday

    for _ in range(7):  # walk back through up to a week of holidays
        hist = client.get_historical_daily(
            security_id=underlying_security_id,
            exchange_segment=exchange_segment,
            instrument=instrument,
            from_date=candidate.isoformat(),
            to_date=(candidate + timedelta(days=1)).isoformat(),
        )
        if hist.get("close"):
            return candidate.isoformat()
        candidate -= timedelta(days=1)

    raise ExpiryResolutionError(
        f"Could not find a valid trading day near inferred previous expiry "
        f"for pricing_expiry={pricing_expiry}"
    )
