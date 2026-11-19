#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit tests for MotionGate, AnalyticsScheduler, dt-aware trackers, and armed P1 mode."""

import time
import unittest

import numpy as np

from dashboard.services.processing_mode_service import ProcessingModeService
from intelligent_tracker.detectors.base import Detection
from intelligent_tracker.pipeline.analytics_scheduler import (
    AnalyticsScheduler,
    LoadShedStage,
    PriorityTier,
)
from intelligent_tracker.pipeline.motion_gate import MotionGate
from intelligent_tracker.tracker.centroid import CentroidTracker
from intelligent_tracker.tracker.sort import SortTracker


class _FakeIdleHook:
    def __init__(self) -> None:
        self.calls: list[tuple[float, float]] = []

    def run_idle_refinement(self, budget_utilization: float, now: float) -> None:
        self.calls.append((budget_utilization, now))


class TestMotionGateAndScheduler(unittest.TestCase):
    """Verify MotionGate speed/triggering and AnalyticsScheduler P0/P1/P2 + shedding."""

    def test_motion_gate_speed_and_first_trigger(self) -> None:
        gate = MotionGate(pixel_delta_threshold=15, changed_ratio_threshold=0.01, hold_seconds=3.0)
        bg = np.zeros((480, 640, 3), dtype=np.uint8)
        fg = bg.copy()
        fg[100:220, 150:270] = 220

        s0 = gate.evaluate("cam_a", bg, now=0.0)
        self.assertFalse(s0.motion_active)

        t0 = time.perf_counter()
        s1 = gate.evaluate("cam_a", fg, now=1.0)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.assertTrue(s1.motion_active)
        self.assertTrue(s1.first_trigger)
        self.assertLess(elapsed_ms, 5.0)

        s2 = gate.evaluate("cam_a", bg, now=2.0)
        self.assertTrue(s2.motion_active)
        self.assertFalse(s2.first_trigger)
        self.assertFalse(gate.is_motion_active("cam_a", now=5.5))

    def test_p0_p1_p2_cadence_across_modes(self) -> None:
        sched = AnalyticsScheduler()
        static_frame = np.zeros((108, 192, 3), dtype=np.uint8)

        d_p0 = sched.should_schedule_frame("cam_1", static_frame, now=1.0, mode="focus_only", is_focused=True)
        self.assertEqual(d_p0.priority_tier, PriorityTier.P0)
        self.assertEqual(d_p0.target_fps, 15.0)

        d_p1 = sched.should_schedule_frame("cam_2", static_frame, now=1.0, mode="focus_only", is_armed=True)
        self.assertEqual(d_p1.priority_tier, PriorityTier.P1)
        self.assertEqual(d_p1.target_fps, 1.0)

        d_p2_focus = sched.should_schedule_frame("cam_3", static_frame, now=1.0, mode="focus_only")
        self.assertFalse(d_p2_focus.should_run)
        self.assertEqual(d_p2_focus.target_fps, 0.0)

        d_p2_rt = sched.should_schedule_frame("cam_3", static_frame, now=1.0, mode="full_realtime")
        self.assertTrue(d_p2_rt.should_run)
        self.assertEqual(d_p2_rt.priority_tier, PriorityTier.P2)
        self.assertEqual(d_p2_rt.target_fps, 1.0)

    def test_p1_first_motion_sla_and_15s_alarm_promotion(self) -> None:
        sched = AnalyticsScheduler()
        bg = np.zeros((108, 192, 3), dtype=np.uint8)
        fg = bg.copy()
        fg[20:70, 40:100] = 240

        d0 = sched.should_schedule_frame("cam_2", bg, now=10.0, mode="focus_only", is_armed=True)
        self.assertTrue(d0.should_run)

        d_motion = sched.should_schedule_frame("cam_2", fg, now=10.2, mode="focus_only", is_armed=True)
        self.assertTrue(d_motion.first_motion_trigger)
        self.assertTrue(d_motion.should_run)
        self.assertEqual(d_motion.target_fps, 8.0)

        rem = sched.promote_alarm("cam_2", duration_s=15.0, now=10.2)
        self.assertAlmostEqual(rem, 15.0, places=2)
        d_p0 = sched.should_schedule_frame("cam_2", bg, now=15.0, mode="focus_only", is_armed=True)
        self.assertEqual(d_p0.priority_tier, PriorityTier.P0)

    def test_three_stage_load_shedding_protects_p1_floor(self) -> None:
        deferred: list[tuple[str, str]] = []
        sched = AnalyticsScheduler(
            max_concurrent_inferences=4,
            deferred_indexing_cb=lambda cid, reason: deferred.append((cid, reason)),
        )
        bg = np.zeros((108, 192, 3), dtype=np.uint8)
        fg = bg.copy()
        fg[10:60, 20:80] = 230
        sched.should_schedule_frame("cam_armed", bg, now=1.0, mode="focus_only", is_armed=True)

        sched.record_inference_start("cam_1", now=1.1)
        sched.record_inference_end("cam_1", latency_ms=140.0, now=1.2)
        d_elev_p2 = sched.should_schedule_frame("cam_bg", bg, now=1.3, mode="full_realtime")
        self.assertEqual(d_elev_p2.load_shed_stage, LoadShedStage.ELEVATED)
        self.assertFalse(d_elev_p2.should_run)

        d_elev_p1 = sched.should_schedule_frame("cam_armed", fg, now=2.1, mode="focus_only", is_armed=True)
        self.assertEqual(d_elev_p1.target_fps, 4.0)

        for _ in range(8):
            sched.record_inference_start("cam_1", now=2.2)
            sched.record_inference_end("cam_1", latency_ms=320.0, now=2.3)

        d_crit_p0 = sched.should_schedule_frame("cam_1", bg, now=2.4, mode="focus_only", is_focused=True)
        self.assertEqual(d_crit_p0.load_shed_stage, LoadShedStage.CRITICAL)
        self.assertEqual(d_crit_p0.target_fps, 8.0)

        d_crit_p1 = sched.should_schedule_frame("cam_armed", fg, now=3.5, mode="focus_only", is_armed=True)
        self.assertGreaterEqual(d_crit_p1.target_fps, 1.0)
        self.assertTrue(len(deferred) >= 1)

    def test_idle_refinement_hook_under_spare_budget(self) -> None:
        hook = _FakeIdleHook()
        sched = AnalyticsScheduler(global_fps_budget=30.0, idle_refinement_hook=hook)
        self.assertTrue(sched.maybe_run_idle_refinement(now=5.0))
        self.assertEqual(len(hook.calls), 1)

        sched.record_inference_start("cam_1", now=6.0)
        sched.record_inference_end("cam_1", latency_ms=180.0, now=6.1)
        self.assertFalse(sched.maybe_run_idle_refinement(now=6.2))


