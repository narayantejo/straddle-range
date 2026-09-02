"""
Signal scoring (spec Section 27).

Produces a 0-100 SIGNAL SCORE and a SIGNAL TYPE label from proximity, zone
entry, direction, price action (reaction), volume, futures OI, and option
activity. Factors with no data available are excluded from the weighted
average rather than penalizing the score, so a scan missing e.g. volume data
doesn't get dragged toward 0.

This is a scanner signal, not a trading recommendation (spec Section 47) --
the label communicates "what pattern the calculated level + price behavior
currently look like", not "buy" or "sell".
"""
from __future__ import annotations

from dataclasses import dataclass

from app.engine.direction import DIRECTION_DOWN, DIRECTION_UP
from app.engine.formulas import (
    ZONE_STATUS_APPROACHING,
    ZONE_STATUS_FAR,
    ZONE_STATUS_INSIDE_ZONE,
    ZONE_STATUS_TOUCH,
    ZONE_STATUS_VERY_CLOSE,
)
from app.engine.reaction import (
    REACTION_BOUNCE,
    REACTION_BREAKDOWN,
    REACTION_BREAKOUT,
    REACTION_REJECTED,
    RESISTANCE_LEVELS,
    SUPPORT_LEVELS,
)

SIGNAL_NO_SETUP = "NO SETUP"


@dataclass(frozen=True)
class ScoringWeights:
    proximity: float = 30.0
    zone_entry: float = 15.0
    direction: float = 15.0
    price_action: float = 15.0
    volume: float = 10.0
    futures_oi: float = 10.0
    option_activity: float = 5.0
    proximity_max_pct: float = 10.0  # abs_distance_pct at/beyond which proximity score is 0


_ZONE_ENTRY_SCORE = {
    ZONE_STATUS_TOUCH: 1.0,
    ZONE_STATUS_VERY_CLOSE: 0.9,
    ZONE_STATUS_INSIDE_ZONE: 0.7,
    ZONE_STATUS_APPROACHING: 0.3,
    ZONE_STATUS_FAR: 0.0,
    REACTION_BOUNCE: 1.0,
    REACTION_REJECTED: 1.0,
    REACTION_BREAKOUT: 1.0,
    REACTION_BREAKDOWN: 1.0,
}

_PRICE_ACTION_SCORE = {
    REACTION_BOUNCE: 1.0,
    REACTION_REJECTED: 1.0,
    REACTION_BREAKOUT: 1.0,
    REACTION_BREAKDOWN: 1.0,
    ZONE_STATUS_TOUCH: 0.6,
    ZONE_STATUS_VERY_CLOSE: 0.4,
    ZONE_STATUS_INSIDE_ZONE: 0.4,
    ZONE_STATUS_APPROACHING: 0.1,
    ZONE_STATUS_FAR: 0.0,
}


@dataclass(frozen=True)
class SignalScore:
    score: float  # 0-100
    signal_type: str


def compute_signal_score(
    level_type: str,
    abs_distance_pct: float,
    base_zone_status: str,
    reaction: str,
    direction: str,
    volume_ratio: float | None = None,
    oi_confirming: bool | None = None,
    option_activity_confirming: bool | None = None,
    weights: ScoringWeights = ScoringWeights(),
) -> SignalScore:
    is_support = level_type in SUPPORT_LEVELS
    is_resistance = level_type in RESISTANCE_LEVELS
    if not is_support and not is_resistance:
        raise ValueError(f"Unknown level_type: {level_type!r}")

    proximity_score = max(0.0, 1.0 - (abs_distance_pct / weights.proximity_max_pct))
    zone_entry_score = _ZONE_ENTRY_SCORE.get(reaction, _ZONE_ENTRY_SCORE.get(base_zone_status, 0.0))
    price_action_score = _PRICE_ACTION_SCORE.get(reaction, _PRICE_ACTION_SCORE.get(base_zone_status, 0.0))

    moving_toward_level = (is_support and direction == DIRECTION_DOWN) or (
        is_resistance and direction == DIRECTION_UP
    )
    direction_score = 1.0 if moving_toward_level else (0.5 if direction not in (DIRECTION_UP, DIRECTION_DOWN) else 0.0)

    factors: list[tuple[float, float]] = [
        (weights.proximity, proximity_score),
        (weights.zone_entry, zone_entry_score),
        (weights.direction, direction_score),
        (weights.price_action, price_action_score),
    ]
    if volume_ratio is not None:
        factors.append((weights.volume, min(volume_ratio / 2.0, 1.0)))
    if oi_confirming is not None:
        factors.append((weights.futures_oi, 1.0 if oi_confirming else 0.0))
    if option_activity_confirming is not None:
        factors.append((weights.option_activity, 1.0 if option_activity_confirming else 0.0))

    total_weight = sum(w for w, _ in factors)
    score = (sum(w * s for w, s in factors) / total_weight * 100) if total_weight > 0 else 0.0
    score = round(score, 1)

    signal_type = _signal_type(level_type, reaction, base_zone_status, score)
    return SignalScore(score=score, signal_type=signal_type)


def _signal_type(level_type: str, reaction: str, base_zone_status: str, score: float) -> str:
    is_support = level_type in SUPPORT_LEVELS
    side = "SUPPORT" if is_support else "RESISTANCE"

    if reaction == REACTION_BREAKOUT:
        return "STRONG BREAKOUT" if score >= 75 else "BREAKOUT"
    if reaction == REACTION_BREAKDOWN:
        return "STRONG BREAKDOWN" if score >= 75 else "BREAKDOWN"
    if reaction == REACTION_BOUNCE:
        return "SUPPORT BOUNCE"
    if reaction == REACTION_REJECTED:
        return "RESISTANCE REJECTION"
    if reaction == ZONE_STATUS_TOUCH:
        return f"{side} TEST"
    if reaction in (ZONE_STATUS_INSIDE_ZONE, ZONE_STATUS_VERY_CLOSE):
        return f"{side} TEST" if score >= 60 else f"{side} APPROACH"
    if reaction == ZONE_STATUS_APPROACHING:
        return f"STRONG {side} APPROACH" if score >= 70 else f"{side} APPROACH"
    return SIGNAL_NO_SETUP
