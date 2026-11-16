#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for Step 3: Pool-Aware Camera Discovery & Driver Resilience.
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.camera_pool import CameraPool
from dashboard.dependencies import bind_app_state, clear_app_state
from intelligent_tracker.camera_device import CameraDeviceHandler
from intelligent_tracker.discovery import discover_all_cameras, find_physical_cameras


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


if __name__ == "__main__":
    unittest.main()
