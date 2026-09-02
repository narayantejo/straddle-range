import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.engine.adaptive_zone import (
    MAX_ZONE_PCT,
    MIN_ZONE_PCT,
    REFERENCE_STRADDLE_PCT,
    compute_adaptive_zone_pct,
)


def test_reference_straddle_returns_base_unchanged():
    # spec's own worked example: spot=1250, straddle=150 -> 12% of spot
    result = compute_adaptive_zone_pct(straddle=150, spot_level=1250, base_zone_pct=0.05)
    assert result == pytest.approx(0.05)


def test_lower_relative_straddle_tightens_zone():
    # RELIANCE 2026-07 cycle: straddle ~5.4% of spot
    result = compute_adaptive_zone_pct(straddle=61.55, spot_level=1267.7, base_zone_pct=0.05)
    assert result < 0.05
    assert result == pytest.approx(0.05 * (61.55 / 1267.7) / 0.12, rel=1e-6)


def test_higher_relative_straddle_widens_zone():
    result = compute_adaptive_zone_pct(straddle=300, spot_level=1250, base_zone_pct=0.05)  # 24% of spot
    assert result > 0.05


def test_clamped_to_minimum():
    result = compute_adaptive_zone_pct(straddle=1, spot_level=10000, base_zone_pct=0.05)
    assert result == MIN_ZONE_PCT


def test_clamped_to_maximum():
    result = compute_adaptive_zone_pct(straddle=900, spot_level=1000, base_zone_pct=0.05)
    assert result == MAX_ZONE_PCT


def test_scales_linearly_with_base_zone_pct():
    r1 = compute_adaptive_zone_pct(straddle=150, spot_level=1250, base_zone_pct=0.02)
    r2 = compute_adaptive_zone_pct(straddle=150, spot_level=1250, base_zone_pct=0.04)
    assert r2 == pytest.approx(r1 * 2)


@pytest.mark.parametrize("straddle,spot", [(0, 1250), (150, 0), (-10, 1250), (150, -1250)])
def test_invalid_inputs_rejected(straddle, spot):
    with pytest.raises(ValueError):
        compute_adaptive_zone_pct(straddle=straddle, spot_level=spot)
