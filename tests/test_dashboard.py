#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for Milestone 6 Web Dashboard (FastAPI, WebSockets, MJPEG streaming, REST API).
"""

from __future__ import division, print_function, absolute_import

import os
import sys
import time
import shutil
import tempfile
import unittest

from fastapi.testclient import TestClient

from dashboard.app import app
import dashboard.app as dashboard_module
from dashboard.stream_manager import StreamManager
from intelligent_tracker.database import TrackerDB


class TestDashboardApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="tracker_dash_test_")
        cls.db_path = os.path.join(cls.test_dir, "test_tracker.db")

        # Initialize test StreamManager with mock components and synthetic video
        cls.manager = StreamManager(db_path=cls.db_path, camera_id="cam_01")
        dashboard_module.stream_manager = cls.manager
        cls.manager.start()

        # Let the worker run a couple frames
        time.sleep(0.3)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        if cls.manager:
            cls.manager.stop()
        if os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_01_serve_index(self):
        """Verify root GET / serves dashboard HTML."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers["content-type"])
        self.assertIn("INTELLIGENT TRACKER", resp.text)
        self.assertIn("interactive-canvas", resp.text)

    def test_02_get_cameras(self):
        """Verify GET /cameras returns camera list."""
        resp = self.client.get("/cameras")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 1)
        cam = data[0]
        self.assertEqual(cam["id"], "cam_01")
        self.assertIn("status", cam)
        self.assertIn("fps", cam)

    def test_03_get_zones(self):
        """Verify GET /zones returns active zones."""
        resp = self.client.get("/zones")
        self.assertEqual(resp.status_code, 200)
        zones = resp.json()
        self.assertIsInstance(zones, list)
        if zones:
            self.assertIn("name", zones[0])
            self.assertIn("occupancy", zones[0])

    def test_04_heatmap_endpoints(self):
        """Verify GET /analytics/heatmap returns image and JSON formats."""
        # 1. Image
        resp_img = self.client.get("/analytics/heatmap")
        self.assertEqual(resp_img.status_code, 200)
        self.assertEqual(resp_img.headers["content-type"], "image/jpeg")
        self.assertGreater(len(resp_img.content), 100)

        # 2. JSON
        resp_json = self.client.get("/analytics/heatmap?format=json")
        self.assertEqual(resp_json.status_code, 200)
        self.assertIn("resolution", resp_json.json())

        # 3. Toggle
        resp_toggle = self.client.post("/analytics/heatmap/toggle")
        self.assertEqual(resp_toggle.status_code, 200)
        self.assertIn("draw_heatmap", resp_toggle.json())

    def test_05_entity_crud_and_gallery(self):
        """Verify entity creation, listing, detail, and deletion."""
        # 1. Create Entity
        create_resp = self.client.post(
            "/entities",
            json={"name": "Alice Guard", "category": "staff", "notes": "Security clearance level 3"}
        )
        self.assertEqual(create_resp.status_code, 200)
        ent = create_resp.json()
        self.assertEqual(ent["name"], "Alice Guard")
        self.assertEqual(ent["category"], "staff")
        ent_id = ent["id"]

        # 2. List Entities
        list_resp = self.client.get("/entities")
        self.assertEqual(list_resp.status_code, 200)
        entities = list_resp.json()
        self.assertTrue(any(e["id"] == ent_id for e in entities))

        # Filter by category
        staff_resp = self.client.get("/entities?category=staff")
        self.assertEqual(staff_resp.status_code, 200)
        self.assertTrue(any(e["id"] == ent_id for e in staff_resp.json()))

        # 3. Get Entity Details
        detail_resp = self.client.get(f"/entities/{ent_id}")
        self.assertEqual(detail_resp.status_code, 200)
        detail = detail_resp.json()
        self.assertEqual(detail["name"], "Alice Guard")
        self.assertIn("signatures", detail)
        self.assertIn("recent_sightings", detail)

        # 4. Duplicate Check
        dup_resp = self.client.post(
            "/entities",
            json={"name": "Alice Guard", "category": "staff"}
        )
        self.assertEqual(dup_resp.status_code, 409)

        # 5. Delete Entity
        del_resp = self.client.delete(f"/entities/{ent_id}")
        self.assertEqual(del_resp.status_code, 200)
        self.assertTrue(del_resp.json()["deleted"])

    def test_06_click_to_tag(self):
        """Verify interactive click-to-tag bounding box endpoint."""
        resp = self.client.post(
            "/tag",
            json={
                "entity_name": "Bob VIP",
                "category": "vip",
                "bbox": [100, 100, 80, 120],
                "notes": "Board executive",
            }
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"]["name"], "Bob VIP")
        self.assertEqual(data["data"]["category"], "vip")
        self.assertIn("signature_id", data["data"])

        # Check that sightings were logged
        sightings_resp = self.client.get(f"/sightings?entity_name=Bob%20VIP")
        self.assertEqual(sightings_resp.status_code, 200)
        sightings = sightings_resp.json()
        self.assertGreaterEqual(len(sightings), 1)
        self.assertEqual(sightings[0]["entity_name"], "Bob VIP")

    def test_07_events_endpoint(self):
        """Verify GET /events returns recent EventBus events."""
        resp = self.client.get("/events?limit=10")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), list)

    def test_08_status_endpoint(self):
        """Verify GET /status telemetry reporting."""
        resp = self.client.get("/status")
        self.assertEqual(resp.status_code, 200)
        status_data = resp.json()
        self.assertEqual(status_data["status"], "online")
        self.assertIn("system", status_data)
        self.assertIn("pipeline", status_data)
        self.assertIn("cpu_percent", status_data["system"])
        self.assertIn("fps", status_data["pipeline"])

    def test_09_stream_endpoint(self):
        """Verify GET /stream/{camera_id} initiates MJPEG multipart stream."""
        with self.client.stream("GET", "/stream/cam_01") as response:
            self.assertEqual(response.status_code, 200)
            self.assertIn("multipart/x-mixed-replace", response.headers["content-type"])
            for chunk in response.iter_raw():
                self.assertGreater(len(chunk), 0)
                break

    def test_10_websocket_telemetry(self):
        """Verify WS /ws/{camera_id} connection and message delivery."""
        with self.client.websocket_connect("/ws/cam_01") as websocket:
            websocket.send_json({"action": "ping"})
            resp = websocket.receive_json()
            self.assertTrue(resp.get("type") == "pong" or "camera_id" in resp or "fps" in resp)


if __name__ == "__main__":
    unittest.main()
