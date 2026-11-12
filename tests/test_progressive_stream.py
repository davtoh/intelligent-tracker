#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit & Integration Tests for Progressive Detection Flush & Streaming API.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.services import progressive_stream_store, video_report_store
from dashboard.services.video_jobs_service import JobStatus, VideoJob, get_video_job_manager
from intelligent_tracker.batch import VideoIndexer


def create_synthetic_clip(
    path: str,
    num_frames: int = 35,
    fps: float = 15.0,
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


class TestBatchProgressiveFlush(unittest.TestCase):
    """Verify VideoIndexer.process_video flushes partial frame_detections every 30 frames."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_prog_flush_")
        self.db_path = os.path.join(self.temp_dir, "tracker.db")
        self.video_path = os.path.join(self.temp_dir, "prog_35f.mp4")
        create_synthetic_clip(self.video_path, num_frames=35, fps=15.0, width=320, height=240)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_progressive_flush_emits_at_30_frame_interval_and_completion(self):
        """Default flush_interval=30 emits intermediate chunk at frame 30 and final remainder."""
        flushes = []

        def on_flush(chunk, meta):
            flushes.append((chunk, dict(meta)))

        indexer = VideoIndexer(db_path=self.db_path, detector_name="mock", sample_rate=1)
        try:
            summary = indexer.process_video(
                self.video_path,
                verbose=False,
                frame_flush_callback=on_flush,
            )
        finally:
            indexer.db.close()

        self.assertEqual(len(flushes), 2)
        first_chunk, first_meta = flushes[0]
        final_chunk, final_meta = flushes[1]

        self.assertFalse(first_meta["final"])
        self.assertEqual(first_meta["processed_frames"], 30)
        self.assertEqual(first_meta["source_resolution"], [320, 240])
        self.assertTrue(final_meta["final"])
        self.assertEqual(final_meta["processed_frames"], 35)

        combined = first_chunk + final_chunk
        self.assertEqual(len(combined), len(summary["frame_detections"]))
        self.assertEqual(
            [f["frame"] for f in combined],
            [f["frame"] for f in summary["frame_detections"]],
        )

    def test_progressive_flush_callback_exception_is_non_fatal(self):
        """Raising inside frame_flush_callback does not abort indexing."""

        def broken_cb(_chunk, _meta):
            raise RuntimeError("transient listener failure")

        indexer = VideoIndexer(db_path=self.db_path, detector_name="mock", sample_rate=1)
        try:
            summary = indexer.process_video(
                self.video_path,
                verbose=False,
                frame_flush_callback=broken_cb,
                flush_interval=10,
            )
        finally:
            indexer.db.close()

        self.assertEqual(summary["processed_frames"], 35)


class TestProgressiveStreamAPI(unittest.TestCase):
    """Verify progressive stream store, incremental ?since= slicing, and REST /stream endpoint."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_prog_api_")
        self.orig_reports_dir = video_report_store.REPORTS_DIR
        self.reports_dir = os.path.join(self.temp_dir, "reports")
        os.makedirs(self.reports_dir, exist_ok=True)
        video_report_store.REPORTS_DIR = self.reports_dir
        self.client = TestClient(app)

    def tearDown(self):
        video_report_store.REPORTS_DIR = self.orig_reports_dir
        with progressive_stream_store._stream_lock:
            progressive_stream_store._streams.clear()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_progressive_store_incremental_slicing_and_partial_cleanup(self):
        """append_progressive_chunk writes disk snapshot; finalize removes temp file; since slices deltas."""
        progressive_stream_store.append_progressive_chunk(
            "job_unit_01",
            "clip.mp4",
            [{"time": 0.0, "frame": 0, "tracks": [{"track_id": 1}]}],
            {"source_resolution": [1920, 1080], "source_fps": 30.0, "processed_frames": 1, "final": False},
        )
        partial_path = os.path.join(self.reports_dir, "clip.mp4_job_unit_01_partial_detections.json")
        self.assertTrue(os.path.isfile(partial_path))

        progressive_stream_store.append_progressive_chunk(
            "job_unit_01",
            "clip.mp4",
            [{"time": 0.5, "frame": 15, "tracks": [{"track_id": 2}]}],
            {"source_resolution": [1920, 1080], "source_fps": 30.0, "processed_frames": 2, "final": False},
        )
        delta = progressive_stream_store.get_progressive_stream("job_unit_01", since=1)
        self.assertIsNotNone(delta)
        self.assertEqual(delta["next_index"], 2)
        self.assertEqual(len(delta["frame_detections"]), 1)
        self.assertEqual(delta["frame_detections"][0]["frame"], 15)

        progressive_stream_store.finalize_progressive_stream("job_unit_01")
        self.assertFalse(os.path.exists(partial_path))

    def test_stream_endpoint_returns_404_empty_live_alias_and_persisted_fallback(self):
        """GET /api/videos/{file}/jobs/{id}/stream covers 404, early empty, live chunks, alias, and fallback."""
        resp_404 = self.client.get("/api/videos/demo.mp4/jobs/job_missing/stream")
        self.assertEqual(resp_404.status_code, 404)

        early_job = VideoJob(
            job_id="job_early_01",
            job_type="analytics",
            filename="demo.mp4",
            status=JobStatus.RUNNING,
        )
        with patch.object(get_video_job_manager(), "get_job", return_value=early_job):
            resp_empty = self.client.get("/api/videos/demo.mp4/jobs/job_early_01/stream")
            self.assertEqual(resp_empty.status_code, 200)
            self.assertEqual(resp_empty.json()["frame_detections"], [])
            self.assertEqual(resp_empty.json()["status"], "running")

            resp_mismatch = self.client.get("/api/videos/other.mp4/jobs/job_early_01/stream")
            self.assertEqual(resp_mismatch.status_code, 404)

            progressive_stream_store.append_progressive_chunk(
                "job_early_01",
                "demo.mp4",
                [
                    {"time": 0.0, "frame": 0, "source_resolution": [2688, 1520], "tracks": [{"track_id": 1}]},
                    {"time": 1.0, "frame": 30, "source_resolution": [2688, 1520], "tracks": [{"track_id": 1}]},
                ],
                {"source_resolution": [2688, 1520], "source_fps": 30.0, "processed_frames": 30, "final": False},
            )
            resp_alias = self.client.get("/api/videos/demo_h264.mp4/jobs/job_early_01/stream?since=1")
            self.assertEqual(resp_alias.status_code, 200)
            body = resp_alias.json()
            self.assertEqual(body["next_index"], 2)
            self.assertEqual(len(body["frame_detections"]), 1)
            self.assertEqual(body["source_resolution"], [2688, 1520])

        run = video_report_store.save_report_run(
            filename="demo.mp4",
            report={"frames_processed": 5, "total_detections": 1},
            config={"detector": "mock"},
            frame_detections=[{"time": 0.2, "frame": 6, "source_resolution": [2688, 1520], "tracks": [{"track_id": 9}]}],
            source_resolution=[2688, 1520],
            source_fps=30.0,
        )
        done_job = VideoJob(
            job_id="job_done_fallback",
            job_type="analytics",
            filename="demo.mp4",
            status=JobStatus.COMPLETED,
            progress=100.0,
            result={"run_id": run["run_id"]},
        )
        with patch.object(get_video_job_manager(), "get_job", return_value=done_job):
            resp_fb = self.client.get("/api/videos/demo_h264.mp4/jobs/job_done_fallback/stream")
            self.assertEqual(resp_fb.status_code, 200)
            fb = resp_fb.json()
            self.assertTrue(fb["final"])
            self.assertEqual(fb["run_id"], run["run_id"])
            self.assertEqual(len(fb["frame_detections"]), 1)
            self.assertEqual(fb["frame_detections"][0]["tracks"][0]["track_id"], 9)


if __name__ == "__main__":
    unittest.main()

