#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit & API Tests for Alias-Complete Report Deletion and Source Resolution Backfill.
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.services import video_report_store
from dashboard.services.video_transcoder import VideoTranscodeService


class TestVideoReportDeletionAndBackfill(unittest.TestCase):
    """Verify per-run deletion, clear-all across aliases, and automatic resolution backfill."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_rep_del_")
        self.orig_reports_dir = video_report_store.REPORTS_DIR
        self.orig_videos_dir = video_report_store.VIDEOS_DIR
        self.videos_dir = os.path.join(self.temp_dir, "videos")
        self.reports_dir = os.path.join(self.temp_dir, "reports")
        os.makedirs(self.videos_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)
        video_report_store.REPORTS_DIR = self.reports_dir
        video_report_store.VIDEOS_DIR = self.videos_dir
        self.client = TestClient(app)

    def tearDown(self):
        video_report_store.REPORTS_DIR = self.orig_reports_dir
        video_report_store.VIDEOS_DIR = self.orig_videos_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_json(self, path: str, payload) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

    def test_delete_single_run_cleans_all_alias_files_and_detections(self):
        """Deleting one run removes duplicate entries across parent/_h264 reports and detection JSON."""
        base_name = "gate_cam.mp4"
        h264_name = "gate_cam_h264.mp4"
        det_r1 = os.path.join(self.reports_dir, f"{base_name}_run_r1_detections.json")
        det_r2 = os.path.join(self.reports_dir, f"{h264_name}_run_r2_detections.json")
        det_r3 = os.path.join(self.reports_dir, f"{base_name}_run_r3_detections.json")
        for p in (det_r1, det_r2, det_r3):
            self._write_json(p, {"frame_detections": []})

        self._write_json(
            os.path.join(self.reports_dir, f"{base_name}_reports.json"),
            [
                {"run_id": "run_r3", "filename": base_name, "timestamp": 300.0, "source_resolution": [2688, 1520], "detections_file": det_r3},
                {"run_id": "run_r1", "filename": base_name, "timestamp": 100.0, "source_resolution": [2688, 1520], "detections_file": det_r1},
            ],
        )
        self._write_json(
            os.path.join(self.reports_dir, f"{h264_name}_reports.json"),
            [
                {"run_id": "run_r2", "filename": h264_name, "timestamp": 200.0, "source_resolution": [1920, 1086], "detections_file": det_r2},
                {"run_id": "run_r1", "filename": base_name, "timestamp": 100.0, "source_resolution": [2688, 1520], "detections_file": det_r1},
            ],
        )

        # Delete via the _h264 alias even though run_r1 originated on the parent file
        resp = self.client.delete(f"/api/videos/{h264_name}/reports/run_r1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["deleted_run_id"], "run_r1")

        self.assertFalse(os.path.exists(det_r1))
        self.assertTrue(os.path.exists(det_r2))
        self.assertTrue(os.path.exists(det_r3))

        remaining = video_report_store.list_report_runs(base_name)
        self.assertEqual([r["run_id"] for r in remaining], ["run_r3", "run_r2"])

        # Missing run returns 404
        resp_404 = self.client.delete(f"/api/videos/{base_name}/reports/run_r1")
        self.assertEqual(resp_404.status_code, 404)

    def test_delete_last_run_and_clear_all_across_aliases(self):
        """Clear-all removes all alias *_reports.json and *_detections.json files cleanly."""
        with open(os.path.join(self.videos_dir, "alley.mkv"), "wb") as f:
            f.write(b"mkv")

        r1 = video_report_store.save_report_run(
            "alley.mkv",
            {"frames_processed": 3, "total_detections": 1},
            {"detector": "mock"},
            frame_detections=[{"time": 0.0, "frame": 0, "tracks": []}],
            source_resolution=[2688, 1520],
        )
        r2 = video_report_store.save_report_run(
            "alley_h264.mp4",
            {"frames_processed": 4, "total_detections": 2},
            {"detector": "mock"},
            frame_detections=[{"time": 0.0, "frame": 0, "tracks": []}],
            source_resolution=[1920, 1086],
        )
        orphan_det = os.path.join(self.reports_dir, "alley_h264.mp4_run_orphan_detections.json")
        self._write_json(orphan_det, {"frame_detections": []})

        resp = self.client.delete("/api/videos/alley_h264.mp4/reports")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["cleared_count"], 2)
        self.assertEqual(video_report_store.list_report_runs("alley.mkv"), [])
        self.assertEqual(video_report_store.list_report_runs("alley_h264.mp4"), [])
        self.assertEqual(os.listdir(self.reports_dir), [])

        # Idempotent clear when already empty
        resp2 = self.client.delete("/api/videos/alley.mkv/reports")
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()["cleared_count"], 0)

        # Single-delete removes empty reports file cleanly
        r3 = video_report_store.save_report_run(
            "alley.mkv", {"frames_processed": 1}, {"detector": "mock"}, source_resolution=[2688, 1520]
        )
        self.assertTrue(video_report_store.delete_report_run("alley.mkv", r3["run_id"]))
        self.assertEqual(os.listdir(self.reports_dir), [])

    def test_delete_blocks_path_traversal_for_recorded_detections_file(self):
        """Deleting a crafted run entry never deletes files outside REPORTS_DIR."""
        outside_file = os.path.join(self.temp_dir, "do_not_delete.txt")
        with open(outside_file, "w", encoding="utf-8") as f:
            f.write("keep")
        self._write_json(
            os.path.join(self.reports_dir, "sec.mp4_reports.json"),
            [{"run_id": "run_bad", "timestamp": 1.0, "detections_file": outside_file}],
        )
        self.assertTrue(video_report_store.delete_report_run("sec.mp4", "run_bad"))
        self.assertTrue(os.path.exists(outside_file))

    def test_legacy_null_source_resolution_backfill_per_run_filename(self):
        """Legacy runs with source_resolution: null heal independently per run filename (2688x1520 vs 1920x1086)."""
        orig_fn = "cam_G94106186.mp4"
        h264_fn = "cam_G94106186_h264.mp4"
        orig_vid = os.path.join(self.videos_dir, orig_fn)
        h264_vid = os.path.join(self.videos_dir, h264_fn)
        with open(orig_vid, "wb") as f:
            f.write(b"hevc")
        with open(h264_vid, "wb") as f:
            f.write(b"h264")

        det1 = os.path.join(self.reports_dir, f"{orig_fn}_run_1_detections.json")
        det2 = os.path.join(self.reports_dir, f"{h264_fn}_run_2_detections.json")
        det3 = os.path.join(self.reports_dir, f"{orig_fn}_run_3_detections.json")
        self._write_json(det1, {"run_id": "run_1", "filename": orig_fn, "frame_detections": [{"time": 1.0, "tracks": []}]})
        self._write_json(det2, {"run_id": "run_2", "filename": h264_fn, "frame_detections": [{"time": 1.0, "tracks": []}]})
        self._write_json(det3, {"run_id": "run_3", "filename": orig_fn, "frame_detections": [{"time": 1.0, "tracks": []}]})

        self._write_json(
            os.path.join(self.reports_dir, f"{orig_fn}_reports.json"),
            [
                {"run_id": "run_3", "filename": orig_fn, "timestamp": 300.0, "source_resolution": None, "detections_file": det3},
                {"run_id": "run_1", "filename": orig_fn, "timestamp": 100.0, "source_resolution": None, "detections_file": det1},
            ],
        )
        self._write_json(
            os.path.join(self.reports_dir, f"{h264_fn}_reports.json"),
            [
                {"run_id": "run_2", "filename": h264_fn, "timestamp": 200.0, "source_resolution": None, "detections_file": det2},
                {"run_id": "run_1", "filename": orig_fn, "timestamp": 100.0, "source_resolution": None, "detections_file": det1},
            ],
        )

        def fake_probe(path: str) -> dict:
            if path.endswith("_h264.mp4"):
                return {"width": 1920, "height": 1086, "fps": 30.0}
            return {"width": 2688, "height": 1520, "fps": 30.0}

        with patch.object(VideoTranscodeService, "probe_video", side_effect=fake_probe):
            runs = video_report_store.list_report_runs(h264_fn)
            by_id = {r["run_id"]: r for r in runs}
            self.assertEqual(by_id["run_1"]["source_resolution"], [2688, 1520])
            self.assertEqual(by_id["run_2"]["source_resolution"], [1920, 1086])
            self.assertEqual(by_id["run_3"]["source_resolution"], [2688, 1520])

            s1 = video_report_store.get_detection_stream(h264_fn, "run_1")
            s2 = video_report_store.get_detection_stream(orig_fn, "run_2")
            s3 = video_report_store.get_detection_stream(h264_fn, "run_3")
            self.assertEqual(s1["source_resolution"], [2688, 1520])
            self.assertEqual(s2["source_resolution"], [1920, 1086])
            self.assertEqual(s3["source_resolution"], [2688, 1520])

        # Persisted on disk so subsequent reads succeed even without probing
        with open(det2, "r", encoding="utf-8") as f:
            self.assertEqual(json.load(f)["source_resolution"], [1920, 1086])

        # Missing video returns None gracefully
        self.assertIsNone(video_report_store._infer_source_resolution_for_filename("does_not_exist.mp4"))


if __name__ == "__main__":
    unittest.main()

