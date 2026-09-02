import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine.direction import DIRECTION_DOWN, DIRECTION_SIDEWAYS, DIRECTION_UP, classify_direction


def test_up_trend():
    assert classify_direction([100, 101, 102], 105) == DIRECTION_UP


def test_down_trend():
    assert classify_direction([100, 99, 98], 95) == DIRECTION_DOWN


def test_sideways_within_band():
    assert classify_direction([100, 100.05], 100.08, sideways_band_pct=0.15) == DIRECTION_SIDEWAYS


def test_sideways_boundary_is_exclusive_up():
    # exactly at the band edge should not count as trending
    assert classify_direction([100], 100.1, sideways_band_pct=0.1) == DIRECTION_SIDEWAYS


def test_insufficient_data_defaults_sideways():
    assert classify_direction([], 100) == DIRECTION_SIDEWAYS


def test_zero_start_price_safe():
    assert classify_direction([0], 10) == DIRECTION_SIDEWAYS
