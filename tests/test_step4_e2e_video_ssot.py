#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Step 4 Milestone 4 Tests: E2E Live-Record Handoff, SQLite Backup/Restore & Fallbacks."""

import os
import shutil
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np
from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.dependencies import get_camera_pool, get_stream_manager
from dashboard.routers import camera_recording
from dashboard.services import video_report_store
from dashboard.stream_manager import StreamManager
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.pipeline.frame_processor import FrameStepResult


class _FakeTrack:
    """Minimal track stub exposing to_dict() for E2E frame handoff."""

    def __init__(self, track_id: int, entity_id: int | None = None) -> None:
        self._data = {"track_id": track_id, "bbox": [8, 12, 36, 44], "entity_id": entity_id, "label": "person"}

    def to_dict(self) -> dict:
        return dict(self._data)


class TestStep4E2EVideoSsot(unittest.TestCase):
    """End-to-end verification for SQLite TrackerDB SSOT and live-record handoff."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="test_step4_e2e_")
        self.addCleanup(self.temp_dir.cleanup)
        self.reports_dir = os.path.join(self.temp_dir.name, "reports")
        self.videos_dir = os.path.join(self.temp_dir.name, "videos")
        os.makedirs(self.reports_dir, exist_ok=True)
        os.makedirs(self.videos_dir, exist_ok=True)
        self._orig_store_reports = video_report_store.REPORTS_DIR
        self._orig_store_videos = video_report_store.VIDEOS_DIR
        self._orig_rec_videos = camera_recording.VIDEOS_DIR
        self._orig_overrides = dict(app.dependency_overrides)
        video_report_store.REPORTS_DIR = self.reports_dir
        video_report_store.VIDEOS_DIR = self.videos_dir
        camera_recording.VIDEOS_DIR = self.videos_dir
        self.addCleanup(self._restore_env)
        self.db_path = os.path.join(self.temp_dir.name, "tracker.db")
        self.client = TestClient(app)

    def _restore_env(self) -> None:
        video_report_store.REPORTS_DIR = self._orig_store_reports
        video_report_store.VIDEOS_DIR = self._orig_store_videos
        camera_recording.VIDEOS_DIR = self._orig_rec_videos
        app.dependency_overrides.clear()
        app.dependency_overrides.update(self._orig_overrides)

    def _make_manager(self, camera_id: str = "cam_e2e") -> StreamManager:
        mgr = StreamManager(
            db_path=self.db_path,
            camera_id=camera_id,
            source_override=0,
            custom_cfg={"video": {"width": 64, "height": 48}, "recording": {"output_dir": self.videos_dir}},
        )
        self.addCleanup(mgr.stop)
        return mgr

    def test_e2e_live_record_stop_immediately_serves_studio_reports_and_detections(self) -> None:
        """Live record -> stop makes /reports and /detections immediately available without batch."""
        mgr = self._make_manager("cam_e2e")
        app.dependency_overrides[get_camera_pool] = lambda: None
        app.dependency_overrides[get_stream_manager] = lambda: mgr

        start_resp = self.client.post("/api/cameras/cam_e2e/record/start", json={"filename": "e2e_live.mp4", "fps": 15.0})
        self.assertEqual(start_resp.status_code, 200)
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        step1 = FrameStepResult(
            frame=frame, detections=[object()], tracks={1: _FakeTrack(1, entity_id=9)},
            identifications=[SimpleNamespace(entity_id=9)], timestamp=100.0, fps=15.0, frame_count=1,
        )
        step2 = FrameStepResult(
            frame=frame, detections=[object()], tracks={1: _FakeTrack(1, entity_id=9)},
            identifications=[], timestamp=100.5, fps=15.0, frame_count=2,
        )
        self.assertTrue(mgr._recording_controller.write_frame(frame, frame, step_res=step1))
        self.assertTrue(mgr._recording_controller.write_frame(frame, frame, step_res=step2))

        stop_resp = self.client.post("/api/cameras/cam_e2e/record/stop")
        self.assertEqual(stop_resp.status_code, 200)
        self.assertIn("report_run_id", stop_resp.json())

        rep_resp = self.client.get("/api/videos/e2e_live.mp4/reports")
        self.assertEqual(rep_resp.status_code, 200)
        runs = rep_resp.json()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["run_type"], "live_capture")
        self.assertEqual(runs[0]["report"]["frames_processed"], 2)

        det_resp = self.client.get("/api/videos/e2e_live.mp4/detections")
        self.assertEqual(det_resp.status_code, 200)
        self.assertEqual(len(det_resp.json()["frame_detections"]), 2)
        self.assertEqual(os.listdir(self.reports_dir), [])

    def test_single_file_sqlite_backup_and_restore_preserves_all_runs(self) -> None:
        """Copying only tracker.db preserves all video runs and detection streams."""
        src_db = TrackerDB(self.db_path)
        live_dets = [{"time": 0.0, "frame": 0, "tracks": [{"track_id": 1, "bbox": [1, 2, 10, 20]}]}]
        batch_dets = [{"time": 0.5, "frame": 15, "tracks": [{"track_id": 2, "bbox": [5, 6, 15, 25]}]}]
        r_live = video_report_store.save_report_run(
            "gate.mp4", {"frames_processed": 10}, {"detector": "live"},
            frame_detections=live_dets, source_resolution=[64, 48], source_fps=15.0,
            run_type="live_capture", db=src_db,
        )
        r_batch = video_report_store.save_report_run(
            "gate.mp4", {"frames_processed": 30}, {"detector": "mock"},
            frame_detections=batch_dets, source_resolution=[64, 48], source_fps=30.0,
            run_type="batch", db=src_db,
        )
        src_db.close()
        self.assertEqual(os.listdir(self.reports_dir), [])

        restore_dir = tempfile.TemporaryDirectory(prefix="test_step4_restore_")
        self.addCleanup(restore_dir.cleanup)
        restored_path = os.path.join(restore_dir.name, "tracker.db")
        shutil.copy2(self.db_path, restored_path)
        restored_db = TrackerDB(restored_path)
        self.addCleanup(restored_db.close)

        runs = video_report_store.list_report_runs("gate.mp4", db=restored_db)
        self.assertEqual({r["run_id"] for r in runs}, {r_live["run_id"], r_batch["run_id"]})
        self.assertEqual(
            video_report_store.get_detection_stream("gate.mp4", r_live["run_id"], db=restored_db)["frame_detections"],
            live_dets,
        )
        self.assertEqual(
            video_report_store.get_detection_stream("gate.mp4", r_batch["run_id"], db=restored_db)["frame_detections"],
            batch_dets,
        )

    def test_non_mocked_fallback_branches_for_missing_camera_and_empty_video(self) -> None:
        """Unconfigured/empty fallback branches return clean 404/[] without mocks."""
        mgr = self._make_manager("cam_present")
        app.dependency_overrides[get_camera_pool] = lambda: None
        app.dependency_overrides[get_stream_manager] = lambda: mgr

        missing_cam = self.client.post("/api/cameras/cam_absent/record/start")
        self.assertEqual(missing_cam.status_code, 404)

        empty_reports = self.client.get("/api/videos/unseen_clip.mp4/reports")
        self.assertEqual(empty_reports.status_code, 200)
        self.assertEqual(empty_reports.json(), [])

        empty_dets = self.client.get("/api/videos/unseen_clip.mp4/detections")
        self.assertEqual(empty_dets.status_code, 404)

        empty_export = self.client.get("/api/videos/unseen_clip.mp4/reports/run_missing/export")
        self.assertEqual(empty_export.status_code, 404)


if __name__ == "__main__":
    unittest.main()
