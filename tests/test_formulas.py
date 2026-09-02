import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.engine.formulas import (
    InvalidMarketDataError,
    classify_zone_status,
    compute_distance,
    compute_monthly_levels,
    nearest_atm_strike,
    ZONE_STATUS_APPROACHING,
    ZONE_STATUS_FAR,
    ZONE_STATUS_INSIDE_ZONE,
    ZONE_STATUS_TOUCH,
    ZONE_STATUS_VERY_CLOSE,
)

SPOT = 1250.0
ATM_STRIKE = 1250.0
ATM_CE = 80.0
ATM_PE = 70.0


def test_spec_example_full_structure():
    levels = compute_monthly_levels(SPOT, ATM_STRIKE, ATM_CE, ATM_PE, zone_pct=0.05)
    assert levels.straddle == pytest.approx(150.0)
    assert levels.midpoint == pytest.approx(75.0)
    assert levels.r1 == pytest.approx(1330.0)
    assert levels.r2 == pytest.approx(1400.0)
    assert levels.s1 == pytest.approx(1180.0)
    assert levels.s2 == pytest.approx(1100.0)


def test_mandatory_s1_uses_atm_pe_not_atm_ce():
    """
    RULE 25 / Section 52: S1 = SPOT_LEVEL - ATM_PE.
    This test must fail if S1 is computed as SPOT - ATM_CE (which would give 1170,
    not 1180).
    """
    levels = compute_monthly_levels(SPOT, ATM_STRIKE, ATM_CE, ATM_PE)
    assert levels.s1 == pytest.approx(1180.0)
    assert levels.s1 != pytest.approx(1170.0)


def test_straddle_calculation():
    levels = compute_monthly_levels(SPOT, ATM_STRIKE, ATM_CE, ATM_PE)
    assert levels.straddle == pytest.approx(ATM_CE + ATM_PE)


def test_midpoint_calculation():
    levels = compute_monthly_levels(SPOT, ATM_STRIKE, ATM_CE, ATM_PE)
    assert levels.midpoint == pytest.approx((ATM_CE + ATM_PE) / 2)


def test_r1_calculation():
    levels = compute_monthly_levels(SPOT, ATM_STRIKE, ATM_CE, ATM_PE)
    assert levels.r1 == pytest.approx(SPOT + ATM_CE)


def test_r2_calculation():
    levels = compute_monthly_levels(SPOT, ATM_STRIKE, ATM_CE, ATM_PE)
    assert levels.r2 == pytest.approx(SPOT + ATM_CE + ATM_PE)


def test_s2_calculation():
    levels = compute_monthly_levels(SPOT, ATM_STRIKE, ATM_CE, ATM_PE)
    assert levels.s2 == pytest.approx(SPOT - ATM_CE - ATM_PE)


def test_level_ordering_enforced():
    levels = compute_monthly_levels(SPOT, ATM_STRIKE, ATM_CE, ATM_PE)
    assert levels.s2 < levels.s1 < levels.spot_level < levels.r1 < levels.r2


def test_s1_zone_5pct():
    levels = compute_monthly_levels(SPOT, ATM_STRIKE, ATM_CE, ATM_PE, zone_pct=0.05)
    assert levels.s1_zone.lower == pytest.approx(1121.0)
    assert levels.s1_zone.upper == pytest.approx(1239.0)


def test_s2_zone_5pct():
    levels = compute_monthly_levels(SPOT, ATM_STRIKE, ATM_CE, ATM_PE, zone_pct=0.05)
    assert levels.s2_zone.lower == pytest.approx(1045.0)
    assert levels.s2_zone.upper == pytest.approx(1155.0)


def test_r1_zone_5pct():
    levels = compute_monthly_levels(SPOT, ATM_STRIKE, ATM_CE, ATM_PE, zone_pct=0.05)
    assert levels.r1_zone.lower == pytest.approx(1263.5)
    assert levels.r1_zone.upper == pytest.approx(1396.5)


