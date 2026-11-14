"""Unit and FastAPI integration tests for PipelineVideoWriter and live stream recording."""

import os
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
from fastapi.testclient import TestClient
import numpy as np

from dashboard.app import app
from dashboard.dependencies import get_camera_pool, get_stream_manager
from dashboard.services.stream_recording import StreamRecordingController, sanitize_recording_filename
from dashboard.stream_manager import StreamManager
from intelligent_tracker.pipeline import PipelineConfig, PipelineEngine, build_writer
from intelligent_tracker.video import PipelineVideoWriter


class _FakePool:
    """Minimal CameraPool stub mapping camera IDs to StreamManager instances."""

    def __init__(self, streams: dict[str, StreamManager]) -> None:
        self.streams = streams
        self.camera_configs = {cid: {"id": cid} for cid in streams}
        self.primary_stream = next(iter(streams.values()), None)

    def get_stream(self, camera_id: str) -> StreamManager | None:
        return self.streams.get(camera_id)


def _make_isolated_stream(tmpdir: str, camera_id: str = "cam_01") -> StreamManager:
    """Create a synthetic mock-detector StreamManager completely isolated in tmpdir."""
    cfg_path = os.path.join(tmpdir, "missing_config.yaml")
    db_path = os.path.join(tmpdir, f"{camera_id}.db")
    rec_dir = os.path.join(tmpdir, "videos")
    return StreamManager(
        config_path=cfg_path,
        db_path=db_path,
        camera_id=camera_id,
        source_override="synthetic",
        custom_cfg={
            "detector": {"type": "mock"},
            "tracker": {"type": "centroid"},
            "reid": {"model": "none"},
            "video": {"width": 320, "height": 240, "framerate": 20},
            "recording": {"output_dir": rec_dir},
        },
    )


def _wait_until(predicate, timeout: float = 4.0) -> bool:
    """Poll predicate briefly until True or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return bool(predicate())


class TestPipelineVideoWriter(unittest.TestCase):
    """Tests for shared PipelineVideoWriter and PipelineEngine/bundle factories."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

    def test_write_resize_grayscale_and_max_frames_bound(self) -> None:
        """PipelineVideoWriter resizes mismatched frames, handles grayscale, and stops at max_frames."""
        out_path = os.path.join(self.tmpdir.name, "nested", "clip.mp4")
        writer = PipelineVideoWriter(out_path, fps=15.0, resolution=(320, 240), max_frames=4)
        self.addCleanup(writer.release)

        bgr_big = np.full((480, 640, 3), 120, dtype=np.uint8)
        gray = np.full((120, 160), 80, dtype=np.uint8)
        self.assertTrue(writer.write(bgr_big))
        self.assertTrue(writer.write(gray))
        self.assertTrue(writer.write(bgr_big))
        self.assertTrue(writer.write(bgr_big))
        self.assertFalse(writer.is_open)
        self.assertFalse(writer.write(bgr_big))

        writer.release()  # idempotent second release
        snap = writer.snapshot()
        self.assertEqual(snap["frames_written"], 4)
        self.assertFalse(snap["is_open"])
        self.assertTrue(os.path.exists(out_path))
        self.assertGreater(snap["size_bytes"], 0)

        cap = cv2.VideoCapture(out_path)
        self.addCleanup(cap.release)
        self.assertTrue(cap.isOpened())
        self.assertEqual(int(cap.get(cv2.CAP_PROP_FRAME_COUNT)), 4)

    def test_codec_fallback_and_validation_errors(self) -> None:
        """Writer falls back across codecs and validates positive parameters."""
        with self.assertRaises(ValueError):
            PipelineVideoWriter(os.path.join(self.tmpdir.name, "bad.mp4"), fps=0.0)
        with self.assertRaises(ValueError):
            PipelineVideoWriter(os.path.join(self.tmpdir.name, "bad.mp4"), resolution=(0, 240))
        with self.assertRaises(ValueError):
            PipelineVideoWriter(os.path.join(self.tmpdir.name, "bad.mp4"), max_frames=0)

        out_path = os.path.join(self.tmpdir.name, "fallback.mp4")
        opened_codecs: list[str] = []

        class _FakeCvWriter:
            def __init__(self, ok: bool) -> None:
                self._ok = ok

            def isOpened(self) -> bool:
                return self._ok

            def write(self, _frame) -> None:
                pass

            def release(self) -> None:
                pass

        def _fake_cv_factory(_path, fourcc, _fps, _size):
            code = "".join(chr((fourcc >> (8 * i)) & 0xFF) for i in range(4))
            opened_codecs.append(code)
            return _FakeCvWriter(ok=(code == "avc1"))

        with patch("intelligent_tracker.video.writers.cv2.VideoWriter", side_effect=_fake_cv_factory):
            writer = PipelineVideoWriter(out_path, codecs=("mp4v", "avc1", "XVID"))
            self.assertEqual(writer.codec, "avc1")
            self.assertEqual(opened_codecs, ["mp4v", "avc1"])
            writer.release()

    def test_bundle_and_engine_create_writer(self) -> None:
        """build_writer and PipelineEngine.create_writer delegate to PipelineVideoWriter."""
        self.assertIsNone(build_writer(PipelineConfig(output_path=None)))
        self.assertIsNone(PipelineEngine.create_writer(None))

        out_a = os.path.join(self.tmpdir.name, "bundle_out.mp4")
        w_a = build_writer(PipelineConfig(output_path=out_a, resolution=(160, 120), framerate=10))
        self.addCleanup(w_a.release)
        self.assertIsInstance(w_a, PipelineVideoWriter)

        out_b = os.path.join(self.tmpdir.name, "engine_out.mp4")
        w_b = PipelineEngine.create_writer(out_b, fps=12.0, resolution=(160, 120), max_frames=2)
        self.addCleanup(w_b.release)
        self.assertIsInstance(w_b, PipelineVideoWriter)
        self.assertEqual(w_b.max_frames, 2)


