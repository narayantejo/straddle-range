"""
Alert evaluation engine.

Evaluates a just-computed daily scan row against the configured alert rules
and logs any that fire (deduped per rule+symbol+level+condition+day via the
alert_log UNIQUE constraint, so re-running the scanner mid-day doesn't spam
duplicate alerts). Dispatches to whichever channels the rule requests.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.alerts import notifiers
from app.alerts.rules import (
    CONDITION_BOUNCE,
    CONDITION_BREAKDOWN,
    CONDITION_BREAKOUT,
    CONDITION_INSIDE_ZONE,
    CONDITION_REJECTED,
    CONDITION_TOUCH,
    CONDITION_WITHIN_PCT,
    LEVEL_ANY,
)
from app.db import database as db
from app.engine.formulas import ZONE_STATUS_INSIDE_ZONE, ZONE_STATUS_TOUCH, ZONE_STATUS_VERY_CLOSE

_INSIDE_ZONE_STATUSES = frozenset({ZONE_STATUS_INSIDE_ZONE, ZONE_STATUS_VERY_CLOSE, ZONE_STATUS_TOUCH})


@dataclass(frozen=True)
class FiredAlert:
    symbol: str
    level_type: str
    condition_type: str
    message: str
    channels: list[str]


def _level_data(row: db.DailyScanRow, level: str) -> dict:
    key = level.lower()
    return {
        "distance_pct": getattr(row, f"distance_pct_{key}"),
        "zone_status": getattr(row, f"zone_status_{key}"),
        "reaction": getattr(row, f"reaction_{key}"),
    }


def _condition_matches(condition_type: str, threshold_pct: float | None, data: dict) -> bool:
    if condition_type == CONDITION_WITHIN_PCT:
        return threshold_pct is not None and abs(data["distance_pct"]) <= threshold_pct
    if condition_type == CONDITION_INSIDE_ZONE:
        return data["zone_status"] in _INSIDE_ZONE_STATUSES
    if condition_type == CONDITION_TOUCH:
        return data["zone_status"] == ZONE_STATUS_TOUCH
    if condition_type == CONDITION_BOUNCE:
        return data["reaction"] == CONDITION_BOUNCE
    if condition_type == CONDITION_REJECTED:
        return data["reaction"] == CONDITION_REJECTED
    if condition_type == CONDITION_BREAKOUT:
        return data["reaction"] == CONDITION_BREAKOUT
    if condition_type == CONDITION_BREAKDOWN:
        return data["reaction"] == CONDITION_BREAKDOWN
    return False


def _message(symbol: str, level_type: str, condition_type: str, data: dict) -> str:
    return (
        f"{symbol}: {level_type} {condition_type} "
        f"(distance {data['distance_pct']:+.2f}%, zone={data['zone_status']}, reaction={data['reaction']})"
    )


def evaluate_scan_row(row: db.DailyScanRow, rules: list) -> list[FiredAlert]:
    """rules: list of sqlite3.Row from db.get_all_alert_rules(), each with
    symbol/level_type/condition_type/threshold_pct/channels/id."""
    fired: list[FiredAlert] = []

    for rule in rules:
        if rule["symbol"] is not None and rule["symbol"] != row.symbol:
            continue

        levels_to_check = ("S1", "S2", "R1", "R2") if rule["level_type"] == LEVEL_ANY else (rule["level_type"],)
        for level_type in levels_to_check:
            data = _level_data(row, level_type)
            if not _condition_matches(rule["condition_type"], rule["threshold_pct"], data):
                continue

            message = _message(row.symbol, level_type, rule["condition_type"], data)
            channels = [c.strip() for c in rule["channels"].split(",") if c.strip()]

            new_id = db.insert_alert_log(
                rule_id=rule["id"],
                symbol=row.symbol,
                level_type=level_type,
                condition_type=rule["condition_type"],
                message=message,
                scan_date=row.scan_date,
                channels_sent="",
            )
            if new_id is None:
                continue  # already fired today for this rule+symbol+level+condition

            sent = notifiers.dispatch(channels, message)
            if sent:
                with db.get_conn() as conn:
                    conn.execute(
                        "UPDATE alert_log SET channels_sent = ? WHERE id = ?",
                        (",".join(sent), new_id),
                    )

            fired.append(
                FiredAlert(
                    symbol=row.symbol,
                    level_type=level_type,
                    condition_type=rule["condition_type"],
                    message=message,
                    channels=channels,
                )
            )

    return fired


def evaluate_scan_rows(rows: list[db.DailyScanRow]) -> list[FiredAlert]:
    rules = db.get_all_alert_rules(enabled_only=True)
    if not rules:
        return []
    fired: list[FiredAlert] = []
    for row in rows:
        fired.extend(evaluate_scan_row(row, rules))
    return fired
