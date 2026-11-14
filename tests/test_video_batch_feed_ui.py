#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Unit Tests for Video Batch Analytics & Feed Promotion API (Milestone 3).

Verifies:
1. POST /api/videos/{filename}/analyze with JSON body payload containing custom detector,
   confidence threshold, sample_rate, and target class filters.
2. POST /api/videos/{filename}/add_as_camera with JSON body payload registering active stream
   with custom detector, tracker, confidence, and target classes.
3. Verification that camera pool preserves the AI detector and tracker configuration.
4. Validation error handling for out-of-bounds confidence thresholds or invalid sample rates.
5. 404 Not Found handling on missing video files.
"""

import os
import shutil
import tempfile
import unittest
import cv2
import numpy as np
from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.camera_pool import CameraPool
from dashboard.dependencies import VIDEOS_DIR, bind_app_state, clear_app_state
from intelligent_tracker.database import TrackerDB


class TestVideoBatchFeedUI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="tracker_video_batch_test_")
        cls.config_file = os.path.join(cls.test_dir, "cameras.json")
        cls.db_path = os.path.join(cls.test_dir, "tracker.db")
        cls.db = TrackerDB(cls.db_path)

        cls.pool = CameraPool(
            config_file=cls.config_file,
            db_path=cls.db_path,
            autostart=False,
        )
        bind_app_state(
            app,
            camera_pool=cls.pool,
            stream_manager=cls.pool.primary_stream,
            db=cls.db,
        )

        cls.client = TestClient(app)

        # Generate a small valid synthetic test video in VIDEOS_DIR for batch testing
        os.makedirs(VIDEOS_DIR, exist_ok=True)
        cls.test_video_filename = "batch_ui_test_clip.mp4"
        cls.test_video_path = os.path.join(VIDEOS_DIR, cls.test_video_filename)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(cls.test_video_path, fourcc, 10.0, (320, 240))
        for f in range(20):
            frame = np.full((240, 320, 3), 40, dtype=np.uint8)
            x = 30 + f * 4
            cv2.rectangle(frame, (x, 50), (x + 35, 110), (0, 255, 0), -1)
            writer.write(frame)
        writer.release()

    @classmethod
    def tearDownClass(cls):
        clear_app_state(app)
        if cls.pool:
            cls.pool.stop_all()
        if cls.db:
            cls.db.close()
        if os.path.exists(cls.test_video_path):
            try:
                os.remove(cls.test_video_path)
            except OSError:
                pass
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_01_add_video_as_camera_json_payload(self):
        """Verify POST /api/videos/{filename}/add_as_camera parses JSON body options."""
        cam_id = "vid_feed_promotion_01"
        payload = {
            "camera_id": cam_id,
            "name": "Promoted Office Video",
            "detector": "mock",
            "tracker": "sort",
            "confidence": 0.42,
            "classes": ["person", "vehicle"],
        }
        resp = self.client.post(
            f"/api/videos/{self.test_video_filename}/add_as_camera",
            json=payload,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["camera_id"], cam_id)
        self.assertEqual(data["detector"], "mock")
        self.assertEqual(data["confidence"], 0.42)
        self.assertEqual(data["classes"], ["person", "vehicle"])

        # Verify stream is registered in CameraPool with exact AI configuration
        cameras = self.pool.list_cameras()
        cam_info = next((c for c in cameras if c["id"] == cam_id), None)
        self.assertIsNotNone(cam_info)
        self.assertEqual(cam_info["detector"], "mock")
        self.assertEqual(cam_info["tracker"], "sort")
        self.assertEqual(cam_info["confidence"], 0.42)
        self.assertEqual(cam_info["classes"], ["person", "vehicle"])

        # Clean up
        self.pool.remove_camera(cam_id)

    def test_02_analyze_video_json_payload(self):
        """Verify POST /api/videos/{filename}/analyze parses JSON body options."""
        payload = {
            "sample_rate": 2,
            "detector": "mock",
            "confidence": 0.35,
            "classes": ["person", "car"],
        }
        resp = self.client.post(
            f"/api/videos/{self.test_video_filename}/analyze",
            json=payload,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        report = data["report"]
        self.assertIn("frames_processed", report)
        self.assertIn("total_detections", report)
        self.assertIn("unique_entities_identified", report)
        self.assertEqual(report["frames_processed"], 10)  # 20 frames / stride 2 = 10

    def test_03_analyze_video_query_fallback(self):
        """Verify POST /api/videos/{filename}/analyze supports query parameters."""
        resp = self.client.post(
            f"/api/videos/{self.test_video_filename}/analyze"
            "?sample_rate=4&detector=mock&confidence=0.50&classes=person"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["report"]["frames_processed"], 5)  # 20 frames / stride 4 = 5

    def test_04_validation_bounds(self):
        """Verify HTTP 422 Unprocessable Entity when parameters exceed validation limits."""
        # Confidence > 1.0
        resp1 = self.client.post(
            f"/api/videos/{self.test_video_filename}/analyze",
            json={"confidence": 1.50},
        )
        self.assertEqual(resp1.status_code, 422)

        # Confidence < 0.01
        resp2 = self.client.post(
            f"/api/videos/{self.test_video_filename}/add_as_camera",
            json={"confidence": 0.00},
        )
        self.assertEqual(resp2.status_code, 422)

        # Sample rate < 1
        resp3 = self.client.post(
            f"/api/videos/{self.test_video_filename}/analyze",
            json={"sample_rate": 0},
        )
        self.assertEqual(resp3.status_code, 422)

    def test_05_nonexistent_video_file(self):
        """Verify HTTP 404 for missing video targets."""
        resp1 = self.client.post(
            "/api/videos/missing_nonexistent_clip.mp4/analyze",
            json={"detector": "mock"},
        )
        self.assertEqual(resp1.status_code, 404)

        resp2 = self.client.post(
            "/api/videos/missing_nonexistent_clip.mp4/add_as_camera",
            json={"camera_id": "vid_missing_01"},
        )
        self.assertEqual(resp2.status_code, 404)


if __name__ == "__main__":
    unittest.main()
