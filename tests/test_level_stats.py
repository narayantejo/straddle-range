import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.backtest.historical_levels import HistoricalCycle
from app.backtest.level_stats import aggregate_level_stats, analyze_cycle, analyze_cycle_level
from app.backtest.price_series import DailyBar
from app.engine.formulas import MonthlyLevels, ZoneBand


def _make_cycle(symbol="TEST") -> HistoricalCycle:
    levels = MonthlyLevels(
        spot_level=1000.0,
        atm_strike=1000.0,
        atm_ce=50.0,
        atm_pe=40.0,
        straddle=90.0,
        midpoint=45.0,
        r1=1050.0,
        r2=1090.0,
        s1=960.0,
        s2=910.0,
        zone_pct=0.05,
        s2_zone=ZoneBand(864.5, 955.5),
        s1_zone=ZoneBand(912.0, 1008.0),
        r1_zone=ZoneBand(997.5, 1102.5),
        r2_zone=ZoneBand(1035.5, 1144.5),
    )
    return HistoricalCycle(
        symbol=symbol,
        calculation_month="2026-01",
        reference_expiry="2025-12-30",
        pricing_expiry="2026-01-27",
        levels=levels,
        ce_volume=1000,
        pe_volume=1000,
    )


def _bars(closes: list[float], start="2026-01-01") -> list[DailyBar]:
    import datetime

    d = datetime.date.fromisoformat(start)
    bars = []
    for i, c in enumerate(closes):
        bars.append(
            DailyBar(
                trade_date=(d + datetime.timedelta(days=i)).isoformat(),
                open=c, high=c + 1, low=c - 1, close=c, volume=1000,
            )
        )
    return bars


def test_support_bounce_detected():
    cycle = _make_cycle()
    # spot drifts down to touch S1 (960) then bounces up
    closes = [1010, 1000, 990, 980, 970, 960, 965, 980, 1000, 1020, 1040]
    bars = _bars(closes)
    event = analyze_cycle_level(cycle, bars, "S1")
    assert event.touched is True
    assert event.exact_touch is True
    assert event.reaction_type == "BOUNCE"
    assert event.subsequent_move_pct > 0
    assert event.mfe_pct > 0


def test_no_touch_when_price_stays_far():
    cycle = _make_cycle()
    closes = [1010, 1015, 1020, 1018, 1022, 1025, 1030]
    bars = _bars(closes)
    event = analyze_cycle_level(cycle, bars, "S1")
    assert event.touched is False
    assert event.exact_touch is False
    assert event.reaction_type is None
    assert event.subsequent_move_pct is None


def test_resistance_rejection_detected():
    cycle = _make_cycle()
    # drifts up to touch R1 (1050) then rejects downward
    closes = [1000, 1010, 1020, 1030, 1040, 1050, 1045, 1030, 1010, 990, 970]
    bars = _bars(closes)
    event = analyze_cycle_level(cycle, bars, "R1")
    assert event.touched is True
    assert event.reaction_type == "REJECTED"
    assert event.subsequent_move_pct < 0


def test_analyze_cycle_returns_all_four_levels():
    cycle = _make_cycle()
    closes = [1000] * 10
    bars = _bars(closes)
    events = analyze_cycle(cycle, bars)
    assert {e.level_type for e in events} == {"S2", "S1", "R1", "R2"}


def test_aggregate_stats_touch_rate():
    cycle1 = _make_cycle("A")
    cycle2 = _make_cycle("B")
    bars_touch = _bars([1010, 1000, 990, 980, 970, 960, 965, 980, 1000, 1020])
    bars_no_touch = _bars([1010, 1015, 1020, 1018, 1022])

    events = [
        analyze_cycle_level(cycle1, bars_touch, "S1"),
        analyze_cycle_level(cycle2, bars_no_touch, "S1"),
    ]
    stats = aggregate_level_stats(events)
    assert stats["S1"].sample_size == 2
    assert stats["S1"].touch_rate_pct == pytest.approx(50.0)


def test_aggregate_stats_only_computes_relevant_rates_by_side():
    cycle = _make_cycle()
    bars = _bars([1010, 1000, 990, 980, 970, 960, 965, 980, 1000, 1020])
    s1_event = analyze_cycle_level(cycle, bars, "S1")
    r1_event = analyze_cycle_level(cycle, bars, "R1")
    stats = aggregate_level_stats([s1_event, r1_event])

    assert stats["S1"].bounce_rate_pct is not None
    assert stats["S1"].rejection_rate_pct is None
    assert stats["S1"].breakout_rate_pct is None

    if "R1" in stats:
        assert stats["R1"].rejection_rate_pct is not None or stats["R1"].breakout_rate_pct is not None
        assert stats["R1"].bounce_rate_pct is None
