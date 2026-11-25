"""
Database Schema Initialization and Migration Mixin.

Manages SQLite DDL table schemas, indexes, pragma tuning, and seed data
for the Intelligent Tracker persistence subsystem.
"""

import logging
import sqlite3
from typing import Any

from intelligent_tracker.category_registry import DEFAULT_CUSTOM_CATEGORIES, migrate_category_registry
from intelligent_tracker.repositories.memory_schema import apply_memory_schema_migrations
from intelligent_tracker.repositories.video_schema import apply_video_schema_migrations

logger = logging.getLogger(__name__)

_CORE_TABLES_DDL = (
    """CREATE TABLE IF NOT EXISTS entities (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
        category TEXT DEFAULT 'person', status TEXT DEFAULT 'active', notes TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );""",
    """CREATE TABLE IF NOT EXISTS entity_signatures (
        id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id INTEGER NOT NULL,
        embedding BLOB NOT NULL, crop_path TEXT DEFAULT '',
        is_anchor INTEGER DEFAULT 0, locked INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
    );""",
    """CREATE TABLE IF NOT EXISTS sightings (
        id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id INTEGER, track_id INTEGER,
        source TEXT DEFAULT '', timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        zone_id TEXT DEFAULT '', bbox TEXT DEFAULT '', confidence REAL DEFAULT 1.0,
        snapshot_path TEXT DEFAULT '', camera_id TEXT DEFAULT '', run_id TEXT DEFAULT '',
        FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE SET NULL
    );""",
    """CREATE TABLE IF NOT EXISTS descriptor_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id INTEGER NOT NULL,
        version_num INTEGER NOT NULL, embedding BLOB NOT NULL,
        crop_path TEXT DEFAULT '', source TEXT DEFAULT 'manual_enrollment',
        notes TEXT DEFAULT '', is_anchor INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
    );""",
)

_SPATIAL_TABLES_DDL = (
    """CREATE TABLE IF NOT EXISTS spatial_zones (
        id INTEGER PRIMARY KEY AUTOINCREMENT, camera_id TEXT NOT NULL, name TEXT NOT NULL,
        polygon_json TEXT NOT NULL, category_filter TEXT DEFAULT '',
        dwell_threshold REAL DEFAULT 5.0, capacity_limit INTEGER, color TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(camera_id, name)
    );""",
    """CREATE TABLE IF NOT EXISTS spatial_tripwires (
        id INTEGER PRIMARY KEY AUTOINCREMENT, camera_id TEXT NOT NULL, name TEXT NOT NULL,
        line_segment_json TEXT NOT NULL, bidirectional INTEGER DEFAULT 1, color TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(camera_id, name)
    );""",
    """CREATE TABLE IF NOT EXISTS spatial_transitions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, link_id TEXT UNIQUE NOT NULL,
        source_camera TEXT NOT NULL, source_zone TEXT NOT NULL,
        target_camera TEXT NOT NULL, target_zone TEXT NOT NULL,
        t_min REAL DEFAULT 2.0, t_max REAL DEFAULT 15.0, prior_boost REAL DEFAULT 0.35,
        bidirectional INTEGER DEFAULT 0, active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );""",
    """CREATE TABLE IF NOT EXISTS homography_calibrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, camera_id TEXT UNIQUE NOT NULL,
        src_points_json TEXT NOT NULL, dst_points_json TEXT NOT NULL,
        matrix_json TEXT NOT NULL, metric_width REAL DEFAULT 10.0,
        metric_height REAL DEFAULT 10.0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );""",
    """CREATE TABLE IF NOT EXISTS camera_world_poses (
        camera_id TEXT PRIMARY KEY,
        origin_x REAL DEFAULT 0.0, origin_y REAL DEFAULT 0.0,
        yaw_deg REAL DEFAULT 0.0, scale REAL DEFAULT 1.0,
        fov_deg REAL DEFAULT 75.0, range_m REAL DEFAULT 12.0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );""",
)

