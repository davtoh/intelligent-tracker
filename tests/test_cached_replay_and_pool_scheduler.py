"""Tests for CachedReplayProvider live rule governance and pool AnalyticsScheduler wiring."""

import os
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

import numpy as np

from dashboard.services.async_inference_worker import (
    AsyncInferenceWorker,
    build_live_step_result,
    build_worker_step_result,
)
from dashboard.services.cached_replay_provider import CachedReplayProvider
from dashboard.services.camera_pool_queries import build_camera_status_row
from dashboard.services.processing_mode_service import ProcessingModeService
from dashboard.services.stream_telemetry import build_stream_telemetry
from dashboard.services.stream_worker import StreamWorker
from intelligent_tracker.analytics.engine import AnalyticsEngine
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.events import EventBus, RSACViolationEvent, TripwireCrossEvent, ZoneEvent
from intelligent_tracker.geometry import Tripwire, ZoneROI
from intelligent_tracker.pipeline import FrameStepResult, PipelineBundle, PipelineConfig
from intelligent_tracker.pipeline.analytics_scheduler import PriorityTier
from intelligent_tracker.rsac import RSACManager


def _make_governed_bundle(db: TrackerDB, camera_id: str = "cam_replay") -> tuple[PipelineBundle, EventBus, list[object]]:
    """Build an isolated PipelineBundle with ZoneROI, Tripwire, RSAC, and EventBus."""
    bus = EventBus()
    bus.start()
    published: list[object] = []
    bus.subscribe("*", lambda ev: published.append(ev))
    zone = ZoneROI(name="vault", polygon=[(50, 50), (300, 50), (300, 300), (50, 300)])
    trip = Tripwire(line_segment=((150, 0), (150, 360)), name="entry")
    rsac = RSACManager(db=db)
    rsac.set_rule(camera_id, "vault", allowed_categories=["staff"])
    analytics = AnalyticsEngine(zones=[zone], tripwires=[trip], event_bus=bus, rsac_manager=rsac, camera_id=camera_id)
    detector = MagicMock()
    bundle = PipelineBundle(
        config=PipelineConfig(camera_id=camera_id),
        detector=detector,
        tracker=MagicMock(),
        analytics=analytics,
        event_bus=bus,
    )
    return bundle, bus, published


