import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.backtest.results import compute_results, compute_results_by_level, compute_results_by_strategy
from app.backtest.simulator import Trade


def _trade(entry_date, exit_date, pnl_pct, level_type="S1", strategy_name="Support Bounce", holding_days=3):
    return Trade(
        symbol="TEST", calculation_month="2026-01", level_type=level_type,
        strategy_name=strategy_name, direction="LONG",
        entry_date=entry_date, entry_price=1000.0,
        exit_date=exit_date, exit_price=1000.0 * (1 + pnl_pct / 100),
        exit_reason="TARGET", holding_days=holding_days, pnl_pct=pnl_pct,
    )


def test_empty_trades_returns_zeroed_results():
    r = compute_results([])
    assert r.total_trades == 0
    assert r.win_rate_pct == 0.0
    assert r.profit_factor is None


def test_win_rate_and_profit_factor():
    trades = [
        _trade("2026-01-01", "2026-01-03", 4.0),
        _trade("2026-01-05", "2026-01-07", 4.0),
        _trade("2026-01-10", "2026-01-12", -2.0),
    ]
    r = compute_results(trades)
    assert r.total_trades == 3
    assert r.winning_trades == 2
    assert r.losing_trades == 1
    assert r.win_rate_pct == pytest.approx(200 / 3)
    assert r.gross_profit_pct == pytest.approx(8.0)
    assert r.gross_loss_pct == pytest.approx(-2.0)
    assert r.net_profit_pct == pytest.approx(6.0)
    assert r.profit_factor == pytest.approx(4.0)  # 8.0 / 2.0
    assert r.expectancy_pct == pytest.approx(2.0)  # 6.0 / 3


def test_no_losses_profit_factor_is_none():
    trades = [_trade("2026-01-01", "2026-01-03", 4.0)]
    r = compute_results(trades)
    assert r.profit_factor is None
    assert r.avg_loss_pct is None


def test_max_drawdown():
    # cumulative: +5, +5 -> 10 (peak), -8 -> 2 (drawdown of 8 from peak 10)
    trades = [
        _trade("2026-01-01", "2026-01-02", 5.0),
        _trade("2026-01-03", "2026-01-04", 5.0),
        _trade("2026-01-05", "2026-01-06", -8.0),
    ]
    r = compute_results(trades)
    assert r.max_drawdown_pct == pytest.approx(8.0)


def test_consecutive_streaks():
    trades = [
        _trade("2026-01-01", "2026-01-02", 1.0),
        _trade("2026-01-03", "2026-01-04", 1.0),
        _trade("2026-01-05", "2026-01-06", 1.0),
        _trade("2026-01-07", "2026-01-08", -1.0),
        _trade("2026-01-09", "2026-01-10", -1.0),
        _trade("2026-01-11", "2026-01-12", 1.0),
    ]
    r = compute_results(trades)
    assert r.max_consecutive_wins == 3
    assert r.max_consecutive_losses == 2


def test_largest_winner_and_loser():
    trades = [
        _trade("2026-01-01", "2026-01-02", 10.0),
        _trade("2026-01-03", "2026-01-04", -5.0),
        _trade("2026-01-05", "2026-01-06", 2.0),
    ]
    r = compute_results(trades)
    assert r.largest_winner_pct == pytest.approx(10.0)
    assert r.largest_loser_pct == pytest.approx(-5.0)


def test_avg_holding_days():
    trades = [
        _trade("2026-01-01", "2026-01-02", 1.0, holding_days=2),
        _trade("2026-01-03", "2026-01-04", 1.0, holding_days=6),
    ]
    r = compute_results(trades)
    assert r.avg_holding_days == pytest.approx(4.0)


def test_compute_results_by_level_groups_correctly():
    trades = [
        _trade("2026-01-01", "2026-01-02", 1.0, level_type="S1"),
        _trade("2026-01-03", "2026-01-04", 2.0, level_type="S1"),
        _trade("2026-01-05", "2026-01-06", -1.0, level_type="R1"),
    ]
    by_level = compute_results_by_level(trades)
    assert set(by_level.keys()) == {"S1", "R1"}
    assert by_level["S1"].total_trades == 2
    assert by_level["R1"].total_trades == 1


def test_compute_results_by_strategy_groups_correctly():
    trades = [
        _trade("2026-01-01", "2026-01-02", 1.0, strategy_name="Support Bounce"),
        _trade("2026-01-03", "2026-01-04", -1.0, strategy_name="R1 Breakout"),
    ]
    by_strategy = compute_results_by_strategy(trades)
    assert set(by_strategy.keys()) == {"Support Bounce", "R1 Breakout"}
