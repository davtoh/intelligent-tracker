"""Milestone 2 tests: StreamWorker & StreamPoolCoordinator hibernation and AI gating."""

import os
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np

from dashboard.services.processing_mode_service import ProcessingModeService
from dashboard.services.stream_pool_coordinator import StreamPoolCoordinator
from dashboard.services.stream_worker import StreamWorker
from dashboard.stream_manager import StreamManager
from intelligent_tracker.world import WorldGraph


def _make_fake_vs(frame: np.ndarray | None = None) -> MagicMock:
    """Create a mock VideoSource supporting context-manager, pause, resume, and read."""
    vs = MagicMock()
    vs.__enter__ = MagicMock(return_value=vs)
    vs.__exit__ = MagicMock(return_value=False)
    if frame is not None:
        vs.read.return_value = (True, frame)
    else:
        vs.read.return_value = (False, None)
    return vs


def _make_worker_host(
    camera_id: str = "cam_01",
    subscriber_count: int = 0,
    is_recording: bool = False,
    svc: ProcessingModeService | None = None,
    in_pool: bool = True,
) -> SimpleNamespace:
    """Create a lightweight StreamManager stand-in for StreamWorker tests."""
    host = SimpleNamespace(
        camera_id=camera_id, name=f"Camera {camera_id}", width=160, height=120,
        subscriber_count=subscriber_count, is_recording=is_recording,
        has_raw_subscribers=False, has_annotated_subscribers=False,
        _is_hibernating=False, _running=True, _stop_event=threading.Event(),
        _lock=threading.RLock(), _latest_raw_frame=None,
        _latest_raw_jpeg=b"raw", _latest_jpeg=b"ann",
        _latest_telemetry={"camera_id": camera_id, "status": "online", "fps": 10.0},
        _recording_controller=None, _overlay_renderer=MagicMock(),
        _broadcast_telemetry=MagicMock(), overlays={}, start_time=0.0,
        analytics=None, rsac_manager=None, homography=None, draw_heatmap=False,
        topology=None, video_source=_make_fake_vs(), db=None, detector=None,
        tracker=None, reid_extractor=None, gallery_matcher=None,
        active_learning=None, enrollment_manager=None, event_bus=None,
        event_pipeline=None, world_graph=None, world_bridge=None,
        world_rule_engine=None, confidence_engine=None,
    )
    if svc is not None:
        host._processing_mode_service = svc
        host._in_camera_pool = in_pool
    return host


