#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit Tests for Unified Video Report Store & Codec Parent/Child Consolidation.
"""

import json
import os
import shutil
import tempfile
import unittest

from dashboard.services import video_report_store


class TestUnifiedReportStoreAndResolutionScaling(unittest.TestCase):
    """Verify consolidated base-name report stacks and resolution metadata persistence."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_report_store_")
        self.orig_reports_dir = video_report_store.REPORTS_DIR
        self.orig_videos_dir = video_report_store.VIDEOS_DIR
        self.videos_dir = os.path.join(self.temp_dir, "videos")
        self.reports_dir = os.path.join(self.temp_dir, "reports")
        os.makedirs(self.videos_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)
        video_report_store.REPORTS_DIR = self.reports_dir
        video_report_store.VIDEOS_DIR = self.videos_dir

    def tearDown(self):
        video_report_store.REPORTS_DIR = self.orig_reports_dir
        video_report_store.VIDEOS_DIR = self.orig_videos_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_save_and_lookup_unified_across_parent_and_h264_child(self):
        """Reports saved under foo.mp4 or foo_h264.mp4 consolidate into one chronological stack."""
        run1 = video_report_store.save_report_run(
            filename="cam_rec.mp4",
            report={"frames_processed": 10, "total_detections": 4, "source_resolution": [2688, 1520], "source_fps": 30.027},
            config={"detector": "yolov8", "classes": ["person"]},
            frame_detections=[{"time": 0.0, "frame": 0, "source_resolution": [2688, 1520], "tracks": [{"track_id": 1, "bbox": [1421, 175, 63, 132]}]}],
        )
        run2 = video_report_store.save_report_run(
            filename="cam_rec_h264.mp4",
            report={"frames_processed": 10, "total_detections": 7, "source_resolution": [1920, 1086], "source_fps": 30.0},
            config={"detector": "yolov8", "classes": ["car"]},
            frame_detections=[{"time": 0.0, "frame": 0, "source_resolution": [1920, 1086], "tracks": [{"track_id": 2, "bbox": [500, 200, 120, 80]}]}],
        )

        runs_parent = video_report_store.list_report_runs("cam_rec.mp4")
        runs_child = video_report_store.list_report_runs("cam_rec_h264.mp4")

        self.assertEqual([r["run_id"] for r in runs_parent], [run2["run_id"], run1["run_id"]])
        self.assertEqual([r["run_id"] for r in runs_child], [run2["run_id"], run1["run_id"]])
        self.assertEqual(runs_parent[1]["source_resolution"], [2688, 1520])
        self.assertEqual(runs_parent[1]["source_fps"], 30.027)

        stream1 = video_report_store.get_detection_stream("cam_rec_h264.mp4", run1["run_id"])
        self.assertIsNotNone(stream1)
        self.assertEqual(stream1["source_resolution"], [2688, 1520])
        self.assertEqual(stream1["source_fps"], 30.027)

    def test_mkv_parent_and_legacy_split_file_merge(self):
        """MKV parent resolves from _h264.mp4 and merges any legacy split report files."""
        with open(os.path.join(self.videos_dir, "hallway.mkv"), "wb") as f:
            f.write(b"mkv")

        run_mkv = video_report_store.save_report_run(
            filename="hallway_h264.mp4",
            report={"frames_processed": 5, "total_detections": 2},
            config={"detector": "mock"},
            source_resolution=[2688, 1520],
            source_fps=30.0,
        )
        self.assertEqual(run_mkv["base_filename"], "hallway.mkv")

        # Simulate legacy split report file written directly under hallway_h264.mp4
        legacy_path = os.path.join(self.reports_dir, "hallway_h264.mp4_reports.json")
        with open(legacy_path, "w", encoding="utf-8") as f:
            json.dump(
                [
                    {"run_id": run_mkv["run_id"], "timestamp": run_mkv["timestamp"]},
                    {"run_id": "run_legacy_01", "timestamp": 1.0, "source_resolution": [1280, 720]},
                ],
                f,
            )

        runs_from_mkv = video_report_store.list_report_runs("hallway.mkv")
        runs_from_h264 = video_report_store.list_report_runs("hallway_h264.mp4")
        self.assertEqual([r["run_id"] for r in runs_from_mkv], [run_mkv["run_id"], "run_legacy_01"])
        self.assertEqual([r["run_id"] for r in runs_from_h264], [run_mkv["run_id"], "run_legacy_01"])


if __name__ == "__main__":
    unittest.main()

