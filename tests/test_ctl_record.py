"""Unit and integration tests for `intelligent-tracker-ctl record` CLI parity."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error

from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.dependencies import get_camera_pool, get_stream_manager
from intelligent_tracker.cli import ctl
from tests.test_camera_recording import _FakePool, _make_isolated_stream, _wait_until


class _FakeHttpResponse:
    """Minimal context-manager adapter wrapping TestClient response bytes."""

    def __init__(self, body_bytes: bytes) -> None:
        self._body = body_bytes

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class TestCtlRecordParity(unittest.TestCase):
    """Verify `intelligent-tracker-ctl record start|stop|status` parity against FastAPI."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def _fake_urlopen(self, req, timeout=8.0):
        path = req.full_url.split("http://dashboard.test", 1)[1]
        headers = {k.lower(): v for k, v in req.header_items()}
        resp = self.client.request(req.get_method(), path, content=req.data, headers=headers)
        if resp.status_code >= 400:
            raise urllib.error.HTTPError(
                req.full_url, resp.status_code, resp.text, hdrs=None, fp=io.BytesIO(resp.content)
            )
        return _FakeHttpResponse(resp.content)

    def test_ctl_record_start_status_and_stop(self) -> None:
        """Start, poll status, and stop MP4 recording via `intelligent-tracker-ctl record`."""
        mgr = _make_isolated_stream(self.tmpdir.name, "cam_01")
        self.addCleanup(mgr.stop)
        mgr.start()
        _wait_until(lambda: mgr.get_latest_telemetry().get("frame_count", 0) >= 1)

        app.dependency_overrides[get_camera_pool] = lambda: _FakePool({"cam_01": mgr})
        app.dependency_overrides[get_stream_manager] = lambda: None

        with (
            patch("dashboard.routers.camera_recording.VIDEOS_DIR", os.path.join(self.tmpdir.name, "videos")),
            patch("urllib.request.urlopen", side_effect=self._fake_urlopen),
        ):
            start_buf = io.StringIO()
            with redirect_stdout(start_buf):
                ctl.main([
                    "record", "start", "cam_01", "--filename", "ctl_clip.mp4",
                    "--raw", "--max-frames", "5", "--url", "http://dashboard.test", "--json",
                ])
            started = json.loads(start_buf.getvalue())
            self.assertTrue(started["is_recording"])
            self.assertFalse(started["annotated"])

            _wait_until(lambda: mgr.get_recording_status()["frames_written"] >= 1)
            status_buf = io.StringIO()
            with redirect_stdout(status_buf):
                ctl.main(["record", "status", "--camera", "cam_01", "--url", "http://dashboard.test"])
            self.assertIn("Recording [cam_01]", status_buf.getvalue())

            stop_buf = io.StringIO()
            with redirect_stdout(stop_buf):
                ctl.main(["record", "stop", "cam_01", "--url", "http://dashboard.test", "--json"])
            self.assertFalse(json.loads(stop_buf.getvalue())["is_recording"])

    def test_ctl_record_error_branches(self) -> None:
        """Missing camera returns exit 1 and missing dashboard URL returns exit 2."""
        app.dependency_overrides[get_camera_pool] = lambda: _FakePool({})
        app.dependency_overrides[get_stream_manager] = lambda: None
        with patch("urllib.request.urlopen", side_effect=self._fake_urlopen):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as bad_cam:
                ctl.main(["record", "status", "missing_cam", "--url", "http://dashboard.test"])
            self.assertEqual(bad_cam.exception.code, 1)

        with patch.dict(os.environ, {"TRACKER_DASHBOARD_URL": "", "APP_URL": ""}, clear=False):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as no_url:
                ctl.main(["record", "status", "cam_01"])
            self.assertEqual(no_url.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
