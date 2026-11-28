"""SQLite Schema v6: Alert Promotion Rules & Alert Policy Settings."""

import sqlite3

ALERT_PROMOTION_RULES_DDL = """CREATE TABLE IF NOT EXISTS alert_promotion_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    event_type TEXT NOT NULL DEFAULT '',
    zone_id TEXT NOT NULL DEFAULT '',
    camera_id TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    min_dwell_time REAL DEFAULT NULL,
    target_severity TEXT NOT NULL DEFAULT 'warning',
    add_tags TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);"""

ALERT_POLICY_SETTINGS_DDL = """CREATE TABLE IF NOT EXISTS alert_policy_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    dwell_override REAL DEFAULT NULL,
    alert_sensitivity REAL NOT NULL DEFAULT 1.0,
    quiet_hours_json TEXT DEFAULT NULL,
    extra_json TEXT NOT NULL DEFAULT '{}',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);"""

ALERT_RULES_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_alert_promotion_rules_enabled ON alert_promotion_rules(enabled);",
)


def ensure_alert_rules_schema(conn_or_cursor: sqlite3.Connection | sqlite3.Cursor) -> None:
    """Idempotently create SQLite v6 alert promotion rules and policy tables."""
    conn_or_cursor.execute(ALERT_PROMOTION_RULES_DDL)
    conn_or_cursor.execute(ALERT_POLICY_SETTINGS_DDL)
    for stmt in ALERT_RULES_INDEXES:
        conn_or_cursor.execute(stmt)


def _migrate_v6_alert_rules(cursor: sqlite3.Cursor) -> None:
    """Create alert_promotion_rules & alert_policy_settings tables and advance schema to v6."""
    ensure_alert_rules_schema(cursor)
    cursor.execute("PRAGMA user_version = 6;")
