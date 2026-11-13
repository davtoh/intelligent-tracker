#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for Dynamic Camera Detector & Pipeline Configuration (Milestone 1).

Verifies:
1. Pydantic request schema validation for confidence thresholds and class filters.
2. CameraPool persistence and StreamManager pipeline configuration propagation.
3. StreamPipelineFactory detector instantiation with custom confidence and class filters.
4. Video file dynamic promotion with detector selection (/api/videos/{name}/add_as_camera).
5. Offline batch occurrence indexing endpoint (/api/videos/{name}/analyze) using VideoIndexer.
"""

import os
import shutil
import tempfile
import unittest
import cv2
import numpy as np
from fastapi.testclient import TestClient
from pydantic import ValidationError

from dashboard.app import app
from dashboard.camera_pool import CameraPool
from dashboard.dependencies import VIDEOS_DIR, bind_app_state, clear_app_state
from dashboard.schemas import (
    CameraAddRequest,
    CameraUpdateRequest,
    VideoAddAsCameraRequest,
    VideoAnalyzeRequest,
)
from dashboard.services.pipeline_factory import StreamPipelineFactory
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.detectors import BaseDetector, MockDetector, OnnxDetector


class TestCameraDetectorConfig(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="tracker_detector_cfg_test_")
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

        # Generate a small valid synthetic test video in VIDEOS_DIR for indexer testing
        os.makedirs(VIDEOS_DIR, exist_ok=True)
        cls.test_video_filename = "detector_test_clip.mp4"
        cls.test_video_path = os.path.join(VIDEOS_DIR, cls.test_video_filename)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(cls.test_video_path, fourcc, 10.0, (320, 240))
        for f in range(15):
            frame = np.full((240, 320, 3), 50, dtype=np.uint8)
            x = 20 + f * 5
            cv2.rectangle(frame, (x, 40), (x + 30, 90), (0, 255, 0), -1)
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

    def test_01_schema_validation(self):
        """Verify CameraAddRequest and CameraUpdateRequest validate detector fields."""
        # 1. Valid default values
        req = CameraAddRequest(
            id="cam_test_01",
            name="Test Camera 1",
            source="synthetic",
        )
        self.assertEqual(req.detector, "yolov8")
        self.assertEqual(req.tracker, "centroid")
        self.assertEqual(req.confidence, 0.40)
        self.assertIsNone(req.classes)

        # 2. String classes comma-separated parsed to list
        req2 = CameraAddRequest(
            id="cam_test_02",
            name="Test Camera 2",
            source="rtsp://fake/stream",
            confidence=0.55,
            classes="person, car , truck",
        )
        self.assertEqual(req2.classes, ["person", "car", "truck"])
        self.assertEqual(req2.confidence, 0.55)

        # 3. Invalid confidence thresholds raise ValidationError
        with self.assertRaises(ValidationError):
            CameraAddRequest(
                id="cam_bad",
                name="Bad",
                source="0",
                confidence=0.00,
            )
        with self.assertRaises(ValidationError):
            CameraAddRequest(
                id="cam_bad",
                name="Bad",
                source="0",
                confidence=1.50,
            )

        # 4. CameraUpdateRequest with partial updates
        up_req = CameraUpdateRequest(
            confidence=0.65,
            classes="person",
        )
        self.assertEqual(up_req.confidence, 0.65)
        self.assertEqual(up_req.classes, ["person"])

    def test_02_camera_pool_persistence_and_propagation(self):
        """Verify CameraPool persists confidence and classes and propagates to custom_cfg."""
        mgr = self.pool.add_camera(
            camera_id="cam_ai_01",
            name="AI Perimeter",
            source="synthetic",
            cam_type="synthetic",
            detector="mock",
            tracker="centroid",
            confidence=0.45,
            classes=["person"],
            enabled=True,
            autostart=False,
        )
        self.assertIn("cam_ai_01", self.pool.camera_configs)
        saved_cfg = self.pool.camera_configs["cam_ai_01"]
        self.assertEqual(saved_cfg["detector"], "mock")
        self.assertEqual(saved_cfg["confidence"], 0.45)
        self.assertEqual(saved_cfg["classes"], ["person"])

        # Check StreamManager configuration
        det_cfg = mgr.cfg.get("detector", {})
        self.assertEqual(det_cfg.get("model"), "mock")
        self.assertEqual(det_cfg.get("confidence"), 0.45)
        self.assertEqual(det_cfg.get("classes"), ["person"])

        # Update camera settings dynamically
        updated = self.pool.update_camera(
            camera_id="cam_ai_01",
            detector="mock",
            confidence=0.75,
            classes=["person", "vehicle"],
        )
        self.assertTrue(updated)
        updated_cfg = self.pool.camera_configs["cam_ai_01"]
        self.assertEqual(updated_cfg["confidence"], 0.75)
        self.assertEqual(updated_cfg["classes"], ["person", "vehicle"])

        # Clean up
        self.pool.remove_camera("cam_ai_01")

    def test_03_pipeline_factory_init_detector(self):
        """Verify StreamPipelineFactory._init_detector configures thresholds and class filters."""
        # 1. Mock detector with custom confidence
        mock_det = StreamPipelineFactory._init_detector({
            "model": "mock",
            "confidence": 0.85,
        })
        self.assertIsInstance(mock_det, MockDetector)
        self.assertEqual(mock_det.confidence, 0.85)

        # 2. YOLOv8 detector with confidence and comma-separated classes
        yolo_det = StreamPipelineFactory._init_detector({
            "model": "yolov8",
            "confidence": 0.50,
            "classes": "person, car",
        })
        self.assertIsInstance(yolo_det, BaseDetector)
        if isinstance(yolo_det, OnnxDetector):
            self.assertEqual(yolo_det.conf_threshold, 0.50)
            self.assertIn(0, yolo_det.classes)  # person is class 0 in COCO

        # 3. Graceful fallback on unknown detector
        fallback_det = StreamPipelineFactory._init_detector({
            "model": "non_existent_detector_999",
            "confidence": 0.30,
        })
        self.assertIsInstance(fallback_det, MockDetector)

    def test_04_api_add_video_as_camera_with_detector(self):
        """Verify POST /api/videos/{name}/add_as_camera accepts detector config."""
        resp = self.client.post(
            f"/api/videos/{self.test_video_filename}/add_as_camera?detector=mock&confidence=0.60&classes=person"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        cam_id = data["camera_id"]
        self.assertIn(cam_id, self.pool.camera_configs)

        saved = self.pool.camera_configs[cam_id]
        self.assertEqual(saved["detector"], "mock")
        self.assertEqual(saved["confidence"], 0.60)
        self.assertEqual(saved["classes"], ["person"])

        # Clean up
        self.pool.remove_camera(cam_id)

    def test_05_api_analyze_video_endpoint(self):
        """Verify POST /api/videos/{name}/analyze runs offline VideoIndexer and returns report."""
        resp = self.client.post(
            f"/api/videos/{self.test_video_filename}/analyze?sample_rate=2&detector=mock&confidence=0.50"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("report", data)

        report = data["report"]
        self.assertIn("frames_processed", report)
        self.assertIn("total_detections", report)
        self.assertIn("total_sightings", report)
        self.assertIn("unique_entities_identified", report)
        self.assertIn("execution_summary", report)
        self.assertEqual(report["frames_processed"], 8)  # 15 frames at sample_rate=2 -> 8 frames

    def test_06_api_missing_video_errors(self):
        """Verify 404 responses when targeting nonexistent video files."""
        res1 = self.client.post("/api/videos/ghost_clip_404.mp4/add_as_camera")
        self.assertEqual(res1.status_code, 404)

        res2 = self.client.post("/api/videos/ghost_clip_404.mp4/analyze")
        self.assertEqual(res2.status_code, 404)

    def test_07_api_system_capabilities(self):
        """Verify GET /api/system/capabilities returns detectors, trackers, Re-ID and COCO classes."""
        resp = self.client.get("/api/system/capabilities")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        # 1. Detectors
        self.assertIn("detectors", data)
        self.assertIn("yolov8", data["detectors"])
        self.assertIn("mock", data["detectors"])
        self.assertIn("primary_detectors", data)
        self.assertTrue(len(data["primary_detectors"]) > 0)

        # 2. Trackers
        self.assertIn("trackers", data)
        self.assertIn("centroid", data["trackers"])
        self.assertIn("sort", data["trackers"])

        # 3. Re-ID Extractors
        self.assertIn("reid_extractors", data)
        self.assertIn("mock", data["reid_extractors"])

        # 4. COCO Classes & Presets
        self.assertIn("coco_classes", data)
        self.assertGreaterEqual(len(data["coco_classes"]), 80)
        self.assertIn("person", data["coco_classes"])
        self.assertIn("car", data["coco_classes"])

        self.assertIn("class_presets", data)
        self.assertEqual(data["class_presets"]["person"], ["person"])
        self.assertIn("car", data["class_presets"]["vehicles"])

        # 5. Source Presets
        self.assertIn("source_presets", data)
        source_values = [p["value"] for p in data["source_presets"]]
        self.assertIn("real", source_values)
        self.assertIn("0", source_values)

    def test_08_camera_pool_list_cameras_detection_fields(self):
        """Verify GET /api/cameras exposes detector, tracker, confidence and classes."""
        cam_id = "test_cap_cam_01"
        payload = {
            "id": cam_id,
            "name": "Capabilities Test Camera",
            "source": "synthetic",
            "type": "synthetic",
            "detector": "mock",
            "tracker": "sort",
            "confidence": 0.45,
            "classes": ["person", "car"],
            "enabled": True,
        }
        res_add = self.client.post("/api/cameras", json=payload)
        self.assertEqual(res_add.status_code, 200)

        # Retrieve list of cameras
        res_list = self.client.get("/api/cameras")
        self.assertEqual(res_list.status_code, 200)
        cameras = res_list.json()
        target = next((c for c in cameras if c["id"] == cam_id), None)
        self.assertIsNotNone(target)
        self.assertEqual(target["detector"], "mock")
        self.assertEqual(target["tracker"], "sort")
        self.assertEqual(target["confidence"], 0.45)
        self.assertEqual(target["classes"], ["person", "car"])

        # Update via PUT /api/cameras/{id}
        res_update = self.client.put(
            f"/api/cameras/{cam_id}",
            json={"confidence": 0.72, "classes": "dog, cat", "tracker": "centroid"},
        )
        self.assertEqual(res_update.status_code, 200)

        res_list_after = self.client.get("/api/cameras")
        cameras_after = res_list_after.json()
        target_after = next((c for c in cameras_after if c["id"] == cam_id), None)
        self.assertIsNotNone(target_after)
        self.assertEqual(target_after["confidence"], 0.72)
        self.assertEqual(target_after["classes"], ["dog", "cat"])
        self.assertEqual(target_after["tracker"], "centroid")

        # Clean up
        self.pool.remove_camera(cam_id)


if __name__ == "__main__":
    unittest.main()

