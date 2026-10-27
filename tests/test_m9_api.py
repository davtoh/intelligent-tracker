#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Unit Tests for Milestone 9 REST API Endpoints.
"""

import os
import base64
import tempfile
import unittest
import cv2
import numpy as np
from fastapi.testclient import TestClient

from dashboard.app import app
import dashboard.app as app_module
from intelligent_tracker.database import TrackerDB
from dashboard.camera_pool import CameraPool


class TestMilestone9API(unittest.TestCase):
    """Test suite for Milestone 9 FastAPI REST API endpoints."""

    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.mkdtemp()
        cls.db_path = os.path.join(cls.tmp_dir, "test_api_m9.db")
        cls.cam_cfg = os.path.join(cls.tmp_dir, "cameras.json")
        cls.db = TrackerDB(cls.db_path)

        # Initialize CameraPool with test DB
        cls.pool = CameraPool(
            config_file=cls.cam_cfg,
            db_path=cls.db_path,
            autostart=False,
        )
        app_module.camera_pool = cls.pool
        app_module.stream_manager = cls.pool.primary_stream
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.pool.stop_all()
        cls.db.close()
        import shutil
        shutil.rmtree(cls.tmp_dir, ignore_errors=True)

    def test_freeze_frame_and_universal_enroll(self):
        """Test GET freeze_frame and POST universal enrollment."""
        # Setup mock raw frame on primary stream
        sm = self.pool.primary_stream
        if sm:
            with sm._lock:
                sm._latest_raw_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                sm._latest_raw_frame[50:150, 100:200] = (0, 200, 255)

        # 1. Freeze frame endpoint
        res = self.client.get("/api/cameras/cam_01/freeze_frame")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("image_base64", data)
        self.assertEqual(data["width"], 640)
        self.assertEqual(data["height"], 480)

        # 2. Universal enroll with bbox
        enroll_res = self.client.post("/api/enroll", json={
            "name": "Dr. Smith (VIP)",
            "category": "vip",
            "security_role": "resident",
            "notes": "Medical resident",
            "is_anchor": True,
            "camera_id": "cam_01",
            "bbox": [100, 50, 100, 100],
        })
        self.assertEqual(enroll_res.status_code, 200)
        enroll_data = enroll_res.json()
        self.assertEqual(enroll_data["status"], "success")
        self.assertIn("entity_id", enroll_data)
        entity_id = enroll_data["entity_id"]

        # 3. Verify descriptor versions
        v_res = self.client.get(f"/api/entities/{entity_id}/versions")
        self.assertEqual(v_res.status_code, 200)
        v_data = v_res.json()
        self.assertEqual(len(v_data["versions"]), 1)
        self.assertEqual(v_data["versions"][0]["version"], 1)

    def test_active_learning_queue_and_actions(self):
        """Test Active Learning queue retrieval and operator triage actions."""
        # Seed an item into review queue
        item_id = self.db.add_review_item(
            camera_id="cam_01",
            track_id=88,
            crop_path="data/crops/candidate_88.jpg",
            similarity_score=0.58,
            matched_entity_id=1,
            matched_entity_name="Alice",
            bbox=(20, 20, 80, 80),
        )

        # 1. List queue
        q_res = self.client.get("/api/active-learning/queue?status=pending")
        self.assertEqual(q_res.status_code, 200)
        q_data = q_res.json()
        self.assertGreaterEqual(q_data["count"], 1)

        # 2. Get single item
        single_res = self.client.get(f"/api/active-learning/{item_id}")
        self.assertEqual(single_res.status_code, 200)
        self.assertEqual(single_res.json()["track_id"], 88)

        # 3. Dismiss item
        dismiss_res = self.client.post(f"/api/active-learning/{item_id}/dismiss", json={"notes": "Dismissed by test"})
        self.assertEqual(dismiss_res.status_code, 200)
        self.assertEqual(dismiss_res.json()["status"], "dismissed")

    def test_rsac_categories_and_rules_crud(self):
        """Test RSAC custom category and zone rule CRUD endpoints."""
        # 1. Categories
        cat_res = self.client.get("/api/rsac/categories")
        self.assertEqual(cat_res.status_code, 200)
        cats = cat_res.json()
        self.assertGreaterEqual(len(cats), 8)

        # Add custom category
        create_cat = self.client.post("/api/rsac/categories", json={
            "id": "maintenance_bot",
            "name": "Cleaning Drone",
            "color": "#14B8A6",
            "badge_icon": "bot",
            "description": "Floor cleaning drone",
        })
        self.assertEqual(create_cat.status_code, 200)

        # Delete custom category
        del_cat = self.client.delete("/api/rsac/categories/maintenance_bot")
        self.assertEqual(del_cat.status_code, 200)

        # 2. RSAC Rules
        rule_res = self.client.post("/api/rsac/rules", json={
            "camera_id": "cam_01",
            "zone_id": "lab_entrance",
            "allowed_categories": ["staff", "vip"],
            "denied_categories": ["restricted"],
            "schedules": [{"days": ["*"], "start_time": "08:00", "end_time": "20:00"}],
            "entity_overrides": {"101": "allow"},
            "alarm_on_breach": True,
        })
        self.assertEqual(rule_res.status_code, 200)

        # List rules
        list_rules = self.client.get("/api/rsac/rules?camera_id=cam_01")
        self.assertEqual(list_rules.status_code, 200)
        self.assertGreaterEqual(len(list_rules.json()), 1)

        # Delete rule
        del_rule = self.client.delete("/api/rsac/rules?camera_id=cam_01&zone_id=lab_entrance")
        self.assertEqual(del_rule.status_code, 200)

    def test_pet_whitelist_endpoints(self):
        """Test pet whitelist add, list, delete endpoints."""
        # Add pet label
        add_res = self.client.post("/api/pets/whitelist", json={"label": "golden_retriever", "notes": "Resident pet"})
        self.assertEqual(add_res.status_code, 200)
        self.assertIn("golden_retriever", add_res.json()["whitelist"])

        # List whitelist
        list_res = self.client.get("/api/pets/whitelist")
        self.assertEqual(list_res.status_code, 200)
        self.assertIn("golden_retriever", list_res.json()["whitelist"])

        # Delete pet label
        del_res = self.client.delete("/api/pets/whitelist/golden_retriever")
        self.assertEqual(del_res.status_code, 200)
        self.assertNotIn("golden_retriever", del_res.json()["whitelist"])


if __name__ == "__main__":
    unittest.main()
