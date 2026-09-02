import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.backtest.historical_levels import HistoricalCycle
from app.backtest.price_series import DailyBar
from app.backtest.simulator import EXIT_CYCLE_END, EXIT_MAX_HOLD, EXIT_STOP, EXIT_TARGET, simulate_cycle
from app.backtest.strategy import DIRECTION_LONG, DIRECTION_SHORT, StrategyConfig
from app.engine.formulas import MonthlyLevels, ZoneBand

# Fixture cycle: S1=960 (zone 912-1008), R1=1050 (zone 997.5-1102.5).
# classify_direction compares the CURRENT close against the START of a
# lookback window (up to 5 prior closes), not day-over-day -- so a "bounce"
# only registers once the close exceeds the earliest price in that window,
# not merely the immediately preceding day. Every scenario below was
# verified against the real classify_direction/classify_zone_status/
# classify_reaction functions before being hardcoded (see the exploration
# in the accompanying session), not hand-guessed.


def _make_cycle() -> HistoricalCycle:
    levels = MonthlyLevels(
        spot_level=1000.0, atm_strike=1000.0, atm_ce=50.0, atm_pe=40.0,
        straddle=90.0, midpoint=45.0, r1=1050.0, r2=1090.0, s1=960.0, s2=910.0,
        zone_pct=0.05,
        s2_zone=ZoneBand(864.5, 955.5), s1_zone=ZoneBand(912.0, 1008.0),
        r1_zone=ZoneBand(997.5, 1102.5), r2_zone=ZoneBand(1035.5, 1144.5),
    )
    return HistoricalCycle(
        symbol="TEST", calculation_month="2026-01", reference_expiry="2025-12-30",
        pricing_expiry="2026-01-27", levels=levels, ce_volume=1000, pe_volume=1000,
    )


def _bars(specs: list[tuple[float, float, float]], start="2026-01-01") -> list[DailyBar]:
    """specs: list of (close, high, low)."""
    d = datetime.date.fromisoformat(start)
    bars = []
    for i, (c, h, l) in enumerate(specs):
        bars.append(
            DailyBar(
                trade_date=(d + datetime.timedelta(days=i)).isoformat(),
                open=c, high=h, low=l, close=c, volume=1000,
            )
        )
    return bars


def test_long_bounce_hits_target():
    cycle = _make_cycle()
    strategy = StrategyConfig("Support Bounce", ("S1",), "BOUNCE", DIRECTION_LONG, stop_loss_pct=2.0, target_pct=4.0, max_holding_days=10)
    # BOUNCE triggers at index2 (close=975, direction flips UP vs the window start 970)
    closes = [
        (970, 971, 969), (960, 961, 959), (975, 976, 974),  # entry at index2, price=975
        (1000, 1001, 999), (1020, 1025, 1015),  # target = 975*1.04=1014, high 1025 >= 1014
    ]
    bars = _bars(closes)
    trades = simulate_cycle(cycle, bars, (strategy,))
    assert len(trades) == 1
    t = trades[0]
    assert t.direction == DIRECTION_LONG
    assert t.entry_price == pytest.approx(975)
    assert t.exit_reason == EXIT_TARGET
    assert t.pnl_pct > 0


def test_long_bounce_hits_stop():
    cycle = _make_cycle()
    strategy = StrategyConfig("Support Bounce", ("S1",), "BOUNCE", DIRECTION_LONG, stop_loss_pct=2.0, target_pct=4.0, max_holding_days=10)
    closes = [
        (970, 971, 969), (960, 961, 959), (975, 976, 974),  # entry at index2, price=975
        (965, 966, 950),  # stop = 975*0.98=955.5, low 950 <= 955.5
    ]
    bars = _bars(closes)
    trades = simulate_cycle(cycle, bars, (strategy,))
    assert len(trades) == 1
    assert trades[0].exit_reason == EXIT_STOP
    assert trades[0].pnl_pct < 0


def test_max_hold_exit_when_no_stop_or_target():
    cycle = _make_cycle()
    strategy = StrategyConfig("Support Bounce", ("S1",), "BOUNCE", DIRECTION_LONG, stop_loss_pct=2.0, target_pct=4.0, max_holding_days=3)
    closes = [
        (970, 971, 969), (960, 961, 959), (975, 976, 974),  # entry at index2, price=975
        (978, 979, 977), (980, 981, 979), (982, 983, 981),  # drifts sideways within [955.5, 1014]
    ]
    bars = _bars(closes)
    trades = simulate_cycle(cycle, bars, (strategy,))
    assert len(trades) == 1
    assert trades[0].exit_reason == EXIT_MAX_HOLD
    assert trades[0].holding_days == 3


def test_cycle_end_exit_when_data_runs_out():
    cycle = _make_cycle()
    strategy = StrategyConfig("Support Bounce", ("S1",), "BOUNCE", DIRECTION_LONG, stop_loss_pct=2.0, target_pct=4.0, max_holding_days=20)
    closes = [
        (970, 971, 969), (960, 961, 959), (975, 976, 974),  # entry at index2, price=975
        (978, 979, 977), (980, 981, 979),  # only 2 more bars, far short of max_holding_days=20
    ]
    bars = _bars(closes)
    trades = simulate_cycle(cycle, bars, (strategy,))
    assert len(trades) == 1
    assert trades[0].exit_reason == EXIT_CYCLE_END
    assert trades[0].exit_date == bars[-1].trade_date


def test_short_rejection_hits_target():
    cycle = _make_cycle()
    strategy = StrategyConfig("Resistance Rejection", ("R1",), "REJECTED", DIRECTION_SHORT, stop_loss_pct=2.0, target_pct=4.0, max_holding_days=10)
    # REJECTED triggers at index3 (close=1000, direction flips DOWN)
    closes = [
        (1020, 1021, 1019), (1050, 1051, 1049), (1030, 1031, 1029),
        (1000, 1001, 999),  # entry at index3, price=1000
        (940, 945, 935),  # target = 1000*0.96=960, low 935 <= 960
    ]
    bars = _bars(closes)
    trades = simulate_cycle(cycle, bars, (strategy,))
    assert len(trades) == 1
    t = trades[0]
    assert t.direction == DIRECTION_SHORT
    assert t.entry_price == pytest.approx(1000)
    assert t.exit_reason == EXIT_TARGET
    assert t.pnl_pct > 0  # short profits when price falls


def test_stop_and_target_same_bar_prefers_stop():
    """If a bar's range crosses both stop and target, the conservative
    assumption is the stop hit first."""
    cycle = _make_cycle()
    strategy = StrategyConfig("Support Bounce", ("S1",), "BOUNCE", DIRECTION_LONG, stop_loss_pct=2.0, target_pct=4.0, max_holding_days=10)
    closes = [
        (970, 971, 969), (960, 961, 959), (975, 976, 974),  # entry at index2, price=975
        (965, 1020, 900),  # wild bar: high blows past target (1014), low blows past stop (955.5)
    ]
    bars = _bars(closes)
    trades = simulate_cycle(cycle, bars, (strategy,))
    assert len(trades) == 1
    assert trades[0].exit_reason == EXIT_STOP


def test_no_trade_when_reaction_never_matches_trigger():
    cycle = _make_cycle()
    strategy = StrategyConfig("Support Bounce", ("S1",), "BOUNCE", DIRECTION_LONG, stop_loss_pct=2.0, target_pct=4.0, max_holding_days=10)
    # price never comes near S1 at all
    closes = [(1200, 1201, 1199)] * 5
    bars = _bars(closes)
    trades = simulate_cycle(cycle, bars, (strategy,))
    assert trades == []
