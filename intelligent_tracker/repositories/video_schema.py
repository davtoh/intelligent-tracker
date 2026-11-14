"""SQLite Video Run Schema & Media Offset Migration Helper.

Defines the ``video_runs`` table (Single Source of Truth for batch indexing
and live-recording analytics runs) and idempotent column migrations adding
``video_filename`` and ``media_offset_sec`` to ``sightings``,
``world_timeline_events``, and ``review_queue``.
"""

import os
import sqlite3

_VIDEO_EXTENSIONS = (".mp4", ".mkv", ".avi", ".mov")

UPSERT_VIDEO_RUN_SQL = """
INSERT INTO video_runs (
    run_id, video_filename, base_filename, run_type, generated_at, timestamp,
    source_resolution, source_fps, config_json, metrics_json, report_json,
    frame_detections_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(run_id) DO UPDATE SET
    video_filename = excluded.video_filename, base_filename = excluded.base_filename,
    run_type = excluded.run_type, generated_at = excluded.generated_at,
    timestamp = excluded.timestamp, source_resolution = excluded.source_resolution,
    source_fps = excluded.source_fps, config_json = excluded.config_json,
    metrics_json = excluded.metrics_json, report_json = excluded.report_json,
    frame_detections_json = COALESCE(excluded.frame_detections_json, video_runs.frame_detections_json)
"""


def safe_video_basename(filename: str) -> str:
    """Extract canonical basename to prevent path traversal."""
    return os.path.basename(str(filename or "").strip())


def canonical_video_base_name(filename: str) -> str:
    """Normalize ``*_h264.*`` child filenames to their base ``*.mp4`` name."""
    safe_name = safe_video_basename(filename)
    stem, _ = os.path.splitext(safe_name)
    return f"{stem[:-5]}.mp4" if stem.lower().endswith("_h264") else safe_name


def expand_video_aliases(filename: str) -> list[str]:
    """Return ordered unique filename aliases for unified parent/_h264 lookup."""
    safe_name = safe_video_basename(filename)
    if not safe_name:
        return []
    canonical = canonical_video_base_name(safe_name)
    stem, _ = os.path.splitext(canonical)
    candidates = [safe_name, canonical, f"{stem}_h264.mp4"] + [
        f"{stem}{ext}" for ext in _VIDEO_EXTENSIONS
    ]
    return list(dict.fromkeys(c for c in candidates if c))

_VIDEO_RUNS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS video_runs (
    run_id TEXT PRIMARY KEY,
    video_filename TEXT NOT NULL,
    base_filename TEXT NOT NULL,
    run_type TEXT NOT NULL DEFAULT 'batch',
    generated_at TEXT DEFAULT '',
    timestamp REAL NOT NULL DEFAULT 0.0,
    source_resolution TEXT,
    source_fps REAL,
    config_json TEXT DEFAULT '{}',
    metrics_json TEXT DEFAULT '{}',
    report_json TEXT DEFAULT '{}',
    frame_detections_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

_VIDEO_RUNS_INDEXES_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_video_runs_filename ON video_runs(video_filename, timestamp DESC);",
    "CREATE INDEX IF NOT EXISTS idx_video_runs_base ON video_runs(base_filename, timestamp DESC);",
)

_MEDIA_COLUMN_MIGRATIONS = (
    ("sightings", "video_filename", "TEXT DEFAULT ''"),
    ("sightings", "media_offset_sec", "REAL DEFAULT 0.0"),
    ("world_timeline_events", "video_filename", "TEXT DEFAULT ''"),
    ("world_timeline_events", "media_offset_sec", "REAL DEFAULT 0.0"),
    ("review_queue", "video_filename", "TEXT DEFAULT ''"),
    ("review_queue", "media_offset_sec", "REAL DEFAULT 0.0"),
)


def _existing_columns(cursor: sqlite3.Cursor, table_name: str) -> set[str]:
    """Return existing column names for ``table_name`` (empty set if missing)."""
    rows = cursor.execute(f"PRAGMA table_info({table_name});").fetchall()
    return {row[1] for row in rows}


def apply_video_schema_migrations(cursor: sqlite3.Cursor) -> None:
    """Idempotently create ``video_runs`` and add media-offset columns."""
    cursor.execute(_VIDEO_RUNS_TABLE_SQL)
    for index_sql in _VIDEO_RUNS_INDEXES_SQL:
        cursor.execute(index_sql)

    col_cache: dict[str, set[str]] = {}
    for table_name, col_name, col_def in _MEDIA_COLUMN_MIGRATIONS:
        if table_name not in col_cache:
            col_cache[table_name] = _existing_columns(cursor, table_name)
        cols = col_cache[table_name]
        if cols and col_name not in cols:
            cursor.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def};"
            )
            cols.add(col_name)