class TestStreamRecordingControllerAndWorker(unittest.TestCase):
    """Tests for StreamRecordingController, StreamManager, and hibernation prevention."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)

    def test_controller_filename_sanitization_and_lifecycle(self) -> None:
        """Controller validates filenames, records raw/annotated frames, and guards double start/stop."""
        self.assertEqual(sanitize_recording_filename("cam 01", "demo_clip"), "demo_clip.mp4")
        for bad in ("", "   ", "../evil.mp4", "sub/clip.mp4", "bad\\clip.mp4", "bad name?.mp4"):
            with self.assertRaises(ValueError):
                sanitize_recording_filename("cam_01", bad)

        ctrl = StreamRecordingController("cam_01", output_dir=self.tmpdir.name)
        self.assertEqual(ctrl.status()["status"], "idle")
        with self.assertRaises(RuntimeError):
            ctrl.stop()

        started = ctrl.start(filename="raw_capture.mp4", fps=10.0, resolution=(160, 120), annotated=False)
        self.assertTrue(started["is_recording"])
        with self.assertRaises(RuntimeError):
            ctrl.start(filename="second.mp4")

        raw = np.zeros((120, 160, 3), dtype=np.uint8)
        ann = np.full((120, 160, 3), 255, dtype=np.uint8)
        self.assertTrue(ctrl.write_frame(raw, ann))
        self.assertTrue(ctrl.write_frame(raw, ann))
        stopped = ctrl.stop()
        self.assertFalse(stopped["is_recording"])
        self.assertEqual(stopped["status"], "stopped")
        self.assertEqual(stopped["frames_written"], 2)
        self.assertGreater(stopped["size_bytes"], 0)

    def test_stream_manager_wakes_hibernating_stream_and_finalizes_on_stop(self) -> None:
        """Recording wakes a hibernating stream, prevents hibernation, and closes MP4 on stop()."""
        mgr = _make_isolated_stream(self.tmpdir.name, "cam_hib")
        self.addCleanup(mgr.stop)
        mgr.start()

        entered_hibernation = _wait_until(lambda: mgr._is_hibernating, timeout=4.0)
        self.assertTrue(entered_hibernation, "Stream did not enter hibernation with 0 subscribers")

        started = mgr.start_recording(filename="wake_test.mp4", annotated=True)
        self.assertTrue(started["is_recording"])
        self.assertFalse(mgr._is_hibernating)

        recorded_enough = _wait_until(
            lambda: mgr.get_recording_status().get("frames_written", 0) >= 3 and not mgr._is_hibernating,
            timeout=4.0,
        )
        self.assertTrue(recorded_enough)
        self.assertTrue(mgr.get_latest_telemetry()["recording"]["is_recording"])

        mgr.stop()
        final_status = mgr.get_recording_status()
        self.assertFalse(final_status["is_recording"])
        self.assertGreaterEqual(final_status["frames_written"], 3)
        self.assertTrue(os.path.exists(final_status["output_path"]))
        self.assertGreater(os.path.getsize(final_status["output_path"]), 0)


class TestCameraRecordingRouter(unittest.TestCase):
    """FastAPI TestClient tests for /api/cameras/{id}/record/* routes."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def test_record_endpoints_via_camera_pool_and_error_branches(self) -> None:
        """Start, status, stop, 404, and 400 branches work against a CameraPool stream."""
        mgr = _make_isolated_stream(self.tmpdir.name, "cam_01")
        self.addCleanup(mgr.stop)
        mgr.start()
        _wait_until(lambda: mgr.get_latest_telemetry().get("frame_count", 0) >= 1)

        pool = _FakePool({"cam_01": mgr})
        app.dependency_overrides[get_camera_pool] = lambda: pool
        app.dependency_overrides[get_stream_manager] = lambda: None

        with patch("dashboard.routers.camera_recording.VIDEOS_DIR", os.path.join(self.tmpdir.name, "videos")):
            self.assertEqual(self.client.get("/api/cameras/unknown/record/status").status_code, 404)
            self.assertEqual(self.client.post("/api/cameras/cam_01/record/stop").status_code, 400)
            self.assertEqual(
                self.client.post("/api/cameras/cam_01/record/start", json={"filename": "../bad.mp4"}).status_code,
                400,
            )

            resp = self.client.post(
                "/api/cameras/cam_01/record/start",
                json={"filename": "api_clip.mp4", "annotated": True},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.json()["is_recording"])
            self.assertEqual(self.client.post("/api/cameras/cam_01/record/start").status_code, 400)

            _wait_until(lambda: self.client.get("/api/cameras/cam_01/record/status").json()["frames_written"] >= 2)
            stopped = self.client.post("/api/cameras/cam_01/record/stop")
            self.assertEqual(stopped.status_code, 200)
            body = stopped.json()
            self.assertFalse(body["is_recording"])
            self.assertGreaterEqual(body["frames_written"], 2)
            self.assertGreater(body["size_bytes"], 0)

    def test_record_endpoints_primary_stream_fallback_when_pool_absent(self) -> None:
        """Endpoints fall back to primary StreamManager when CameraPool is None."""
        mgr = _make_isolated_stream(self.tmpdir.name, "cam_primary")
        self.addCleanup(mgr.stop)
        mgr.start()
        _wait_until(lambda: mgr.get_latest_telemetry().get("frame_count", 0) >= 1)

        app.dependency_overrides[get_camera_pool] = lambda: None
        app.dependency_overrides[get_stream_manager] = lambda: mgr

        with patch("dashboard.routers.camera_recording.VIDEOS_DIR", os.path.join(self.tmpdir.name, "videos")):
            self.assertEqual(self.client.get("/api/cameras/other_cam/record/status").status_code, 404)
            resp = self.client.post("/api/cameras/cam_primary/record/start", json={"max_frames": 3})
            self.assertEqual(resp.status_code, 200)
            done = _wait_until(
                lambda: not self.client.get("/api/cameras/cam_primary/record/status").json()["is_recording"],
                timeout=4.0,
            )
            self.assertTrue(done)
            status_body = self.client.get("/api/cameras/cam_primary/record/status").json()
            self.assertEqual(status_body["status"], "completed")
            self.assertEqual(status_body["frames_written"], 3)


if __name__ == "__main__":
    unittest.main()
