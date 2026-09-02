"""
Backtest strategy configuration (spec Section 36), adapted to trade the
underlying spot/equity rather than actual CE/PE options -- see project
decision: DhanHQ's historical option data proved too slow/unreliable for a
full multi-stock, multi-month backtest, and spot P&L directly tests whether
the S/R methodology + reaction classification has predictive value,
independent of options mechanics (theta decay, IV changes) that would be a
separate concern even if that data were reliable.
"""
from __future__ import annotations

from dataclasses import dataclass

DIRECTION_LONG = "LONG"
DIRECTION_SHORT = "SHORT"


@dataclass(frozen=True)
class StrategyConfig:
    name: str
    level_types: tuple[str, ...]
    trigger_reaction: str  # "BOUNCE" / "REJECTED" / "BREAKOUT" / "BREAKDOWN"
    direction: str  # DIRECTION_LONG / DIRECTION_SHORT
    stop_loss_pct: float = 2.0
    target_pct: float = 4.0
    max_holding_days: int = 10


DEFAULT_STRATEGIES: tuple[StrategyConfig, ...] = (
    StrategyConfig("Support Bounce", ("S1", "S2"), "BOUNCE", DIRECTION_LONG),
    StrategyConfig("Resistance Rejection", ("R1", "R2"), "REJECTED", DIRECTION_SHORT),
    StrategyConfig("R1 Breakout", ("R1",), "BREAKOUT", DIRECTION_LONG),
    StrategyConfig("R2 Breakout", ("R2",), "BREAKOUT", DIRECTION_LONG),
    StrategyConfig("S1 Breakdown", ("S1",), "BREAKDOWN", DIRECTION_SHORT),
    StrategyConfig("S2 Breakdown", ("S2",), "BREAKDOWN", DIRECTION_SHORT),
)
