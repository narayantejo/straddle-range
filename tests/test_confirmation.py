import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.engine.confirmation import ConfirmationConfig, ConfirmationInputs, evaluate_confirmation


def test_single_tick_above_resistance_not_confirmed_by_default_penetration():
    """A close that's barely above the level should fail the % penetration check."""
    config = ConfirmationConfig(
        require_candle_close=True, require_pct_penetration=True, pct_penetration_threshold=0.5
    )
    inputs = ConfirmationInputs(level=100.0, direction_is_up=True, latest_close=100.1)
    result = evaluate_confirmation(config, inputs)
    assert result.checks["candle_close"] is True
    assert result.checks["pct_penetration"] is False
    assert result.confirmed is False


def test_confirmed_breakout_with_sufficient_penetration():
    config = ConfirmationConfig(
        require_candle_close=True, require_pct_penetration=True, pct_penetration_threshold=0.5
    )
    inputs = ConfirmationInputs(level=100.0, direction_is_up=True, latest_close=101.0)
    result = evaluate_confirmation(config, inputs)
    assert result.confirmed is True


def test_breakdown_direction():
    config = ConfirmationConfig(require_candle_close=True, require_pct_penetration=False)
    inputs = ConfirmationInputs(level=100.0, direction_is_up=False, latest_close=99.0)
    result = evaluate_confirmation(config, inputs)
    assert result.checks["candle_close"] is True
    assert result.confirmed is True

    inputs_not_below = ConfirmationInputs(level=100.0, direction_is_up=False, latest_close=100.5)
    result2 = evaluate_confirmation(config, inputs_not_below)
    assert result2.checks["candle_close"] is False
    assert result2.confirmed is False


def test_consecutive_closes_required():
    config = ConfirmationConfig(
        require_candle_close=False,
        require_pct_penetration=False,
        require_consecutive_closes=True,
        consecutive_closes_needed=3,
    )
    # only 2 of the last 3 closes are above the level -> not confirmed
    inputs = ConfirmationInputs(
        level=100.0, direction_is_up=True, latest_close=101.0, recent_closes=[99.0, 100.5]
    )
    result = evaluate_confirmation(config, inputs)
    assert result.checks["consecutive_closes"] is False
    assert result.confirmed is False

    inputs_ok = ConfirmationInputs(
        level=100.0, direction_is_up=True, latest_close=101.0, recent_closes=[100.2, 100.5]
    )
    result_ok = evaluate_confirmation(config, inputs_ok)
    assert result_ok.checks["consecutive_closes"] is True
    assert result_ok.confirmed is True


def test_volume_confirmation():
    config = ConfirmationConfig(
        require_candle_close=False,
        require_pct_penetration=False,
        require_volume_confirmation=True,
        volume_ratio_threshold=1.5,
    )
    low_vol = ConfirmationInputs(
        level=100.0, direction_is_up=True, latest_close=101.0,
        current_volume=100, average_volume=100,
    )
    assert evaluate_confirmation(config, low_vol).confirmed is False

    high_vol = ConfirmationInputs(
        level=100.0, direction_is_up=True, latest_close=101.0,
        current_volume=200, average_volume=100,
    )
    assert evaluate_confirmation(config, high_vol).confirmed is True


def test_oi_confirmation_rising_oi_confirms():
    config = ConfirmationConfig(
        require_candle_close=False,
        require_pct_penetration=False,
        require_oi_confirmation=True,
        oi_change_pct_threshold=2.0,
    )
    inputs = ConfirmationInputs(
        level=100.0, direction_is_up=True, latest_close=101.0,
        current_oi=110, previous_oi=100,
    )
    assert evaluate_confirmation(config, inputs).confirmed is True

    falling_oi = ConfirmationInputs(
        level=100.0, direction_is_up=True, latest_close=101.0,
        current_oi=95, previous_oi=100,
    )
    assert evaluate_confirmation(config, falling_oi).confirmed is False


def test_missing_data_fails_check_not_crashes():
    config = ConfirmationConfig(
        require_candle_close=False,
        require_pct_penetration=False,
        require_volume_confirmation=True,
        require_oi_confirmation=True,
    )
    inputs = ConfirmationInputs(level=100.0, direction_is_up=True, latest_close=101.0)
    result = evaluate_confirmation(config, inputs)
    assert result.checks["volume"] is False
    assert result.checks["futures_oi"] is False
    assert result.confirmed is False


def test_all_checks_disabled_never_confirms():
    config = ConfirmationConfig(
        require_candle_close=False,
        require_pct_penetration=False,
        require_consecutive_closes=False,
        require_volume_confirmation=False,
        require_oi_confirmation=False,
        require_momentum=False,
    )
    inputs = ConfirmationInputs(level=100.0, direction_is_up=True, latest_close=200.0)
    result = evaluate_confirmation(config, inputs)
    assert result.confirmed is False
    assert all(v is None for v in result.checks.values())


def test_multiple_checks_all_must_pass():
    config = ConfirmationConfig(
        require_candle_close=True,
        require_pct_penetration=True,
        pct_penetration_threshold=0.5,
        require_volume_confirmation=True,
        volume_ratio_threshold=1.5,
    )
    # candle close + penetration pass, volume fails -> overall not confirmed
    inputs = ConfirmationInputs(
        level=100.0, direction_is_up=True, latest_close=101.0,
        current_volume=100, average_volume=100,
    )
    result = evaluate_confirmation(config, inputs)
    assert result.checks["candle_close"] is True
    assert result.checks["pct_penetration"] is True
    assert result.checks["volume"] is False
    assert result.confirmed is False
