#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for Step 3 Milestone 1: On-Demand ROI Recognition & Tag Commit API.
"""

import base64
import os
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from dashboard.app import create_app
from dashboard.dependencies import clear_app_state
from intelligent_tracker.database import TrackerDB


class _FakeStreamManager:
    """Minimal isolated stream manager stub for ROI recognition tests."""

    def __init__(self, frame: np.ndarray | None, detector=None) -> None:
        self._lock = threading.RLock()
        self._latest_raw_frame = frame
        self.detector = detector
        self.reid_extractor = None
        self.gallery_matcher = SimpleNamespace(reload_gallery=lambda: None)
        self.rsac_manager = SimpleNamespace(reload=lambda: None)


class _FakePool:
    """Minimal camera pool stub for gallery reload verification."""

    def __init__(self, mgr: _FakeStreamManager | None = None) -> None:
        self._mgr = mgr
        self.reload_count = 0

    def get_stream(self, camera_id: str):
        if camera_id == "cam_01":
            return self._mgr
        return None

    def reload_all_galleries(self) -> None:
        self.reload_count += 1


class TestStep3RoiRecognitionApi(unittest.TestCase):
    """Isolated API tests for /api/tag/recognize-roi and /api/tag/commit."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "test_tracker.db")
        self.videos_dir = os.path.join(self.tmp.name, "videos")
        self.crops_dir = os.path.join(self.tmp.name, "crops")
        os.makedirs(self.videos_dir, exist_ok=True)
        os.makedirs(self.crops_dir, exist_ok=True)

        self.db = TrackerDB(db_path=self.db_path)
        self.addCleanup(self.db.close)

        self.frame = np.zeros((240, 320, 3), dtype=np.uint8)
        self.frame[40:180, 100:160] = (40, 180, 220)  # Tall person-like ROI

        self.mgr = _FakeStreamManager(self.frame)
        self.pool = _FakePool(self.mgr)

        self.app = create_app()
        self.app.state.db = self.db
        self.app.state.camera_pool = self.pool
        self.app.state.stream_manager = self.mgr
        self.addCleanup(clear_app_state, self.app)

        self.p_videos = patch("dashboard.routers.tagging.VIDEOS_DIR", self.videos_dir)
        self.p_crops = patch("dashboard.routers.tagging.CROPS_DIR", self.crops_dir)
        self.p_videos.start()
        self.p_crops.start()
        self.addCleanup(self.p_videos.stop)
        self.addCleanup(self.p_crops.stop)

        self.client = TestClient(self.app)

    def _write_synthetic_video(self, filename: str) -> str:
        path = os.path.join(self.videos_dir, filename)
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        writer = cv2.VideoWriter(path, fourcc, 10.0, (160, 120))
        for idx in range(5):
            img = np.zeros((120, 160, 3), dtype=np.uint8)
            img[20:100, 30:110] = (30 + idx * 10, 120, 200)
            writer.write(img)
        writer.release()
        return path

    def test_recognize_roi_live_camera_empty_gallery_heuristic(self) -> None:
        resp = self.client.post(
            "/api/tag/recognize-roi",
            json={"camera_id": "cam_01", "bbox": [100, 40, 60, 140]},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["bbox"], [100, 40, 60, 140])
        self.assertEqual(data["classification"]["label"], "person")
        self.assertEqual(data["classification"]["method"], "heuristic")
        self.assertEqual(data["candidates"], [])
        self.assertIsNone(data["best_match"])
        self.assertTrue(data["crop_base64"].startswith("data:image/jpeg;base64,"))

    def test_recognize_roi_detector_branch_and_gallery_match(self) -> None:
        # Commit an entity first so gallery is populated
        commit_resp = self.client.post(
            "/api/tag/commit",
            json={
                "entity_name": "Alice",
                "category": "person",
                "camera_id": "cam_01",
                "bbox": [100, 40, 60, 140],
                "notes": "VIP",
            },
        )
        self.assertEqual(commit_resp.status_code, 200)
        commit_data = commit_resp.json()["data"]
        self.assertEqual(commit_data["entity_name"], "Alice")
        self.assertEqual(self.pool.reload_count, 1)
        self.assertTrue(os.path.isfile(os.path.abspath(commit_data["crop_path"])))

        # Attach a mock detector to verify detector classification branch
        self.mgr.detector = SimpleNamespace(
            detect=lambda crop: [SimpleNamespace(label="person", confidence=0.94)]
        )
        rec_resp = self.client.post(
            "/api/tag/recognize-roi",
            json={"camera_id": "cam_01", "bbox": [100, 40, 60, 140], "top_k": 3},
        )
        self.assertEqual(rec_resp.status_code, 200)
        rec_data = rec_resp.json()["data"]
        self.assertEqual(rec_data["classification"]["method"], "detector")
        self.assertAlmostEqual(rec_data["classification"]["confidence"], 0.94, places=2)
        self.assertIsNotNone(rec_data["best_match"])
        self.assertEqual(rec_data["best_match"]["name"], "Alice")
        self.assertGreater(rec_data["best_match"]["similarity"], 0.95)

    def test_recognize_roi_video_seek_and_crop_base64(self) -> None:
        self._write_synthetic_video("clip.avi")
        vid_resp = self.client.post(
            "/api/tag/recognize-roi",
            json={
                "video_filename": "clip.avi",
                "timestamp_sec": 0.2,
                "bbox": [30, 20, 80, 40],
            },
        )
        self.assertEqual(vid_resp.status_code, 200)
        self.assertEqual(vid_resp.json()["data"]["classification"]["label"], "vehicle")

        ok, buf = cv2.imencode(".jpg", self.frame[40:180, 100:160])
        self.assertTrue(ok)
        b64 = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")
        b64_resp = self.client.post(
            "/api/tag/recognize-roi",
            json={"crop_base64": b64},
        )
        self.assertEqual(b64_resp.status_code, 200)
        self.assertEqual(b64_resp.json()["data"]["classification"]["label"], "person")

    def test_commit_existing_entity_appends_signature(self) -> None:
        first = self.client.post(
            "/api/tag/commit",
            json={"entity_name": "Bob", "camera_id": "cam_01", "bbox": [100, 40, 60, 140]},
        )
        self.assertEqual(first.status_code, 200)
        eid = first.json()["data"]["entity_id"]

        second = self.client.post(
            "/api/tag/commit",
            json={
                "entity_id": eid,
                "entity_name": "Bob",
                "category": "staff",
                "camera_id": "cam_01",
                "bbox": [100, 40, 60, 140],
            },
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["data"]["entity_id"], eid)
        sigs = self.db.get_signatures(entity_id=eid)
        self.assertEqual(len(sigs), 2)
        self.assertEqual(self.pool.reload_count, 2)

    def test_error_branches_400_404_503(self) -> None:
        # Missing source -> 400
        r1 = self.client.post("/api/tag/recognize-roi", json={"bbox": [0, 0, 20, 20]})
        self.assertEqual(r1.status_code, 400)

        # Bad base64 -> 400
        r2 = self.client.post("/api/tag/recognize-roi", json={"crop_base64": "not-valid-b64!!!"})
        self.assertEqual(r2.status_code, 400)

        # Missing video -> 404
        r3 = self.client.post(
            "/api/tag/recognize-roi",
            json={"video_filename": "missing.mp4", "bbox": [0, 0, 20, 20]},
        )
        self.assertEqual(r3.status_code, 404)

        # Missing camera -> 404
        r4 = self.client.post(
            "/api/tag/recognize-roi",
            json={"camera_id": "cam_99", "bbox": [0, 0, 20, 20]},
        )
        self.assertEqual(r4.status_code, 404)

        # Empty live buffer -> 503
        self.mgr._latest_raw_frame = None
        r5 = self.client.post(
            "/api/tag/recognize-roi",
            json={"camera_id": "cam_01", "bbox": [0, 0, 20, 20]},
        )
        self.assertEqual(r5.status_code, 503)


if __name__ == "__main__":
    unittest.main()
