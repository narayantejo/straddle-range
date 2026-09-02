"""
Market reaction classification (spec Section 18 + 27).

Combines the static zone status (from app.engine.formulas.classify_zone_status)
with price direction and breakout/breakdown confirmation to produce the full
reaction vocabulary: FAR, APPROACHING, VERY_CLOSE, INSIDE_ZONE, TOUCH, BOUNCE,
REJECTED, BREAKOUT, BREAKDOWN.

This is the boundary the spec draws in Section 47: the CALCULATED LEVEL
(S1/S2/R1/R2, fixed for the month) is math; the REACTION here is what actually
happened when price met that level. Never conflate the two.
"""
from __future__ import annotations

from app.engine.confirmation import ConfirmationResult
from app.engine.direction import DIRECTION_DOWN, DIRECTION_UP
from app.engine.formulas import (
    ZONE_STATUS_INSIDE_ZONE,
    ZONE_STATUS_TOUCH,
    ZONE_STATUS_VERY_CLOSE,
)

REACTION_BOUNCE = "BOUNCE"
REACTION_REJECTED = "REJECTED"
REACTION_BREAKOUT = "BREAKOUT"
REACTION_BREAKDOWN = "BREAKDOWN"

SUPPORT_LEVELS = ("S1", "S2")
RESISTANCE_LEVELS = ("R1", "R2")

_ZONE_ENGAGED = frozenset({ZONE_STATUS_TOUCH, ZONE_STATUS_INSIDE_ZONE, ZONE_STATUS_VERY_CLOSE})


def classify_reaction(
    level_type: str,
    base_zone_status: str,
    direction: str,
    confirmation: ConfirmationResult | None,
) -> str:
    """
    level_type: one of "S1", "S2", "R1", "R2".
    base_zone_status: output of formulas.classify_zone_status for this level.
    direction: output of direction.classify_direction.
    confirmation: result of confirmation.evaluate_confirmation for a break
        beyond this level in the "away from spot" direction, or None if not
        evaluated (e.g. price isn't near/beyond the level at all).
    """
    is_support = level_type in SUPPORT_LEVELS
    is_resistance = level_type in RESISTANCE_LEVELS
    if not is_support and not is_resistance:
        raise ValueError(f"Unknown level_type: {level_type!r}")

    if confirmation is not None and confirmation.confirmed:
        return REACTION_BREAKDOWN if is_support else REACTION_BREAKOUT

    if base_zone_status in _ZONE_ENGAGED:
        if is_support and direction == DIRECTION_UP:
            return REACTION_BOUNCE
        if is_resistance and direction == DIRECTION_DOWN:
            return REACTION_REJECTED

    return base_zone_status
