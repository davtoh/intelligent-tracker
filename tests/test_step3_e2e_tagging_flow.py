#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
End-to-end integration tests for Step 3 Milestone 4:
Live camera and recorded video ROI draw -> recognize -> commit -> gallery match/reload,
including non-mocked single-stream, Re-ID color, and detector fallback branches.
"""

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
from intelligent_tracker.matching.gallery import GalleryMatcher
from intelligent_tracker.reid.factory import ReIDExtractorFactory
from intelligent_tracker.rsac import RSACManager


class _StreamStub:
    """Minimal stream holder with real GalleryMatcher and RSACManager."""

    def __init__(self, frame: np.ndarray, matcher: GalleryMatcher, rsac: RSACManager) -> None:
        self._lock = threading.RLock()
        self._latest_raw_frame = frame
        self.detector = None
        self.reid_extractor = None
        self.gallery_matcher = matcher
        self.rsac_manager = rsac


class _PoolStub:
    """Minimal multi-camera pool delegating gallery reloads to real matchers."""

    def __init__(self, streams: dict[str, _StreamStub]) -> None:
        self.streams = streams

    def get_stream(self, camera_id: str | None = None):
        return self.streams.get(camera_id) if camera_id else None

    def reload_all_galleries(self) -> None:
        for stream in self.streams.values():
            if stream.gallery_matcher:
                stream.gallery_matcher.reload_gallery()
            if stream.rsac_manager:
                stream.rsac_manager.reload()


class TestStep3E2ETaggingFlow(unittest.TestCase):
    """End-to-end ROI tagging, gallery reload, and fallback branch verification."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "e2e_tracker.db")
        self.videos_dir = os.path.join(self.tmp.name, "videos")
        self.crops_dir = os.path.join(self.tmp.name, "crops")
        os.makedirs(self.videos_dir, exist_ok=True)
        os.makedirs(self.crops_dir, exist_ok=True)

        self.db = TrackerDB(db_path=self.db_path)
        self.addCleanup(self.db.close)

        self.matcher = GalleryMatcher(db=self.db, extractor=ReIDExtractorFactory.create("color"))
        self.rsac = RSACManager(db=self.db)

        self.frame = np.zeros((240, 320, 3), dtype=np.uint8)
        self.frame[30:180, 90:160] = (50, 175, 225)
        self.frame[10:50, 10:50] = (180, 90, 40)

        self.stream = _StreamStub(self.frame, self.matcher, self.rsac)
        self.pool = _PoolStub({"cam_01": self.stream})

        self.app = create_app()
        self.app.state.db = self.db
        self.app.state.camera_pool = self.pool
        self.app.state.stream_manager = self.stream
        self.addCleanup(clear_app_state, self.app)

        self.p_videos = patch("dashboard.routers.tagging.VIDEOS_DIR", self.videos_dir)
        self.p_crops = patch("dashboard.routers.tagging.CROPS_DIR", self.crops_dir)
        self.p_videos.start()
        self.p_crops.start()
        self.addCleanup(self.p_videos.stop)
        self.addCleanup(self.p_crops.stop)

        self.client = TestClient(self.app)

    def _create_synthetic_video(self, filename: str) -> str:
        path = os.path.join(self.videos_dir, filename)
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        writer = cv2.VideoWriter(path, fourcc, 10.0, (160, 120))
        for idx in range(6):
            img = np.zeros((120, 160, 3), dtype=np.uint8)
            img[20:65, 30:120] = (20 + idx * 5, 140, 210)
            writer.write(img)
        writer.release()
        return path

    def test_live_camera_roi_draw_recognize_commit_and_gallery_match(self) -> None:
        rec1 = self.client.post(
            "/api/tag/recognize-roi",
            json={"camera_id": "cam_01", "bbox": [90, 30, 70, 150]},
        )
        self.assertEqual(rec1.status_code, 200)
        d1 = rec1.json()["data"]
        self.assertEqual(d1["classification"]["label"], "person")
        self.assertEqual(d1["candidates"], [])

        commit = self.client.post(
            "/api/tag/commit",
            json={
                "entity_name": "Elena",
                "category": "person",
                "camera_id": "cam_01",
                "bbox": [90, 30, 70, 150],
                "notes": "Live ROI tag",
            },
        )
        self.assertEqual(commit.status_code, 200)
        c_data = commit.json()["data"]
        self.assertTrue(os.path.isfile(os.path.abspath(c_data["crop_path"])))
        self.assertIn("Elena", self.matcher.gallery_names)

        rec2 = self.client.post(
            "/api/tag/recognize-roi",
            json={"camera_id": "cam_01", "bbox": [92, 32, 68, 148], "top_k": 3},
        )
        self.assertEqual(rec2.status_code, 200)
        d2 = rec2.json()["data"]
        self.assertIsNotNone(d2["best_match"])
        self.assertEqual(d2["best_match"]["name"], "Elena")
        self.assertGreater(d2["best_match"]["similarity"], 0.9)

    def test_video_timestamp_roi_draw_recognize_commit_and_gallery_reload(self) -> None:
        self._create_synthetic_video("patrol_clip.avi")
        rec1 = self.client.post(
            "/api/tag/recognize-roi",
            json={"video_filename": "patrol_clip.avi", "timestamp_sec": 0.3, "bbox": [30, 20, 90, 45]},
        )
        self.assertEqual(rec1.status_code, 200)
        self.assertEqual(rec1.json()["data"]["classification"]["label"], "vehicle")

        commit = self.client.post(
            "/api/tag/commit",
            json={
                "entity_name": "Van-07",
                "category": "vehicle",
                "video_filename": "patrol_clip.avi",
                "timestamp_sec": 0.3,
                "bbox": [30, 20, 90, 45],
            },
        )
        self.assertEqual(commit.status_code, 200)
        self.assertIn("Van-07", self.matcher.gallery_names)

        rec2 = self.client.post(
            "/api/tag/recognize-roi",
            json={"video_filename": "patrol_clip.avi", "timestamp_sec": 0.4, "bbox": [30, 20, 90, 45]},
        )
        self.assertEqual(rec2.status_code, 200)
        self.assertEqual(rec2.json()["data"]["best_match"]["name"], "Van-07")

    def test_single_stream_fallback_without_camera_pool(self) -> None:
        self.app.state.camera_pool = None
        self.stream.camera_id = "cam_01"
        rec = self.client.post(
            "/api/tag/recognize-roi",
            json={"camera_id": "cam_01", "bbox": [10, 10, 40, 40]},
        )
        self.assertEqual(rec.status_code, 200)
        self.assertEqual(rec.json()["data"]["classification"]["label"], "object")
        self.assertEqual(rec.json()["data"]["classification"]["method"], "heuristic")

        commit = self.client.post(
            "/api/tag/commit",
            json={
                "entity_name": "SquareBox",
                "category": "object",
                "camera_id": "cam_01",
                "bbox": [10, 10, 40, 40],
            },
        )
        self.assertEqual(commit.status_code, 200)
        self.assertIn("SquareBox", self.matcher.gallery_names)

    def test_detector_exception_falls_back_to_heuristic(self) -> None:
        def _boom(_crop):
            raise RuntimeError("detector unavailable")

        self.stream.detector = SimpleNamespace(detect=_boom)
        resp = self.client.post(
            "/api/tag/recognize-roi",
            json={"camera_id": "cam_01", "bbox": [90, 30, 70, 150]},
        )
        self.assertEqual(resp.status_code, 200)
        cls_info = resp.json()["data"]["classification"]
        self.assertEqual(cls_info["method"], "heuristic")
        self.assertEqual(cls_info["label"], "person")