class TestCachedReplayAndPoolScheduler(unittest.TestCase):
    """Verify zero-GPU CachedReplayProvider governance, loop resets, and pool scheduling."""

    def test_cached_replay_emits_zone_tripwire_rsac_with_zero_detector_calls(self) -> None:
        """Pre-indexed video_file camera emits live Zone/Tripwire/RSAC events with 0 GPU calls."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = TrackerDB(os.path.join(tmp.name, "replay.db"))
        self.addCleanup(db.close)
        bundle, bus, published = _make_governed_bundle(db)
        self.addCleanup(bus.stop)

        dets = [
            {"time": 0.0, "frame": 0, "source_resolution": [640, 360], "tracks": [
                {"id": 7, "bbox": [80, 100, 40, 80], "centroid": [100, 140], "label": "person", "category": "visitor"}
            ]},
            {"time": 0.1, "frame": 1, "source_resolution": [640, 360], "tracks": [
                {"id": 7, "bbox": [180, 100, 40, 80], "centroid": [200, 140], "label": "person", "category": "visitor"}
            ]},
        ]
        db.save_video_run("clip.mp4", report={"frames_processed": 2}, frame_detections=dets, source_resolution=[640, 360], source_fps=10.0)
        vs = SimpleNamespace(is_file=True, source="data/videos/clip.mp4", source_fps=10.0)
        provider = CachedReplayProvider(db, vs, bundle=bundle)
        proc = SimpleNamespace(bundle=bundle, step=MagicMock())
        worker = AsyncInferenceWorker(proc, replay_provider=provider)
        svc = ProcessingModeService()
        frame = np.zeros((360, 640, 3), dtype=np.uint8)

        res1 = build_live_step_result(worker, frame, now=1.0, frame_seq=1, run_vision=True, scheduler=svc.scheduler, camera_id="cam_replay")
        res2 = build_live_step_result(worker, frame, now=1.1, frame_seq=2, run_vision=True, scheduler=svc.scheduler, camera_id="cam_replay")
        bus.wait_until_empty(timeout=1.0)

        bundle.detector.detect.assert_not_called()
        proc.step.assert_not_called()
        self.assertEqual(getattr(res1, "priority_tier", None), "REPLAY")
        self.assertTrue(getattr(res2, "replay_active", False))
        self.assertEqual(svc.scheduler.get_summary()["active_inferences"], 0)
        self.assertTrue(any(isinstance(e, ZoneEvent) for e in published))
        self.assertTrue(any(isinstance(e, TripwireCrossEvent) for e in published))
        self.assertTrue(any(isinstance(e, RSACViolationEvent) for e in published))

    def test_cached_replay_resets_state_on_loop_wrap_around(self) -> None:
        """Loop wrap-around resets zone current_occupants and analytics _prev_centroids cleanly."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = TrackerDB(os.path.join(tmp.name, "loop.db"))
        self.addCleanup(db.close)
        bundle, bus, _ = _make_governed_bundle(db)
        self.addCleanup(bus.stop)

        dets = [
            {"time": 0.0, "frame": 0, "source_resolution": [640, 360], "tracks": [
                {"id": 1, "bbox": [80, 100, 40, 80], "centroid": [100, 140], "label": "person"}
            ]},
            {"time": 0.1, "frame": 1, "source_resolution": [640, 360], "tracks": [
                {"id": 1, "bbox": [180, 100, 40, 80], "centroid": [200, 140], "label": "person"}
            ]},
        ]
        db.save_video_run("loop.mp4", report={"frames_processed": 2}, frame_detections=dets, source_resolution=[640, 360], source_fps=10.0)
        vs = SimpleNamespace(is_file=True, source="data/videos/loop.mp4", source_fps=10.0)
        provider = CachedReplayProvider(db, vs, bundle=bundle)
        frame = np.zeros((360, 640, 3), dtype=np.uint8)

        provider.build_step_result(frame, now=1.0, frame_seq=1)
        provider.build_step_result(frame, now=1.1, frame_seq=2)
        self.assertIn(1, bundle.analytics.zones["vault"].current_occupants)
        provider.build_step_result(frame, now=1.2, frame_seq=3)
        self.assertEqual(provider.loop_reset_count, 1)

    def test_unindexed_video_falls_back_to_scheduler_live_inference(self) -> None:
        """Unindexed video_file camera returns None from CachedReplayProvider and uses AnalyticsScheduler."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = TrackerDB(os.path.join(tmp.name, "empty.db"))
        self.addCleanup(db.close)
        vs = SimpleNamespace(is_file=True, source="data/videos/unindexed.mp4", source_fps=10.0)
        provider = CachedReplayProvider(db, vs)
        step_done = threading.Event()
        proc = SimpleNamespace(step=lambda f, timestamp, max_dim=1280: (step_done.set() or FrameStepResult(frame=f, timestamp=timestamp)))
        worker = AsyncInferenceWorker(proc, replay_provider=provider)
        worker.start()
        self.addCleanup(worker.stop)

        svc = ProcessingModeService()
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        res = build_live_step_result(
            worker, frame, now=5.0, frame_seq=1, run_vision=True,
            scheduler=svc.scheduler, camera_id="cam_unindexed", mode="focus_only", is_focused=True,
        )
        self.assertTrue(step_done.wait(timeout=2.0))
        self.assertEqual(getattr(res, "priority_tier", None), PriorityTier.P0.value)
        self.assertFalse(getattr(res, "replay_active", False))

    def test_focus_only_armed_p1_motion_and_alarm_promotion_to_p0(self) -> None:
        """Unfocused armed camera runs P1 in focus_only and promotes to P0 within <= 2.0 s on intrusion."""
        svc = ProcessingModeService()
        svc.update(mode="focus_only", focused_camera_id="cam_01", active_tab="live")
        mgr = SimpleNamespace(camera_id="cam_02", is_armed=True, _processing_mode_service=svc)
        worker = StreamWorker(mgr)
        self.assertTrue(worker._should_run_vision_step(is_recording=False))

        static_f = np.zeros((72, 128, 3), dtype=np.uint8)
        motion_f = np.full((72, 128, 3), 220, dtype=np.uint8)
        proc = SimpleNamespace(step=lambda f, timestamp, max_dim=1280: FrameStepResult(frame=f, tracks={1: SimpleNamespace(id=1, centroid=(10, 10))}, timestamp=timestamp))
        async_w = AsyncInferenceWorker(proc, scheduler=svc.scheduler, camera_id="cam_02", is_armed=True)
        async_w.start()
        self.addCleanup(async_w.stop)

        d_idle = build_live_step_result(async_w, static_f, now=1.0, frame_seq=1, run_vision=True, scheduler=svc.scheduler, camera_id="cam_02", mode="focus_only", is_focused=False, is_armed=True)
        self.assertEqual(getattr(d_idle, "priority_tier", None), "P1")
        d_motion = build_live_step_result(async_w, motion_f, now=1.3, frame_seq=2, run_vision=True, scheduler=svc.scheduler, camera_id="cam_02", mode="focus_only", is_focused=False, is_armed=True)
        self.assertTrue(getattr(d_motion, "motion_active", False))
        # Wait briefly for async step to complete and promote alarm
        for _ in range(20):
            if svc.scheduler.get_camera_summary("cam_02")["priority_tier"] == "P0":
                break
            threading.Event().wait(0.05)
        self.assertEqual(svc.scheduler.get_camera_summary("cam_02")["priority_tier"], "P0")

    def test_telemetry_and_camera_status_row_expose_armed_and_scheduler_fields(self) -> None:
        """build_stream_telemetry and build_camera_status_row expose scheduler and armed fields."""
        svc = ProcessingModeService()
        mgr = SimpleNamespace(
            camera_id="cam_01", is_armed=True, is_running=True, _processing_mode_service=svc,
            homography=None, overlays={}, analytics=None, event_bus=None,
            video_source=SimpleNamespace(width=640, height=360, is_synthetic=True),
            get_latest_telemetry=lambda: {"fps": 12.0, "active_tracks": []},
        )
        step_res = FrameStepResult(frame=np.zeros((360, 640, 3), dtype=np.uint8), timestamp=1.0)
        setattr(step_res, "priority_tier", "P1")
        setattr(step_res, "target_fps", 8.0)
        setattr(step_res, "motion_active", True)
        setattr(step_res, "load_shed_stage", "normal")
        setattr(step_res, "replay_active", False)
        telem = build_stream_telemetry(mgr, {}, 1.0, 12.0, (360, 640, 3), 1, step_res=step_res)
        self.assertEqual(telem["priority_tier"], "P1")
        self.assertTrue(telem["motion_active"])
        row = build_camera_status_row("cam_01", {"armed": True}, mgr)
        self.assertTrue(row["armed"])

    def test_real_clock_worker_step_prunes_fps_window_and_bounds_alarm_hold(self) -> None:
        """Unmocked build_worker_step_result + ProcessingModeService.get_state share monotonic clock."""
        svc = ProcessingModeService(mode="focus_only", focused_camera_id="cam_01", active_tab="live")
        svc.scheduler.record_inference_start("cam_02", now=time.monotonic() - 3.0)
        svc.scheduler.record_inference_end("cam_02", latency_ms=15.0)
        mgr = SimpleNamespace(
            camera_id="cam_02", is_armed=True, is_running=True, _is_hibernating=False,
            is_recording=False, subscriber_count=1, _processing_mode_service=svc,
        )
        pool = SimpleNamespace(streams={"cam_02": mgr})
        proc = SimpleNamespace(
            step=lambda f, timestamp, max_dim=1280: FrameStepResult(
                frame=f, tracks={1: SimpleNamespace(id=1, centroid=(10, 10))}, timestamp=timestamp
            )
        )
        async_w = AsyncInferenceWorker(proc, scheduler=svc.scheduler, camera_id="cam_02", is_armed=True)
        async_w.start()
        self.addCleanup(async_w.stop)

        frame = np.full((72, 128, 3), 180, dtype=np.uint8)
        build_worker_step_result(mgr, async_w, frame, frame_seq=1, run_vision=True, is_rec=False)
        for _ in range(30):
            if async_w.get_latest_result() is not None:
                break
            threading.Event().wait(0.02)

        state = svc.get_state(pool)
        cam_state = state["camera_states"]["cam_02"]
        self.assertEqual(cam_state["priority_tier"], "P0")
        self.assertGreater(cam_state["alarm_hold_s"], 0.0)
        self.assertLessEqual(cam_state["alarm_hold_s"], 15.0)
        self.assertEqual(len(svc.scheduler._inference_timestamps), 1)
        future_summary = svc.scheduler.get_summary(now=time.monotonic() + 2.5)
        self.assertEqual(future_summary["rolling_fps"], 0.0)
        self.assertEqual(len(svc.scheduler._inference_timestamps), 0)


if __name__ == "__main__":
    unittest.main()
