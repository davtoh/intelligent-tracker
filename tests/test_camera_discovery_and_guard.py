#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for Step 3: Pool-Aware Camera Discovery & Driver Resilience.
"""

import os
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.camera_pool import CameraPool
from dashboard.dependencies import bind_app_state, clear_app_state
from intelligent_tracker.camera_device import CameraDeviceHandler
from intelligent_tracker.discovery import discover_all_cameras, find_physical_cameras
from intelligent_tracker.video.capture_guard import CaptureReadGuard
from intelligent_tracker.video.capture_helpers import compute_reconnect_backoff
from intelligent_tracker.video.source import VideoSource


class TestPoolAwareCameraDiscovery(unittest.TestCase):
    """Tests for pool-aware USB camera discovery without COM contention."""

    @patch.object(CameraDeviceHandler, "get_friendly_name", return_value="Mock Webcam 0")
    @patch.object(CameraDeviceHandler, "probe_device")
    def test_discover_usb_cameras_skips_active_indices(self, mock_probe, _mock_name):
        """Active USB indices must not be re-probed via probe_device()."""
        mock_probe.side_effect = lambda idx: (
            {"index": idx, "name": f"Cam {idx}", "resolution": "640x480", "fps": 30.0}
            if idx == 1
            else None
        )
        cams = CameraDeviceHandler.discover_usb_cameras(max_devices=3, active_indices={0})
        probed = [call.args[0] for call in mock_probe.call_args_list]
        self.assertEqual(probed, [1, 2])
        self.assertEqual([c["index"] for c in cams], [0, 1])
        self.assertTrue(cams[0]["in_use"])
        self.assertEqual(cams[0]["name"], "Mock Webcam 0")

    @patch.object(CameraDeviceHandler, "probe_device", return_value=None)
    def test_discover_usb_cameras_uses_active_devices_metadata(self, mock_probe):
        """Supplied active_devices metadata is preserved for skipped indices."""
        active_meta = {
            0: {
                "name": "Logitech C920",
                "resolution": "1280x720",
                "width": 1280,
                "height": 720,
                "fps": 30.0,
            }
        }
        cams = CameraDeviceHandler.discover_usb_cameras(
            max_devices=2,
            active_indices={0},
            active_devices=active_meta,
        )
        mock_probe.assert_called_once_with(1)
        self.assertEqual(len(cams), 1)
        self.assertEqual(cams[0]["name"], "Logitech C920")
        self.assertEqual(cams[0]["resolution"], "1280x720")
        self.assertTrue(cams[0]["in_use"])

    @patch.object(CameraDeviceHandler, "probe_device")
    def test_discover_usb_cameras_idle_backward_compat(self, mock_probe):
        """When active_indices is None, all indices 0..max_devices-1 are probed."""
        mock_probe.return_value = None
        cams = CameraDeviceHandler.discover_usb_cameras(max_devices=2)
        self.assertEqual(cams, [])
        self.assertEqual([c.args[0] for c in mock_probe.call_args_list], [0, 1])

    @patch.object(CameraDeviceHandler, "get_friendly_name", return_value="Active USB 0")
    @patch.object(CameraDeviceHandler, "probe_device", return_value=None)
    def test_scanner_and_usb_thread_active_indices(self, mock_probe, _mock_name):
        """discover_all_cameras and find_physical_cameras thread active_indices cleanly."""
        usb_only = find_physical_cameras(max_devices=2, active_indices={0})
        self.assertEqual(len(usb_only), 1)
        self.assertEqual(usb_only[0].status, "in_use")
        self.assertTrue(usb_only[0].details["in_use"])

        all_cams = discover_all_cameras(
            include_usb=True,
            include_onvif=False,
            include_lan_rtsp=False,
            active_indices={0},
        )
        self.assertEqual(len(all_cams), 1)
        self.assertEqual(all_cams[0].source, 0)
        self.assertNotIn(0, [c.args[0] for c in mock_probe.call_args_list])

    def test_camera_pool_get_active_usb_indices(self):
        """CameraPool.get_active_usb_indices extracts only running USB indices."""
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        pool = CameraPool(config_file=os.path.join(tmpdir.name, "cameras.json"), autostart=False)
        self.addCleanup(pool.stop_all)

        mgr_usb_int = MagicMock(is_running=True, source_override=0)
        mgr_usb_str = MagicMock(is_running=True, source_override="2")
        mgr_stopped = MagicMock(is_running=False, source_override=1)
        mgr_rtsp = MagicMock(is_running=True, source_override="rtsp://10.0.0.5/live")
        pool.camera_configs = {
            "cam0": {"source": 0, "type": "usb"},
            "cam2": {"source": "2", "type": "usb"},
            "cam1": {"source": 1, "type": "usb"},
            "cam_rtsp": {"source": "rtsp://10.0.0.5/live", "type": "rtsp"},
        }
        pool.streams = {
            "cam0": mgr_usb_int,
            "cam2": mgr_usb_str,
            "cam1": mgr_stopped,
            "cam_rtsp": mgr_rtsp,
        }
        self.assertEqual(pool.get_active_usb_indices(), {0, 2})

    @patch.object(CameraDeviceHandler, "probe_device", return_value=None)
    def test_api_discover_route_skips_active_pool_usb(self, mock_probe):
        """GET /api/cameras/discover skips probing USB indices active in CameraPool."""
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        pool = CameraPool(config_file=os.path.join(tmpdir.name, "cameras.json"), autostart=False)
        self.addCleanup(pool.stop_all)

        mock_vs = MagicMock(width=1280, height=720, is_synthetic=False, source=0)
        mock_mgr = MagicMock(is_running=True, source_override=0, video_source=mock_vs)
        mock_mgr.get_latest_telemetry.return_value = {"fps": 29.5, "active_tracks": []}
        pool.camera_configs = {"cam0": {"name": "Desk Cam", "source": 0, "type": "usb"}}
        pool.streams = {"cam0": mock_mgr}

        bind_app_state(app, camera_pool=pool)
        self.addCleanup(clear_app_state, app)
        client = TestClient(app)

        resp = client.get("/api/cameras/discover?include_usb=true&include_onvif=false&include_lan_rtsp=false")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["source"], 0)
        self.assertEqual(data[0]["status"], "in_use")
        self.assertEqual(data[0]["resolution"], "1280x720")
        self.assertNotIn(0, [c.args[0] for c in mock_probe.call_args_list])


class TestDriverWarmupAndAutoReopen(unittest.TestCase):
    """Tests for DirectShow warmup grace, exponential backoff, and auto-reopen."""

    def test_capture_guard_warmup_vs_steady_state_timeout(self):
        """First read uses warmup_timeout; subsequent reads use steady-state timeout."""
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        cap = MagicMock()
        cap.read.side_effect = lambda: (time.sleep(0.18), (True, frame))[1]
        guard = CaptureReadGuard(timeout=0.08, warmup_timeout=0.45)
        self.addCleanup(guard.stop)

        ret1, res1 = guard.read(cap)
        self.assertTrue(ret1)
        self.assertIsNotNone(res1)

        ret2, res2 = guard.read(cap)
        self.assertFalse(ret2)
        self.assertIsNone(res2)
        self.assertTrue(guard.last_read_timed_out)

    def test_video_source_passes_warmup_then_steady_timeout(self):
        """CaptureWorkerMixin passes warmup_timeout on first read, then read_timeout."""
        vs = VideoSource(source="synthetic", read_timeout=2.0, warmup_timeout=5.0)
        vs._cap = MagicMock()
        vs._cap.isOpened.return_value = True
        vs._running = True
        timeouts = []
        frame = np.zeros((10, 10, 3), dtype=np.uint8)

        def fake_read(_cap, timeout=None, stop_event=None):
            timeouts.append(timeout)
            if len(timeouts) >= 2:
                vs._running = False
            return True, frame

        vs._read_guard = MagicMock()
        vs._read_guard.read.side_effect = fake_read
        vs._capture_worker()
        self.assertEqual(timeouts, [5.0, 2.0])

    def test_exponential_backoff_progression(self):
        """compute_reconnect_backoff and _handle_reconnection scale exponentially."""
        delays = [compute_reconnect_backoff(i, base_delay=1.0, max_backoff=30.0) for i in range(1, 8)]
        self.assertEqual(delays, [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0])

        vs = VideoSource(source="synthetic", reconnect_delay=1.0, max_reconnect_attempts=5)
        observed_waits = []
        vs._stop_event = MagicMock()
        vs._stop_event.wait.side_effect = lambda timeout: (observed_waits.append(timeout), False)[1]
        with patch.object(vs, "_open_capture", return_value=False):
            _, attempts = vs._handle_reconnection(0)
            _, attempts = vs._handle_reconnection(attempts)
            _, attempts = vs._handle_reconnection(attempts)
        self.assertEqual(observed_waits, [1.0, 2.0, 4.0])
        self.assertEqual(attempts, 3)

    def test_severed_driver_auto_reopen_and_interruptible_stop(self):
        """Severed driver triggers auto-reopen and _stop_event wakes backoff in <10ms."""
        vs = VideoSource(source="synthetic", reconnect_delay=10.0, max_reconnect_attempts=3)
        timer = threading.Timer(0.02, vs._stop_event.set)
        timer.start()
        self.addCleanup(timer.cancel)
        t0 = time.perf_counter()
        cont, _ = vs._handle_reconnection(0)
        elapsed = time.perf_counter() - t0
        self.assertFalse(cont)
        self.assertLess(elapsed, 0.2)

    def test_severed_driver_reopens_and_resets_guard(self):
        """Timed-out read severs driver, triggers auto-reopen, and resets guard."""
        vs = VideoSource(source="synthetic", reconnect_delay=0.01, max_reconnect_attempts=3)
        vs.is_file = False
        vs._cap = MagicMock()
        vs._cap.isOpened.return_value = True
        vs._running = True
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        calls = {"n": 0}

        def fake_read(_cap, timeout=None, stop_event=None):
            calls["n"] += 1
            if calls["n"] == 1:
                vs._read_guard.last_read_timed_out = True
                return False, None
            vs._read_guard.last_read_timed_out = False
            vs._running = False
            return True, frame

        vs._read_guard = MagicMock(is_reconnecting=False, last_read_timed_out=False)
        vs._read_guard.read.side_effect = fake_read
        with patch.object(vs, "_open_capture", side_effect=lambda: (setattr(vs, "_cap", MagicMock()), True)[1]):
            vs._capture_worker()
        vs._read_guard.safe_driver_unbind.assert_called_once()
        vs._read_guard.reset.assert_called_once()


if __name__ == "__main__":
    unittest.main()
