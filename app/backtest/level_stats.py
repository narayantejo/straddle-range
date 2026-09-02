"""
Statistical level-performance analysis (spec Section 38): touch rate, exact
touch rate, bounce/rejection/breakout/breakdown rate, average reaction, and
MFE/MAE, computed per level across historical monthly cycles.

Walks each cycle's daily price series through the EXACT SAME classification
functions the live scanner uses (app.engine.formulas.classify_zone_status,
app.engine.direction.classify_direction, app.engine.confirmation, and
app.engine.reaction.classify_reaction) -- a backtested "touch" or "bounce" is
classified identically to how the live app would have called it on that day,
not a separate parallel definition.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.backtest.historical_levels import HistoricalCycle
from app.backtest.price_series import DailyBar
from app.engine import formulas
from app.engine.confirmation import ConfirmationConfig, ConfirmationInputs, evaluate_confirmation
from app.engine.direction import classify_direction
from app.engine.reaction import RESISTANCE_LEVELS, SUPPORT_LEVELS, classify_reaction

_LEVEL_NAMES = ("s2", "s1", "r1", "r2")
_ENGAGED = frozenset(
    {formulas.ZONE_STATUS_TOUCH, formulas.ZONE_STATUS_VERY_CLOSE, formulas.ZONE_STATUS_INSIDE_ZONE}
)

DEFAULT_LOOKFORWARD_DAYS = 10


@dataclass(frozen=True)
class LevelEvent:
    symbol: str
    calculation_month: str
    level_type: str
    touched: bool
    exact_touch: bool
    first_touch_date: str | None
    reaction_type: str | None  # BOUNCE / REJECTED / BREAKOUT / BREAKDOWN / None
    subsequent_move_pct: float | None
    mfe_pct: float | None
    mae_pct: float | None


def _zone_band_for(level_type: str, cycle: HistoricalCycle) -> tuple[float, formulas.ZoneBand]:
    levels = cycle.levels
    mapping = {
        "S2": (levels.s2, levels.s2_zone),
        "S1": (levels.s1, levels.s1_zone),
        "R1": (levels.r1, levels.r1_zone),
        "R2": (levels.r2, levels.r2_zone),
    }
    return mapping[level_type]


def analyze_cycle_level(
    cycle: HistoricalCycle,
    bars: list[DailyBar],
    level_type: str,
    lookforward_days: int = DEFAULT_LOOKFORWARD_DAYS,
    confirmation_config: ConfirmationConfig | None = None,
) -> LevelEvent:
    confirmation_config = confirmation_config or ConfirmationConfig()
    level_value, zone = _zone_band_for(level_type, cycle)
    is_resistance = level_type in RESISTANCE_LEVELS

    touch_index: int | None = None
    exact_touch = False
    touched = False
    closes = [b.close for b in bars]

    for i, bar in enumerate(bars):
        status = formulas.classify_zone_status(bar.close, level_value, zone)
        if status in _ENGAGED:
            touched = True
            if status == formulas.ZONE_STATUS_TOUCH:
                exact_touch = True
            if touch_index is None:
                touch_index = i

    if touch_index is None:
        return LevelEvent(
            symbol=cycle.symbol,
            calculation_month=cycle.calculation_month,
            level_type=level_type,
            touched=False,
            exact_touch=False,
            first_touch_date=None,
            reaction_type=None,
            subsequent_move_pct=None,
            mfe_pct=None,
            mae_pct=None,
        )

    window_end = min(touch_index + lookforward_days, len(bars) - 1)
    touch_close = closes[touch_index]
    reaction_type: str | None = None

    for i in range(touch_index, window_end + 1):
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
        if reaction in ("BOUNCE", "REJECTED", "BREAKOUT", "BREAKDOWN"):
            reaction_type = reaction
            break

    window_bars = bars[touch_index : window_end + 1]
    end_close = closes[window_end]
    subsequent_move_pct = ((end_close - touch_close) / touch_close) * 100 if touch_close else None

    highs = [b.high for b in window_bars]
    lows = [b.low for b in window_bars]
    if is_resistance:
        mfe_pct = ((touch_close - min(lows)) / touch_close) * 100 if touch_close else None
        mae_pct = ((max(highs) - touch_close) / touch_close) * 100 if touch_close else None
    else:
        mfe_pct = ((max(highs) - touch_close) / touch_close) * 100 if touch_close else None
        mae_pct = ((touch_close - min(lows)) / touch_close) * 100 if touch_close else None

    return LevelEvent(
        symbol=cycle.symbol,
        calculation_month=cycle.calculation_month,
        level_type=level_type,
        touched=touched,
        exact_touch=exact_touch,
        first_touch_date=bars[touch_index].trade_date,
        reaction_type=reaction_type,
        subsequent_move_pct=subsequent_move_pct,
        mfe_pct=mfe_pct,
        mae_pct=mae_pct,
    )


def analyze_cycle(
    cycle: HistoricalCycle,
    bars: list[DailyBar],
    lookforward_days: int = DEFAULT_LOOKFORWARD_DAYS,
    confirmation_config: ConfirmationConfig | None = None,
) -> list[LevelEvent]:
    return [
        analyze_cycle_level(cycle, bars, level.upper(), lookforward_days, confirmation_config)
        for level in _LEVEL_NAMES
    ]


@dataclass(frozen=True)
class LevelStats:
    level_type: str
    sample_size: int
    touch_rate_pct: float
    exact_touch_rate_pct: float
    bounce_rate_pct: float | None  # None for resistance levels
    rejection_rate_pct: float | None  # None for support levels
    breakout_rate_pct: float | None  # None for support levels
    breakdown_rate_pct: float | None  # None for resistance levels
    avg_reaction_pct: float | None
    avg_mfe_pct: float | None
    avg_mae_pct: float | None


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def aggregate_level_stats(events: list[LevelEvent]) -> dict[str, LevelStats]:
    result: dict[str, LevelStats] = {}
    for level_type in ("S2", "S1", "R1", "R2"):
        level_events = [e for e in events if e.level_type == level_type]
        n = len(level_events)
        if n == 0:
            continue
        touched_events = [e for e in level_events if e.touched]
        n_touched = len(touched_events)

        touch_rate = (n_touched / n) * 100
        exact_touch_rate = (sum(1 for e in level_events if e.exact_touch) / n) * 100

        reactions = [e.reaction_type for e in touched_events if e.reaction_type]
        is_support = level_type in SUPPORT_LEVELS

        bounce_rate = rejection_rate = breakout_rate = breakdown_rate = None
        if n_touched > 0:
            if is_support:
                bounce_rate = (reactions.count("BOUNCE") / n_touched) * 100
                breakdown_rate = (reactions.count("BREAKDOWN") / n_touched) * 100
            else:
                rejection_rate = (reactions.count("REJECTED") / n_touched) * 100
                breakout_rate = (reactions.count("BREAKOUT") / n_touched) * 100

        avg_reaction = _avg([e.subsequent_move_pct for e in touched_events if e.subsequent_move_pct is not None])
        avg_mfe = _avg([e.mfe_pct for e in touched_events if e.mfe_pct is not None])
        avg_mae = _avg([e.mae_pct for e in touched_events if e.mae_pct is not None])

        result[level_type] = LevelStats(
            level_type=level_type,
            sample_size=n,
            touch_rate_pct=touch_rate,
            exact_touch_rate_pct=exact_touch_rate,
            bounce_rate_pct=bounce_rate,
            rejection_rate_pct=rejection_rate,
            breakout_rate_pct=breakout_rate,
            breakdown_rate_pct=breakdown_rate,
            avg_reaction_pct=avg_reaction,
            avg_mfe_pct=avg_mfe,
            avg_mae_pct=avg_mae,
        )
    return result
