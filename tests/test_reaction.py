import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.engine.confirmation import ConfirmationResult
from app.engine.direction import DIRECTION_DOWN, DIRECTION_SIDEWAYS, DIRECTION_UP
from app.engine.formulas import (
    ZONE_STATUS_APPROACHING,
    ZONE_STATUS_FAR,
    ZONE_STATUS_INSIDE_ZONE,
    ZONE_STATUS_TOUCH,
)
from app.engine.reaction import (
    REACTION_BOUNCE,
    REACTION_BREAKDOWN,
    REACTION_BREAKOUT,
    REACTION_REJECTED,
    classify_reaction,
)

CONFIRMED = ConfirmationResult(confirmed=True, checks={})
NOT_CONFIRMED = ConfirmationResult(confirmed=False, checks={})


def test_support_touch_with_up_direction_is_bounce():
    result = classify_reaction("S1", ZONE_STATUS_TOUCH, DIRECTION_UP, NOT_CONFIRMED)
    assert result == REACTION_BOUNCE


def test_support_touch_with_down_direction_stays_touch():
    result = classify_reaction("S1", ZONE_STATUS_TOUCH, DIRECTION_DOWN, NOT_CONFIRMED)
    assert result == ZONE_STATUS_TOUCH


def test_resistance_touch_with_down_direction_is_rejected():
    result = classify_reaction("R1", ZONE_STATUS_TOUCH, DIRECTION_DOWN, NOT_CONFIRMED)
    assert result == REACTION_REJECTED


def test_resistance_touch_with_up_direction_stays_touch():
    result = classify_reaction("R1", ZONE_STATUS_TOUCH, DIRECTION_UP, NOT_CONFIRMED)
    assert result == ZONE_STATUS_TOUCH


def test_confirmed_break_above_resistance_is_breakout():
    result = classify_reaction("R2", ZONE_STATUS_INSIDE_ZONE, DIRECTION_UP, CONFIRMED)
    assert result == REACTION_BREAKOUT


def test_confirmed_break_below_support_is_breakdown():
    result = classify_reaction("S2", ZONE_STATUS_INSIDE_ZONE, DIRECTION_DOWN, CONFIRMED)
    assert result == REACTION_BREAKDOWN


def test_confirmation_takes_priority_over_bounce():
    # even if direction looks like a bounce setup, a confirmed breakdown wins
    result = classify_reaction("S1", ZONE_STATUS_TOUCH, DIRECTION_UP, CONFIRMED)
    assert result == REACTION_BREAKDOWN


def test_far_status_passes_through_unchanged():
    result = classify_reaction("S1", ZONE_STATUS_FAR, DIRECTION_UP, None)
    assert result == ZONE_STATUS_FAR


def test_approaching_status_passes_through_unchanged():
    result = classify_reaction("R1", ZONE_STATUS_APPROACHING, DIRECTION_SIDEWAYS, None)
    assert result == ZONE_STATUS_APPROACHING


def test_invalid_level_type_raises():
    with pytest.raises(ValueError):
        classify_reaction("X9", ZONE_STATUS_TOUCH, DIRECTION_UP, None)
