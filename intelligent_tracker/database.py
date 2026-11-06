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
import sqlite3
import threading
import logging
from typing import Optional

from intelligent_tracker.repositories import (
    SchemaMixin,
    EntityMixin,
    SignatureMixin,
    DescriptorMixin,
    AnalyticsMixin,
    SpatialMixin,
    LearningMixin,
    RsacMixin,
    WhitelistMixin,
    TelemetryMixin,
)

logger = logging.getLogger(__name__)


class TrackerDB(
    SchemaMixin,
    EntityMixin,
    SignatureMixin,
    DescriptorMixin,
    AnalyticsMixin,
    SpatialMixin,
    LearningMixin,
    RsacMixin,
    WhitelistMixin,
    TelemetryMixin,
):
    """
    Thread-safe SQLite database manager for entities, Re-ID signatures, and sightings.

    Composed from focused domain mixins in ``intelligent_tracker.repositories``:
    - ``SchemaMixin``: DDL schema management, indexes, migrations, and seed data.
    - ``EntityMixin``: Entity registration, updates, and high-level enrollment.
    - ``SignatureMixin``: Re-ID embedding vectors, serialization, and gallery matrices.
    - ``DescriptorMixin``: Historical descriptor versioning and locked anchor rollback.
    - ``AnalyticsMixin``: Sighting audit trails, analytics, dwell times, and CSV/JSON exports.
    - ``SpatialMixin``: Scenario Studio zones, tripwires, transitions, and homography.
    - ``LearningMixin``: Active learning inbox queue and role-based custom categories.
    - ``RsacMixin``: Role-based spatial access control rules and pet whitelists.
    - ``WhitelistMixin``: Local offline-first whitelist and cloud sync outbox queuing.
    - ``TelemetryMixin``: Hardware resource usage samples and stream lifecycle events.
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

    def close(self) -> None:
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


__all__ = ["TrackerDB"]
