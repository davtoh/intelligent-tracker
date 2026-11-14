"""Versioned SQLite Memory & FTS5 Schema Migration Helper.

Manages the ``PRAGMA user_version = 1`` schema upgrade for long-term entity
confidence state and full-text searchable world timeline events without
disturbing pre-existing v0 tables or rows.
"""

import sqlite3

MEMORY_SCHEMA_VERSION = 1

_CONFIDENCE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS entity_confidence_state (
    entity_id INTEGER PRIMARY KEY,
    confidence REAL NOT NULL DEFAULT 0.5,
    face_score REAL DEFAULT 0.0,
    body_score REAL DEFAULT 0.0,
    streak_count INTEGER DEFAULT 0,
    observation_count INTEGER DEFAULT 0,
    confirmation_count INTEGER DEFAULT 0,
    rejection_count INTEGER DEFAULT 0,
    ambiguity_penalty REAL DEFAULT 0.0,
    last_camera_id TEXT DEFAULT '',
    last_zone_id TEXT DEFAULT '',
    last_seen_at REAL NOT NULL DEFAULT 0.0,
    evidence_json TEXT DEFAULT '{}',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
);
"""

_TIMELINE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS world_timeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL DEFAULT 'sighting',
    entity_id INTEGER,
    entity_name TEXT DEFAULT '',
    category TEXT DEFAULT '',
    camera_id TEXT DEFAULT '',
    zone_id TEXT DEFAULT '',
    timestamp REAL NOT NULL,
    confidence REAL DEFAULT 1.0,
    title TEXT DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    tags TEXT DEFAULT '',
    metadata_json TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE SET NULL
);
"""

_TIMELINE_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS world_timeline_fts USING fts5(
    title,
    summary,
    entity_name,
    category,
    camera_id,
    zone_id,
    event_type,
    tags,
    content='world_timeline_events',
    content_rowid='id',
    tokenize='porter unicode61'
);
"""

_TIMELINE_TRIGGERS_SQL = (
    """
    CREATE TRIGGER IF NOT EXISTS world_timeline_events_ai
    AFTER INSERT ON world_timeline_events BEGIN
        INSERT INTO world_timeline_fts(
            rowid, title, summary, entity_name, category, camera_id, zone_id, event_type, tags
        ) VALUES (
            new.id, new.title, new.summary, new.entity_name, new.category,
            new.camera_id, new.zone_id, new.event_type, new.tags
        );
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS world_timeline_events_ad
    AFTER DELETE ON world_timeline_events BEGIN
        INSERT INTO world_timeline_fts(
            world_timeline_fts, rowid, title, summary, entity_name, category,
            camera_id, zone_id, event_type, tags
        ) VALUES (
            'delete', old.id, old.title, old.summary, old.entity_name, old.category,
            old.camera_id, old.zone_id, old.event_type, old.tags
        );
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS world_timeline_events_au
    AFTER UPDATE ON world_timeline_events BEGIN
        INSERT INTO world_timeline_fts(
            world_timeline_fts, rowid, title, summary, entity_name, category,
            camera_id, zone_id, event_type, tags
        ) VALUES (
            'delete', old.id, old.title, old.summary, old.entity_name, old.category,
            old.camera_id, old.zone_id, old.event_type, old.tags
        );
        INSERT INTO world_timeline_fts(
            rowid, title, summary, entity_name, category, camera_id, zone_id, event_type, tags
        ) VALUES (
            new.id, new.title, new.summary, new.entity_name, new.category,
            new.camera_id, new.zone_id, new.event_type, new.tags
        );
    END;
    """,
)

_MEMORY_INDEXES_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_entity_confidence_score ON entity_confidence_state(confidence DESC, last_seen_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_world_timeline_ts ON world_timeline_events(timestamp DESC);",
    "CREATE INDEX IF NOT EXISTS idx_world_timeline_entity ON world_timeline_events(entity_id, timestamp DESC);",
    "CREATE INDEX IF NOT EXISTS idx_world_timeline_cam_zone ON world_timeline_events(camera_id, zone_id, timestamp DESC);",
    "CREATE INDEX IF NOT EXISTS idx_world_timeline_type ON world_timeline_events(event_type, timestamp DESC);",
)


def apply_memory_schema_migrations(cursor: sqlite3.Cursor) -> int:
    """Idempotently migrate SQLite schema to ``MEMORY_SCHEMA_VERSION`` (1)."""
    row = cursor.execute("PRAGMA user_version;").fetchone()
    current_version = int(row[0]) if row else 0
    if current_version >= MEMORY_SCHEMA_VERSION:
        return current_version

    cursor.execute(_CONFIDENCE_TABLE_SQL)
    cursor.execute(_TIMELINE_TABLE_SQL)
    cursor.execute(_TIMELINE_FTS_SQL)
    for trigger_sql in _TIMELINE_TRIGGERS_SQL:
        cursor.execute(trigger_sql)
    for index_sql in _MEMORY_INDEXES_SQL:
        cursor.execute(index_sql)
    cursor.execute(f"PRAGMA user_version = {MEMORY_SCHEMA_VERSION};")
    return MEMORY_SCHEMA_VERSION

