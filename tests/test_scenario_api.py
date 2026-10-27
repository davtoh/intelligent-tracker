#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for Scenario Studio, Space Awareness & Homography REST APIs (dashboard/app.py).
"""

import os
import shutil
import tempfile
import unittest
from datetime import datetime

from fastapi.testclient import TestClient

from dashboard.app import app
import dashboard.app as app_module
from dashboard.camera_pool import CameraPool
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.scenarios import ScenarioManager


class TestScenarioApi(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="tracker_scenario_api_test_")
        cls.config_file = os.path.join(cls.test_dir, "cameras.json")
        cls.db_path = os.path.join(cls.test_dir, "tracker.db")
        cls.scenarios_yaml = os.path.join(cls.test_dir, "scenarios.yaml")

        # Initialize test database
        cls.db = TrackerDB(cls.db_path)
        cls.eid = cls.db.add_entity("Test VIP", category="vip")

        # Set up CameraPool in app
        cls.pool = CameraPool(
            config_file=cls.config_file,
            db_path=cls.db_path,
            autostart=False,
        )
        app_module.camera_pool = cls.pool
        app_module.stream_manager = cls.pool.primary_stream

        # Set up ScenarioManager in app
        cls.scenario_mgr = ScenarioManager(
            config_path=cls.scenarios_yaml,
            db=cls.db,
        )
        app_module.scenario_manager = cls.scenario_mgr

        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        if cls.pool:
            cls.pool.stop_all()
        if hasattr(cls, "db") and cls.db:
            cls.db.close()
        if os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_01_get_scenarios(self):
        """Verify GET /api/scenarios returns top-level configuration."""
        resp = self.client.get("/api/scenarios")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("cameras", data)
        self.assertIn("spatial_transitions", data)

    def test_02_create_and_delete_zone(self):
        """Verify POST /api/scenarios/zones and DELETE /api/scenarios/zones/{cam}/{name}."""
        payload = {
            "camera_id": "cam_01",
            "name": "Secured Vault",
            "polygon": [[50, 50], [250, 50], [250, 250], [50, 250]],
            "dwell_threshold": 10.0,
            "capacity_limit": 3,
            "category_filter": "visitor",
            "color": [255, 0, 100],
        }
        resp = self.client.post("/api/scenarios/zones", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["zone"]["name"], "Secured Vault")

        # Query camera scenarios
        resp2 = self.client.get("/api/scenarios/cam_01")
        self.assertEqual(resp2.status_code, 200)
        c_data = resp2.json()
        zone_names = [z["name"] for z in c_data["zones"]]
        self.assertIn("Secured Vault", zone_names)

        # Delete zone
        del_resp = self.client.delete("/api/scenarios/zones/cam_01/Secured%20Vault")
        self.assertEqual(del_resp.status_code, 200)
        self.assertEqual(del_resp.json()["status"], "success")

    def test_03_create_and_delete_tripwire(self):
        """Verify POST and DELETE tripwires endpoints."""
        payload = {
            "camera_id": "cam_01",
            "name": "Entry Tripwire",
            "line_segment": [[100, 300], [400, 300]],
            "bidirectional": True,
            "color": [0, 255, 255],
        }
        resp = self.client.post("/api/scenarios/tripwires", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["tripwire"]["name"], "Entry Tripwire")

        # Delete tripwire
        del_resp = self.client.delete("/api/scenarios/tripwires/cam_01/Entry%20Tripwire")
        self.assertEqual(del_resp.status_code, 200)
        self.assertEqual(del_resp.json()["status"], "success")

    def test_04_homography_and_bev(self):
        """Verify POST /api/scenarios/homography, GET calibration, and GET BEV image."""
        payload = {
            "camera_id": "cam_01",
            "src_points": [[100, 100], [500, 100], [600, 400], [0, 400]],
            "dst_points": [[0, 0], [10, 0], [10, 20], [0, 20]],
            "metric_width": 10.0,
            "metric_height": 20.0,
        }
        resp = self.client.post("/api/scenarios/homography", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertTrue(data["homography"]["is_calibrated"])

        # GET calibration profile
        resp_get = self.client.get("/api/scenarios/homography/cam_01")
        self.assertEqual(resp_get.status_code, 200)
        self.assertTrue(resp_get.json()["is_calibrated"])

        # GET BEV minimap JPEG image
        resp_bev = self.client.get("/api/scenarios/bev/cam_01")
        self.assertEqual(resp_bev.status_code, 200)
        self.assertEqual(resp_bev.headers["content-type"], "image/jpeg")
        self.assertGreater(len(resp_bev.content), 100)

    def test_05_cross_camera_topology_transitions(self):
        """Verify POST, GET, and DELETE /api/topology/transitions."""
        payload = {
            "link_id": "link_test_gate_lobby",
            "source_camera": "cam_01",
            "source_zone": "Gate",
            "target_camera": "cam_02",
            "target_zone": "Lobby",
            "t_min": 3.0,
            "t_max": 20.0,
            "prior_boost": 0.40,
            "bidirectional": False,
            "active": True,
        }
        resp = self.client.post("/api/topology/transitions", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["link"]["link_id"], "link_test_gate_lobby")

        # GET transitions
        resp_list = self.client.get("/api/topology/transitions")
        self.assertEqual(resp_list.status_code, 200)
        link_ids = [l["link_id"] for l in resp_list.json()]
        self.assertIn("link_test_gate_lobby", link_ids)

        # GET active priors
        resp_priors = self.client.get("/api/topology/priors")
        self.assertEqual(resp_priors.status_code, 200)
        self.assertIsInstance(resp_priors.json(), list)

        # DELETE transition
        del_resp = self.client.delete("/api/topology/transitions/link_test_gate_lobby")
        self.assertEqual(del_resp.status_code, 200)
        self.assertEqual(del_resp.json()["status"], "success")

    def test_06_trajectory_journey_endpoints(self):
        """Verify GET /api/journey/search and POST /api/journey/export."""
        # Add test sightings
        t0 = datetime.fromtimestamp(1700001000.0).isoformat()
        t1 = datetime.fromtimestamp(1700001010.0).isoformat()
        self.db.add_sighting(entity_id=self.eid, track_id=5, source="cam_01", timestamp=t0, zone_id="Gate", bbox=[10, 10, 30, 30])
        self.db.add_sighting(entity_id=self.eid, track_id=5, source="cam_01", timestamp=t1, zone_id="Gate", bbox=[15, 15, 30, 30])

        # Search journey
        resp = self.client.get(f"/api/journey/search?entity_id={self.eid}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["entity_name"], "Test VIP")
        self.assertGreaterEqual(data["total_hops"], 1)

        # Export journey video
        export_payload = {
            "entity_id": self.eid,
            "entity_name": "Test VIP",
        }
        resp_export = self.client.post("/api/journey/export", json=export_payload)
        self.assertEqual(resp_export.status_code, 200)
        exp_data = resp_export.json()
        self.assertEqual(exp_data["status"], "success")
        self.assertIn("video_file", exp_data)
        self.assertTrue(exp_data["video_file"].endswith(".mp4"))

    def test_07_camera_overlays_endpoints(self):
        """Verify GET and POST /api/cameras/{id}/overlays."""
        resp = self.client.get("/api/cameras/cam_01/overlays")
        self.assertEqual(resp.status_code, 200)
        overlays = resp.json()
        self.assertIn("bboxes", overlays)
        self.assertIn("bev_minimap", overlays)

        # Update overlay flags
        update_payload = {
            "bev_minimap": True,
            "heatmap": True,
            "velocity": False,
        }
        post_resp = self.client.post("/api/cameras/cam_01/overlays", json=update_payload)
        self.assertEqual(post_resp.status_code, 200)
        up_data = post_resp.json()
        self.assertEqual(up_data["status"], "success")
        self.assertTrue(up_data["overlays"]["bev_minimap"])
        self.assertTrue(up_data["overlays"]["heatmap"])
        self.assertFalse(up_data["overlays"]["velocity"])


if __name__ == "__main__":
    unittest.main()
