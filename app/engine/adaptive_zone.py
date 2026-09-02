"""
Straddle-based adaptive zone width.

The spec's zone formula (app.engine.formulas: zone = level x (1 +/- zone%))
is a flat percentage of the LEVEL's price magnitude. Since a stock's price
is typically many multiples of its monthly ATM premium, a flat zone% tends
to produce a zone band that is wide relative to the actual S1/R1 spacing
(which is set by the premium, not the price) -- most visibly for
lower-relative-IV stocks, where the zone can swallow most of the cycle's
real trading range (observed on RELIANCE's 2026-07 cycle: straddle was only
~5.4% of spot, and R1's flat-5% zone extended back past S1).

This module does NOT change the zone formula itself -- app.engine.formulas
stays exactly spec-literal. It only computes a per-stock, per-cycle zone%
INPUT to feed into that same formula, scaled continuously by how large the
straddle is relative to spot, anchored to the spec's own worked example
(Section 10: spot=1250, straddle=150 -> straddle is 12% of spot) as the
volatility level that maps to the user's chosen base zone% unchanged.
"""
from __future__ import annotations

REFERENCE_STRADDLE_PCT = 0.12  # spec's own worked example: 150/1250
MIN_ZONE_PCT = 0.01
MAX_ZONE_PCT = 0.15


def compute_adaptive_zone_pct(
    straddle: float,
    spot_level: float,
    base_zone_pct: float = 0.05,
    reference_straddle_pct: float = REFERENCE_STRADDLE_PCT,
    min_zone_pct: float = MIN_ZONE_PCT,
    max_zone_pct: float = MAX_ZONE_PCT,
) -> float:
    """
    Returns a zone% scaled linearly by (straddle / spot) relative to
    reference_straddle_pct, clamped to [min_zone_pct, max_zone_pct].

    A stock whose straddle is exactly reference_straddle_pct of spot gets
    base_zone_pct back unchanged. Lower relative straddle (lower implied
    volatility for that expiry) tightens the zone; higher relative straddle
    widens it.
    """
    if spot_level <= 0 or straddle <= 0:
        raise ValueError(f"spot_level and straddle must be > 0, got {spot_level}, {straddle}")

    straddle_pct_of_spot = straddle / spot_level
    scaled = base_zone_pct * (straddle_pct_of_spot / reference_straddle_pct)
    return max(min_zone_pct, min(max_zone_pct, scaled))
