"""
Aggregate backtest results (spec Section 37).

P&L figures are simple per-trade % returns, summed -- not a compounded
equity curve and not capital/position-sized (see app.backtest.simulator).
"max_drawdown_pct" and the equity curve it's derived from follow the same
convention: cumulative sum of trade pnl_pct in chronological order, not
compounded growth.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.backtest.simulator import Trade


@dataclass(frozen=True)
class BacktestResults:
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    gross_profit_pct: float
    gross_loss_pct: float  # <= 0
    net_profit_pct: float
    avg_profit_pct: float | None
    avg_loss_pct: float | None
    profit_factor: float | None  # gross_profit / abs(gross_loss); None if no losses
    expectancy_pct: float
    max_drawdown_pct: float
    avg_holding_days: float
    largest_winner_pct: float | None
    largest_loser_pct: float | None
    max_consecutive_wins: int
    max_consecutive_losses: int


_EMPTY_RESULTS = BacktestResults(
    total_trades=0, winning_trades=0, losing_trades=0, win_rate_pct=0.0,
    gross_profit_pct=0.0, gross_loss_pct=0.0, net_profit_pct=0.0,
    avg_profit_pct=None, avg_loss_pct=None, profit_factor=None, expectancy_pct=0.0,
    max_drawdown_pct=0.0, avg_holding_days=0.0, largest_winner_pct=None,
    largest_loser_pct=None, max_consecutive_wins=0, max_consecutive_losses=0,
)


def compute_results(trades: list[Trade]) -> BacktestResults:
    if not trades:
        return _EMPTY_RESULTS

    ordered = sorted(trades, key=lambda t: (t.entry_date, t.exit_date))
    wins = [t for t in ordered if t.pnl_pct > 0]
    losses = [t for t in ordered if t.pnl_pct <= 0]

    gross_profit = sum(t.pnl_pct for t in wins)
    gross_loss = sum(t.pnl_pct for t in losses)
    net_profit = gross_profit + gross_loss

    cum = peak = max_dd = 0.0
    max_win_streak = cur_win_streak = 0
    max_loss_streak = cur_loss_streak = 0
    for t in ordered:
        cum += t.pnl_pct
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
        if t.pnl_pct > 0:
            cur_win_streak += 1
            cur_loss_streak = 0
        else:
            cur_loss_streak += 1
            cur_win_streak = 0
        max_win_streak = max(max_win_streak, cur_win_streak)
        max_loss_streak = max(max_loss_streak, cur_loss_streak)

    n = len(ordered)
    return BacktestResults(
        total_trades=n,
        winning_trades=len(wins),
        losing_trades=len(losses),
        win_rate_pct=(len(wins) / n) * 100,
        gross_profit_pct=gross_profit,
        gross_loss_pct=gross_loss,
        net_profit_pct=net_profit,
        avg_profit_pct=(gross_profit / len(wins)) if wins else None,
        avg_loss_pct=(gross_loss / len(losses)) if losses else None,
        profit_factor=(gross_profit / abs(gross_loss)) if gross_loss < 0 else None,
        expectancy_pct=net_profit / n,
        max_drawdown_pct=max_dd,
        avg_holding_days=sum(t.holding_days for t in ordered) / n,
        largest_winner_pct=max((t.pnl_pct for t in ordered), default=None),
        largest_loser_pct=min((t.pnl_pct for t in ordered), default=None),
        max_consecutive_wins=max_win_streak,
        max_consecutive_losses=max_loss_streak,
    )


def compute_results_by_level(trades: list[Trade]) -> dict[str, BacktestResults]:
    by_level: dict[str, list[Trade]] = {}
    for t in trades:
        by_level.setdefault(t.level_type, []).append(t)
    return {level: compute_results(ts) for level, ts in by_level.items()}


def compute_results_by_strategy(trades: list[Trade]) -> dict[str, BacktestResults]:
    by_strategy: dict[str, list[Trade]] = {}
    for t in trades:
        by_strategy.setdefault(t.strategy_name, []).append(t)
    return {name: compute_results(ts) for name, ts in by_strategy.items()}
