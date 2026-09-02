import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.engine.direction import DIRECTION_DOWN, DIRECTION_SIDEWAYS, DIRECTION_UP
from app.engine.formulas import ZONE_STATUS_FAR, ZONE_STATUS_TOUCH
from app.engine.reaction import REACTION_BOUNCE, REACTION_BREAKDOWN, REACTION_BREAKOUT
from app.engine.signal_scoring import SIGNAL_NO_SETUP, compute_signal_score


def test_far_from_level_scores_low_and_no_setup():
    result = compute_signal_score(
        "S1", abs_distance_pct=20.0, base_zone_status=ZONE_STATUS_FAR,
        reaction=ZONE_STATUS_FAR, direction=DIRECTION_SIDEWAYS,
    )
    assert result.score < 30
    assert result.signal_type == SIGNAL_NO_SETUP


def test_confirmed_bounce_scores_high():
    result = compute_signal_score(
        "S1", abs_distance_pct=0.1, base_zone_status=ZONE_STATUS_TOUCH,
        reaction=REACTION_BOUNCE, direction=DIRECTION_UP,
    )
    assert result.score >= 70
    assert result.signal_type == "SUPPORT BOUNCE"


def test_confirmed_breakout_scores_high_and_labeled():
    result = compute_signal_score(
        "R1", abs_distance_pct=0.2, base_zone_status=ZONE_STATUS_TOUCH,
        reaction=REACTION_BREAKOUT, direction=DIRECTION_UP,
        volume_ratio=2.0, oi_confirming=True,
    )
    assert result.signal_type in ("BREAKOUT", "STRONG BREAKOUT")
    assert result.score >= 70


def test_confirmed_breakdown_labeled_correctly():
    result = compute_signal_score(
        "S2", abs_distance_pct=0.2, base_zone_status=ZONE_STATUS_TOUCH,
        reaction=REACTION_BREAKDOWN, direction=DIRECTION_DOWN,
    )
    assert result.signal_type in ("BREAKDOWN", "STRONG BREAKDOWN")


def test_score_bounded_0_to_100():
    result = compute_signal_score(
        "R2", abs_distance_pct=0.0, base_zone_status=ZONE_STATUS_TOUCH,
        reaction=REACTION_BREAKOUT, direction=DIRECTION_UP,
        volume_ratio=5.0, oi_confirming=True, option_activity_confirming=True,
    )
    assert 0 <= result.score <= 100


def test_missing_optional_factors_does_not_crash_or_zero_out():
    with_data = compute_signal_score(
        "S1", abs_distance_pct=1.0, base_zone_status=ZONE_STATUS_TOUCH,
        reaction=REACTION_BOUNCE, direction=DIRECTION_UP,
        volume_ratio=1.0, oi_confirming=False, option_activity_confirming=False,
    )
    without_data = compute_signal_score(
        "S1", abs_distance_pct=1.0, base_zone_status=ZONE_STATUS_TOUCH,
        reaction=REACTION_BOUNCE, direction=DIRECTION_UP,
    )
    # missing factors should be excluded from the average, not treated as 0
    assert without_data.score > with_data.score


def test_invalid_level_type_raises():
    with pytest.raises(ValueError):
        compute_signal_score(
            "XX", abs_distance_pct=1.0, base_zone_status=ZONE_STATUS_TOUCH,
            reaction=ZONE_STATUS_TOUCH, direction=DIRECTION_UP,
        )
