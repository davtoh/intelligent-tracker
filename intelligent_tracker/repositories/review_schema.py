"""
Schema v5 Migration Helper for Reversible Active Learning Review Decisions.

Defines the ``review_decisions`` audit table DDL, indexes, and idempotent
``PRAGMA user_version = 5`` migration helper.
"""

import sqlite3

REVIEW_DECISIONS_DDL = """CREATE TABLE IF NOT EXISTS review_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    prior_status TEXT DEFAULT 'pending',
    prior_entity_id INTEGER,
    new_entity_id INTEGER,
    created_signature_id INTEGER,
    created_descriptor_version_id INTEGER,
    created_sighting_id INTEGER,
    created_negative_exemplar_id INTEGER,
    created_entity_id INTEGER,
    prior_state_json TEXT DEFAULT '{}',
    reviewer TEXT DEFAULT 'operator',
    notes TEXT DEFAULT '',
    undone INTEGER DEFAULT 0,
    undone_at TIMESTAMP,
    undone_by TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (review_id) REFERENCES review_queue(id) ON DELETE CASCADE
);"""

REVIEW_DECISIONS_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_review_decisions_review "
    "ON review_decisions(review_id, id DESC);",
    "CREATE INDEX IF NOT EXISTS idx_review_decisions_undone "
    "ON review_decisions(undone, created_at DESC);",
)


def _migrate_v5_review_decisions(cursor: sqlite3.Cursor) -> None:
    """Create schema v5 ``review_decisions`` audit table and indexes idempotently."""
    cursor.execute(REVIEW_DECISIONS_DDL)
    for stmt in REVIEW_DECISIONS_INDEXES:
        cursor.execute(stmt)
    cursor.execute("PRAGMA user_version = 5;")
