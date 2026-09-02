"""
Breakout/breakdown confirmation engine (spec Sections 20-21).

A single tick beyond R1/R2/S1/S2 must NOT be classified as a confirmed
breakout/breakdown. This module evaluates a configurable set of independent
checks; the caller decides (via ConfirmationConfig) which checks must all
pass for a break to be "confirmed".
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ConfirmationConfig:
    """Each flag independently enables/disables that confirmation check
    (spec: "Allow the user to enable/disable individual confirmations")."""

    require_candle_close: bool = True
    require_pct_penetration: bool = True
    pct_penetration_threshold: float = 0.5  # % beyond the level, fraction e.g. 0.5 == 0.5%

    require_consecutive_closes: bool = False
    consecutive_closes_needed: int = 2

    require_volume_confirmation: bool = False
    volume_ratio_threshold: float = 1.5  # today's volume / avg volume

    require_oi_confirmation: bool = False
    oi_change_pct_threshold: float = 2.0  # % change in futures OI, fraction e.g. 2.0 == 2%

    require_momentum: bool = False


@dataclass
class ConfirmationInputs:
    level: float
    direction_is_up: bool  # True when checking a breakout (upside), False for breakdown (downside)
    latest_close: float
    recent_closes: list[float] = field(default_factory=list)  # oldest-first, excludes latest_close
    current_volume: float | None = None
    average_volume: float | None = None
    current_oi: float | None = None
    previous_oi: float | None = None
    momentum_confirmed: bool | None = None  # caller-supplied signal (e.g. RSI/MACD), optional


@dataclass(frozen=True)
class ConfirmationResult:
    confirmed: bool
    checks: dict[str, bool | None]  # None means "not evaluated" (check disabled)


def _beyond(level: float, price: float, direction_is_up: bool) -> bool:
    return price > level if direction_is_up else price < level


def evaluate_confirmation(
    config: ConfirmationConfig, inputs: ConfirmationInputs
) -> ConfirmationResult:
    checks: dict[str, bool | None] = {}
    enabled_results: list[bool] = []

    if config.require_candle_close:
        result = _beyond(inputs.level, inputs.latest_close, inputs.direction_is_up)
        checks["candle_close"] = result
        enabled_results.append(result)
    else:
        checks["candle_close"] = None

    if config.require_pct_penetration:
        if inputs.level == 0:
            result = False
        else:
            penetration_pct = abs((inputs.latest_close - inputs.level) / inputs.level) * 100
            result = _beyond(inputs.level, inputs.latest_close, inputs.direction_is_up) and (
                penetration_pct >= config.pct_penetration_threshold
            )
        checks["pct_penetration"] = result
        enabled_results.append(result)
    else:
        checks["pct_penetration"] = None

    if config.require_consecutive_closes:
        window = inputs.recent_closes[-(config.consecutive_closes_needed - 1) :] + [
            inputs.latest_close
        ]
        result = len(window) >= config.consecutive_closes_needed and all(
            _beyond(inputs.level, c, inputs.direction_is_up) for c in window
        )
        checks["consecutive_closes"] = result
        enabled_results.append(result)
    else:
        checks["consecutive_closes"] = None

    if config.require_volume_confirmation:
        if not inputs.current_volume or not inputs.average_volume or inputs.average_volume == 0:
            result = False
        else:
            result = (inputs.current_volume / inputs.average_volume) >= config.volume_ratio_threshold
        checks["volume"] = result
        enabled_results.append(result)
    else:
        checks["volume"] = None

    if config.require_oi_confirmation:
        if inputs.current_oi is None or not inputs.previous_oi:
            result = False
        else:
            oi_change_pct = ((inputs.current_oi - inputs.previous_oi) / inputs.previous_oi) * 100
            # Rising OI in the direction of the move confirms the break; falling OI
            # (short-covering / long-unwinding) does not.
            result = oi_change_pct >= config.oi_change_pct_threshold
        checks["futures_oi"] = result
        enabled_results.append(result)
    else:
        checks["futures_oi"] = None

    if config.require_momentum:
        result = bool(inputs.momentum_confirmed)
        checks["momentum"] = result
        enabled_results.append(result)
    else:
        checks["momentum"] = None

    confirmed = bool(enabled_results) and all(enabled_results)
    return ConfirmationResult(confirmed=confirmed, checks=checks)
