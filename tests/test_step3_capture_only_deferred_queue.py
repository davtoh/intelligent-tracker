"""End-to-end unit and API tests for Step 3 Milestone 3: Capture-Only & Deferred Queue."""

import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
import numpy as np

from dashboard import app as app_module
from dashboard.dependencies import get_camera_pool, get_stream_manager
from dashboard.services.processing_mode_service import ProcessingModeService
from dashboard.services.stream_recording import StreamRecordingController
from dashboard.services.stream_worker import StreamWorker
from dashboard.stream_manager import StreamManager


class _FakeWriter:
    """In-memory PipelineVideoWriter test double recording written frames."""

    def __init__(self, path, fps=20.0, resolution=(64, 48), max_frames=None, max_duration_s=None):
        self.path = path
        self.fps = fps
        self.resolution = resolution
        self.frames = []
        self.is_open = True

    def write(self, frame):
        self.frames.append(frame.copy())
        return True

    def release(self):
        self.is_open = False

    def snapshot(self):
        w, h = self.resolution
        return {
            "codec": "mp4v",
            "width": w,
            "height": h,
            "frames_written": len(self.frames),
            "elapsed_s": round(len(self.frames) / max(1.0, self.fps), 3),
            "size_bytes": len(self.frames) * 100,
        }


class _FakeVideoSource:
    """Lightweight synthetic VideoSource yielding N frames then stopping."""

    def __init__(self, manager_ref, count=3):
        self._mgr = manager_ref
        self._remaining = count
        self.width = 64
        self.height = 48
        self.fps = 10.0
        self.paused = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, timeout=1.0):
        if self._remaining <= 0:
            self._mgr._running = False
            self._mgr._stop_event.set()
            return False, None
        self._remaining -= 1
        return True, np.zeros((48, 64, 3), dtype=np.uint8)

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def release(self):
        pass


