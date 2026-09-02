import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import date

import pytest

from app.backtest.expiry_calendar import (
    CURRENT_REGIME_START,
    UnsupportedHistoricalPeriodError,
    _last_weekday_of_month,
    months_between,
    resolve_monthly_expiry,
)


def test_last_weekday_of_month_tuesday():
    # August 2026: last Tuesday
    d = _last_weekday_of_month(2026, 8, weekday=1)
    assert d.weekday() == 1
    assert d.month == 8
    assert d.year == 2026
    # must be the LAST occurrence, i.e. within 7 days of month end
    import calendar
    last_day_of_month = calendar.monthrange(2026, 8)[1]
    assert (last_day_of_month - d.day) < 7


def test_last_weekday_of_month_december_rollover():
    d = _last_weekday_of_month(2025, 12, weekday=1)
    assert d.month == 12
    assert d.year == 2025


def test_pre_regime_month_rejected_without_network():
    with pytest.raises(UnsupportedHistoricalPeriodError):
        resolve_monthly_expiry("RELIANCE", 2025, 6)  # well before 2025-09 regime start


def test_regime_start_boundary_month_rejected():
    # August 2025 predates the regime start (2025-09-01)
    with pytest.raises(UnsupportedHistoricalPeriodError):
        resolve_monthly_expiry("RELIANCE", 2025, 8)


def test_months_between_single_month():
    assert months_between(2026, 3, 2026, 3) == [(2026, 3)]


def test_months_between_spans_year_boundary():
    result = months_between(2025, 11, 2026, 2)
    assert result == [(2025, 11), (2025, 12), (2026, 1), (2026, 2)]


def test_current_regime_start_date():
    # Effective date of the SEBI circular (SEBI/HO/MRD/TPD-1/P/CIR/2025/76);
    # the regime START date itself need not fall on a Tuesday.
    assert CURRENT_REGIME_START == date(2025, 9, 1)
