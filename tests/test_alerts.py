import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app import config
from app.alerts import engine
from app.alerts.rules import (
    CONDITION_BOUNCE,
    CONDITION_BREAKDOWN,
    CONDITION_INSIDE_ZONE,
    CONDITION_TOUCH,
    CONDITION_WITHIN_PCT,
    LEVEL_ANY,
)
from app.db import database as db
from app.engine.formulas import ZONE_STATUS_FAR, ZONE_STATUS_INSIDE_ZONE, ZONE_STATUS_TOUCH


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    return tmp_path


def _make_row(symbol="TESTSTK", **overrides) -> db.DailyScanRow:
    defaults = dict(
        monthly_level_id=1,
        symbol=symbol,
        scan_date="2026-08-29",
        scan_timestamp="2026-08-29T10:00:00+00:00",
        spot=100.0,
        distance_s2=-20.0,
        distance_s1=-1.0,
        distance_r1=15.0,
        distance_r2=30.0,
        distance_pct_s2=-16.0,
        distance_pct_s1=-1.0,
        distance_pct_r1=13.0,
        distance_pct_r2=24.0,
        zone_status_s2=ZONE_STATUS_FAR,
        zone_status_s1=ZONE_STATUS_TOUCH,
        zone_status_r1=ZONE_STATUS_FAR,
        zone_status_r2=ZONE_STATUS_FAR,
        reaction_s2=ZONE_STATUS_FAR,
        reaction_s1=CONDITION_BOUNCE,
        reaction_r1=ZONE_STATUS_FAR,
        reaction_r2=ZONE_STATUS_FAR,
        absolute_nearest_level="S1",
        absolute_nearest_level_distance_pct=1.0,
    )
    defaults.update(overrides)
    return db.DailyScanRow(**defaults)


def test_within_pct_rule_fires(temp_db):
    db.insert_alert_rule(db.AlertRuleRow(level_type="S1", condition_type=CONDITION_WITHIN_PCT, threshold_pct=2.0))
    rules = db.get_all_alert_rules()
    row = _make_row()
    fired = engine.evaluate_scan_row(row, rules)
    assert len(fired) == 1
    assert fired[0].condition_type == CONDITION_WITHIN_PCT
    assert fired[0].level_type == "S1"


def test_within_pct_rule_does_not_fire_when_far(temp_db):
    db.insert_alert_rule(db.AlertRuleRow(level_type="R1", condition_type=CONDITION_WITHIN_PCT, threshold_pct=2.0))
    rules = db.get_all_alert_rules()
    row = _make_row()  # R1 distance_pct is 13%, well outside 2%
    fired = engine.evaluate_scan_row(row, rules)
    assert fired == []


def test_bounce_rule_fires_on_matching_reaction(temp_db):
    db.insert_alert_rule(db.AlertRuleRow(level_type="S1", condition_type=CONDITION_BOUNCE))
    rules = db.get_all_alert_rules()
    row = _make_row()
    fired = engine.evaluate_scan_row(row, rules)
    assert any(f.condition_type == CONDITION_BOUNCE for f in fired)


def test_touch_rule_matches_zone_status(temp_db):
    db.insert_alert_rule(db.AlertRuleRow(level_type="S1", condition_type=CONDITION_TOUCH))
    rules = db.get_all_alert_rules()
    row = _make_row()
    fired = engine.evaluate_scan_row(row, rules)
    assert any(f.condition_type == CONDITION_TOUCH for f in fired)


def test_inside_zone_matches_touch_too(temp_db):
    """TOUCH is a stricter subset of INSIDE_ZONE-family statuses, so an
    INSIDE_ZONE alert rule should still catch a TOUCH condition."""
    db.insert_alert_rule(db.AlertRuleRow(level_type="S1", condition_type=CONDITION_INSIDE_ZONE))
    rules = db.get_all_alert_rules()
    row = _make_row()  # zone_status_s1 = TOUCH
    fired = engine.evaluate_scan_row(row, rules)
    assert any(f.condition_type == CONDITION_INSIDE_ZONE for f in fired)


def test_any_level_expands_to_all_four(temp_db):
    db.insert_alert_rule(db.AlertRuleRow(level_type=LEVEL_ANY, condition_type=CONDITION_WITHIN_PCT, threshold_pct=50.0))
    rules = db.get_all_alert_rules()
    row = _make_row()
    fired = engine.evaluate_scan_row(row, rules)
    fired_levels = {f.level_type for f in fired}
    assert fired_levels == {"S1", "S2", "R1", "R2"}


def test_symbol_scoped_rule_ignores_other_symbols(temp_db):
    db.insert_alert_rule(
        db.AlertRuleRow(symbol="OTHERSTOCK", level_type="S1", condition_type=CONDITION_WITHIN_PCT, threshold_pct=5.0)
    )
    rules = db.get_all_alert_rules()
    row = _make_row(symbol="TESTSTK")
    fired = engine.evaluate_scan_row(row, rules)
    assert fired == []


def test_duplicate_alert_same_day_does_not_refire(temp_db):
    db.insert_alert_rule(db.AlertRuleRow(level_type="S1", condition_type=CONDITION_WITHIN_PCT, threshold_pct=2.0))
    rules = db.get_all_alert_rules()
    row = _make_row()
    first = engine.evaluate_scan_row(row, rules)
    second = engine.evaluate_scan_row(row, rules)
    assert len(first) == 1
    assert len(second) == 0  # deduped by (rule, symbol, level, condition, scan_date)


def test_disabled_rule_does_not_fire(temp_db):
    db.insert_alert_rule(
        db.AlertRuleRow(level_type="S1", condition_type=CONDITION_WITHIN_PCT, threshold_pct=2.0, enabled=0)
    )
    rules = db.get_all_alert_rules(enabled_only=True)
    assert rules == []


def test_breakdown_condition_does_not_match_bounce_reaction(temp_db):
    db.insert_alert_rule(db.AlertRuleRow(level_type="S1", condition_type=CONDITION_BREAKDOWN))
    rules = db.get_all_alert_rules()
    row = _make_row()  # reaction_s1 = BOUNCE, not BREAKDOWN
    fired = engine.evaluate_scan_row(row, rules)
    assert fired == []
