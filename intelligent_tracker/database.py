#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Persistent SQLite Entity, Signature & Sighting Database Module.

Provides:

- ``TrackerDB``: Embedded, zero-configuration thread-safe SQLite database manager
  storing:

  1. ``entities``: Registered individuals, vehicles, or tracked assets with categories and metadata.
  2. ``entity_signatures``: Feature embeddings (BLOBs) and thumbnail crops for visual Re-ID.
  3. ``sightings``: Complete audit trail of where, when, and with what confidence each entity appeared.

- Indexing for fast chronological timeline and source-based lookup queries.
- Occurrence analytics and summary export (JSON, CSV).
"""

import os
import csv
import json
import time
import sqlite3
import threading
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Any, Union

import numpy as np
import cv2


class TrackerDB:
    """
    Thread-safe SQLite database manager for entities, Re-ID signatures, and sightings.
    """

    def __init__(self, db_path: str = "data/tracker.db"):
        """
        Initialize TrackerDB.

        :param db_path: Path to SQLite database file, or ':memory:' for in-memory DB.
        """
        self.db_path = db_path
        self._lock = threading.RLock()

        if db_path != ":memory:":
            db_dir = os.path.dirname(os.path.abspath(db_path))
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)

        # Initialize connection
        self._conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=30.0,
        )
        self._conn.row_factory = sqlite3.Row

        # Configure connection for concurrency and integrity
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys = ON;")
                if self.db_path != ":memory:":
                    cursor.execute("PRAGMA journal_mode = WAL;")
                cursor.execute("PRAGMA busy_timeout = 5000;")
            finally:
                cursor.close()

            self._init_schema()

    def _init_schema(self):
        """Create tables and indexes if they do not exist."""
        with self._lock:
            cursor = self._conn.cursor()
            try:
                # 1. Entities table
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

                # 2. Entity Signatures table (multi-dimensional feature embeddings)
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

                # 3. Sightings audit trail table
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

                # 4. Spatial Zones table (Scenario Studio)
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

                # 5. Spatial Tripwires table
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

                # 6. Cross-Camera Spatial Transitions table
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

                # 7. Ground Plane Homography Calibrations table
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

                # 8. Descriptor Version History table (Locked Anchors & Memory Rollback)
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

                # 9. Active Learning Review Queue table ("Review & Learn" Inbox)
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

                # 10. Role-Based Custom Categories table
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

                # 11. RSAC Zone Rules table
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

                # 12. Pet Whitelist table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS pet_whitelist (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        category_or_label TEXT UNIQUE NOT NULL,
                        notes TEXT DEFAULT '',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)

                # 13. Enterprise Cloud Hub Sync State table
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

                # 14. Offline-First Local Whitelist table
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
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_whitelist_plate ON local_whitelist(plate_number);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_whitelist_tier ON local_whitelist(clearance_tier);")

                # 15. Offline Access Outbox Queue table
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
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_offline_access_synced ON offline_access_queue(synced);")

                # System Resource Metrics & Stream Lifecycle Telemetry
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
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_metrics_timestamp ON system_resource_metrics(timestamp);")

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
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_lifecycle_camera ON stream_lifecycle_events(camera_id, timestamp);")

                # Safe column additions for existing entity_signatures tables
                for col_def in ("is_anchor INTEGER DEFAULT 0", "locked INTEGER DEFAULT 0"):
                    try:
                        cursor.execute(f"ALTER TABLE entity_signatures ADD COLUMN {col_def};")
                    except sqlite3.OperationalError:
                        pass

                try:
                    cursor.execute("ALTER TABLE descriptor_versions ADD COLUMN is_anchor INTEGER DEFAULT 0;")
                except sqlite3.OperationalError:
                    pass

                # Seed default custom categories
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

                # Seed default pet whitelist
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

                # 13. Indexes for rapid lookups
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_sightings_entity_ts
                    ON sightings(entity_id, timestamp);
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_sightings_source_ts
                    ON sightings(source, timestamp);
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_signatures_entity
                    ON entity_signatures(entity_id);
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_entities_category
                    ON entities(category);
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_spatial_zones_cam
                    ON spatial_zones(camera_id);
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_spatial_tripwires_cam
                    ON spatial_tripwires(camera_id);
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_desc_versions_entity
                    ON descriptor_versions(entity_id, version_num);
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_review_queue_status
                    ON review_queue(status, timestamp);
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_rsac_zone_rules_cam
                    ON rsac_zone_rules(camera_id, zone_id);
                """)

                self._conn.commit()
            finally:
                cursor.close()

    # -------------------------------------------------------------------------
    # Entity CRUD Operations
    # -------------------------------------------------------------------------

    def add_entity(
        self,
        name: str,
        category: str = "person",
        status: str = "active",
        notes: str = "",
    ) -> int:
        """
        Register a new entity in the database.

        :return: Created entity ID.
        """
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO entities (name, category, status, notes, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (name.strip(), category.strip(), status.strip(), notes.strip(), now, now),
                )
                self._conn.commit()
                return cursor.lastrowid
            finally:
                cursor.close()

    def update_entity(
        self,
        entity_id: int,
        name: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> bool:
        """
        Update fields of an existing entity.

        :return: True if entity was found and updated.
        """
        fields = []
        values = []

        if name is not None:
            fields.append("name = ?")
            values.append(name.strip())
        if category is not None:
            fields.append("category = ?")
            values.append(category.strip())
        if status is not None:
            fields.append("status = ?")
            values.append(status.strip())
        if notes is not None:
            fields.append("notes = ?")
            values.append(notes.strip())

        if not fields:
            return False

        fields.append("updated_at = ?")
        values.append(time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
        values.append(entity_id)

        query = "UPDATE entities SET {} WHERE id = ?".format(", ".join(fields))

        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute(query, values)
                self._conn.commit()
                return cursor.rowcount > 0
            finally:
                cursor.close()

    def get_entity(self, entity_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve single entity by ID."""
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute("SELECT * FROM entities WHERE id = ?", (entity_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
            finally:
                cursor.close()

    def get_entity_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Retrieve single entity by name."""
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute("SELECT * FROM entities WHERE name = ?", (name.strip(),))
                row = cursor.fetchone()
                return dict(row) if row else None
            finally:
                cursor.close()

    def list_entities(
        self,
        category: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List entities, optionally filtered by category or status."""
        query = "SELECT * FROM entities"
        conditions = []
        params = []

        if category:
            conditions.append("category = ?")
            params.append(category.strip())
        if status:
            conditions.append("status = ?")
            params.append(status.strip())

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY id ASC"

        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute(query, params)
                return [dict(r) for r in cursor.fetchall()]
            finally:
                cursor.close()

    def delete_entity(self, entity_id: int) -> bool:
        """
        Delete an entity and cascade delete associated signatures.

        :return: True if deleted.
        """
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
                self._conn.commit()
                return cursor.rowcount > 0
            finally:
                cursor.close()

    # -------------------------------------------------------------------------
    # Entity Signatures (Visual Re-ID Embeddings)
    # -------------------------------------------------------------------------

    @staticmethod
    def serialize_embedding(embedding: np.ndarray) -> bytes:
        """Serialize a 1D NumPy float vector to bytes."""
        arr = np.asarray(embedding, dtype=np.float32).flatten()
        return arr.tobytes()

    @staticmethod
    def deserialize_embedding(blob: bytes) -> np.ndarray:
        """Deserialize raw bytes back to 1D NumPy float32 array."""
        return np.frombuffer(blob, dtype=np.float32)

    def add_signature(
        self,
        entity_id: int,
        embedding: np.ndarray,
        crop_path: str = "",
        is_anchor: int = 0,
        locked: int = 0,
    ) -> int:
        """
        Add a feature signature embedding for an entity.

        :param entity_id: Target entity ID.
        :param embedding: 1D NumPy float vector representing the visual embedding.
        :param crop_path: Optional path to saved cropped thumbnail image.
        :param is_anchor: If 1, marks as ground-truth Locked Anchor never modified by continuous learning.
        :param locked: If 1, prevents automatic eviction.
        :return: Created signature ID.
        """
        blob = self.serialize_embedding(embedding)
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())

        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO entity_signatures (entity_id, embedding, crop_path, is_anchor, locked, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (entity_id, blob, crop_path.strip(), int(is_anchor), int(locked), now),
                )
                sig_id = cursor.lastrowid
                self._conn.commit()
                return sig_id
            finally:
                cursor.close()

    def add_entity_signature(
        self,
        entity_id: int,
        embedding: Optional[np.ndarray] = None,
        feature_vector: Optional[np.ndarray] = None,
        crop_path: str = "",
        is_anchor: int = 0,
        locked: int = 0,
    ) -> int:
        """Alias for add_signature accepting either feature_vector or embedding."""
        vec = feature_vector if feature_vector is not None else embedding
        if vec is None:
            raise ValueError("Must provide feature_vector or embedding")
        return self.add_signature(
            entity_id=entity_id,
            embedding=vec,
            crop_path=crop_path,
            is_anchor=is_anchor,
            locked=locked,
        )

    def update_entity_signature(
        self,
        signature_id: int,
        embedding: Optional[np.ndarray] = None,
        feature_vector: Optional[np.ndarray] = None,
        crop_path: Optional[str] = None,
    ) -> bool:
        """Update existing signature feature vector or crop path."""
        vec = feature_vector if feature_vector is not None else embedding
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        with self._lock:
            cur = self._conn.cursor()
            try:
                updates = ["created_at = ?"]
                params: List[Any] = [now]
                if vec is not None:
                    updates.append("embedding = ?")
                    params.append(self.serialize_embedding(vec))
                if crop_path is not None:
                    updates.append("crop_path = ?")
                    params.append(crop_path.strip())
                params.append(signature_id)
                cur.execute(f"UPDATE entity_signatures SET {', '.join(updates)} WHERE id = ?", params)
                self._conn.commit()
                return cur.rowcount > 0
            finally:
                cur.close()

    def get_entity_signatures(
        self,
        entity_id: int,
        anchors_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """Retrieve signatures for an entity with feature_vector alias."""
        return self.get_signatures(entity_id=entity_id, anchors_only=anchors_only)

    def get_signatures(
        self,
        entity_id: Optional[int] = None,
        anchors_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve signatures, optionally filtered for a specific entity or locked anchors.

        :param entity_id: Optional entity ID filter.
        :param anchors_only: If True, only returns locked ground-truth anchors.
        :return: List of dicts with deserialized `embedding` arrays.
        """
        query = "SELECT id, entity_id, embedding, crop_path, is_anchor, locked, created_at FROM entity_signatures"
        conditions = []
        params = []
        if entity_id is not None:
            conditions.append("entity_id = ?")
            params.append(entity_id)
        if anchors_only:
            conditions.append("is_anchor = 1")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY id ASC"

        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute(query, params)
                results = []
                for row in cursor.fetchall():
                    item = dict(row)
                    item["embedding"] = self.deserialize_embedding(item["embedding"])
                    item["feature_vector"] = item["embedding"]
                    results.append(item)
                return results
            finally:
                cursor.close()

    def get_gallery_embeddings(self) -> Tuple[np.ndarray, List[int], List[str], List[str]]:
        """
        Fetch all gallery signatures as a unified 2D matrix for vectorized matching.

        :return: Tuple of:
            - `embeddings_matrix`: np.ndarray of shape (N, D) float32 (empty (0, 0) if no signatures)
            - `entity_ids`: List[int] of length N
            - `names`: List[str] of length N
            - `categories`: List[str] of length N
        """
        query = """
            SELECT s.embedding, e.id AS entity_id, e.name, e.category
            FROM entity_signatures s
            JOIN entities e ON s.entity_id = e.id
            WHERE e.status = 'active'
            ORDER BY s.id ASC
        """
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute(query)
                rows = cursor.fetchall()
            finally:
                cursor.close()

        if not rows:
            return np.empty((0, 0), dtype=np.float32), [], [], []

        vectors = []
        entity_ids = []
        names = []
        categories = []

        for row in rows:
            vec = self.deserialize_embedding(row["embedding"])
            vectors.append(vec)
            entity_ids.append(row["entity_id"])
            names.append(row["name"])
            categories.append(row["category"])

        embeddings_matrix = np.vstack(vectors).astype(np.float32)
        return embeddings_matrix, entity_ids, names, categories

    # -------------------------------------------------------------------------
    # Sightings Audit Trail & Analytics
    # -------------------------------------------------------------------------

    def add_sighting(
        self,
        entity_id: Optional[int],
        track_id: Optional[int] = None,
        source: str = "",
        timestamp: Optional[Union[float, str, datetime]] = None,
        zone_id: str = "",
        bbox: Union[str, Tuple[int, int, int, int], List[int]] = "",
        confidence: float = 1.0,
        snapshot_path: str = "",
    ) -> int:
        """
        Log an entity sighting to the audit trail.

        :return: Created sighting ID.
        """
        if timestamp is None:
            ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        elif isinstance(timestamp, (int, float)):
            ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(timestamp))
        elif isinstance(timestamp, datetime):
            ts_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        else:
            ts_str = str(timestamp)

        if isinstance(bbox, (list, tuple)):
            bbox_str = json.dumps([int(v) for v in bbox])
        else:
            bbox_str = str(bbox)

        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO sightings (
                        entity_id, track_id, source, timestamp, zone_id, bbox, confidence, snapshot_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entity_id,
                        track_id,
                        source.strip(),
                        ts_str,
                        zone_id.strip(),
                        bbox_str,
                        float(confidence),
                        snapshot_path.strip(),
                    ),
                )
                self._conn.commit()
                return cursor.lastrowid
            finally:
                cursor.close()

    record_sighting = add_sighting

    def get_sightings(
        self,
        entity_id: Optional[int] = None,
        source: Optional[str] = None,
        zone_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query sightings audit trail with flexible filtering."""
        query = """
            SELECT s.*, e.name AS entity_name, e.category AS entity_category
            FROM sightings s
            LEFT JOIN entities e ON s.entity_id = e.id
        """
        conditions = []
        params = []

        if entity_id is not None:
            conditions.append("s.entity_id = ?")
            params.append(entity_id)
        if source:
            conditions.append("s.source = ?")
            params.append(source.strip())
        if zone_id:
            conditions.append("s.zone_id = ?")
            params.append(zone_id.strip())
        if start_time:
            conditions.append("s.timestamp >= ?")
            params.append(start_time)
        if end_time:
            conditions.append("s.timestamp <= ?")
            params.append(end_time)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY s.timestamp DESC"
        if limit > 0:
            query += " LIMIT ?"
            params.append(limit)

        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute(query, params)
                return [dict(r) for r in cursor.fetchall()]
            finally:
                cursor.close()

    query_sightings = get_sightings

    def get_entity_analytics(self, entity_id: int) -> Dict[str, Any]:
        """
        Compute occurrence frequency, dwell timeline, and zone journey for an entity.
        """
        entity = self.get_entity(entity_id)
        if not entity:
            return {"error": "Entity not found", "entity_id": entity_id}

        with self._lock:
            cursor = self._conn.cursor()
            try:
                # Count and time bounds
                cursor.execute(
                    """
                    SELECT COUNT(*) as total_sightings,
                           MIN(timestamp) as first_seen,
                           MAX(timestamp) as last_seen,
                           COUNT(DISTINCT source) as distinct_sources,
                           COUNT(DISTINCT zone_id) as distinct_zones
                    FROM sightings
                    WHERE entity_id = ?
                    """,
                    (entity_id,),
                )
                stats = dict(cursor.fetchone())

                # Distinct sources list
                cursor.execute(
                    "SELECT DISTINCT source FROM sightings WHERE entity_id = ? AND source != ''",
                    (entity_id,),
                )
                sources = [r[0] for r in cursor.fetchall()]

                # Distinct zones list
                cursor.execute(
                    "SELECT DISTINCT zone_id FROM sightings WHERE entity_id = ? AND zone_id != ''",
                    (entity_id,),
                )
                zones = [r[0] for r in cursor.fetchall()]

                # Detailed chronological sightings
                cursor.execute(
                    """
                    SELECT timestamp, source, zone_id, track_id, confidence
                    FROM sightings
                    WHERE entity_id = ?
                    ORDER BY timestamp ASC
                    """,
                    (entity_id,),
                )
                timeline = [dict(r) for r in cursor.fetchall()]
            finally:
                cursor.close()

        # Dwell time approximation based on sighting timestamps
        estimated_dwell_seconds = 0.0
        if len(timeline) >= 2:
            try:
                t_first = datetime.strptime(stats["first_seen"], "%Y-%m-%d %H:%M:%S")
                t_last = datetime.strptime(stats["last_seen"], "%Y-%m-%d %H:%M:%S")
                span = (t_last - t_first).total_seconds()
                # If seen across a short window, span is dwell
                estimated_dwell_seconds = max(0.0, span)
            except Exception:
                pass

        return {
            "entity": entity,
            "total_sightings": stats["total_sightings"],
            "first_seen": stats["first_seen"],
            "last_seen": stats["last_seen"],
            "distinct_sources_count": stats["distinct_sources"],
            "sources": sources,
            "distinct_zones_count": stats["distinct_zones"],
            "zones": zones,
            "estimated_dwell_seconds": estimated_dwell_seconds,
            "timeline": timeline,
        }

    # -------------------------------------------------------------------------
    # High-Level Enrollment Helper
    # -------------------------------------------------------------------------

    def enroll_entity(
        self,
        name: str,
        category: str = "person",
        frame: Optional[np.ndarray] = None,
        bbox: Optional[Tuple[int, int, int, int]] = None,
        embedding: Optional[np.ndarray] = None,
        notes: str = "",
        extractor: Optional[Any] = None,
        save_crop_dir: Optional[str] = "data/crops",
        is_anchor: bool = True,
    ) -> Dict[str, Any]:
        """
        Convenience method to register an entity, extract its visual crop,
        compute embedding vector, save thumbnail crop, and store signature.

        :param name: Entity name (e.g. 'Forklift #02', 'Alice').
        :param category: Category (e.g. 'staff', 'vip', 'vehicle').
        :param frame: Full BGR frame containing the entity.
        :param bbox: (x, y, w, h) bounding box.
        :param embedding: Precomputed embedding (optional if extractor provided).
        :param notes: Metadata notes.
        :param extractor: BaseFeatureExtractor instance (optional if embedding provided).
        :param save_crop_dir: Directory where thumbnail crop image should be saved.
        :param is_anchor: If True, marks signature as a ground-truth Locked Anchor.
        :return: Created entity info dict with signature_id and crop_path.
        """
        crop_path = ""
        computed_embedding = embedding

        if frame is not None and bbox is not None:
            x, y, w, h = [int(v) for v in bbox]
            ih, iw = frame.shape[:2]
            x1 = max(0, min(x, iw - 1))
            y1 = max(0, min(y, ih - 1))
            x2 = max(x1 + 1, min(x + w, iw))
            y2 = max(y1 + 1, min(y + h, ih))
            crop = frame[y1:y2, x1:x2]

            # Compute embedding via extractor if not supplied
            if computed_embedding is None and extractor is not None:
                computed_embedding = extractor.extract_crop(crop)

            # Save crop thumbnail
            if save_crop_dir and crop.size > 0:
                os.makedirs(save_crop_dir, exist_ok=True)
                crop_filename = "{}_{}_{}.jpg".format(
                    name.replace(" ", "_").lower(),
                    int(time.time()),
                    np.random.randint(1000, 9999),
                )
                crop_path = os.path.join(save_crop_dir, crop_filename)
                cv2.imwrite(crop_path, crop)

        # Check if entity already exists by name
        existing = self.get_entity_by_name(name)
        if existing:
            entity_id = existing["id"]
            self.update_entity(entity_id, category=category, notes=notes)
        else:
            entity_id = self.add_entity(name=name, category=category, notes=notes)

        # Add signature if embedding is available
        signature_id = None
        if computed_embedding is not None:
            signature_id = self.add_signature(
                entity_id=entity_id,
                embedding=computed_embedding,
                crop_path=crop_path,
                is_anchor=1 if is_anchor else 0,
                locked=1 if is_anchor else 0,
            )

        entity_data = self.get_entity(entity_id) or {}
        entity_data["signature_id"] = signature_id
        entity_data["crop_path"] = crop_path
        return entity_data

    # -------------------------------------------------------------------------
    # Export Utilities (JSON & CSV)
    # -------------------------------------------------------------------------

    def export_sightings_csv(self, output_path: str, entity_id: Optional[int] = None) -> str:
        """Export sightings to a CSV file."""
        sightings = self.get_sightings(entity_id=entity_id, limit=0)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

        fieldnames = [
            "id", "entity_id", "entity_name", "entity_category", "track_id",
            "source", "timestamp", "zone_id", "bbox", "confidence", "snapshot_path"
        ]
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for s in sightings:
                row = {k: s.get(k, "") for k in fieldnames}
                writer.writerow(row)
        return output_path

    def export_sightings_json(self, output_path: str, entity_id: Optional[int] = None) -> str:
        """Export sightings to a JSON file."""
        sightings = self.get_sightings(entity_id=entity_id, limit=0)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(sightings, f, indent=2, default=str)
        return output_path

    # -------------------------------------------------------------------------
    # Spatial Studio & Homography Persistence (Milestone 8)
    # -------------------------------------------------------------------------

    def save_zone(
        self,
        camera_id: str,
        name: str,
        polygon: List[Union[List[float], Tuple[float, float]]],
        category_filter: str = "",
        dwell_threshold: float = 5.0,
        capacity_limit: Optional[int] = None,
        color: Union[str, List[int], Tuple[int, ...]] = "",
    ) -> int:
        """Create or update a spatial zone for a camera."""
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        poly_json = json.dumps(polygon)
        color_str = json.dumps(color) if isinstance(color, (list, tuple)) else str(color)
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO spatial_zones (camera_id, name, polygon_json, category_filter, dwell_threshold, capacity_limit, color, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(camera_id, name) DO UPDATE SET
                        polygon_json = excluded.polygon_json,
                        category_filter = excluded.category_filter,
                        dwell_threshold = excluded.dwell_threshold,
                        capacity_limit = excluded.capacity_limit,
                        color = excluded.color,
                        updated_at = excluded.updated_at
                    """,
                    (camera_id, name, poly_json, category_filter, dwell_threshold, capacity_limit, color_str, now, now),
                )
                self._conn.commit()
                return cur.lastrowid
            finally:
                cur.close()

    def get_zones(self, camera_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve spatial zones, optionally filtered by camera_id."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                if camera_id:
                    cur.execute("SELECT * FROM spatial_zones WHERE camera_id = ? ORDER BY name ASC", (camera_id,))
                else:
                    cur.execute("SELECT * FROM spatial_zones ORDER BY camera_id, name ASC")
                rows = cur.fetchall()
                results = []
                for r in rows:
                    d = dict(r)
                    d["polygon"] = json.loads(d["polygon_json"])
                    try:
                        d["color"] = json.loads(d["color"]) if d["color"] else [0, 200, 100]
                    except Exception:
                        d["color"] = [0, 200, 100]
                    results.append(d)
                return results
            finally:
                cur.close()

    def delete_zone(self, camera_id: str, name: str) -> bool:
        """Delete a spatial zone by camera and name."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("DELETE FROM spatial_zones WHERE camera_id = ? AND name = ?", (camera_id, name))
                self._conn.commit()
                return cur.rowcount > 0
            finally:
                cur.close()

    def save_tripwire(
        self,
        camera_id: str,
        name: str,
        line_segment: List[Union[List[float], Tuple[float, float]]],
        bidirectional: bool = True,
        color: Union[str, List[int], Tuple[int, ...]] = "",
    ) -> int:
        """Create or update a spatial tripwire for a camera."""
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        line_json = json.dumps(line_segment)
        color_str = json.dumps(color) if isinstance(color, (list, tuple)) else str(color)
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO spatial_tripwires (camera_id, name, line_segment_json, bidirectional, color, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(camera_id, name) DO UPDATE SET
                        line_segment_json = excluded.line_segment_json,
                        bidirectional = excluded.bidirectional,
                        color = excluded.color,
                        updated_at = excluded.updated_at
                    """,
                    (camera_id, name, line_json, 1 if bidirectional else 0, color_str, now, now),
                )
                self._conn.commit()
                return cur.lastrowid
            finally:
                cur.close()

    def get_tripwires(self, camera_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve spatial tripwires, optionally filtered by camera_id."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                if camera_id:
                    cur.execute("SELECT * FROM spatial_tripwires WHERE camera_id = ? ORDER BY name ASC", (camera_id,))
                else:
                    cur.execute("SELECT * FROM spatial_tripwires ORDER BY camera_id, name ASC")
                rows = cur.fetchall()
                results = []
                for r in rows:
                    d = dict(r)
                    d["line_segment"] = json.loads(d["line_segment_json"])
                    d["bidirectional"] = bool(d["bidirectional"])
                    try:
                        d["color"] = json.loads(d["color"]) if d["color"] else [0, 255, 255]
                    except Exception:
                        d["color"] = [0, 255, 255]
                    results.append(d)
                return results
            finally:
                cur.close()

    def delete_tripwire(self, camera_id: str, name: str) -> bool:
        """Delete a spatial tripwire by camera and name."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("DELETE FROM spatial_tripwires WHERE camera_id = ? AND name = ?", (camera_id, name))
                self._conn.commit()
                return cur.rowcount > 0
            finally:
                cur.close()

    def save_spatial_transition(
        self,
        link_id: str,
        source_camera: str,
        source_zone: str,
        target_camera: str,
        target_zone: str,
        t_min: float = 2.0,
        t_max: float = 15.0,
        prior_boost: float = 0.35,
        bidirectional: bool = False,
        active: bool = True,
    ) -> int:
        """Create or update a cross-camera spatial transition link."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO spatial_transitions (link_id, source_camera, source_zone, target_camera, target_zone, t_min, t_max, prior_boost, bidirectional, active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(link_id) DO UPDATE SET
                        source_camera = excluded.source_camera,
                        source_zone = excluded.source_zone,
                        target_camera = excluded.target_camera,
                        target_zone = excluded.target_zone,
                        t_min = excluded.t_min,
                        t_max = excluded.t_max,
                        prior_boost = excluded.prior_boost,
                        bidirectional = excluded.bidirectional,
                        active = excluded.active
                    """,
                    (link_id, source_camera, source_zone, target_camera, target_zone, t_min, t_max, prior_boost, 1 if bidirectional else 0, 1 if active else 0),
                )
                self._conn.commit()
                return cur.lastrowid
            finally:
                cur.close()

    def get_spatial_transitions(self) -> List[Dict[str, Any]]:
        """Retrieve all cross-camera spatial transition links."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("SELECT * FROM spatial_transitions ORDER BY id ASC")
                rows = cur.fetchall()
                results = []
                for r in rows:
                    d = dict(r)
                    d["bidirectional"] = bool(d["bidirectional"])
                    d["active"] = bool(d["active"])
                    results.append(d)
                return results
            finally:
                cur.close()

    def delete_spatial_transition(self, link_id: str) -> bool:
        """Delete a spatial transition link by link_id."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("DELETE FROM spatial_transitions WHERE link_id = ?", (link_id,))
                self._conn.commit()
                return cur.rowcount > 0
            finally:
                cur.close()

    def save_homography_calibration(
        self,
        camera_id: str,
        src_points: List[Union[List[float], Tuple[float, float]]],
        dst_points: List[Union[List[float], Tuple[float, float]]],
        matrix: List[List[float]],
        metric_width: float = 10.0,
        metric_height: float = 10.0,
    ) -> int:
        """Save 4-point homography calibration for a camera channel."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO homography_calibrations (camera_id, src_points_json, dst_points_json, matrix_json, metric_width, metric_height)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(camera_id) DO UPDATE SET
                        src_points_json = excluded.src_points_json,
                        dst_points_json = excluded.dst_points_json,
                        matrix_json = excluded.matrix_json,
                        metric_width = excluded.metric_width,
                        metric_height = excluded.metric_height
                    """,
                    (camera_id, json.dumps(src_points), json.dumps(dst_points), json.dumps(matrix), metric_width, metric_height),
                )
                self._conn.commit()
                return cur.lastrowid
            finally:
                cur.close()

    def get_homography_calibration(self, camera_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve homography calibration profile for a camera."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("SELECT * FROM homography_calibrations WHERE camera_id = ?", (camera_id,))
                row = cur.fetchone()
                if not row:
                    return None
                d = dict(row)
                d["src_points"] = json.loads(d["src_points_json"])
                d["dst_points"] = json.loads(d["dst_points_json"])
                d["homography_matrix"] = json.loads(d["matrix_json"])
                return d
            finally:
                cur.close()

    def delete_homography_calibration(self, camera_id: str) -> bool:
        """Delete homography calibration profile for a camera."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("DELETE FROM homography_calibrations WHERE camera_id = ?", (camera_id,))
                self._conn.commit()
                return cur.rowcount > 0
            finally:
                cur.close()

    # -------------------------------------------------------------------------
    # Descriptor Versions & Memory Rollback (Milestone 9)
    # -------------------------------------------------------------------------

    def record_descriptor_version(
        self,
        entity_id: int,
        embedding: Optional[np.ndarray] = None,
        feature_vector: Optional[np.ndarray] = None,
        crop_path: str = "",
        source: str = "manual_enrollment",
        notes: str = "",
        version: Optional[int] = None,
        version_num: Optional[int] = None,
        update_reason: str = "",
        is_anchor: int = 0,
        **kwargs,
    ) -> int:
        """
        Record a descriptor version snapshot for historical rollback and drift monitoring.

        :param entity_id: Entity ID.
        :param embedding: Feature vector (or feature_vector).
        :param crop_path: Optional path to thumbnail crop.
        :param source: 'manual_enrollment', 'active_learning', 'ema_update', 'rollback'.
        :param notes: Metadata or operator notes.
        :param version: Explicit version number (optional).
        :param update_reason: Optional alias for notes/source.
        :param is_anchor: Ground truth locked anchor indicator.
        :return: Created version ID.
        """
        vec = feature_vector if feature_vector is not None else embedding
        if vec is None:
            vec = np.zeros(16, dtype=np.float32)
        blob = self.serialize_embedding(vec)
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())

        ver = version if version is not None else version_num
        reason = update_reason or notes or source
        src = source if (source != "manual_enrollment" or not update_reason) else update_reason

        with self._lock:
            cur = self._conn.cursor()
            try:
                if ver is None:
                    cur.execute("SELECT COALESCE(MAX(version_num), 0) FROM descriptor_versions WHERE entity_id = ?", (entity_id,))
                    max_ver = cur.fetchone()[0]
                    ver = max_ver + 1

                cur.execute(
                    """
                    INSERT INTO descriptor_versions (entity_id, version_num, embedding, crop_path, source, notes, is_anchor, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (entity_id, ver, blob, crop_path.strip(), src.strip(), reason.strip(), int(is_anchor), now),
                )
                self._conn.commit()
                return cur.lastrowid
            finally:
                cur.close()

    def get_descriptor_versions(self, entity_id: int) -> List[Dict[str, Any]]:
        """Retrieve historical descriptor versions for an entity, sorted descending by version."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    "SELECT id, entity_id, version_num, embedding, crop_path, source, notes, is_anchor, created_at "
                    "FROM descriptor_versions WHERE entity_id = ? ORDER BY version_num DESC",
                    (entity_id,),
                )
                results = []
                for row in cur.fetchall():
                    item = dict(row)
                    item["version"] = item["version_num"]
                    item["embedding"] = self.deserialize_embedding(item["embedding"])
                    item["feature_vector"] = item["embedding"]
                    item["update_reason"] = item["notes"] or item["source"]
                    results.append(item)
                return results
            finally:
                cur.close()

    def rollback_descriptor(self, entity_id: int, version: Optional[int] = None, version_num: Optional[int] = None) -> bool:
        """
        Rollback an entity's active descriptor signature to an earlier historical version.

        :param entity_id: Target entity ID.
        :param version: Version number to restore (alias version_num).
        :return: True if successfully restored.
        """
        ver = version if version is not None else version_num
        if ver is None:
            return False

        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    "SELECT embedding, crop_path FROM descriptor_versions WHERE entity_id = ? AND version_num = ?",
                    (entity_id, ver),
                )
                row = cur.fetchone()
                if not row:
                    return False

                blob = row["embedding"]
                crop_path = row["crop_path"]

                # Check if non-anchor signature exists to update
                cur.execute(
                    "SELECT id FROM entity_signatures WHERE entity_id = ? AND is_anchor = 0 ORDER BY id DESC LIMIT 1",
                    (entity_id,),
                )
                dyn_sig = cur.fetchone()
                if dyn_sig:
                    cur.execute(
                        "UPDATE entity_signatures SET embedding = ?, crop_path = ?, created_at = ? WHERE id = ?",
                        (blob, crop_path, now, dyn_sig[0]),
                    )
                else:
                    # Update all or insert rolled back signature
                    cur.execute(
                        "UPDATE entity_signatures SET embedding = ?, crop_path = ?, created_at = ? WHERE entity_id = ?",
                        (blob, crop_path, now, entity_id),
                    )

                # Record rollback event in version history
                cur.execute("SELECT COALESCE(MAX(version_num), 0) FROM descriptor_versions WHERE entity_id = ?", (entity_id,))
                max_ver = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO descriptor_versions (entity_id, version_num, embedding, crop_path, source, notes, is_anchor, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (entity_id, max_ver + 1, blob, crop_path, f"rollback_to_v{ver}", f"Restored signature from v{ver}", 0, now),
                )
                self._conn.commit()
                return True
            finally:
                cur.close()

    # -------------------------------------------------------------------------
    # Active Learning "Review & Learn" Inbox (Milestone 9)
    # -------------------------------------------------------------------------

    def add_review_item(
        self,
        camera_id: str,
        track_id: int,
        crop_path: str,
        suggested_entity_id: Optional[int] = None,
        suggested_name: str = "",
        suggested_category: str = "",
        similarity: float = 0.0,
        status: str = "pending",
        **kwargs,
    ) -> int:
        """Add an ambiguous detection to the active learning review queue."""
        if "similarity_score" in kwargs:
            similarity = kwargs["similarity_score"]
        if "matched_entity_id" in kwargs and suggested_entity_id is None:
            suggested_entity_id = kwargs["matched_entity_id"]
        if "matched_entity_name" in kwargs and not suggested_name:
            suggested_name = kwargs["matched_entity_name"]
        if "matched_category" in kwargs and not suggested_category:
            suggested_category = kwargs["matched_category"]

        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO review_queue (camera_id, track_id, crop_path, timestamp, suggested_entity_id, suggested_name, suggested_category, similarity, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (camera_id, track_id, crop_path.strip(), now, suggested_entity_id, suggested_name.strip(), suggested_category.strip(), float(similarity), status.strip()),
                )
                self._conn.commit()
                return cur.lastrowid
            finally:
                cur.close()

    def list_review_items(self, status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """List active learning review items, optionally filtered by status."""
        query = "SELECT * FROM review_queue"
        params = []
        if status:
            query += " WHERE status = ?"
            params.append(status.strip())
        query += " ORDER BY id DESC"
        if limit > 0:
            query += " LIMIT ?"
            params.append(int(limit))

        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(query, params)
                return [dict(r) for r in cur.fetchall()]
            finally:
                cur.close()

    def get_review_item(self, review_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve single review queue item by ID."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("SELECT * FROM review_queue WHERE id = ?", (review_id,))
                row = cur.fetchone()
                return dict(row) if row else None
            finally:
                cur.close()

    def update_review_status(self, review_id: int, status: str, reviewed_by: str = "operator") -> bool:
        """Update status of a review queue candidate ('confirmed', 'reassigned', 'enrolled_new', 'dismissed')."""
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    "UPDATE review_queue SET status = ?, reviewed_at = ?, reviewed_by = ? WHERE id = ?",
                    (status.strip(), now, reviewed_by.strip(), review_id),
                )
                self._conn.commit()
                return cur.rowcount > 0
            finally:
                cur.close()

    # -------------------------------------------------------------------------
    # Role-Based Spatial Access Control (RSAC) & Custom Categories (Milestone 9)
    # -------------------------------------------------------------------------

    def get_custom_categories(self) -> List[Dict[str, Any]]:
        """List all registered custom categories with color badges."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("SELECT * FROM custom_categories ORDER BY id ASC")
                return [dict(r) for r in cur.fetchall()]
            finally:
                cur.close()

    def set_custom_category(
        self,
        cat_id: str,
        name: str,
        color: str = "#3B82F6",
        description: str = "",
        badge_icon: str = "",
    ) -> bool:
        """Register or update custom category badge."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO custom_categories (id, name, color, badge_icon, description)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        color = excluded.color,
                        badge_icon = excluded.badge_icon,
                        description = excluded.description
                    """,
                    (cat_id.strip().lower(), name.strip(), color.strip(), badge_icon.strip(), description.strip()),
                )
                self._conn.commit()
                return True
            finally:
                cur.close()

    def delete_custom_category(self, cat_id: str) -> bool:
        """Delete custom category."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("DELETE FROM custom_categories WHERE id = ?", (cat_id.strip().lower(),))
                self._conn.commit()
                return cur.rowcount > 0
            finally:
                cur.close()

    def get_rsac_rules(self, camera_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List RSAC zone permission rules, optionally filtered by camera."""
        query = "SELECT * FROM rsac_zone_rules"
        params = []
        if camera_id:
            query += " WHERE camera_id = ?"
            params.append(camera_id)
        query += " ORDER BY camera_id, zone_id ASC"

        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(query, params)
                results = []
                for r in cur.fetchall():
                    d = dict(r)
                    d["allowed_categories"] = json.loads(d["allowed_categories_json"])
                    d["denied_categories"] = json.loads(d["denied_categories_json"])
                    d["schedules"] = json.loads(d["schedules_json"])
                    d["entity_overrides"] = json.loads(d["entity_overrides_json"])
                    d["alarm_on_breach"] = bool(d["alarm_on_breach"])
                    results.append(d)
                return results
            finally:
                cur.close()

    def get_rsac_rule(self, camera_id: str, zone_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve single RSAC rule for a camera zone."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("SELECT * FROM rsac_zone_rules WHERE camera_id = ? AND zone_id = ?", (camera_id, zone_id))
                row = cur.fetchone()
                if not row:
                    return None
                d = dict(row)
                d["allowed_categories"] = json.loads(d["allowed_categories_json"])
                d["denied_categories"] = json.loads(d["denied_categories_json"])
                d["schedules"] = json.loads(d["schedules_json"])
                d["entity_overrides"] = json.loads(d["entity_overrides_json"])
                d["alarm_on_breach"] = bool(d["alarm_on_breach"])
                return d
            finally:
                cur.close()

    def set_rsac_rule(
        self,
        camera_id: str,
        zone_id: str,
        allowed_categories: List[str],
        denied_categories: Optional[List[str]] = None,
        schedules: Optional[List[Dict[str, Any]]] = None,
        entity_overrides: Optional[Dict[str, str]] = None,
        alarm_on_breach: bool = True,
    ) -> bool:
        """Create or update RSAC permissions for a zone."""
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        allowed_json = json.dumps(allowed_categories or [])
        denied_json = json.dumps(denied_categories or [])
        schedules_json = json.dumps(schedules or [])
        overrides_json = json.dumps(entity_overrides or {})

        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO rsac_zone_rules (camera_id, zone_id, allowed_categories_json, denied_categories_json, schedules_json, entity_overrides_json, alarm_on_breach, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(camera_id, zone_id) DO UPDATE SET
                        allowed_categories_json = excluded.allowed_categories_json,
                        denied_categories_json = excluded.denied_categories_json,
                        schedules_json = excluded.schedules_json,
                        entity_overrides_json = excluded.entity_overrides_json,
                        alarm_on_breach = excluded.alarm_on_breach,
                        updated_at = excluded.updated_at
                    """,
                    (camera_id, zone_id, allowed_json, denied_json, schedules_json, overrides_json, 1 if alarm_on_breach else 0, now, now),
                )
                self._conn.commit()
                return True
            finally:
                cur.close()

    def delete_rsac_rule(self, camera_id: str, zone_id: str) -> bool:
        """Delete RSAC rule for a zone."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("DELETE FROM rsac_zone_rules WHERE camera_id = ? AND zone_id = ?", (camera_id, zone_id))
                self._conn.commit()
                return cur.rowcount > 0
            finally:
                cur.close()

    # -------------------------------------------------------------------------
    # Pet Whitelist Management (Milestone 9)
    # -------------------------------------------------------------------------

    def get_pet_whitelist(self) -> List[str]:
        """List all whitelisted pet labels and categories."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("SELECT category_or_label FROM pet_whitelist ORDER BY id ASC")
                return [r[0] for r in cur.fetchall()]
            finally:
                cur.close()

    def add_pet_whitelist(self, label: str, notes: str = "") -> bool:
        """Add label or category to pet whitelist."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    "INSERT OR IGNORE INTO pet_whitelist (category_or_label, notes) VALUES (?, ?)",
                    (label.strip().lower(), notes.strip()),
                )
                self._conn.commit()
                return cur.rowcount > 0
            finally:
                cur.close()

    def remove_pet_whitelist(self, label: str) -> bool:
        """Remove label from pet whitelist."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("DELETE FROM pet_whitelist WHERE category_or_label = ?", (label.strip().lower(),))
                self._conn.commit()
                return cur.rowcount > 0
            finally:
                cur.close()

    # -------------------------------------------------------------------------
    # Enterprise Cloud Hub Offline-First Cache & Local Whitelist
    # -------------------------------------------------------------------------

    def get_sync_state(self, sync_key: str = "default") -> Optional[Dict[str, Any]]:
        """Retrieve synchronization state and ETag for Cloud Hub delta sync."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("SELECT * FROM tracker_sync_state WHERE sync_key = ?", (sync_key,))
                row = cur.fetchone()
                if not row:
                    return None
                data = dict(row)
                try:
                    data["metadata"] = json.loads(data.get("metadata_json") or "{}")
                except Exception:
                    data["metadata"] = {}
                return data
            finally:
                cur.close()

    def update_sync_state(
        self,
        sync_key: str = "default",
        last_etag: str = "",
        active_whitelist_count: int = 0,
        status: str = "synced",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Update or insert Cloud Hub synchronization checkpoint state."""
        meta_json = json.dumps(metadata or {})
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO tracker_sync_state (sync_key, last_etag, last_sync_timestamp, active_whitelist_count, status, metadata_json)
                    VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?, ?)
                    ON CONFLICT(sync_key) DO UPDATE SET
                        last_etag = excluded.last_etag,
                        last_sync_timestamp = CURRENT_TIMESTAMP,
                        active_whitelist_count = excluded.active_whitelist_count,
                        status = excluded.status,
                        metadata_json = excluded.metadata_json
                    """,
                    (sync_key, last_etag, int(active_whitelist_count), str(status), meta_json),
                )
                self._conn.commit()
                return True
            finally:
                cur.close()

    def upsert_whitelist_entry(
        self,
        credential_id: str,
        entity_name: str,
        clearance_tier: str = "VISITOR",
        plate_number: str = "",
        embedding: Optional[Union[np.ndarray, bytes]] = None,
        valid_from: Optional[str] = None,
        valid_until: Optional[str] = None,
        is_banned: bool = False,
        sync_version: int = 1,
    ) -> int:
        """Insert or update an authoritative credential in the local offline whitelist."""
        blob = None
        if embedding is not None:
            if isinstance(embedding, np.ndarray):
                blob = embedding.astype(np.float32).tobytes()
            elif isinstance(embedding, (bytes, bytearray)):
                blob = bytes(embedding)

        norm_plate = plate_number.strip().upper().replace(" ", "").replace("-", "") if plate_number else ""
        tier = clearance_tier.strip().upper()

        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO local_whitelist (
                        credential_id, entity_name, clearance_tier, plate_number,
                        embedding, valid_from, valid_until, is_banned, sync_version, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(credential_id) DO UPDATE SET
                        entity_name = excluded.entity_name,
                        clearance_tier = excluded.clearance_tier,
                        plate_number = excluded.plate_number,
                        embedding = coalesce(excluded.embedding, local_whitelist.embedding),
                        valid_from = excluded.valid_from,
                        valid_until = excluded.valid_until,
                        is_banned = excluded.is_banned,
                        sync_version = excluded.sync_version,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        credential_id.strip(),
                        entity_name.strip(),
                        tier,
                        norm_plate,
                        blob,
                        valid_from,
                        valid_until,
                        1 if is_banned else 0,
                        int(sync_version),
                    ),
                )
                self._conn.commit()
                return cur.lastrowid
            finally:
                cur.close()

    def get_whitelist_entry(self, credential_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single local whitelist entry by credential ID."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("SELECT * FROM local_whitelist WHERE credential_id = ?", (credential_id.strip(),))
                row = cur.fetchone()
                if not row:
                    return None
                data = dict(row)
                if data.get("embedding"):
                    data["embedding_array"] = np.frombuffer(data["embedding"], dtype=np.float32)
                return data
            finally:
                cur.close()

    def list_whitelist(
        self,
        clearance_tier: Optional[str] = None,
        active_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """List local whitelist credentials, optionally filtered by tier or active status."""
        query = "SELECT * FROM local_whitelist WHERE 1=1"
        params: List[Any] = []
        if clearance_tier:
            query += " AND clearance_tier = ?"
            params.append(clearance_tier.strip().upper())
        if active_only:
            query += " AND is_banned = 0 AND (valid_until IS NULL OR valid_until >= CURRENT_TIMESTAMP)"

        query += " ORDER BY updated_at DESC"

        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(query, params)
                results = []
                for row in cur.fetchall():
                    d = dict(row)
                    results.append(d)
                return results
            finally:
                cur.close()

    def delete_whitelist_entry(self, credential_id: str) -> bool:
        """Remove a credential from local whitelist cache."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("DELETE FROM local_whitelist WHERE credential_id = ?", (credential_id.strip(),))
                self._conn.commit()
                return cur.rowcount > 0
            finally:
                cur.close()

    def enqueue_offline_access(
        self,
        event_uuid: str,
        camera_id: str,
        access_granted: bool,
        credential_id: Optional[str] = None,
        direction: str = "in",
        decision_reason: str = "",
        snapshot_path: str = "",
    ) -> int:
        """Buffer a gate access attempt in the offline outbox queue."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO offline_access_queue (
                        event_uuid, credential_id, camera_id, direction,
                        access_granted, decision_reason, snapshot_path, synced
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        event_uuid.strip(),
                        credential_id.strip() if credential_id else None,
                        camera_id.strip(),
                        direction.strip().lower(),
                        1 if access_granted else 0,
                        decision_reason.strip(),
                        snapshot_path.strip(),
                    ),
                )
                self._conn.commit()
                return cur.lastrowid
            finally:
                cur.close()

    def get_pending_offline_access(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve unsynced access logs waiting to be flushed to Cloud Hub."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    "SELECT * FROM offline_access_queue WHERE synced = 0 ORDER BY occurred_at ASC LIMIT ?",
                    (int(limit),),
                )
                return [dict(r) for r in cur.fetchall()]
            finally:
                cur.close()

    def mark_offline_access_synced(self, event_uuids: List[str]) -> int:
        """Mark successfully transmitted access logs as synced."""
        if not event_uuids:
            return 0
        placeholders = ",".join("?" for _ in event_uuids)
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    f"UPDATE offline_access_queue SET synced = 1, synced_at = CURRENT_TIMESTAMP WHERE event_uuid IN ({placeholders})",
                    event_uuids,
                )
                self._conn.commit()
                return cur.rowcount
            finally:
                cur.close()

    # -------------------------------------------------------------------------
    # System Resource Metrics & Stream Lifecycle Events
    # -------------------------------------------------------------------------

    def record_resource_metric(
        self,
        cpu_percent: float,
        memory_mb: float,
        active_streams: int,
        hibernating_streams: int,
        total_subscribers: int,
        timestamp: Optional[float] = None,
    ) -> int:
        """Record a periodic system resource telemetry sample."""
        ts = timestamp if timestamp is not None else time.time()
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO system_resource_metrics (
                        timestamp, cpu_percent, memory_mb, active_streams, hibernating_streams, total_subscribers
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (ts, float(cpu_percent), float(memory_mb), int(active_streams), int(hibernating_streams), int(total_subscribers)),
                )
                self._conn.commit()
                return cur.lastrowid
            finally:
                cur.close()

    def get_resource_metrics(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve recent system resource telemetry samples in chronological order."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    SELECT * FROM (
                        SELECT * FROM system_resource_metrics ORDER BY timestamp DESC LIMIT ?
                    ) ORDER BY timestamp ASC
                    """,
                    (int(limit),),
                )
                return [dict(r) for r in cur.fetchall()]
            finally:
                cur.close()

    def record_lifecycle_event(
        self,
        camera_id: str,
        event_type: str,
        old_state: Optional[str] = None,
        new_state: Optional[str] = None,
        subscriber_count: int = 0,
        details: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> int:
        """Log a stream lifecycle transition (e.g. START, HIBERNATE, RESUME, EVICT, STOP)."""
        ts = timestamp if timestamp is not None else time.time()
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO stream_lifecycle_events (
                        timestamp, camera_id, event_type, old_state, new_state, subscriber_count, details
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (ts, str(camera_id), str(event_type).upper(), old_state, new_state, int(subscriber_count), details),
                )
                self._conn.commit()
                return cur.lastrowid
            finally:
                cur.close()

    def get_lifecycle_events(
        self,
        camera_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Retrieve historical stream lifecycle events."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                if camera_id:
                    cur.execute(
                        """
                        SELECT * FROM stream_lifecycle_events
                        WHERE camera_id = ?
                        ORDER BY timestamp DESC LIMIT ?
                        """,
                        (str(camera_id), int(limit)),
                    )
                else:
                    cur.execute(
                        """
                        SELECT * FROM stream_lifecycle_events
                        ORDER BY timestamp DESC LIMIT ?
                        """,
                        (int(limit),),
                    )
                return [dict(r) for r in cur.fetchall()]
            finally:
                cur.close()

    # -------------------------------------------------------------------------
    # Context Manager & Lifecycle
    # -------------------------------------------------------------------------

    def close(self):
        """Close SQLite database connection."""
        with self._lock:
            if hasattr(self, "_conn") and self._conn is not None:
                try:
                    self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                except Exception:
                    pass
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        self.close()
