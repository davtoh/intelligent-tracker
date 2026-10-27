#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for ScenarioManager & Spatial Orchestration (intelligent_tracker/scenarios.py).
"""

import os
import shutil
import tempfile
import unittest

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.scenarios import ScenarioManager
from intelligent_tracker.geometry import ZoneROI, Tripwire
from intelligent_tracker.homography import GroundPlaneHomography
from intelligent_tracker.topology import SpatialTransitionLink


class TestScenarioManager(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="scenario_test_")
        self.yaml_path = os.path.join(self.test_dir, "test_scenarios.yaml")
        self.db_path = os.path.join(self.test_dir, "test_tracker.db")
        self.db = TrackerDB(self.db_path)
        self.manager = ScenarioManager(
            config_path=self.yaml_path,
            db=self.db,
        )

    def tearDown(self):
        if self.db:
            self.db.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_save_and_get_zone(self):
        """Test creating, saving to SQLite & YAML, and retrieving a zone."""
        poly = [(50, 50), (200, 50), (200, 200), (50, 200)]
        z = self.manager.save_zone(
            camera_id="cam_01",
            name="Restricted Area",
            polygon=poly,
            category_filter="person",
            dwell_threshold=8.0,
            capacity_limit=2,
            color=(0, 255, 128),
        )
        self.assertEqual(z.name, "Restricted Area")
        self.assertEqual(z.dwell_threshold, 8.0)
        self.assertEqual(z.capacity_limit, 2)

        # Verify in memory
        c_entry = self.manager._ensure_camera_entry("cam_01")
        self.assertIn("Restricted Area", c_entry["zones"])

        # Verify in DB
        db_zones = self.db.get_zones("cam_01")
        self.assertEqual(len(db_zones), 1)
        self.assertEqual(db_zones[0]["name"], "Restricted Area")
        self.assertEqual(db_zones[0]["dwell_threshold"], 8.0)

        # Verify in YAML
        self.assertTrue(os.path.exists(self.yaml_path))

    def test_delete_zone(self):
        """Test deleting a zone updates memory, DB, and YAML."""
        self.manager.save_zone(
            camera_id="cam_01",
            name="Temporary Zone",
            polygon=[(0, 0), (10, 0), (10, 10), (0, 10)],
        )
        self.assertTrue(self.manager.delete_zone("cam_01", "Temporary Zone"))
        self.assertNotIn("Temporary Zone", self.manager.cameras["cam_01"]["zones"])
        self.assertEqual(len(self.db.get_zones("cam_01")), 0)

    def test_save_and_delete_tripwire(self):
        """Test tripwire creation, persistence, and deletion."""
        tw = self.manager.save_tripwire(
            camera_id="cam_01",
            name="Perimeter Fence",
            line_segment=[(100, 200), (300, 200)],
            bidirectional=False,
            color=(0, 255, 255),
        )
        self.assertEqual(tw.name, "Perimeter Fence")
        self.assertFalse(tw.bidirectional)

        db_tw = self.db.get_tripwires("cam_01")
        self.assertEqual(len(db_tw), 1)
        self.assertEqual(db_tw[0]["name"], "Perimeter Fence")

        deleted = self.manager.delete_tripwire("cam_01", "Perimeter Fence")
        self.assertTrue(deleted)
        self.assertEqual(len(self.db.get_tripwires("cam_01")), 0)

    def test_save_and_get_homography(self):
        """Test homography calibration saving and retrieving."""
        src = [(10, 10), (90, 10), (90, 90), (10, 90)]
        homo = self.manager.save_homography(
            camera_id="cam_01",
            src_points=src,
            metric_width=5.0,
            metric_height=5.0,
        )
        self.assertTrue(homo.is_calibrated)
        self.assertEqual(homo.metric_width, 5.0)

        db_homo = self.db.get_homography_calibration("cam_01")
        self.assertIsNotNone(db_homo)
        self.assertEqual(db_homo["metric_width"], 5.0)

    def test_reload_from_sqlite_and_yaml(self):
        """Test reloading scenarios cleanly on startup from storage."""
        # 1. Populate
        self.manager.save_zone(
            camera_id="cam_reload",
            name="Vault",
            polygon=[(0, 0), (50, 0), (50, 50), (0, 50)],
        )
        self.manager.save_tripwire(
            camera_id="cam_reload",
            name="Line 1",
            line_segment=[(10, 10), (20, 20)],
        )
        self.manager.topology.add_link(
            SpatialTransitionLink(
                link_id="reload_link",
                source_camera="cam_reload",
                source_zone="Vault",
                target_camera="cam_02",
                target_zone="Hallway",
            )
        )
        self.manager.save_to_yaml()

        # 2. Instantiate a fresh ScenarioManager pointing to same files
        fresh_mgr = ScenarioManager(
            config_path=self.yaml_path,
            db=self.db,
        )
        c_entry = fresh_mgr.cameras.get("cam_reload")
        self.assertIsNotNone(c_entry)
        self.assertIn("Vault", c_entry["zones"])
        self.assertIn("Line 1", c_entry["tripwires"])


if __name__ == "__main__":
    unittest.main()
