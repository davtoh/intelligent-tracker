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

                # 4. Indexes for rapid lookups
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
    ) -> int:
        """
        Add a feature signature embedding for an entity.

        :param entity_id: Target entity ID.
        :param embedding: 1D NumPy float vector representing the visual embedding.
        :param crop_path: Optional path to saved cropped thumbnail image.
        :return: Created signature ID.
        """
        blob = self.serialize_embedding(embedding)
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())

        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO entity_signatures (entity_id, embedding, crop_path, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (entity_id, blob, crop_path.strip(), now),
                )
                self._conn.commit()
                return cursor.lastrowid
            finally:
                cursor.close()

    def get_signatures(self, entity_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Retrieve signatures, optionally filtered for a specific entity.

        :return: List of dicts with deserialized `embedding` arrays.
        """
        query = "SELECT id, entity_id, embedding, crop_path, created_at FROM entity_signatures"
        params = []
        if entity_id is not None:
            query += " WHERE entity_id = ?"
            params.append(entity_id)
        query += " ORDER BY id ASC"

        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute(query, params)
                results = []
                for row in cursor.fetchall():
                    item = dict(row)
                    item["embedding"] = self.deserialize_embedding(item["embedding"])
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
    # Context Manager & Lifecycle
    # -------------------------------------------------------------------------

    def close(self):
        """Close SQLite database connection."""
        with self._lock:
            if hasattr(self, "_conn") and self._conn is not None:
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
