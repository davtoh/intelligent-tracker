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

import sqlite3
import threading
import logging

from intelligent_tracker.repositories import (
    SQLiteConnectionCoordinator,
    get_connection_coordinator,
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
    MemoryMixin,
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
    MemoryMixin,
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

    def __init__(
        self,
        db_path: str = "data/tracker.db",
        coordinator: SQLiteConnectionCoordinator | None = None,
    ):
        """
        Initialize TrackerDB.

        :param db_path: Path to SQLite database file, or ':memory:' for in-memory DB.
        :param coordinator: Optional connection/lock coordinator (defaults to global registry).
        """
        self.db_path = db_path
        self._coordinator = coordinator or get_connection_coordinator()
        self._lock: threading.RLock = self._coordinator.get_path_lock(db_path)
        self._conn: sqlite3.Connection | None = None
        self._closed = False

        with self._lock:
            self._conn, self._lock = self._coordinator.open_connection(
                self.db_path, lock=self._lock
            )
            try:
                self._init_schema()
            except Exception:
                self.close()
                raise

    def close(self) -> None:
        """Close SQLite database connection idempotently."""
        lock = getattr(self, "_lock", None)
        if lock is None:
            return
        with lock:
            if getattr(self, "_closed", False) or getattr(self, "_conn", None) is None:
                self._closed = True
                self._conn = None
                return
            conn = self._conn
            self._conn = None
            self._closed = True
            self._coordinator.close_connection(self.db_path, conn, lock)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        self.close()


__all__ = ["TrackerDB"]
