#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for Dynamic Multi-Stream Orchestrator (CameraPool) (Milestone 7).
"""

import os
import sys
import time
import shutil
import tempfile
import unittest

from dashboard.camera_pool import CameraPool
from dashboard.stream_manager import StreamManager


class TestCameraPool(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="tracker_pool_test_")
        self.config_file = os.path.join(self.test_dir, "test_cameras.json")
        self.db_path = os.path.join(self.test_dir, "test_tracker.db")
        self.pool = CameraPool(
            config_file=self.config_file,
            db_path=self.db_path,
            autostart=False,
        )

    def tearDown(self):
        if self.pool:
            self.pool.stop_all()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_pool_initialization_seeds_default_camera(self):
        """Verify CameraPool auto-seeds default primary camera on fresh start."""
        self.assertIn("cam_01", self.pool.camera_configs)
        self.assertEqual(self.pool.camera_configs["cam_01"]["source"], "synthetic")
        self.assertTrue(os.path.exists(self.config_file))

    def test_02_hot_add_camera_dynamically(self):
        """Verify dynamic hot-add of a new camera stream without restart."""
        mgr = self.pool.add_camera(
            camera_id="cam_02",
            name="Loading Dock 02",
            source="synthetic",
            cam_type="synthetic",
            detector="mock",
            tracker="centroid",
            enabled=True,
            autostart=True,
        )
        self.assertIsInstance(mgr, StreamManager)
        self.assertIn("cam_02", self.pool.streams)
        self.assertIn("cam_02", self.pool.camera_configs)
        self.assertEqual(self.pool.camera_configs["cam_02"]["name"], "Loading Dock 02")
        self.assertTrue(mgr.is_running)

        # Let the background pipeline process a couple frames
        time.sleep(0.3)
        self.assertIsNotNone(mgr.get_latest_frame_jpeg())

    def test_03_update_camera_metadata(self):
        """Verify editing display name and stream properties dynamically."""
        self.pool.add_camera(
            camera_id="cam_03",
            name="Old Name",
            source="synthetic",
            autostart=False,
        )
        updated = self.pool.update_camera(
            camera_id="cam_03",
            name="New Perimeter Gate",
            detector="mock",
        )
        self.assertTrue(updated)
        self.assertEqual(self.pool.camera_configs["cam_03"]["name"], "New Perimeter Gate")

    def test_04_toggle_camera_stream(self):
        """Verify pausing and resuming stream processing."""
        mgr = self.pool.add_camera(
            camera_id="cam_04",
            name="Driveway",
            source="synthetic",
            autostart=True,
        )
        self.assertTrue(mgr.is_running)

        # Toggle to disabled
        new_state = self.pool.toggle_camera("cam_04", enabled=False)
        self.assertFalse(new_state)
        self.assertFalse(self.pool.camera_configs["cam_04"]["enabled"])

        # Toggle back to enabled
        new_state = self.pool.toggle_camera("cam_04", enabled=True)
        self.assertTrue(new_state)
        self.assertTrue(self.pool.camera_configs["cam_04"]["enabled"])

    def test_05_remove_camera_dynamically(self):
        """Verify removing a camera stream cleans up background threads and config."""
        self.pool.add_camera(
            camera_id="cam_05",
            name="Temporary Feed",
            source="synthetic",
            autostart=True,
        )
        self.assertIn("cam_05", self.pool.streams)
        removed = self.pool.remove_camera("cam_05")
        self.assertTrue(removed)
        self.assertNotIn("cam_05", self.pool.streams)
        self.assertNotIn("cam_05", self.pool.camera_configs)

    def test_06_primary_stream_fallback(self):
        """Verify primary_stream property returns a valid StreamManager."""
        primary = self.pool.primary_stream
        self.assertIsNotNone(primary)
        self.assertEqual(primary.camera_id, "cam_01")

        # Test get_stream with default
        stream = self.pool.get_stream("default")
        self.assertEqual(stream, primary)

    def test_07_list_cameras_telemetry(self):
        """Verify list_cameras aggregates live metrics across streams."""
        self.pool.add_camera(
            camera_id="cam_06",
            name="East Corridor",
            source="synthetic",
            autostart=True,
        )
        cams = self.pool.list_cameras()
        self.assertIsInstance(cams, list)
        self.assertGreaterEqual(len(cams), 2)

        cam_ids = [c["id"] for c in cams]
        self.assertIn("cam_01", cam_ids)
        self.assertIn("cam_06", cam_ids)

        c6 = next(c for c in cams if c["id"] == "cam_06")
        self.assertEqual(c6["name"], "East Corridor")
        self.assertIn("fps", c6)
        self.assertIn("status", c6)
        self.assertIn("resolution", c6)

    def test_08_persistence_and_auto_boot_restoration(self):
        """Verify that a new CameraPool instance restores all saved cameras from JSON."""
        self.pool.add_camera(
            camera_id="cam_persisted",
            name="Main Lobby",
            source="synthetic",
            autostart=False,
        )

        # Create separate pool pointing to same config
        restored_pool = CameraPool(
            config_file=self.config_file,
            db_path=self.db_path,
            autostart=False,
        )
        try:
            self.assertIn("cam_persisted", restored_pool.camera_configs)
            self.assertEqual(restored_pool.camera_configs["cam_persisted"]["name"], "Main Lobby")
        finally:
            restored_pool.stop_all()


if __name__ == "__main__":
    unittest.main()
