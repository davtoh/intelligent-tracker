#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Step 3 Milestone 1 Unit Tests: Streaming FPS, Replay, Hibernation & P3 Capture/Motion."""

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import cv2
import numpy as np

from dashboard.services.async_inference_worker import build_live_step_result
from dashboard.services.camera_pool_queries import build_camera_status_row
from dashboard.services.file_detection_replay import FileDetectionReplayProvider
from dashboard.services.processing_mode_service import ProcessingModeService
from dashboard.services.stream_worker import StreamWorker
from dashboard.stream_manager import StreamManager
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.detectors import MockDetector
from intelligent_tracker.lifecycle import StreamLifecycleManager
from intelligent_tracker.pipeline.analytics_scheduler import AnalyticsScheduler, PriorityTier
from intelligent_tracker.pipeline.config import PipelineConfig
from intelligent_tracker.pipeline.engine import PipelineEngine
from intelligent_tracker.pipeline.frame_processor import FrameProcessor, FrameStepResult
from intelligent_tracker.pipeline.motion_gate import MotionGate
from intelligent_tracker.video.capture_helpers import compute_capture_timing, rewind_or_reopen_loop_video
from intelligent_tracker.video.source import VideoSource


def _write_mp4(path: Path, frames: int = 4, fps: float = 10.0) -> None:
    """Write a tiny synthetic MP4 clip for isolated capture/replay tests."""
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (160, 120))
    try:
        for idx in range(frames):
            img = np.full((120, 160, 3), 20 + idx * 30, dtype=np.uint8)
            writer.write(img)
    finally:
        writer.release()


