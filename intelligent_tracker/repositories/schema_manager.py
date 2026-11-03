"""
Database Schema Initialization and Migration Mixin.

Manages SQLite DDL table schemas, indexes, pragma tuning, and seed data
for the Intelligent Tracker persistence subsystem.
"""

import sqlite3
import logging

logger = logging.getLogger(__name__)


class SchemaMixin:
    """Provides schema creation, index setup, and default data seeding."""

    def _init_schema(self) -> None:
        """Create tables and indexes if they do not exist."""
        with self._lock:
            cursor = self._conn.cursor()
            try:
                self._init_core_tables(cursor)
                self._init_spatial_tables(cursor)
                self._init_learning_tables(cursor)
                self._init_security_tables(cursor)
                self._init_telemetry_tables(cursor)
                self._apply_schema_migrations(cursor)
                self._seed_default_data(cursor)
                self._init_indexes(cursor)
                self._conn.commit()
            finally:
                cursor.close()

    def _init_core_tables(self, cursor: sqlite3.Cursor) -> None:
        """Initialize entities, signatures, sightings, and descriptor version tables."""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT DEFAULT 'person',
                status TEXT DEFAULT 'active',
                notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS entity_signatures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id INTEGER NOT NULL,
                embedding BLOB NOT NULL,
                crop_path TEXT DEFAULT '',
                is_anchor INTEGER DEFAULT 0,
                locked INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sightings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id INTEGER,
                track_id INTEGER,
                source TEXT DEFAULT '',
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                zone_id TEXT DEFAULT '',
                bbox TEXT DEFAULT '',
                confidence REAL DEFAULT 1.0,
                snapshot_path TEXT DEFAULT '',
                FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE SET NULL
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS descriptor_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id INTEGER NOT NULL,
                version_num INTEGER NOT NULL,
                embedding BLOB NOT NULL,
                crop_path TEXT DEFAULT '',
                source TEXT DEFAULT 'manual_enrollment',
                notes TEXT DEFAULT '',
                is_anchor INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
            );
        """)

    def _init_spatial_tables(self, cursor: sqlite3.Cursor) -> None:
        """Initialize Scenario Studio zones, tripwires, transitions, and homography calibrations."""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS spatial_zones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_id TEXT NOT NULL,
                name TEXT NOT NULL,
                polygon_json TEXT NOT NULL,
                category_filter TEXT DEFAULT '',
                dwell_threshold REAL DEFAULT 5.0,
                capacity_limit INTEGER,
                color TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(camera_id, name)
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS spatial_tripwires (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_id TEXT NOT NULL,
                name TEXT NOT NULL,
                line_segment_json TEXT NOT NULL,
                bidirectional INTEGER DEFAULT 1,
                color TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(camera_id, name)
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS spatial_transitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                link_id TEXT UNIQUE NOT NULL,
                source_camera TEXT NOT NULL,
                source_zone TEXT NOT NULL,
                target_camera TEXT NOT NULL,
                target_zone TEXT NOT NULL,
                t_min REAL DEFAULT 2.0,
                t_max REAL DEFAULT 15.0,
                prior_boost REAL DEFAULT 0.35,
                bidirectional INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS homography_calibrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_id TEXT UNIQUE NOT NULL,
                src_points_json TEXT NOT NULL,
                dst_points_json TEXT NOT NULL,
                matrix_json TEXT NOT NULL,
                metric_width REAL DEFAULT 10.0,
                metric_height REAL DEFAULT 10.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

    def _init_learning_tables(self, cursor: sqlite3.Cursor) -> None:
        """Initialize Active Learning review queue and custom categories."""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS review_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_id TEXT NOT NULL,
                track_id INTEGER NOT NULL,
                crop_path TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                suggested_entity_id INTEGER,
                suggested_name TEXT DEFAULT '',
                suggested_category TEXT DEFAULT '',
                similarity REAL DEFAULT 0.0,
                status TEXT DEFAULT 'pending',
                reviewed_at TIMESTAMP,
                reviewed_by TEXT DEFAULT 'operator'
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS custom_categories (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                color TEXT DEFAULT '#3B82F6',
                badge_icon TEXT DEFAULT '',
                description TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

    def _init_security_tables(self, cursor: sqlite3.Cursor) -> None:
        """Initialize RSAC zone rules, pet whitelist, and cloud sync/whitelist tables."""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rsac_zone_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_id TEXT NOT NULL,
                zone_id TEXT NOT NULL,
                allowed_categories_json TEXT DEFAULT '[]',
                denied_categories_json TEXT DEFAULT '[]',
                schedules_json TEXT DEFAULT '[]',
                entity_overrides_json TEXT DEFAULT '{}',
                alarm_on_breach INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(camera_id, zone_id)
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pet_whitelist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_or_label TEXT UNIQUE NOT NULL,
                notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tracker_sync_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sync_key TEXT UNIQUE NOT NULL,
                last_etag TEXT DEFAULT '',
                last_sync_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                active_whitelist_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'synced',
                metadata_json TEXT DEFAULT '{}'
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS local_whitelist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                credential_id TEXT UNIQUE NOT NULL,
                entity_name TEXT NOT NULL,
                clearance_tier TEXT NOT NULL DEFAULT 'VISITOR',
                plate_number TEXT DEFAULT '',
                embedding BLOB,
                valid_from TIMESTAMP,
                valid_until TIMESTAMP,
                is_banned INTEGER DEFAULT 0,
                sync_version INTEGER DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS offline_access_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_uuid TEXT UNIQUE NOT NULL,
                credential_id TEXT,
                camera_id TEXT NOT NULL,
                direction TEXT DEFAULT 'in',
                access_granted INTEGER NOT NULL,
                decision_reason TEXT DEFAULT '',
                occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                snapshot_path TEXT DEFAULT '',
                synced INTEGER DEFAULT 0,
                synced_at TIMESTAMP
            );
        """)

    def _init_telemetry_tables(self, cursor: sqlite3.Cursor) -> None:
        """Initialize telemetry and stream lifecycle event tables."""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_resource_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                cpu_percent REAL,
                memory_mb REAL,
                active_streams INTEGER,
                hibernating_streams INTEGER,
                total_subscribers INTEGER
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stream_lifecycle_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                camera_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                old_state TEXT,
                new_state TEXT,
                subscriber_count INTEGER,
                details TEXT
            );
        """)

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

    def _seed_default_data(self, cursor: sqlite3.Cursor) -> None:
        """Seed default role-based categories and pet whitelist entries."""
        default_cats = [
            ("person", "Person", "#3B82F6", "user", "General human person"),
            ("family_car", "Family Car", "#10B981", "car", "Whitelisted resident family vehicle"),
            ("delivery_truck", "Delivery Truck", "#F59E0B", "truck", "Courier or logistics vehicle"),
            ("cleaning_crew", "Cleaning Crew", "#8B5CF6", "sparkles", "Authorized maintenance crew"),
            ("guard_dog", "Guard Dog", "#EC4899", "shield", "Authorized security canine"),
            ("pet", "Household Pet", "#06B6D4", "paw", "Whitelisted domestic pet"),
            ("vip", "VIP Resident", "#6366F1", "star", "High priority resident or guest"),
            ("restricted", "Restricted / Watchlist", "#EF4444", "alert-triangle", "Watchlist or unauthorized presence"),
        ]
        cursor.executemany(
            "INSERT OR IGNORE INTO custom_categories (id, name, color, badge_icon, description) VALUES (?, ?, ?, ?, ?)",
            default_cats,
        )
        default_pets = [
            ("dog", "Canine family pet"),
            ("cat", "Feline family pet"),
            ("pet", "Generic domestic pet"),
            ("guard_dog", "Trained security or family guard dog"),
        ]
        cursor.executemany(
            "INSERT OR IGNORE INTO pet_whitelist (category_or_label, notes) VALUES (?, ?)",
            default_pets,
        )

    def _init_indexes(self, cursor: sqlite3.Cursor) -> None:
        """Create indices for fast timeline, lookup, and analytics queries."""
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_whitelist_plate ON local_whitelist(plate_number);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_whitelist_tier ON local_whitelist(clearance_tier);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_offline_access_synced ON offline_access_queue(synced);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_metrics_timestamp ON system_resource_metrics(timestamp);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_lifecycle_camera ON stream_lifecycle_events(camera_id, timestamp);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sightings_entity_ts ON sightings(entity_id, timestamp);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sightings_source_ts ON sightings(source, timestamp);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_signatures_entity ON entity_signatures(entity_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entities_category ON entities(category);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_spatial_zones_cam ON spatial_zones(camera_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_spatial_tripwires_cam ON spatial_tripwires(camera_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_desc_versions_entity ON descriptor_versions(entity_id, version_num);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_review_queue_status ON review_queue(status, timestamp);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_rsac_zone_rules_cam ON rsac_zone_rules(camera_id, zone_id);")