class TestStreamWorkerHibernationAndGating(unittest.TestCase):
    """Verify StreamWorker hibernation and vision-step gating across all modes."""

    def test_legacy_host_without_service_uses_subscriber_hibernation(self) -> None:
        host = _make_worker_host(subscriber_count=0, is_recording=False, svc=None)
        worker = StreamWorker(host)
        self.assertFalse(worker._should_hibernate(False, frame_count=0))
        self.assertTrue(worker._should_hibernate(False, frame_count=1))
        self.assertFalse(worker._should_hibernate(True, frame_count=1))
        self.assertTrue(worker._should_run_vision_step(False))

    def test_focus_only_hibernates_unfocused_and_respects_recording(self) -> None:
        svc = ProcessingModeService(mode="focus_only", focused_camera_id="cam_01", active_tab="live")
        cam2 = _make_worker_host(camera_id="cam_02", subscriber_count=1, svc=svc, in_pool=True)
        w2 = StreamWorker(cam2)
        self.assertTrue(w2._should_hibernate(False, frame_count=0))
        self.assertFalse(w2._should_hibernate(True, frame_count=0))
        self.assertFalse(w2._should_run_vision_step(False))
        self.assertTrue(w2._should_run_vision_step(True))

    def test_full_realtime_never_hibernates_in_pool_and_runs_vision_on_any_tab(self) -> None:
        svc = ProcessingModeService(mode="full_realtime", focused_camera_id="cam_01", active_tab="videos")
        host = _make_worker_host(camera_id="cam_02", subscriber_count=0, svc=svc, in_pool=True)
        worker = StreamWorker(host)
        self.assertFalse(worker._should_hibernate(False, frame_count=5))
        self.assertTrue(worker._should_run_vision_step(False))

    def test_capture_only_and_paused_skip_vision_step_and_handle_hibernation(self) -> None:
        svc = ProcessingModeService(mode="capture_only", focused_camera_id="cam_01", active_tab="live")
        host = _make_worker_host(camera_id="cam_01", subscriber_count=0, svc=svc, in_pool=True)
        worker = StreamWorker(host)
        self.assertFalse(worker._should_run_vision_step(True))
        self.assertTrue(worker._should_hibernate(False, frame_count=1))
        self.assertFalse(worker._should_hibernate(True, frame_count=1))

        svc.update(mode="paused")
        self.assertTrue(worker._should_hibernate(False, frame_count=0))
        self.assertFalse(worker._should_run_vision_step(True))

    def test_tab_gating_pauses_vision_step_in_focus_only_unless_recording(self) -> None:
        svc = ProcessingModeService(mode="focus_only", focused_camera_id="cam_01", active_tab="videos")
        host = _make_worker_host(camera_id="cam_01", subscriber_count=1, svc=svc, in_pool=True)
        worker = StreamWorker(host)
        self.assertFalse(worker._should_run_vision_step(False))
        self.assertTrue(worker._should_run_vision_step(True))
        svc.update(active_tab="live")
        self.assertTrue(worker._should_run_vision_step(False))

    def test_handle_hibernation_pauses_and_resumes_video_source(self) -> None:
        svc = ProcessingModeService(mode="paused")
        host = _make_worker_host(camera_id="cam_01", svc=svc)
        host._stop_event.set()
        worker = StreamWorker(host)
        self.assertTrue(worker._handle_hibernation(host.video_source, frame_count=0))
        self.assertTrue(host._is_hibernating)
        self.assertEqual(host._latest_telemetry["status"], "hibernating")
        host.video_source.pause.assert_called_once()

        svc.update(mode="full_realtime")
        self.assertFalse(worker._handle_hibernation(host.video_source, frame_count=0))
        self.assertFalse(host._is_hibernating)
        self.assertEqual(host._latest_telemetry["status"], "online")
        host.video_source.resume.assert_called_once()

    def test_run_skips_processor_step_in_capture_only_and_executes_in_full_realtime(self) -> None:
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        svc = ProcessingModeService(mode="capture_only")
        host = _make_worker_host(camera_id="cam_01", subscriber_count=1, svc=svc)
        host.video_source = _make_fake_vs(frame=frame)
        worker = StreamWorker(host)
        mock_proc = MagicMock(frame_count=0)
        worker._get_processor = MagicMock(return_value=mock_proc)
        worker._process_single_frame = MagicMock(side_effect=lambda _: host._stop_event.set())
        worker.run()
        mock_proc.step.assert_not_called()
        worker._process_single_frame.assert_called_once()

        svc.update(mode="full_realtime")
        host._stop_event.clear()
        worker._process_single_frame = MagicMock(side_effect=lambda _: host._stop_event.set())
        worker.run()
        mock_proc.step.assert_called_once()


class TestCoordinatorAndManagerModeSync(unittest.TestCase):
    """Verify StreamPoolCoordinator and StreamManager processing mode integration."""

    def test_coordinator_attaches_service_and_syncs_hibernation_states(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        svc = ProcessingModeService(mode="focus_only", focused_camera_id="cam_01", active_tab="live")
        wg = WorldGraph()
        coord = StreamPoolCoordinator(
            db_path=os.path.join(tmpdir.name, "test.db"),
            base_config_path="configs/demo.yaml",
            world_graph=wg,
            processing_mode_service=svc,
        )
        self.addCleanup(coord.stop_all)
        m1 = coord.create_and_register_stream("cam_01", {"source": "synthetic", "detector": "mock"}, start=False)
        m2 = coord.register_camera_stream("cam_02", {"source": "synthetic"}, enabled=False, autostart=False)
        self.assertIs(m1._processing_mode_service, svc)
        self.assertIs(m2._processing_mode_service, svc)
        self.assertTrue(m1._in_camera_pool)
        self.assertTrue(m2._in_camera_pool)

        m2._running = True
        coord.sync_processing_mode(svc)
        self.assertTrue(m2._is_hibernating)
        svc.update(mode="full_realtime")
        coord.sync_processing_mode(svc)
        self.assertFalse(m2._is_hibernating)

    def test_stream_manager_start_recording_wakes_hibernating_stream(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        svc = ProcessingModeService(mode="focus_only", focused_camera_id="cam_01")
        mgr = StreamManager(
            config_path="configs/demo.yaml",
            db_path=os.path.join(tmpdir.name, "mgr.db"),
            camera_id="cam_02",
            source_override="synthetic",
            custom_cfg={"detector": {"model": "mock"}, "recording": {"output_dir": tmpdir.name}},
            processing_mode_service=svc,
        )
        self.addCleanup(mgr.stop)
        mgr._is_hibernating = True
        mgr._latest_telemetry["status"] = "hibernating"
        res = mgr.start_recording(filename="wake_test.mp4")
        self.assertTrue(res["is_recording"])
        self.assertFalse(mgr._is_hibernating)
        self.assertEqual(mgr._latest_telemetry["status"], "online")
        mgr.stop_recording()


if __name__ == "__main__":
    unittest.main()