class TestCaptureOnlyRecordingController(unittest.TestCase):
    """Unit tests for StreamRecordingController capture_only and deferred indexing."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

    def test_capture_only_writes_raw_skips_live_run_and_enqueues_deferred(self):
        svc = ProcessingModeService(mode="capture_only")
        svc.enqueue_deferred_indexing = MagicMock(return_value={"job_id": "job_def_1"})
        db_mock = MagicMock()
        ctrl = StreamRecordingController(
            "cam_01", output_dir=self._tmpdir.name, writer_factory=_FakeWriter,
            db_getter=lambda: db_mock, mode_service_getter=lambda: svc,
        )
        started = ctrl.start(filename="cap.mp4", fps=10.0, resolution=(64, 48), annotated=True)
        self.assertFalse(started["annotated"])
        self.assertEqual(started["processing_mode"], "capture_only")
        raw = np.zeros((48, 64, 3), dtype=np.uint8)
        ann = np.full((48, 64, 3), 255, dtype=np.uint8)
        step_res = SimpleNamespace(timestamp=1.0, tracks={}, detections=[1], identifications=[], frame=raw)
        self.assertTrue(ctrl.write_frame(raw, ann, step_res=step_res))
        self.assertEqual(int(ctrl._writer.frames[0].sum()), 0)
        self.assertEqual(ctrl._recorded_frames, [])
        stopped = ctrl.stop()
        self.assertFalse(stopped["annotated"])
        self.assertEqual(stopped["processing_mode"], "capture_only")
        self.assertEqual(stopped["deferred_job_id"], "job_def_1")
        self.assertIsNone(stopped.get("report_run_id"))
        svc.enqueue_deferred_indexing.assert_called_once()

    def test_switching_to_capture_only_before_stop_still_enqueues_deferred(self):
        svc = ProcessingModeService(mode="focus_only")
        svc.enqueue_deferred_indexing = MagicMock(return_value={"job_id": "job_def_2"})
        ctrl = StreamRecordingController(
            "cam_01", output_dir=self._tmpdir.name, writer_factory=_FakeWriter,
            mode_service_getter=lambda: svc,
        )
        ctrl.start(filename="switch.mp4", fps=10.0, resolution=(64, 48))
        svc.update(mode="capture_only")
        ctrl.write_frame(np.zeros((48, 64, 3), dtype=np.uint8))
        stopped = ctrl.stop()
        self.assertFalse(stopped["annotated"])
        self.assertEqual(stopped["processing_mode"], "capture_only")
        self.assertEqual(stopped["deferred_job_id"], "job_def_2")

    def test_focus_only_does_not_enqueue_deferred_and_enqueue_error_is_safe(self):
        svc = ProcessingModeService(mode="focus_only")
        svc.enqueue_deferred_indexing = MagicMock(side_effect=RuntimeError("queue down"))
        ctrl = StreamRecordingController(
            "cam_01", output_dir=self._tmpdir.name, writer_factory=_FakeWriter,
            mode_service_getter=lambda: svc,
        )
        ctrl.start(filename="focus.mp4", fps=10.0, resolution=(64, 48))
        stopped = ctrl.stop()
        self.assertEqual(stopped["processing_mode"], "focus_only")
        self.assertIsNone(stopped.get("deferred_job_id"))
        svc.enqueue_deferred_indexing.assert_not_called()

        svc.update(mode="capture_only")
        ctrl.start(filename="err.mp4", fps=10.0, resolution=(64, 48))
        safe_stop = ctrl.stop()
        self.assertEqual(safe_stop["status"], "stopped")
        self.assertIsNone(safe_stop.get("deferred_job_id"))


class TestCaptureOnlyEndToEndIntegration(unittest.TestCase):
    """Integration tests for StreamWorker + StreamManager + FastAPI record/stop."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

    def _make_stream_manager(self, svc: ProcessingModeService) -> StreamManager:
        db_path = os.path.join(self._tmpdir.name, "test.db")
        cfg = {"detector": {"type": "mock"}, "recording": {"output_dir": self._tmpdir.name}}
        sm = StreamManager(
            db_path=db_path, camera_id="cam_01", custom_cfg=cfg, processing_mode_service=svc,
        )
        self.addCleanup(sm.stop)
        sm._recording_controller = StreamRecordingController(
            "cam_01", output_dir=self._tmpdir.name, writer_factory=_FakeWriter,
            db_getter=lambda: sm.db, mode_service_getter=lambda: sm._processing_mode_service,
        )
        sm.video_source = _FakeVideoSource(sm, count=2)
        return sm

    def test_stream_worker_capture_only_skips_ai_step_and_enqueues_on_stop(self):
        svc = ProcessingModeService(mode="capture_only")
        svc.enqueue_deferred_indexing = MagicMock(return_value={"job_id": "job_worker_1"})
        sm = self._make_stream_manager(svc)
        worker = StreamWorker(sm)
        mock_proc = MagicMock()
        worker._get_processor = lambda: mock_proc
        mock_proc.frame_count = 0
        sm.start_recording(filename="worker_cap.mp4", fps=10.0, resolution=(64, 48))
        sm._running = True
        worker.run()
        mock_proc.step.assert_not_called()
        stopped = sm.stop_recording()
        self.assertFalse(stopped["annotated"])
        self.assertEqual(stopped["frames_written"], 2)
        self.assertEqual(stopped["deferred_job_id"], "job_worker_1")

    def test_api_capture_only_record_start_and_stop_returns_deferred_job_id(self):
        svc = ProcessingModeService(mode="focus_only")
        sm = self._make_stream_manager(svc)
        pool = SimpleNamespace(camera_configs={"cam_01": {}}, streams={"cam_01": sm}, get_stream=lambda cid: sm)
        app_module.app.dependency_overrides[get_camera_pool] = lambda: pool
        app_module.app.dependency_overrides[get_stream_manager] = lambda: sm
        self.addCleanup(app_module.app.dependency_overrides.clear)
        fake_job = SimpleNamespace(job_id="job_api_99", status="queued")
        with (
            patch("dashboard.routers.processing_mode.get_processing_mode_service", return_value=svc),
            patch("dashboard.services.processing_mode_service.submit_async_analytics_job", return_value=fake_job),
            patch("dashboard.services.processing_mode_service.get_video_job_manager", return_value=MagicMock()),
        ):
            client = TestClient(app_module.app)
            self.assertEqual(client.post("/api/system/processing-mode", json={"mode": "capture_only"}).status_code, 200)
            r_start = client.post("/api/cameras/cam_01/record/start", json={"filename": "api_cap.mp4"})
            self.assertEqual(r_start.status_code, 200)
            sm._recording_controller.write_frame(np.zeros((48, 64, 3), dtype=np.uint8))
            r_stop = client.post("/api/cameras/cam_01/record/stop")
            self.assertEqual(r_stop.status_code, 200)
            body = r_stop.json()
            self.assertFalse(body["annotated"])
            self.assertEqual(body["processing_mode"], "capture_only")
            self.assertEqual(body["deferred_job_id"], "job_api_99")
            self.assertIsNone(body.get("report_run_id"))
            self.assertEqual(len(svc.get_state()["deferred_jobs"]), 1)