class TestTimeSlicedTrackersAndModeService(unittest.TestCase):
    """Verify dt-aware SortTracker/CentroidTracker and ProcessingModeService armed P1."""

    def test_sort_tracker_dt_persistence_and_time_sliced_emit(self) -> None:
        sort = SortTracker(max_age=1, min_hits=3, iou_threshold=0.2, max_age_seconds=2.5)
        det = [Detection(bbox=(50, 50, 40, 60), class_id=0, confidence=0.9, label="person")]
        t0 = sort.update(det, timestamp=0.0, confirmed_only=True)
        self.assertEqual(len(t0), 0)

        t1 = sort.update(det, timestamp=1.0, confirmed_only=True)
        self.assertEqual(len(t1), 1)
        tid = next(iter(t1))

        sort.update([], timestamp=2.0, confirmed_only=True)
        self.assertEqual(len(sort.trackers), 1)
        t3 = sort.update(det, timestamp=3.0, confirmed_only=True)
        self.assertIn(tid, t3)

        sort.update([], timestamp=6.0, confirmed_only=True)
        self.assertEqual(len(sort.trackers), 0)

    def test_centroid_tracker_dt_persistence_and_time_sliced_emit(self) -> None:
        tracker = CentroidTracker(max_disappeared=1, min_hits=3, max_age_seconds=2.5)
        det = [Detection(bbox=(100, 100, 40, 60), class_id=0, confidence=0.9, label="person")]
        tracker.update(det, timestamp=0.0, confirmed_only=True)

        t1 = tracker.update(det, timestamp=1.0, confirmed_only=True)
        self.assertEqual(len(t1), 1)
        tid = next(iter(t1))

        tracker.update([], timestamp=2.0, confirmed_only=True)
        self.assertIn(tid, tracker.tracks)
        tracker.update([], timestamp=4.6, confirmed_only=True)
        self.assertNotIn(tid, tracker.tracks)

    def test_processing_mode_service_armed_p1_and_state_summary(self) -> None:
        svc = ProcessingModeService(mode="focus_only", focused_camera_id="cam_01", active_tab="analytics")
        self.assertFalse(svc.should_run_vision_step("cam_02", is_recording=False, is_armed=False))
        self.assertTrue(svc.should_run_vision_step("cam_02", is_recording=False, is_armed=True))

        state = svc.get_state()
        self.assertIn("scheduler", state)
        self.assertEqual(state["scheduler"]["load_shed_stage"], "NORMAL")


if __name__ == "__main__":
    unittest.main()
