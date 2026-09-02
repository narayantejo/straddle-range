-- Monthly S/R levels: one immutable row per stock per monthly cycle.
-- Never UPDATEd or DELETEd once written (spec Section 32: never overwrite history).
CREATE TABLE IF NOT EXISTS monthly_levels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    company_name TEXT NOT NULL,
    calculation_month TEXT NOT NULL,        -- e.g. "2026-08" (the cycle these levels govern)
    reference_expiry_date TEXT NOT NULL,    -- previous monthly expiry -> SPOT_LEVEL source
    reference_spot_price REAL NOT NULL,
    pricing_expiry_date TEXT NOT NULL,      -- next monthly expiry -> ATM CE/PE source
    atm_strike REAL NOT NULL,
    atm_ce REAL NOT NULL,
    atm_pe REAL NOT NULL,
    straddle_value REAL NOT NULL,
    midpoint REAL NOT NULL,
    s2 REAL NOT NULL,
    s1 REAL NOT NULL,
    r1 REAL NOT NULL,
    r2 REAL NOT NULL,
    s2_lower_zone REAL NOT NULL,
    s2_upper_zone REAL NOT NULL,
    s1_lower_zone REAL NOT NULL,
    s1_upper_zone REAL NOT NULL,
    r1_lower_zone REAL NOT NULL,
    r1_upper_zone REAL NOT NULL,
    r2_lower_zone REAL NOT NULL,
    r2_upper_zone REAL NOT NULL,
    zone_pct REAL NOT NULL,
    calculation_timestamp TEXT NOT NULL,
    data_source TEXT NOT NULL DEFAULT 'DhanHQ',
    UNIQUE (symbol, calculation_month)
);

CREATE INDEX IF NOT EXISTS idx_monthly_levels_symbol ON monthly_levels(symbol);

-- Daily scan snapshots: append-only, one row per stock per scan.
CREATE TABLE IF NOT EXISTS daily_scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    monthly_level_id INTEGER NOT NULL REFERENCES monthly_levels(id),
    symbol TEXT NOT NULL,
    scan_date TEXT NOT NULL,
    scan_timestamp TEXT NOT NULL,
    spot REAL NOT NULL,
    futures_price REAL,
    volume REAL,
    volume_change_pct REAL,
    futures_oi REAL,
    futures_oi_change_pct REAL,
    distance_s2 REAL NOT NULL,
    distance_s1 REAL NOT NULL,
    distance_r1 REAL NOT NULL,
    distance_r2 REAL NOT NULL,
    distance_pct_s2 REAL NOT NULL,
    distance_pct_s1 REAL NOT NULL,
    distance_pct_r1 REAL NOT NULL,
    distance_pct_r2 REAL NOT NULL,
    zone_status_s2 TEXT NOT NULL,
    zone_status_s1 TEXT NOT NULL,
    zone_status_r1 TEXT NOT NULL,
    zone_status_r2 TEXT NOT NULL,
    reaction_s2 TEXT,      -- FAR/APPROACHING/VERY_CLOSE/INSIDE_ZONE/TOUCH/BOUNCE/BREAKDOWN
    reaction_s1 TEXT,
    reaction_r1 TEXT,      -- FAR/APPROACHING/VERY_CLOSE/INSIDE_ZONE/TOUCH/REJECTED/BREAKOUT
    reaction_r2 TEXT,
    nearest_support TEXT,
    nearest_support_distance_pct REAL,
    nearest_resistance TEXT,
    nearest_resistance_distance_pct REAL,
    absolute_nearest_level TEXT NOT NULL,
    absolute_nearest_level_distance_pct REAL NOT NULL,
    direction TEXT,
    signal_type TEXT,
    signal_score REAL,
    signal_level TEXT,     -- which of S2/S1/R1/R2 the best signal_score/signal_type refers to
    ce_watch INTEGER NOT NULL DEFAULT 0,  -- option-buying mode: support approach/reaction (Section 28)
    pe_watch INTEGER NOT NULL DEFAULT 0   -- option-buying mode: resistance approach/reaction (Section 28)
);

CREATE INDEX IF NOT EXISTS idx_daily_scans_symbol_date ON daily_scans(symbol, scan_date);
CREATE INDEX IF NOT EXISTS idx_daily_scans_monthly_level ON daily_scans(monthly_level_id);

-- Configurable alert rules (spec Section 39). One row per (symbol, level, condition);
-- symbol NULL means the rule applies globally to every stock.
CREATE TABLE IF NOT EXISTS alert_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,                    -- NULL = applies to all stocks
    level_type TEXT NOT NULL,       -- S1, S2, R1, R2, or 'ANY'
    condition_type TEXT NOT NULL,   -- WITHIN_PCT, INSIDE_ZONE, TOUCH, BOUNCE, REJECTED, BREAKOUT, BREAKDOWN
    threshold_pct REAL,             -- used when condition_type = WITHIN_PCT
    enabled INTEGER NOT NULL DEFAULT 1,
    channels TEXT NOT NULL DEFAULT 'dashboard',  -- comma-separated: dashboard,email,telegram
    created_at TEXT NOT NULL
);

-- Fired alerts, append-only. One row per (rule, symbol, level, condition, scan_date) so the
-- same condition doesn't re-fire every scan within the same trading day.
CREATE TABLE IF NOT EXISTS alert_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER REFERENCES alert_rules(id),
    symbol TEXT NOT NULL,
    level_type TEXT NOT NULL,
    condition_type TEXT NOT NULL,
    message TEXT NOT NULL,
    scan_date TEXT NOT NULL,
    fired_at TEXT NOT NULL,
    channels_sent TEXT NOT NULL DEFAULT '',
    UNIQUE (rule_id, symbol, level_type, condition_type, scan_date)
);

CREATE INDEX IF NOT EXISTS idx_alert_log_fired_at ON alert_log(fired_at);
CREATE INDEX IF NOT EXISTS idx_alert_log_symbol ON alert_log(symbol);