_SECURITY_TABLES_DDL = (
    """CREATE TABLE IF NOT EXISTS rsac_zone_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT, camera_id TEXT NOT NULL, zone_id TEXT NOT NULL,
        allowed_categories_json TEXT DEFAULT '[]', denied_categories_json TEXT DEFAULT '[]',
        schedules_json TEXT DEFAULT '[]', entity_overrides_json TEXT DEFAULT '{}',
        alarm_on_breach INTEGER DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(camera_id, zone_id)
    );""",
    """CREATE TABLE IF NOT EXISTS pet_whitelist (
        id INTEGER PRIMARY KEY AUTOINCREMENT, category_or_label TEXT UNIQUE NOT NULL,
        notes TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );""",
    """CREATE TABLE IF NOT EXISTS tracker_sync_state (
        id INTEGER PRIMARY KEY AUTOINCREMENT, sync_key TEXT UNIQUE NOT NULL,
        last_etag TEXT DEFAULT '', last_sync_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        active_whitelist_count INTEGER DEFAULT 0, status TEXT DEFAULT 'synced',
        metadata_json TEXT DEFAULT '{}'
    );""",
    """CREATE TABLE IF NOT EXISTS local_whitelist (
        id INTEGER PRIMARY KEY AUTOINCREMENT, credential_id TEXT UNIQUE NOT NULL,
        entity_name TEXT NOT NULL, clearance_tier TEXT NOT NULL DEFAULT 'VISITOR',
        plate_number TEXT DEFAULT '', embedding BLOB,
        valid_from TIMESTAMP, valid_until TIMESTAMP, is_banned INTEGER DEFAULT 0,
        sync_version INTEGER DEFAULT 1, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );""",
    """CREATE TABLE IF NOT EXISTS offline_access_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT, event_uuid TEXT UNIQUE NOT NULL,
        credential_id TEXT, camera_id TEXT NOT NULL, direction TEXT DEFAULT 'in',
        access_granted INTEGER NOT NULL, decision_reason TEXT DEFAULT '',
        occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, snapshot_path TEXT DEFAULT '',
        synced INTEGER DEFAULT 0, synced_at TIMESTAMP
    );""",
)

_LEARNING_TABLES_DDL = (
    """CREATE TABLE IF NOT EXISTS review_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT, camera_id TEXT NOT NULL,
        track_id INTEGER NOT NULL, crop_path TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, suggested_entity_id INTEGER,
        suggested_name TEXT DEFAULT '', suggested_category TEXT DEFAULT '',
        similarity REAL DEFAULT 0.0, status TEXT DEFAULT 'pending',
        reviewed_at TIMESTAMP, reviewed_by TEXT DEFAULT 'operator',
        video_filename TEXT DEFAULT '', media_offset_sec REAL DEFAULT 0.0,
        bbox_json TEXT DEFAULT '', frame_width INTEGER DEFAULT 0,
        frame_height INTEGER DEFAULT 0, run_id TEXT DEFAULT ''
    );""",
    """CREATE TABLE IF NOT EXISTS custom_categories (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, color TEXT DEFAULT '#3B82F6',
        badge_icon TEXT DEFAULT '', description TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );""",
    """CREATE TABLE IF NOT EXISTS negative_exemplars (
        id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id INTEGER,
        label TEXT DEFAULT '', embedding BLOB NOT NULL,
        crop_path TEXT DEFAULT '', source TEXT DEFAULT '',
        notes TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
    );""",
)

_TELEMETRY_TABLES_DDL = (
    """CREATE TABLE IF NOT EXISTS system_resource_metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL NOT NULL,
        cpu_percent REAL, memory_mb REAL, active_streams INTEGER,
        hibernating_streams INTEGER, total_subscribers INTEGER
    );""",
    """CREATE TABLE IF NOT EXISTS stream_lifecycle_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL NOT NULL,
        camera_id TEXT NOT NULL, event_type TEXT NOT NULL,
        old_state TEXT, new_state TEXT, subscriber_count INTEGER, details TEXT
    );""",
)

_INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_whitelist_plate ON local_whitelist(plate_number);",
    "CREATE INDEX IF NOT EXISTS idx_whitelist_tier ON local_whitelist(clearance_tier);",
    "CREATE INDEX IF NOT EXISTS idx_offline_access_synced ON offline_access_queue(synced);",
    "CREATE INDEX IF NOT EXISTS idx_metrics_timestamp ON system_resource_metrics(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_lifecycle_camera ON stream_lifecycle_events(camera_id, timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_sightings_entity_ts ON sightings(entity_id, timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_sightings_source_ts ON sightings(source, timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_signatures_entity ON entity_signatures(entity_id);",
    "CREATE INDEX IF NOT EXISTS idx_entities_category ON entities(category);",
    "CREATE INDEX IF NOT EXISTS idx_spatial_zones_cam ON spatial_zones(camera_id);",
    "CREATE INDEX IF NOT EXISTS idx_spatial_tripwires_cam ON spatial_tripwires(camera_id);",
    "CREATE INDEX IF NOT EXISTS idx_desc_versions_entity ON descriptor_versions(entity_id, version_num);",
    "CREATE INDEX IF NOT EXISTS idx_review_queue_status ON review_queue(status, timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_rsac_zone_rules_cam ON rsac_zone_rules(camera_id, zone_id);",
    "CREATE INDEX IF NOT EXISTS idx_negative_exemplars_entity ON negative_exemplars(entity_id);",
)