class TestStep3StreamingFpsAndReplay(unittest.TestCase):
    """Verify P1-6, P1-7, P1-9, P1-10, P3-1, P3-2, and P3-4 invariants."""

    def test_p1_6_capture_only_updates_annotated_mjpeg(self):
        """capture_only mode encodes raw JPEGs and falls back in get_latest_frame_jpeg(annotated=True)."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        svc = ProcessingModeService(mode="capture_only")
        mgr = StreamManager(
            camera_id="cam_p16",
            source_override="synthetic",
            db_path=os.path.join(tmp.name, "p16.db"),
            custom_cfg={"detector": {"model": "mock"}, "reid": {"model": "color"}},
            processing_mode_service=svc,
        )
        self.addCleanup(mgr.stop)
        worker = StreamWorker(mgr)
        f1 = np.full((120, 160, 3), 30, dtype=np.uint8)
        f2 = np.full((120, 160, 3), 210, dtype=np.uint8)
        worker._process_single_frame(FrameStepResult(frame=f1, detections=[], tracks={}, analytics={}, identifications=[]))
        j1 = mgr.get_latest_frame_jpeg(annotated=True)
        worker._process_single_frame(FrameStepResult(frame=f2, detections=[], tracks={}, analytics={}, identifications=[]))
        j2 = mgr.get_latest_frame_jpeg(annotated=True)
        self.assertNotEqual(j1, j2)
        self.assertGreater(len(j2), 0)

    def test_p1_7_prefers_measured_fps_and_pause_resets(self):
        """StreamWorker telemetry prefers vs.measured_fps; pause() clears FPS history."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        mgr = StreamManager(
            camera_id="cam_p17",
            source_override="synthetic",
            db_path=os.path.join(tmp.name, "p17.db"),
            custom_cfg={"detector": {"model": "mock"}, "reid": {"model": "color"}},
            processing_mode_service=None,
        )
        self.addCleanup(mgr.stop)
        mgr.video_source._measured_fps = 14.2
        worker = StreamWorker(mgr)
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        worker._process_single_frame(
            FrameStepResult(frame=frame, detections=[], tracks={}, analytics={}, identifications=[], fps=450.0, frame_count=1)
        )
        self.assertAlmostEqual(mgr.get_latest_telemetry()["fps"], 14.2, places=1)
        mgr.video_source._frame_interval_samples.append(0.1)
        mgr.video_source._last_frame_time = 10.0
        mgr.video_source.pause()
        self.assertEqual(mgr.video_source.measured_fps, 0.0)
        self.assertEqual(mgr.video_source._frame_interval_samples, [])
        self.assertIsNone(mgr.video_source._last_frame_time)

    def test_p1_7_frame_processor_cadence_and_capture_timing(self):
        """FrameProcessor.step tracks inter-step cadence; compute_capture_timing updates dynamically."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bundle = PipelineEngine.build(
            PipelineConfig(db_path=os.path.join(tmp.name, "cad.db"), detector_model="mock", reid_model="color")
        )
        self.addCleanup(bundle.close)
        bundle.detector = MockDetector(boxes=[])
        proc = FrameProcessor(bundle)
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        proc.step(frame, timestamp=100.0)
        time.sleep(0.05)
        res = proc.step(frame, timestamp=100.05)
        self.assertLess(res.fps, 40.0)
        worker = MagicMock(is_file=True, source_fps=25.0, fps_limit=None)
        eff_fps, min_dt = compute_capture_timing(worker)
        self.assertEqual(eff_fps, 25.0)
        self.assertAlmostEqual(min_dt, 0.04, places=4)

    def test_p1_9_non_loop_eof_and_p3_4_rewind_reopen(self):
        """loop_video=False terminates at EOF without restart; seek failure reopens and increments loop_count."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        vid = Path(tmp.name) / "clip.mp4"
        _write_mp4(vid, frames=3, fps=10.0)
        vs = VideoSource(str(vid), loop_video=False)
        self.addCleanup(vs.stop)
        count = 0
        while count < 10:
            ok, _ = vs.read(timeout=1.0)
            if not ok:
                break
            count += 1
        self.assertGreater(count, 0)
        self.assertFalse(vs._running)
        self.assertEqual(vs.read(timeout=0.05), (False, None))

        fake_cap = MagicMock()
        fake_cap.set.return_value = False
        mock_worker = MagicMock(_cap=fake_cap, _loop_count=0, _stop_event=threading.Event())
        mock_worker._open_capture.return_value = True
        keep, empty = rewind_or_reopen_loop_video(mock_worker, 0, MagicMock())
        self.assertTrue(keep)
        self.assertEqual(empty, 0)
        self.assertEqual(mock_worker._loop_count, 1)
        mock_worker._open_capture.assert_called_once()

    def test_p3_2_file_read_timeout_reopens_instead_of_terminating(self):
        """is_file=True reopens capture on is_severed read timeout instead of stopping worker."""
        vs = VideoSource("synthetic")
        vs.is_synthetic, vs.is_file = False, True
        guard = MagicMock(last_read_timed_out=True, is_reconnecting=False)
        vs._running = True
        vs._cap = MagicMock()
        vs._open_capture = MagicMock(return_value=True)
        keep, empty, attempts = vs._handle_read_failure(guard, 2, 0)
        self.assertTrue(keep)
        self.assertEqual(empty, 0)
        vs._open_capture.assert_called_once()
        guard.reset.assert_called_once()

    def test_p1_9_deleted_video_run_exits_replay_and_scheduler_resets(self):
        """Deleting a video_run evicts REPLAY cache; paused/capture_only resets scheduler tier."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = TrackerDB(os.path.join(tmp.name, "rep.db"))
        self.addCleanup(db.close)
        vs = MagicMock(is_file=True, source=os.path.join(tmp.name, "vid.mp4"), source_fps=10.0)
        rep = FileDetectionReplayProvider(db, vs)
        saved = db.save_video_run(
            video_filename="vid.mp4",
            report={"entities": [], "alerts": []},
            frame_detections=[{"frame_idx": 0, "timestamp_sec": 0.0, "tracks": []}],
            source_fps=10.0,
        )
        self.assertTrue(rep.ensure_loaded())
        self.assertTrue(db.delete_video_run("vid.mp4", saved["run_id"]))
        self.assertFalse(rep.ensure_loaded())

        sched = AnalyticsScheduler()
        sched.should_schedule_frame("c1", mode="focus_only", is_focused=True, now=1.0)
        self.assertEqual(sched.get_camera_summary("c1", now=1.1)["priority_tier"], "P0")
        res = build_live_step_result(
            MagicMock(), np.zeros((16, 16, 3), dtype=np.uint8), now=2.0, frame_seq=1,
            run_vision=False, scheduler=sched, camera_id="c1", mode="paused",
        )
        self.assertEqual(getattr(res, "priority_tier"), PriorityTier.P2.value)
        self.assertEqual(sched.get_camera_summary("c1", now=2.1)["priority_tier"], "P2")

    def test_p1_10_hibernation_guards_and_evict_clears_modes(self):
        """Paused mode blocks _resume_video_source, surfaces status, and evict clears _subscriber_modes."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        svc = ProcessingModeService(mode="paused")
        mgr = StreamManager(
            camera_id="cam_p110",
            source_override="synthetic",
            db_path=os.path.join(tmp.name, "p110.db"),
            custom_cfg={"detector": {"model": "mock"}, "reid": {"model": "color"}},
            processing_mode_service=svc,
        )
        self.addCleanup(mgr.stop)
        mgr.video_source.pause()
        mgr.add_subscriber("sub1", annotated=False)
        self.assertTrue(mgr.video_source.is_paused)
        mgr._is_hibernating = True
        row = build_camera_status_row("cam_p110", {"enabled": True}, mgr)
        self.assertEqual(row["status"], "paused")
        self.assertTrue(row["is_hibernating"])

        pool = MagicMock(streams={"cam_p110": mgr}, _lock=threading.RLock())
        lcm = StreamLifecycleManager(camera_pool=pool, autostart_sampler=False)
        lcm.evict_subscribers("cam_p110")
        self.assertEqual(mgr._subscriber_registry._subscriber_modes, {})

    def test_p3_1_motion_gate_re_seeds_after_hibernation_gap(self):
        """MotionGate re-seeds bg_luma after evaluation gaps > max(hold_seconds, 2.0)."""
        mg = MotionGate(hold_seconds=3.0)
        dark = np.zeros((72, 128, 3), dtype=np.uint8)
        bright = np.full((72, 128, 3), 220, dtype=np.uint8)
        mg.evaluate("cam_mg", dark, now=1.0)
        wake = mg.evaluate("cam_mg", bright, now=10.0)
        self.assertFalse(wake.motion_active)
        self.assertFalse(wake.first_trigger)


if __name__ == "__main__":
    unittest.main()
