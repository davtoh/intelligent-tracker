#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Step 4 Milestone 2 Tests: SQLite TrackerDB Report SSOT, Legacy Migration & Export API."""

import json
import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.services import video_report_store
from intelligent_tracker.database import TrackerDB


class TestStep4ReportSsotAndExport(unittest.TestCase):
    """Verify 100% SQLite report persistence, legacy JSON auto-migration, and export API."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="test_step4_ssot_")
        self.addCleanup(self.temp_dir.cleanup)
        self.orig_reports_dir = video_report_store.REPORTS_DIR
        self.orig_videos_dir = video_report_store.VIDEOS_DIR
        self.reports_dir = os.path.join(self.temp_dir.name, "reports")
        self.videos_dir = os.path.join(self.temp_dir.name, "videos")
        os.makedirs(self.reports_dir, exist_ok=True)
        os.makedirs(self.videos_dir, exist_ok=True)
        video_report_store.REPORTS_DIR = self.reports_dir
        video_report_store.VIDEOS_DIR = self.videos_dir
        self.addCleanup(self._restore_dirs)
        self.db = TrackerDB(os.path.join(self.temp_dir.name, "explicit.db"))
        self.addCleanup(self.db.close)
        self.client = TestClient(app)

    def _restore_dirs(self) -> None:
        video_report_store.REPORTS_DIR = self.orig_reports_dir
        video_report_store.VIDEOS_DIR = self.orig_videos_dir

    def test_save_report_run_writes_only_to_sqlite_not_json(self) -> None:
        """Saving a run stores metadata and detections in TrackerDB without creating JSON files."""
        dets = [{"time": 0.5, "frame": 15, "tracks": [{"track_id": 7, "bbox": [10, 20, 30, 40]}]}]
        saved = video_report_store.save_report_run(
            filename="gate.mp4",
            report={"frames_processed": 30, "total_detections": 1},
            config={"detector": "mock"},
            frame_detections=dets,
            source_resolution=[1920, 1080],
            source_fps=30.0,
            db=self.db,
        )
        self.assertEqual(os.listdir(self.reports_dir), [])
        row = self.db.get_video_run(saved["run_id"], include_detections=True)
        self.assertIsNotNone(row)
        self.assertEqual(row["source_resolution"], [1920, 1080])
        self.assertEqual(row["frame_detections"], dets)

    def test_legacy_json_auto_migrates_into_trackerdb_on_first_access(self) -> None:
        """Legacy *_reports.json and *_detections.json auto-import into TrackerDB on read."""
        rep_path = os.path.join(self.reports_dir, "cam_legacy.mp4_reports.json")
        det_path = os.path.join(self.reports_dir, "cam_legacy.mp4_run_leg1_detections.json")
        dets = [{"time": 1.0, "frame": 30, "tracks": [{"track_id": 3, "bbox": [1, 2, 3, 4]}]}]
        with open(det_path, "w", encoding="utf-8") as f:
            json.dump({"run_id": "run_leg1", "filename": "cam_legacy.mp4", "frame_detections": dets}, f)
        with open(rep_path, "w", encoding="utf-8") as f:
            json.dump([{
                "run_id": "run_leg1", "filename": "cam_legacy.mp4", "timestamp": 123.0,
                "source_resolution": [1280, 720], "source_fps": 25.0,
                "report": {"frames_processed": 10}, "config": {"detector": "mock"},
                "detections_file": det_path,
            }], f)

        runs = video_report_store.list_report_runs("cam_legacy_h264.mp4", db=self.db)
        self.assertEqual([r["run_id"] for r in runs], ["run_leg1"])
        os.remove(rep_path)
        os.remove(det_path)

        stream = video_report_store.get_detection_stream("cam_legacy_h264.mp4", "run_leg1", db=self.db)
        self.assertIsNotNone(stream)
        self.assertEqual(stream["frame_detections"], dets)

    def test_export_endpoint_returns_portable_json_attachment(self) -> None:
        """GET /api/videos/{filename}/reports/{run_id}/export downloads full run + detections."""
        dets = [{"time": 0.0, "frame": 0, "tracks": [{"track_id": 1, "bbox": [5, 5, 20, 40]}]}]
        saved = video_report_store.save_report_run(
            filename="alley.mkv",
            report={"frames_processed": 5, "total_detections": 1},
            config={"detector": "mock"},
            frame_detections=dets,
            source_resolution=[2688, 1520],
            source_fps=30.0,
        )
        rid = saved["run_id"]
        resp = self.client.get(f"/api/videos/alley_h264.mp4/reports/{rid}/export")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("attachment; filename=", resp.headers.get("content-disposition", ""))
        body = resp.json()
        self.assertEqual(body["schema_version"], 1)
        self.assertEqual(body["run_id"], rid)
        self.assertEqual(body["frame_detections"], dets)
        self.assertEqual(body["report"]["frames_processed"], 5)

    def test_export_endpoint_returns_404_for_missing_run(self) -> None:
        """GET /api/videos/{filename}/reports/{run_id}/export returns 404 when absent."""
        resp = self.client.get("/api/videos/missing.mp4/reports/run_nope/export")
        self.assertEqual(resp.status_code, 404)

    def test_delete_and_clear_on_sqlite_ssot(self) -> None:
        """Single delete and clear-all operate cleanly across aliases in TrackerDB."""
        r1 = video_report_store.save_report_run("yard.mkv", {"frames_processed": 2}, {"detector": "mock"}, db=self.db)
        r2 = video_report_store.save_report_run("yard_h264.mp4", {"frames_processed": 4}, {"detector": "mock"}, db=self.db)
        self.assertTrue(video_report_store.delete_report_run("yard_h264.mp4", r1["run_id"], db=self.db))
        remaining = video_report_store.list_report_runs("yard.mkv", db=self.db)
        self.assertEqual([r["run_id"] for r in remaining], [r2["run_id"]])
        self.assertEqual(video_report_store.clear_report_runs("yard.mkv", db=self.db), 1)
        self.assertEqual(video_report_store.list_report_runs("yard_h264.mp4", db=self.db), [])


if __name__ == "__main__":
    unittest.main()
