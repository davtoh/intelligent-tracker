#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit Tests for Memory Schema Migration (v0 -> v1) & MemoryMixin FTS5 Repository."""

from concurrent.futures import ThreadPoolExecutor
import os
import sqlite3
import tempfile
import unittest

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.repositories.memory_schema import MEMORY_SCHEMA_VERSION


def _seed_v0_database(db_path: str) -> None:
    """Create and populate a legacy PRAGMA user_version=0 SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            category TEXT DEFAULT 'person', status TEXT DEFAULT 'active',
            notes TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE entity_signatures (
            id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id INTEGER NOT NULL,
            embedding BLOB NOT NULL, crop_path TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE sightings (
            id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id INTEGER,
            track_id INTEGER, source TEXT DEFAULT '',
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            zone_id TEXT DEFAULT '', bbox TEXT DEFAULT '',
            confidence REAL DEFAULT 1.0, snapshot_path TEXT DEFAULT ''
        );
        INSERT INTO entities (id, name, category) VALUES (42, 'Legacy Alice', 'person');
        INSERT INTO entity_signatures (entity_id, embedding, crop_path) VALUES (42, X'0000803F0000803F', 'legacy.jpg');
        INSERT INTO sightings (entity_id, track_id, source, zone_id) VALUES (42, 7, 'cam_01', 'lobby');
        PRAGMA user_version = 0;
        """
    )
    conn.commit()
    conn.close()


