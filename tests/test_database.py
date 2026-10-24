#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for TrackerDB module (intelligent_tracker/database.py).
"""

from __future__ import division, print_function, absolute_import

import os
import csv
import json
import shutil
import tempfile
import unittest
import threading
import numpy as np

from intelligent_tracker.database import TrackerDB


class TestTrackerDB(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_tracker.db")
        self.db = TrackerDB(self.db_path)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_schema_initialization(self):
        """Test tables and indexes are properly created."""
        cursor = self.db._conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cursor.fetchall()]
        self.assertIn("entities", tables)
        self.assertIn("entity_signatures", tables)
        self.assertIn("sightings", tables)

    def test_entity_crud(self):
        """Test entity addition, lookup, update, list, and delete."""
        # 1. Add entity
        eid = self.db.add_entity(name="Forklift #02", category="vehicle", notes="Warehouse A")
        self.assertIsInstance(eid, int)
        self.assertGreater(eid, 0)

        # 2. Get entity
        ent = self.db.get_entity(eid)
        self.assertIsNotNone(ent)
        self.assertEqual(ent["name"], "Forklift #02")
        self.assertEqual(ent["category"], "vehicle")
        self.assertEqual(ent["status"], "active")
        self.assertEqual(ent["notes"], "Warehouse A")

        # 3. Lookup by name
        ent_by_name = self.db.get_entity_by_name("Forklift #02")
        self.assertIsNotNone(ent_by_name)
        self.assertEqual(ent_by_name["id"], eid)

        # 4. Update entity
        updated = self.db.update_entity(eid, notes="Warehouse B relocated", status="idle")
        self.assertTrue(updated)
        ent_updated = self.db.get_entity(eid)
        self.assertEqual(ent_updated["notes"], "Warehouse B relocated")
        self.assertEqual(ent_updated["status"], "idle")

        # 5. List entities
        all_ents = self.db.list_entities()
        self.assertEqual(len(all_ents), 1)

        # 6. Delete entity
        deleted = self.db.delete_entity(eid)
        self.assertTrue(deleted)
        self.assertIsNone(self.db.get_entity(eid))

    def test_signature_serialization_and_gallery(self):
        """Test feature vector BLOB serialization, storage, and gallery retrieval."""
        eid1 = self.db.add_entity(name="Alice", category="staff")
        eid2 = self.db.add_entity(name="Bob", category="visitor")

        vec1 = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)
        vec2 = np.array([0.5, 0.6, 0.7, 0.8], dtype=np.float32)
        vec1_b = np.array([0.11, 0.21, 0.31, 0.41], dtype=np.float32)

        sig1 = self.db.add_signature(eid1, vec1, crop_path="crops/alice_1.jpg")
        sig2 = self.db.add_signature(eid2, vec2, crop_path="crops/bob_1.jpg")
        sig3 = self.db.add_signature(eid1, vec1_b, crop_path="crops/alice_2.jpg")

        self.assertIsInstance(sig1, int)
        self.assertIsInstance(sig2, int)
        self.assertIsInstance(sig3, int)

        # Get signatures for Alice
        alice_sigs = self.db.get_signatures(eid1)
        self.assertEqual(len(alice_sigs), 2)
        np.testing.assert_allclose(alice_sigs[0]["embedding"], vec1, rtol=1e-5)
        np.testing.assert_allclose(alice_sigs[1]["embedding"], vec1_b, rtol=1e-5)

        # Gallery matrix fetch
        mat, ids, names, categories = self.db.get_gallery_embeddings()
        self.assertEqual(mat.shape, (3, 4))
        self.assertEqual(ids, [eid1, eid2, eid1])
        self.assertEqual(names, ["Alice", "Bob", "Alice"])
        self.assertEqual(categories, ["staff", "visitor", "staff"])

    def test_cascade_delete_signatures(self):
        """Deleting an entity should cascade delete its signatures."""
        eid = self.db.add_entity(name="Charlie", category="customer")
        vec = np.ones(8, dtype=np.float32)
        self.db.add_signature(eid, vec)

        self.assertEqual(len(self.db.get_signatures(eid)), 1)
        self.db.delete_entity(eid)
        self.assertEqual(len(self.db.get_signatures(eid)), 0)

    def test_sightings_audit_trail_and_analytics(self):
        """Test sighting logging, queries, and analytics aggregation."""
        eid = self.db.add_entity(name="David", category="vip")

        # Add multiple sightings
        s1 = self.db.add_sighting(
            entity_id=eid,
            track_id=101,
            source="camera_front",
            timestamp="2026-10-24 10:00:00",
            zone_id="entrance",
            bbox=(10, 20, 50, 100),
            confidence=0.92,
        )
        s2 = self.db.add_sighting(
            entity_id=eid,
            track_id=101,
            source="camera_front",
            timestamp="2026-10-24 10:01:30",
            zone_id="lobby",
            bbox=(60, 20, 50, 100),
            confidence=0.88,
        )
        s3 = self.db.add_sighting(
            entity_id=eid,
            track_id=205,
            source="camera_back",
            timestamp="2026-10-24 10:05:00",
            zone_id="exit",
            bbox=(120, 50, 40, 80),
            confidence=0.95,
        )

        # Query sightings
        sightings = self.db.get_sightings(entity_id=eid)
        self.assertEqual(len(sightings), 3)
        self.assertEqual(sightings[0]["id"], s3)  # Ordered by DESC timestamp

        # Query by zone
        lobby_sightings = self.db.get_sightings(zone_id="lobby")
        self.assertEqual(len(lobby_sightings), 1)
        self.assertEqual(lobby_sightings[0]["id"], s2)

        # Entity analytics
        analytics = self.db.get_entity_analytics(eid)
        self.assertEqual(analytics["total_sightings"], 3)
        self.assertEqual(analytics["first_seen"], "2026-10-24 10:00:00")
        self.assertEqual(analytics["last_seen"], "2026-10-24 10:05:00")
        self.assertEqual(analytics["distinct_sources_count"], 2)
        self.assertIn("camera_front", analytics["sources"])
        self.assertIn("camera_back", analytics["sources"])
        self.assertEqual(analytics["distinct_zones_count"], 3)
        self.assertEqual(analytics["estimated_dwell_seconds"], 300.0)

    def test_enroll_entity_helper(self):
        """Test high-level enroll_entity with synthetic frame and crop."""
        frame = np.zeros((200, 200, 3), dtype=np.uint8)
        frame[30:90, 40:110] = [0, 255, 0]  # Green box
        bbox = (40, 30, 70, 60)
        embedding = np.array([0.1, 0.5, 0.9], dtype=np.float32)

        crops_dir = os.path.join(self.temp_dir, "crops")
        result = self.db.enroll_entity(
            name="Delivery Van #1",
            category="delivery",
            frame=frame,
            bbox=bbox,
            embedding=embedding,
            notes="Morning courier",
            save_crop_dir=crops_dir,
        )

        self.assertEqual(result["name"], "Delivery Van #1")
        self.assertEqual(result["category"], "delivery")
        self.assertIsNotNone(result["signature_id"])
        self.assertTrue(os.path.isfile(result["crop_path"]))

    def test_export_csv_and_json(self):
        """Test CSV and JSON sightings export."""
        eid = self.db.add_entity(name="Test Subject")
        self.db.add_sighting(entity_id=eid, track_id=1, source="cam0", timestamp="2026-10-24 12:00:00")

        csv_path = os.path.join(self.temp_dir, "export.csv")
        json_path = os.path.join(self.temp_dir, "export.json")

        self.db.export_sightings_csv(csv_path)
        self.db.export_sightings_json(json_path)

        self.assertTrue(os.path.isfile(csv_path))
        self.assertTrue(os.path.isfile(json_path))
        with open(csv_path, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("Test Subject", content)
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["entity_name"], "Test Subject")

    def test_thread_safety(self):
        """Test concurrent multi-threaded writes and reads."""
        def worker(idx):
            for i in range(10):
                eid = self.db.add_entity(name=f"Worker-{idx}-{i}")
                self.db.add_signature(eid, np.random.randn(8).astype(np.float32))
                self.db.add_sighting(eid, track_id=idx * 100 + i, source=f"cam_{idx}")

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        ents = self.db.list_entities()
        self.assertEqual(len(ents), 40)
        sightings = self.db.get_sightings(limit=0)
        self.assertEqual(len(sightings), 40)


if __name__ == "__main__":
    unittest.main()