def test_r2_zone_5pct():
    levels = compute_monthly_levels(SPOT, ATM_STRIKE, ATM_CE, ATM_PE, zone_pct=0.05)
    assert levels.r2_zone.lower == pytest.approx(1330.0)
    assert levels.r2_zone.upper == pytest.approx(1470.0)


def test_zone_pct_configurable():
    levels = compute_monthly_levels(SPOT, ATM_STRIKE, ATM_CE, ATM_PE, zone_pct=0.02)
    assert levels.r1_zone.lower == pytest.approx(1330.0 * 0.98)
    assert levels.r1_zone.upper == pytest.approx(1330.0 * 1.02)


@pytest.mark.parametrize(
    "spot,atm_strike,atm_ce,atm_pe",
    [
        (None, 1250, 80, 70),
        (1250, 1250, None, 70),
        (1250, 1250, 80, None),
        (0, 1250, 80, 70),
        (1250, 1250, -80, 70),
        (1250, 1250, 80, 0),
    ],
)
def test_invalid_market_data_rejected(spot, atm_strike, atm_ce, atm_pe):
    with pytest.raises(InvalidMarketDataError):
        compute_monthly_levels(spot, atm_strike, atm_ce, atm_pe)


def test_nearest_atm_strike_exact_match():
    assert nearest_atm_strike(1250, [1200, 1250, 1300]) == 1250


def test_nearest_atm_strike_closest():
    assert nearest_atm_strike(1258, [1200, 1250, 1300]) == 1250
    assert nearest_atm_strike(1280, [1200, 1250, 1300]) == 1300


def test_nearest_atm_strike_no_strikes_raises():
    with pytest.raises(InvalidMarketDataError):
        nearest_atm_strike(1250, [])


def test_distance_calculation():
    d = compute_distance(current_spot=1200, level=1180)
    assert d.signed_distance == pytest.approx(20.0)
    assert d.abs_distance == pytest.approx(20.0)
    assert d.distance_pct == pytest.approx((20 / 1180) * 100, abs=1e-3)
    assert d.abs_distance_pct == pytest.approx(abs((20 / 1180) * 100), abs=1e-3)


def test_distance_negative_when_below_level():
    d = compute_distance(current_spot=1160, level=1180)
    assert d.signed_distance < 0
    assert d.distance_pct < 0
    assert d.abs_distance_pct > 0


def test_zone_status_touch():
    levels = compute_monthly_levels(SPOT, ATM_STRIKE, ATM_CE, ATM_PE, zone_pct=0.05)
    status = classify_zone_status(levels.s1, levels.s1, levels.s1_zone)
    assert status == ZONE_STATUS_TOUCH


def test_zone_status_inside_zone():
    levels = compute_monthly_levels(SPOT, ATM_STRIKE, ATM_CE, ATM_PE, zone_pct=0.05)
    # inside zone but far enough from the exact level to not be VERY_CLOSE/TOUCH
    price = levels.s1 * 1.03
    status = classify_zone_status(price, levels.s1, levels.s1_zone)
    assert status == ZONE_STATUS_INSIDE_ZONE


def test_zone_status_very_close():
    levels = compute_monthly_levels(SPOT, ATM_STRIKE, ATM_CE, ATM_PE, zone_pct=0.05)
    price = levels.s1 * 1.005
    status = classify_zone_status(price, levels.s1, levels.s1_zone)
    assert status == ZONE_STATUS_VERY_CLOSE


def test_zone_status_approaching():
    levels = compute_monthly_levels(SPOT, ATM_STRIKE, ATM_CE, ATM_PE, zone_pct=0.05)
    price = levels.s1 * 1.08
    status = classify_zone_status(price, levels.s1, levels.s1_zone)
    assert status == ZONE_STATUS_APPROACHING


def test_zone_status_far():
    levels = compute_monthly_levels(SPOT, ATM_STRIKE, ATM_CE, ATM_PE, zone_pct=0.05)
    price = levels.s1 * 1.50
    status = classify_zone_status(price, levels.s1, levels.s1_zone)
    assert status == ZONE_STATUS_FAR
