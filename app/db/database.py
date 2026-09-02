from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from app import config

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


_DAILY_SCANS_MIGRATIONS = [
    ("reaction_s2", "TEXT"),
    ("reaction_s1", "TEXT"),
    ("reaction_r1", "TEXT"),
    ("reaction_r2", "TEXT"),
    ("signal_level", "TEXT"),
    ("ce_watch", "INTEGER NOT NULL DEFAULT 0"),
    ("pe_watch", "INTEGER NOT NULL DEFAULT 0"),
]


def _migrate_daily_scans(conn: sqlite3.Connection) -> None:
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(daily_scans)")}
    for col_name, col_type in _DAILY_SCANS_MIGRATIONS:
        if col_name not in existing_cols:
            conn.execute(f"ALTER TABLE daily_scans ADD COLUMN {col_name} {col_type}")


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA_PATH.read_text())
        _migrate_daily_scans(conn)
        conn.commit()


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


@dataclass
class MonthlyLevelRow:
    symbol: str
    company_name: str
    calculation_month: str
    reference_expiry_date: str
    reference_spot_price: float
    pricing_expiry_date: str
    atm_strike: float
    atm_ce: float
    atm_pe: float
    straddle_value: float
    midpoint: float
    s2: float
    s1: float
    r1: float
    r2: float
    s2_lower_zone: float
    s2_upper_zone: float
    s1_lower_zone: float
    s1_upper_zone: float
    r1_lower_zone: float
    r1_upper_zone: float
    r2_lower_zone: float
    r2_upper_zone: float
    zone_pct: float
    calculation_timestamp: str
    data_source: str = "DhanHQ"


def insert_monthly_levels(row: MonthlyLevelRow) -> int:
    """Insert a new immutable monthly level row. Raises sqlite3.IntegrityError
    if a row for (symbol, calculation_month) already exists -- callers must
    not overwrite historical monthly levels (spec Section 32)."""
    fields = asdict(row)
    cols = ", ".join(fields.keys())
    placeholders = ", ".join(f":{k}" for k in fields.keys())
    with get_conn() as conn:
        cur = conn.execute(
            f"INSERT INTO monthly_levels ({cols}) VALUES ({placeholders})", fields
        )
        return cur.lastrowid


def get_latest_monthly_levels(symbol: str) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM monthly_levels WHERE symbol = ? "
            "ORDER BY reference_expiry_date DESC LIMIT 1",
            (symbol,),
        )
        return cur.fetchone()


def get_monthly_levels_for_month(symbol: str, calculation_month: str) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM monthly_levels WHERE symbol = ? AND calculation_month = ?",
            (symbol, calculation_month),
        )
        return cur.fetchone()