class SchemaMixin:
    """Provides schema creation, index setup, and default data seeding."""

    _conn: Any
    _lock: Any

    def _init_schema(self) -> None:
        """Create tables and indexes if they do not exist."""
        with self._lock:
            if self._conn is None:
                raise RuntimeError("Database connection is closed")
            cursor = self._conn.cursor()
            try:
                for ddl in (
                    _CORE_TABLES_DDL + _SPATIAL_TABLES_DDL
                    + _LEARNING_TABLES_DDL + _SECURITY_TABLES_DDL + _TELEMETRY_TABLES_DDL
                ):
                    cursor.execute(ddl)
                self._apply_schema_migrations(cursor)
                self._seed_default_data(cursor)
                self._init_indexes(cursor)
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cursor.close()

    def _apply_schema_migrations(self, cursor: sqlite3.Cursor) -> None:
        """Apply safe column migrations for existing databases."""
        for col_def in ("is_anchor INTEGER DEFAULT 0", "locked INTEGER DEFAULT 0"):
            try:
                cursor.execute(f"ALTER TABLE entity_signatures ADD COLUMN {col_def};")
            except sqlite3.OperationalError:
                pass
        try:
            cursor.execute("ALTER TABLE descriptor_versions ADD COLUMN is_anchor INTEGER DEFAULT 0;")
        except sqlite3.OperationalError:
            pass
        for col_def in (
            "bbox_json TEXT DEFAULT ''",
            "frame_width INTEGER DEFAULT 0",
            "frame_height INTEGER DEFAULT 0",
            "run_id TEXT DEFAULT ''",
        ):
            try:
                cursor.execute(f"ALTER TABLE review_queue ADD COLUMN {col_def};")
            except sqlite3.OperationalError:
                pass
        apply_memory_schema_migrations(cursor)
        apply_video_schema_migrations(cursor)
        self._migrate_user_version(cursor)

    def _migrate_user_version(self, cursor: sqlite3.Cursor) -> None:
        """Apply versioned PRAGMA user_version schema migrations idempotently."""
        ver_row = cursor.execute("PRAGMA user_version;").fetchone()
        cur_ver = int(ver_row[0]) if ver_row else 0
        if cur_ver < 2:
            for col_def in ("camera_id TEXT DEFAULT ''", "run_id TEXT DEFAULT ''"):
                try:
                    cursor.execute(f"ALTER TABLE sightings ADD COLUMN {col_def};")
                except sqlite3.OperationalError:
                    pass
            cursor.execute(
                "UPDATE sightings SET camera_id = source "
                "WHERE (camera_id IS NULL OR camera_id = '') AND source != '' "
                "AND (video_filename IS NULL OR video_filename = '');"
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sightings_camera_id ON sightings(camera_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sightings_run_id ON sightings(run_id);")
            cursor.execute("PRAGMA user_version = 2;")
        if cur_ver < 3:
            try:
                cursor.execute("ALTER TABLE world_timeline_events ADD COLUMN run_id TEXT DEFAULT '';")
            except sqlite3.OperationalError:
                pass
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_timeline_run_id ON world_timeline_events(run_id);")
            cursor.execute("PRAGMA user_version = 3;")
        if cur_ver < 4:
            cursor.execute(
                """CREATE TABLE IF NOT EXISTS learned_classes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    slug TEXT UNIQUE NOT NULL,
                    parent_coco_class TEXT DEFAULT '',
                    color TEXT DEFAULT '#06B6D4',
                    threshold REAL DEFAULT 0.65,
                    description TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );"""
            )
            cursor.execute(
                """CREATE TABLE IF NOT EXISTS learned_class_exemplars (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    class_id INTEGER NOT NULL,
                    embedding BLOB NOT NULL,
                    crop_path TEXT DEFAULT '',
                    source_camera_id TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (class_id) REFERENCES learned_classes(id) ON DELETE CASCADE
                );"""
            )
            cursor.execute(
                """CREATE TABLE IF NOT EXISTS camera_class_overrides (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    camera_id TEXT NOT NULL,
                    coco_class TEXT NOT NULL,
                    action TEXT NOT NULL DEFAULT 'suppress',
                    relabel_to TEXT DEFAULT '',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(camera_id, coco_class)
                );"""
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_learned_exemplars_class ON learned_class_exemplars(class_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_camera_class_overrides_cam ON camera_class_overrides(camera_id);")
            cursor.execute("PRAGMA user_version = 4;")

    def _seed_default_data(self, cursor: sqlite3.Cursor) -> None:
        """Seed default role-based categories and pet whitelist entries."""
        default_cats = [
            (c["id"], c["name"], c["color"], c["badge_icon"], c["description"])
            for c in DEFAULT_CUSTOM_CATEGORIES
        ]
        cursor.executemany(
            "INSERT OR IGNORE INTO custom_categories (id, name, color, badge_icon, description) VALUES (?, ?, ?, ?, ?)",
            default_cats,
        )
        default_pets = [
            ("dog", "Canine family pet"),
            ("cat", "Feline family pet"),
            ("pet", "Generic domestic pet"),
        ]
        cursor.executemany(
            "INSERT OR IGNORE INTO pet_whitelist (category_or_label, notes) VALUES (?, ?)",
            default_pets,
        )
        migrate_category_registry(cursor)

    def _init_indexes(self, cursor: sqlite3.Cursor) -> None:
        """Create indices for fast timeline, lookup, and analytics queries."""
        for stmt in _INDEX_STATEMENTS:
            cursor.execute(stmt)