class TestMemoryRepository(unittest.TestCase):
    """Tests PRAGMA user_version=1 migration, confidence state, FTS5 BM25, and WAL concurrency."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.db_path = os.path.join(self.tmp_dir.name, "memory_test.db")

    def test_fresh_db_initializes_v1_schema(self):
        """Fresh TrackerDB sets PRAGMA user_version=1 and creates memory tables."""
        db = TrackerDB(self.db_path)
        self.addCleanup(db.close)
        self.assertEqual(db.get_schema_version(), MEMORY_SCHEMA_VERSION)
        with db._lock:
            tables = {
                row[0]
                for row in db._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
                ).fetchall()
            }
        self.assertIn("entity_confidence_state", tables)
        self.assertIn("world_timeline_events", tables)
        self.assertIn("world_timeline_fts", tables)

    def test_v0_to_v1_migration_preserves_existing_data_and_is_idempotent(self):
        """Pre-populated v0 DB upgrades cleanly to v1 without data loss."""
        _seed_v0_database(self.db_path)

        db = TrackerDB(self.db_path)
        self.addCleanup(db.close)
        self.assertEqual(db.get_schema_version(), 1)
        alice = db.get_entity(42)
        self.assertIsNotNone(alice)
        self.assertEqual(alice["name"], "Legacy Alice")
        self.assertEqual(len(db.get_entity_signatures(42)), 1)
        self.assertEqual(len(db.get_sightings(entity_id=42)), 1)
        db.close()

        db2 = TrackerDB(self.db_path)
        self.addCleanup(db2.close)
        self.assertEqual(db2.get_schema_version(), 1)
        self.assertEqual(db2.get_entity(42)["name"], "Legacy Alice")

    def test_entity_confidence_crud_and_filtering(self):
        """Confidence upserts, retrieval, clamping, and min_confidence filtering work."""
        db = TrackerDB(self.db_path)
        self.addCleanup(db.close)
        alice_id = db.add_entity("Alice", "person")
        bob_id = db.add_entity("Bob", "staff")

        saved = db.upsert_entity_confidence(
            entity_id=alice_id, confidence=1.25, face_score=0.91, body_score=0.84,
            streak_count=5, observation_count=12, confirmation_count=1,
            last_camera_id="cam_01", last_zone_id="lobby", last_seen_at=1000.0,
            evidence={"topology_prior": 0.35},
        )
        self.assertEqual(saved["confidence"], 1.0)
        self.assertEqual(saved["entity_name"], "Alice")
        self.assertEqual(saved["evidence"]["topology_prior"], 0.35)

        db.upsert_entity_confidence(
            entity_id=bob_id, confidence=0.42, last_camera_id="cam_02", last_seen_at=900.0
        )
        self.assertIsNone(db.get_entity_confidence(99999))
        high = db.list_entity_confidences(min_confidence=0.80)
        self.assertEqual([row["entity_id"] for row in high], [alice_id])
        all_rows = db.list_entity_confidences()
        self.assertEqual([row["entity_id"] for row in all_rows], [alice_id, bob_id])

    def test_fts5_indexing_bm25_ranking_filters_and_delete(self):
        """FTS5 indexing, BM25 ranking, punctuation safety, structured filters, and delete sync."""
        db = TrackerDB(self.db_path)
        self.addCleanup(db.close)
        alice_id = db.add_entity("Alice", "person")
        bob_id = db.add_entity("Bob", "visitor")

        ev1 = db.index_timeline_event(
            summary="Alice entered the restricted server_room carrying a badge",
            event_type="rsac_breach", entity_id=alice_id, entity_name="Alice",
            category="person", camera_id="cam_02", zone_id="server_room",
            timestamp=100.0, confidence=0.92, title="Server Room Entry",
            tags="breach badge", metadata={"clip": "clip_1.mp4"},
        )
        ev2 = db.index_timeline_event(
            summary="Bob walked past the lobby kiosk", event_type="zone_enter",
            entity_id=bob_id, entity_name="Bob", category="visitor",
            camera_id="cam_01", zone_id="lobby", timestamp=200.0, confidence=0.85, title="Lobby Sighting",
        )
        ev3 = db.index_timeline_event(
            summary="Alice appeared in lobby", event_type="sighting",
            entity_id=alice_id, entity_name="Alice", category="person",
            camera_id="cam_01", zone_id="lobby", timestamp=300.0, confidence=0.88, title="Alice Lobby",
        )

        hits = db.search_timeline_events(query="Where was Alice in server_room? (breach)*")
        self.assertGreaterEqual(len(hits), 2)
        self.assertEqual(hits[0]["id"], ev1)
        self.assertEqual(hits[0]["metadata"]["clip"], "clip_1.mp4")

        strict_hits = db.search_timeline_events(query="Alice lobby", zone_id="lobby", require_all=True)
        self.assertEqual([h["id"] for h in strict_hits], [ev3])
        window_hits = db.search_timeline_events(query="   ", start_time=150.0, end_time=250.0)
        self.assertEqual([h["id"] for h in window_hits], [ev2])

        self.assertTrue(db.delete_timeline_event(ev1))
        self.assertIsNone(db.get_timeline_event(ev1))
        self.assertEqual(db.search_timeline_events(query="server_room", require_all=True), [])

    def test_concurrent_wal_writes_across_threads(self):
        """Concurrent threads sharing file-backed TrackerDB perform WAL writes cleanly."""
        db = TrackerDB(self.db_path)
        self.addCleanup(db.close)
        eid = db.add_entity("ConcurrentEntity", "person")

        def worker(idx: int) -> int:
            db.upsert_entity_confidence(entity_id=eid, confidence=0.5 + (idx % 5) * 0.05, last_seen_at=float(idx))
            return db.index_timeline_event(
                summary=f"Concurrent observation {idx} in lobby",
                entity_id=eid, entity_name="ConcurrentEntity",
                camera_id="cam_01", zone_id="lobby", timestamp=float(idx),
            )

        with ThreadPoolExecutor(max_workers=6) as pool:
            ids = list(pool.map(worker, range(30)))

        self.assertEqual(len(ids), 30)
        results = db.search_timeline_events(query="Concurrent observation", limit=50)
        self.assertEqual(len(results), 30)


if __name__ == "__main__":
    unittest.main()
