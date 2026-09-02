"""Alert rule types (spec Section 39)."""
from __future__ import annotations

CONDITION_WITHIN_PCT = "WITHIN_PCT"
CONDITION_INSIDE_ZONE = "INSIDE_ZONE"
CONDITION_TOUCH = "TOUCH"
CONDITION_BOUNCE = "BOUNCE"
CONDITION_REJECTED = "REJECTED"
CONDITION_BREAKOUT = "BREAKOUT"
CONDITION_BREAKDOWN = "BREAKDOWN"

ALL_CONDITIONS = (
    CONDITION_WITHIN_PCT,
    CONDITION_INSIDE_ZONE,
    CONDITION_TOUCH,
    CONDITION_BOUNCE,
    CONDITION_REJECTED,
    CONDITION_BREAKOUT,
    CONDITION_BREAKDOWN,
)

LEVEL_S1 = "S1"
LEVEL_S2 = "S2"
LEVEL_R1 = "R1"
LEVEL_R2 = "R2"
LEVEL_ANY = "ANY"

ALL_LEVELS = (LEVEL_S1, LEVEL_S2, LEVEL_R1, LEVEL_R2, LEVEL_ANY)

CHANNEL_DASHBOARD = "dashboard"
CHANNEL_EMAIL = "email"
CHANNEL_TELEGRAM = "telegram"


def default_rules() -> list[dict]:
    """A sensible default rule set covering every level with every condition
    type at the dashboard channel -- matches spec Section 39's "S1/S2: within
    5/3/2/1%, inside zone, touch, bounce, breakdown" / "R1/R2: ... rejection,
    breakout" list, applied globally (symbol=None -> all stocks)."""
    rules = []
    for level in (LEVEL_S1, LEVEL_S2):
        rules.append({"level_type": level, "condition_type": CONDITION_WITHIN_PCT, "threshold_pct": 2.0})
        rules.append({"level_type": level, "condition_type": CONDITION_INSIDE_ZONE, "threshold_pct": None})
        rules.append({"level_type": level, "condition_type": CONDITION_TOUCH, "threshold_pct": None})
        rules.append({"level_type": level, "condition_type": CONDITION_BOUNCE, "threshold_pct": None})
        rules.append({"level_type": level, "condition_type": CONDITION_BREAKDOWN, "threshold_pct": None})
    for level in (LEVEL_R1, LEVEL_R2):
        rules.append({"level_type": level, "condition_type": CONDITION_WITHIN_PCT, "threshold_pct": 2.0})
        rules.append({"level_type": level, "condition_type": CONDITION_INSIDE_ZONE, "threshold_pct": None})
        rules.append({"level_type": level, "condition_type": CONDITION_TOUCH, "threshold_pct": None})
        rules.append({"level_type": level, "condition_type": CONDITION_REJECTED, "threshold_pct": None})
        rules.append({"level_type": level, "condition_type": CONDITION_BREAKOUT, "threshold_pct": None})
    return rules
