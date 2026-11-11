#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit & Integration Tests for Video Pairing, Idempotent Transcoding,
Container PTS Timing, Resolution-Aware Reports, and Overlay Scaling.
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.dependencies import VIDEOS_DIR
from dashboard.services import video_report_store
from dashboard.services.video_jobs_service import get_video_job_manager
from intelligent_tracker.batch import VideoIndexer


def create_test_clip(
    path: str,
    num_frames: int = 8,
    fps: float = 12.5,
    width: int = 320,
    height: int = 240,
) -> str:
    """Create a tiny synthetic MP4 clip with a moving green target."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(path, fourcc, fps, (width, height))
    for i in range(num_frames):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        x = int(20 + (i * 10) % max(40, width - 60))
        cv2.rectangle(frame, (x, 40), (x + 40, 100), (0, 255, 0), -1)
        writer.write(frame)
    writer.release()
    return path


class TestVideoPairingAndIdempotencyAPI(unittest.TestCase):
    """Verify SC-01 pairing metadata in /api/videos and SC-02 idempotent /transcode."""

    @classmethod
    def setUpClass(cls):
        os.makedirs(VIDEOS_DIR, exist_ok=True)
        cls.client = TestClient(app)
        cls.created_files = []

        cls.paired_src = "pair_unit_clip.mp4"
        cls.paired_h264 = "pair_unit_clip_h264.mp4"
        cls.unpaired_src = "unpaired_unit_clip.mp4"
        cls.zero_byte_src = "zerobyte_unit_clip.mp4"
        cls.zero_byte_h264 = "zerobyte_unit_clip_h264.mp4"

        for name in (cls.paired_src, cls.paired_h264, cls.unpaired_src, cls.zero_byte_src):
            full = os.path.join(VIDEOS_DIR, name)
            create_test_clip(full, num_frames=6, fps=10.0)
            cls.created_files.append(full)

        zero_path = os.path.join(VIDEOS_DIR, cls.zero_byte_h264)
        with open(zero_path, "wb") as f:
            f.write(b"")
        cls.created_files.append(zero_path)

    @classmethod
    def tearDownClass(cls):
        for full in cls.created_files:
            if os.path.exists(full):
                try:
                    os.remove(full)
                except OSError:
                    pass

    def test_list_videos_pairing_flags(self):
        """SC-01: Non-web-compatible recording with valid _h264 copy sets has_converted_h264=True."""
        resp = self.client.get("/api/videos")
        self.assertEqual(resp.status_code, 200)
        by_name = {item["filename"]: item for item in resp.json()}

        paired_item = by_name.get(self.paired_src)
        self.assertIsNotNone(paired_item)
        self.assertFalse(paired_item["web_compatible"])
        self.assertTrue(paired_item["has_converted_h264"])
        self.assertEqual(paired_item["converted_filename"], self.paired_h264)

        child_item = by_name.get(self.paired_h264)
        self.assertIsNotNone(child_item)
        self.assertFalse(child_item["has_converted_h264"])
        self.assertIsNone(child_item["converted_filename"])

        unpaired_item = by_name.get(self.unpaired_src)
        self.assertIsNotNone(unpaired_item)
        self.assertFalse(unpaired_item["has_converted_h264"])
        self.assertIsNone(unpaired_item["converted_filename"])

        zero_item = by_name.get(self.zero_byte_src)
        self.assertIsNotNone(zero_item)
        self.assertFalse(zero_item["has_converted_h264"])

    def test_transcode_idempotent_skips_ffmpeg_when_output_exists(self):
        """SC-02: POST /transcode without force returns HTTP 200 already_exists without spawning ffmpeg."""
        with patch(
            "dashboard.services.video_transcoder.VideoTranscodeService.transcode_to_h264_async"
        ) as mock_async, patch(
            "dashboard.services.video_transcoder.VideoTranscodeService.transcode_to_h264"
        ) as mock_sync:
            resp = self.client.post(f"/api/videos/{self.paired_src}/transcode?async_mode=true")
            self.assertEqual(resp.status_code, 200)
            payload = resp.json()
            self.assertEqual(payload["status"], "success")
            self.assertTrue(payload["already_exists"])
            self.assertEqual(payload["output_filename"], self.paired_h264)
            self.assertEqual(payload["video_url"], f"/videos/{self.paired_h264}")
            mock_async.assert_not_called()
            mock_sync.assert_not_called()

    def test_transcode_force_true_bypasses_guard(self):
        """POST /transcode?force=true executes transcoder even when _h264 copy exists."""
        with patch(
            "dashboard.services.video_transcoder.VideoTranscodeService.transcode_to_h264",
            return_value=True,
        ) as mock_sync:
            resp = self.client.post(
                f"/api/videos/{self.paired_src}/transcode?async_mode=false&force=true"
            )
            self.assertEqual(resp.status_code, 200)
            payload = resp.json()
            self.assertEqual(payload["status"], "success")
            self.assertNotIn("already_exists", payload)
            mock_sync.assert_called_once()


class TestBatchPTSAndResolutionMetadata(unittest.TestCase):
    """Verify SYM-02 and SYM-03: container PTS timestamps and source_resolution capture."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_batch_pts_")
        self.db_path = os.path.join(self.temp_dir, "tracker.db")
        self.video_path = os.path.join(self.temp_dir, "pts_clip.mp4")
        create_test_clip(self.video_path, num_frames=8, fps=12.5, width=320, height=240)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_process_video_records_source_resolution_and_fps(self):
        """VideoIndexer stores source_resolution and source_fps in summary and detection frames."""
        indexer = VideoIndexer(
            db_path=self.db_path,
            detector_name="mock",
            sample_rate=1,
        )
        try:
            summary = indexer.process_video(self.video_path, verbose=False)
            self.assertEqual(summary["source_resolution"], [320, 240])
            self.assertAlmostEqual(summary["source_fps"], 12.5, places=2)
            self.assertGreater(len(summary["frame_detections"]), 0)
            for pkt in summary["frame_detections"]:
                self.assertEqual(pkt["source_resolution"], [320, 240])
        finally:
            indexer.db.close()

    def test_process_video_uses_container_pts_and_falls_back_when_zero_or_negative(self):
        """Container PTS overrides frame division; <= 0.0 PTS falls back to (read_frames - 1) / fps."""
        fake_frame = np.zeros((1086, 1920, 3), dtype=np.uint8)
        cv2.rectangle(fake_frame, (100, 100), (200, 300), (0, 255, 0), -1)

        # Simulate 3 frames:
        # Frame 0: POS_MSEC=0.0 -> fallback 0.0s
        # Frame 1: POS_MSEC=45.0 -> PTS 0.045s (distinct from 1/30.0 = 0.033s!)
        # Frame 2: POS_MSEC=-1.0 -> fallback 2 / 25.0 = 0.08s
        pos_values = iter([0.0, 45.0, -1.0])
        read_count = {"n": 0}

        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True

        def _cap_get(prop):
            if prop == cv2.CAP_PROP_FRAME_COUNT:
                return 3
            if prop == cv2.CAP_PROP_FPS:
                return 25.0
            if prop == cv2.CAP_PROP_FRAME_WIDTH:
                return 0  # Also tests fallback to frame.shape width/height
            if prop == cv2.CAP_PROP_FRAME_HEIGHT:
                return 0
            if prop == cv2.CAP_PROP_POS_MSEC:
                return next(pos_values, -1.0)
            return 0.0

        def _cap_read():
            if read_count["n"] < 3:
                read_count["n"] += 1
                return True, fake_frame.copy()
            return False, None

        mock_cap.get.side_effect = _cap_get
        mock_cap.read.side_effect = _cap_read

        indexer = VideoIndexer(db_path=self.db_path, detector_name="mock", sample_rate=1)
        try:
            with patch("intelligent_tracker.batch.cv2.VideoCapture", return_value=mock_cap):
                summary = indexer.process_video(self.video_path, verbose=False)

            self.assertEqual(summary["source_resolution"], [1920, 1086])
            self.assertEqual(summary["source_fps"], 25.0)
            times = [pkt["time"] for pkt in summary["frame_detections"]]
            self.assertEqual(times, [0.0, 0.045, 0.08])
        finally:
            indexer.db.close()


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
