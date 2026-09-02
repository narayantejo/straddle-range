"""
Trade strategy simulator (spec Sections 34-37).

No-look-ahead: walks each cycle's daily bars strictly in chronological
order. A trade is only ever recognized on the bar where the SAME
classify_reaction() the live scanner would have produced that day already
confirms it -- never using a later bar's information to decide to enter
"today". Exit checks (stop/target) use that day's high/low (a stop or
target can realistically trigger intraday, not only at the close); entry
and max-hold/cycle-end exits use the close.

P&L is a simple per-trade % return (not a compounded equity curve, not
capital/position-sized) -- this backtests whether the S/R + reaction setup
itself has an edge, not portfolio-level money management.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.backtest.historical_levels import HistoricalCycle
from app.backtest.price_series import DailyBar
from app.backtest.strategy import DIRECTION_LONG, StrategyConfig
from app.engine import formulas
from app.engine.confirmation import ConfirmationConfig, ConfirmationInputs, evaluate_confirmation
from app.engine.direction import classify_direction
from app.engine.reaction import RESISTANCE_LEVELS, classify_reaction

EXIT_STOP = "STOP"
EXIT_TARGET = "TARGET"
EXIT_MAX_HOLD = "MAX_HOLD"
EXIT_CYCLE_END = "CYCLE_END"


@dataclass(frozen=True)
class Trade:
    symbol: str
    calculation_month: str
    level_type: str
    strategy_name: str
    direction: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    exit_reason: str
    holding_days: int
    pnl_pct: float


def _level_value_and_zone(level_type: str, cycle: HistoricalCycle) -> tuple[float, formulas.ZoneBand]:
    levels = cycle.levels
    mapping = {
        "S2": (levels.s2, levels.s2_zone),
        "S1": (levels.s1, levels.s1_zone),
        "R1": (levels.r1, levels.r1_zone),
        "R2": (levels.r2, levels.r2_zone),
    }
    return mapping[level_type]


def _pnl_pct(direction: str, entry_price: float, exit_price: float) -> float:
    if direction == DIRECTION_LONG:
        return ((exit_price - entry_price) / entry_price) * 100
    return ((entry_price - exit_price) / entry_price) * 100


def _find_exit(
    bars: list[DailyBar], entry_index: int, entry_price: float, strategy: StrategyConfig
) -> tuple[int, float, str]:
    is_long = strategy.direction == DIRECTION_LONG
    if is_long:
        stop_price = entry_price * (1 - strategy.stop_loss_pct / 100)
        target_price = entry_price * (1 + strategy.target_pct / 100)
    else:
        stop_price = entry_price * (1 + strategy.stop_loss_pct / 100)
        target_price = entry_price * (1 - strategy.target_pct / 100)

    last_index = len(bars) - 1
    max_index = min(entry_index + strategy.max_holding_days, last_index)

    for i in range(entry_index + 1, max_index + 1):
        bar = bars[i]
        # If both stop and target were crossed within the same bar, assume
        # the stop hit first (conservative -- avoids an over-optimistic
        # backtest on a gap/whipsaw day).
        if is_long:
            if bar.low <= stop_price:
                return i, stop_price, EXIT_STOP
            if bar.high >= target_price:
                return i, target_price, EXIT_TARGET
        else:
            if bar.high >= stop_price:
                return i, stop_price, EXIT_STOP
            if bar.low <= target_price:
                return i, target_price, EXIT_TARGET
        if i == entry_index + strategy.max_holding_days:
            return i, bar.close, EXIT_MAX_HOLD

    return max_index, bars[max_index].close, EXIT_CYCLE_END


def _simulate_level_strategy(
    cycle: HistoricalCycle,
    bars: list[DailyBar],
    level_type: str,
    strategy: StrategyConfig,
    confirmation_config: ConfirmationConfig,
) -> list[Trade]:
    level_value, zone = _level_value_and_zone(level_type, cycle)
    is_resistance = level_type in RESISTANCE_LEVELS
    closes = [b.close for b in bars]

    trades: list[Trade] = []
    i = 0
    n = len(bars)
    while i < n:
        prior_closes = closes[max(0, i - 5) : i]
        direction = classify_direction(prior_closes, closes[i])
        status = formulas.classify_zone_status(closes[i], level_value, zone)
        conf_inputs = ConfirmationInputs(
            level=level_value,
            direction_is_up=is_resistance,
            latest_close=closes[i],
            recent_closes=prior_closes,
        )
        confirmation = evaluate_confirmation(confirmation_config, conf_inputs)
        reaction = classify_reaction(level_type, status, direction, confirmation)

        if reaction == strategy.trigger_reaction:
            entry_index = i
            entry_price = closes[i]
            exit_index, exit_price, exit_reason = _find_exit(bars, entry_index, entry_price, strategy)
            trades.append(
                Trade(
                    symbol=cycle.symbol,
                    calculation_month=cycle.calculation_month,
                    level_type=level_type,
                    strategy_name=strategy.name,
                    direction=strategy.direction,
                    entry_date=bars[entry_index].trade_date,
                    entry_price=entry_price,
                    exit_date=bars[exit_index].trade_date,
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                    holding_days=exit_index - entry_index,
                    pnl_pct=_pnl_pct(strategy.direction, entry_price, exit_price),
                )
            )
            i = exit_index + 1  # no overlapping positions for this level+strategy
        else:
            i += 1
    return trades


def simulate_cycle(
    cycle: HistoricalCycle,
    bars: list[DailyBar],
    strategies: tuple[StrategyConfig, ...],
    confirmation_config: ConfirmationConfig | None = None,
) -> list[Trade]:
    confirmation_config = confirmation_config or ConfirmationConfig()
    trades: list[Trade] = []
    for strategy in strategies:
        for level_type in strategy.level_types:
            trades.extend(_simulate_level_strategy(cycle, bars, level_type, strategy, confirmation_config))
    return trades