def get_all_latest_monthly_levels() -> list[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.execute(
            """
            SELECT ml.* FROM monthly_levels ml
            INNER JOIN (
                SELECT symbol, MAX(reference_expiry_date) AS max_ref
                FROM monthly_levels GROUP BY symbol
            ) latest
            ON ml.symbol = latest.symbol AND ml.reference_expiry_date = latest.max_ref
            """
        )
        return cur.fetchall()


def get_monthly_level_history(symbol: str) -> list[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM monthly_levels WHERE symbol = ? ORDER BY reference_expiry_date ASC",
            (symbol,),
        )
        return cur.fetchall()


@dataclass
class DailyScanRow:
    monthly_level_id: int
    symbol: str
    scan_date: str
    scan_timestamp: str
    spot: float
    distance_s2: float
    distance_s1: float
    distance_r1: float
    distance_r2: float
    distance_pct_s2: float
    distance_pct_s1: float
    distance_pct_r1: float
    distance_pct_r2: float
    zone_status_s2: str
    zone_status_s1: str
    zone_status_r1: str
    zone_status_r2: str
    absolute_nearest_level: str
    absolute_nearest_level_distance_pct: float
    futures_price: Optional[float] = None
    volume: Optional[float] = None
    volume_change_pct: Optional[float] = None
    futures_oi: Optional[float] = None
    futures_oi_change_pct: Optional[float] = None
    nearest_support: Optional[str] = None
    nearest_support_distance_pct: Optional[float] = None
    nearest_resistance: Optional[str] = None
    nearest_resistance_distance_pct: Optional[float] = None
    direction: Optional[str] = None
    signal_type: Optional[str] = None
    signal_score: Optional[float] = None
    signal_level: Optional[str] = None
    reaction_s2: Optional[str] = None
    reaction_s1: Optional[str] = None
    reaction_r1: Optional[str] = None
    reaction_r2: Optional[str] = None
    ce_watch: int = 0
    pe_watch: int = 0


def insert_daily_scan(row: DailyScanRow) -> int:
    fields = asdict(row)
    cols = ", ".join(fields.keys())
    placeholders = ", ".join(f":{k}" for k in fields.keys())
    with get_conn() as conn:
        cur = conn.execute(
            f"INSERT INTO daily_scans ({cols}) VALUES ({placeholders})", fields
        )
        return cur.lastrowid


def get_latest_scan_for_symbol(symbol: str) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM daily_scans WHERE symbol = ? ORDER BY scan_timestamp DESC LIMIT 1",
            (symbol,),
        )
        return cur.fetchone()


def get_latest_scan_all_symbols() -> list[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.execute(
            """
            SELECT ds.* FROM daily_scans ds
            INNER JOIN (
                SELECT symbol, MAX(scan_timestamp) AS max_ts
                FROM daily_scans GROUP BY symbol
            ) latest
            ON ds.symbol = latest.symbol AND ds.scan_timestamp = latest.max_ts
            """
        )
        return cur.fetchall()


def get_scan_history(symbol: str, limit: int = 500) -> list[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM daily_scans WHERE symbol = ? ORDER BY scan_timestamp DESC LIMIT ?",
            (symbol, limit),
        )
        return cur.fetchall()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AlertRuleRow:
    level_type: str
    condition_type: str
    symbol: Optional[str] = None
    threshold_pct: Optional[float] = None
    enabled: int = 1
    channels: str = "dashboard"
    created_at: str = ""


def insert_alert_rule(row: AlertRuleRow) -> int:
    if not row.created_at:
        row.created_at = now_iso()
    fields = asdict(row)
    cols = ", ".join(fields.keys())
    placeholders = ", ".join(f":{k}" for k in fields.keys())
    with get_conn() as conn:
        cur = conn.execute(f"INSERT INTO alert_rules ({cols}) VALUES ({placeholders})", fields)
        return cur.lastrowid


def delete_alert_rule(rule_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM alert_rules WHERE id = ?", (rule_id,))


def get_all_alert_rules(enabled_only: bool = True) -> list[sqlite3.Row]:
    with get_conn() as conn:
        if enabled_only:
            cur = conn.execute("SELECT * FROM alert_rules WHERE enabled = 1")
        else:
            cur = conn.execute("SELECT * FROM alert_rules")
        return cur.fetchall()


def insert_alert_log(
    rule_id: Optional[int],
    symbol: str,
    level_type: str,
    condition_type: str,
    message: str,
    scan_date: str,
    channels_sent: str = "",
) -> Optional[int]:
    """Returns the new row id, or None if this exact alert already fired today
    (UNIQUE constraint on rule_id+symbol+level_type+condition_type+scan_date)."""
    with get_conn() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO alert_log "
                "(rule_id, symbol, level_type, condition_type, message, scan_date, fired_at, channels_sent) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (rule_id, symbol, level_type, condition_type, message, scan_date, now_iso(), channels_sent),
            )
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None


def get_recent_alerts(limit: int = 200) -> list[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM alert_log ORDER BY fired_at DESC LIMIT ?", (limit,))
        return cur.fetchall()
