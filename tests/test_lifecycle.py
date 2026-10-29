#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for StreamLifecycleManager, SQLite Telemetry Persistence & Admin REST APIs.
"""

import os
import shutil
import tempfile
import unittest

from fastapi.testclient import TestClient

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.lifecycle import StreamLifecycleManager
from dashboard.stream_manager import StreamManager
from dashboard.camera_pool import CameraPool
from dashboard.app import app
import dashboard.app as dashboard_module


class TestLifecycleManager(unittest.TestCase):
    """Verifies StreamLifecycleManager and SQLite database persistence."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="tracker_lifecycle_test_")
        self.db_path = os.path.join(self.test_dir, "test_tracker.db")
        self.db = TrackerDB(self.db_path)
        self.config_file = os.path.join(self.test_dir, "test_cameras.json")
        self.pool = CameraPool(
            config_file=self.config_file,
            db_path=self.db_path,
            autostart=False,
        )
        self.lm = StreamLifecycleManager(
            db=self.db,
            camera_pool=self.pool,
            autostart_sampler=False,
        )

    def tearDown(self):
        self.lm.stop_sampler()
        self.pool.stop_all()
        self.db.close()
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_database_resource_metrics(self):
        """Verify recording and querying system resource samples."""
        self.db.record_resource_metric(
            cpu_percent=12.5,
            memory_mb=256.0,
            active_streams=2,
            hibernating_streams=3,
            total_subscribers=4,
        )
        metrics = self.db.get_resource_metrics(limit=10)
        self.assertEqual(len(metrics), 1)
        self.assertAlmostEqual(metrics[0]["cpu_percent"], 12.5, places=1)
        self.assertAlmostEqual(metrics[0]["memory_mb"], 256.0, places=1)
        self.assertEqual(metrics[0]["active_streams"], 2)
        self.assertEqual(metrics[0]["total_subscribers"], 4)

    def test_database_lifecycle_events(self):
        """Verify recording and querying lifecycle transition logs."""
        self.db.record_lifecycle_event(
            camera_id="cam_01",
            event_type="HIBERNATE",
            old_state="ONLINE",
            new_state="HIBERNATING",
            subscriber_count=0,
            details="Zero viewers auto-hibernate",
        )
        events = self.db.get_lifecycle_events(camera_id="cam_01", limit=10)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["camera_id"], "cam_01")
        self.assertEqual(events[0]["event_type"], "HIBERNATE")
        self.assertEqual(events[0]["new_state"], "HIBERNATING")

    def test_manager_diagnostics_and_eviction(self):
        """Verify StreamLifecycleManager diagnostics and forced eviction."""
        # Add a running camera stream
        mgr = self.pool.add_camera(
            camera_id="cam_audit",
            name="Audit Channel",
            source="synthetic",
            autostart=True,
        )
        mgr.add_subscriber("test_lease_token")
        self.assertEqual(mgr.subscriber_count, 1)

        diag = self.lm.get_diagnostics()
        self.assertGreater(diag["thread_count"], 0)
        self.assertGreaterEqual(diag["total_streams"], 1)

        # Force eviction
        res = self.lm.evict_subscribers("cam_audit", reason="Test eviction")
        self.assertTrue(res["success"])
        self.assertEqual(res["evicted_subscribers"], 1)
        self.assertEqual(res["new_state"], "HIBERNATING")
        self.assertEqual(mgr.subscriber_count, 0)

        # Verify eviction event was logged
        events = self.lm.get_lifecycle_history(camera_id="cam_audit")
        self.assertGreaterEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "EVICT")

    def test_hibernate_all_idle(self):
        """Verify sweeping idle channels."""
        self.pool.add_camera(
            camera_id="cam_idle",
            name="Idle Channel",
            source="synthetic",
            autostart=True,
        )
        res = self.lm.hibernate_all_idle()
        self.assertTrue(res["success"])
        self.assertIn("cam_idle", res["channels"])


class TestLifecycleAPI(unittest.TestCase):
    """Verifies FastAPI REST endpoints for lifecycle management."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="tracker_lifecycle_api_")
        cls.db_path = os.path.join(cls.test_dir, "test_tracker.db")
        cls.db = TrackerDB(cls.db_path)
        cls.config_file = os.path.join(cls.test_dir, "test_cameras.json")
        cls.pool = CameraPool(
            config_file=cls.config_file,
            db_path=cls.db_path,
            autostart=False,
        )
        cls.lm = StreamLifecycleManager(
            db=cls.db,
            camera_pool=cls.pool,
            autostart_sampler=False,
        )
        dashboard_module.camera_pool = cls.pool
        dashboard_module.lifecycle_manager = cls.lm
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.lm.stop_sampler()
        cls.pool.stop_all()
        cls.db.close()
        if os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_api_system_processes(self):
        resp = self.client.get("/api/system/processes")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("pid", data)
        self.assertIn("thread_count", data)
        self.assertIn("streams", data)

    def test_api_evict_and_metrics(self):
        # Sample one metric
        self.lm.record_sample()

        resp = self.client.get("/api/system/metrics?limit=10")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 1)

        # Hibernate all idle endpoint
        resp_hib = self.client.post("/api/system/hibernate_all")
        self.assertEqual(resp_hib.status_code, 200)
        self.assertTrue(resp_hib.json()["success"])

        # Events endpoint
        resp_ev = self.client.get("/api/system/events")
        self.assertEqual(resp_ev.status_code, 200)
        self.assertIsInstance(resp_ev.json(), list)


if __name__ == "__main__":
    unittest.main()

