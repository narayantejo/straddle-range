"""
Price direction classification (spec Section 19).

Pure function over a series of recent closes -- no API calls here, so it's
fully unit-testable. Direction is the slope of a short-lookback linear fit
over the last N closes (today's spot included as the most recent point),
normalized by price level so the sideways band is comparable across stocks
of very different prices.
"""
from __future__ import annotations

DIRECTION_UP = "UP"
DIRECTION_DOWN = "DOWN"
DIRECTION_SIDEWAYS = "SIDEWAYS"


def classify_direction(
    recent_closes: list[float],
    current_price: float,
    sideways_band_pct: float = 0.15,
) -> str:
    """
    recent_closes: prior EOD closes, oldest first (does NOT include current_price).
    current_price: today's live/latest price, appended as the most recent point.
    sideways_band_pct: total % move over the lookback window below which the
        move is considered noise, not a trend (fraction, e.g. 0.15 == 0.15%).

    Returns UP / DOWN / SIDEWAYS. Requires at least 1 prior close; with fewer
    than 2 points total, returns SIDEWAYS (not enough data to infer a trend).
    """
    series = [*recent_closes, current_price]
    if len(series) < 2:
        return DIRECTION_SIDEWAYS

    start = series[0]
    end = series[-1]
    if start == 0:
        return DIRECTION_SIDEWAYS

    pct_change = ((end - start) / start) * 100
    if abs(pct_change) < sideways_band_pct:
        return DIRECTION_SIDEWAYS
    return DIRECTION_UP if pct_change > 0 else DIRECTION_DOWN
