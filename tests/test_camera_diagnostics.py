#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for Camera Health Manager and Diagnostics API Router.
"""

import unittest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.services.camera_diagnostics import CameraHealthManager, CameraHealthReport


class TestCameraDiagnostics(unittest.TestCase):
    """Test suite for CameraHealthManager state transitions and diagnostic endpoints."""

    def setUp(self):
        self.health_mgr = CameraHealthManager()
        self.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        from dashboard.dependencies import set_camera_pool
        set_camera_pool(None)

    def test_health_manager_error_lifecycle(self):
        """Verify error registration, remediation deduction, and error frame synthesis."""
        cam_id = "test_cam_err"
        self.health_mgr.set_error(
            camera_id=cam_id,
            error_msg="Video file not found: data/videos/vecino.mp4",
            error_code="FILE_NOT_FOUND",
            attempted_paths=["/app/data/videos/vecino.mp4", "data/videos/vecino.mp4"],
        )

        rep = self.health_mgr.get_health(cam_id)
        self.assertEqual(rep.status, "error")
        self.assertEqual(rep.error_code, "FILE_NOT_FOUND")
        self.assertIn("missing", rep.suggested_action.lower())
        self.assertEqual(rep.failure_count, 1)

        # Verify error frame synthesis
        jpeg_bytes = self.health_mgr.create_error_placeholder_jpeg(cam_id, name="Vecino Video")
        self.assertIsInstance(jpeg_bytes, bytes)
        self.assertGreater(len(jpeg_bytes), 500)

        # Transition back to online
        self.health_mgr.set_online(cam_id, fps=29.9)
        rep_online = self.health_mgr.get_health(cam_id)
        self.assertEqual(rep_online.status, "online")
        self.assertEqual(rep_online.error_code, "OK")
        self.assertEqual(rep_online.failure_count, 0)
        self.assertEqual(rep_online.fps, 29.9)

    def test_api_diagnostics_summary(self):
        """Verify GET /api/cameras/diagnostics/summary returns multi-channel status."""
        resp = self.client.get("/api/cameras/diagnostics/summary")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("total_cameras", data)
        self.assertIn("online_count", data)
        self.assertIn("error_count", data)
        self.assertIn("reports", data)

    def test_api_camera_diagnostics_detail(self):
        """Verify GET /api/cameras/{id}/diagnostics returns structured report."""
        # Use existing configured camera from cameras.json
        resp = self.client.get("/api/cameras/synthetic_01/diagnostics")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("camera_id"), "synthetic_01")
        self.assertIn("status", data)
        self.assertIn("error_code", data)

    def test_api_camera_release(self):
        """Verify POST /api/cameras/{id}/release executes targeted hardware unlock."""
        with patch("intelligent_tracker.camera_tool.release_camera_by_index", return_value={"status": "released", "probed_status": "AVAILABLE"}):
            with patch("intelligent_tracker.camera_device.CameraDeviceHandler.probe_device", return_value={"fps": 30.0, "valid": True}):
                resp = self.client.post("/api/cameras/usb_0/release")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertEqual(data.get("status"), "success")
                self.assertIn("release_result", data)


if __name__ == "__main__":
    unittest.main()

