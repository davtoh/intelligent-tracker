#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for CameraDeviceHandler hardware abstraction module.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from intelligent_tracker.camera_device import CameraDeviceHandler
from intelligent_tracker.video import (
    find_first_real_camera,
    find_physical_cameras,
    is_physical_camera,
    resolve_camera_source,
)


class TestCameraDeviceHandler(unittest.TestCase):
    """Test suite for CameraDeviceHandler functionality and safety protocols."""

    def test_validate_frame_null_and_empty(self):
        """Verify that None, non-array, and empty arrays are rejected."""
        self.assertFalse(CameraDeviceHandler.validate_frame(None))
        self.assertFalse(CameraDeviceHandler.validate_frame("not an array"))
        self.assertFalse(CameraDeviceHandler.validate_frame(np.array([])))

    def test_validate_frame_black_sensor_fault(self):
        """Verify that a completely dead pitch-black frame is rejected."""
        black_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        self.assertFalse(CameraDeviceHandler.validate_frame(black_frame, min_std=0.5))

    def test_validate_frame_valid_visual_data(self):
        """Verify that frames with valid lighting and visual variance pass validation."""
        valid_frame = np.full((480, 640, 3), 128, dtype=np.uint8)
        valid_frame[100:200, 100:200] = 200
        self.assertTrue(CameraDeviceHandler.validate_frame(valid_frame))

    def test_safe_release_none(self):
        """Safe release on None should complete without error."""
        try:
            CameraDeviceHandler.safe_release(None, settle_delay=0.0)
        except Exception as e:
            self.fail(f"safe_release(None) raised unexpected exception: {e}")

    def test_safe_release_mock_cap(self):
        """Verify that safe_release invokes cap.release() and handles errors."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        CameraDeviceHandler.safe_release(mock_cap, settle_delay=0.0)
        mock_cap.release.assert_called_once()

    def test_get_preferred_backends(self):
        """Verify that preferred backends return a non-empty list of integers."""
        backends = CameraDeviceHandler.get_preferred_backends()
        self.assertIsInstance(backends, list)
        self.assertGreater(len(backends), 0)
        if sys.platform.startswith("win"):
            self.assertIn(cv2.CAP_DSHOW, backends)

    def test_is_container_environment(self):
        """Verify is_container_environment returns a boolean."""
        res = CameraDeviceHandler.is_container_environment()
        self.assertIsInstance(res, bool)

    @patch("cv2.VideoCapture")
    def test_probe_device_mock_success(self, mock_vc_cls):
        """Verify probe_device parses frame metrics correctly on valid device."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        sample_frame = np.full((480, 640, 3), 100, dtype=np.uint8)
        sample_frame[10:50, 10:50] = 250
        mock_cap.read.return_value = (True, sample_frame)
        mock_cap.get.side_effect = lambda prop: 640.0 if prop == cv2.CAP_PROP_FRAME_WIDTH else (
            480.0 if prop == cv2.CAP_PROP_FRAME_HEIGHT else 30.0
        )
        mock_cap.getBackendName.return_value = "DSHOW"
        mock_vc_cls.return_value = mock_cap

        info = CameraDeviceHandler.probe_device(0)
        self.assertIsNotNone(info)
        self.assertEqual(info["index"], 0)
        self.assertEqual(info["resolution"], "640x480")
        self.assertEqual(info["fps"], 30.0)
        self.assertEqual(info["backend"], "DSHOW")
        self.assertTrue(info["valid"])

    @patch("cv2.VideoCapture")
    def test_probe_device_mock_failure(self, mock_vc_cls):
        """Verify probe_device returns None when device fails to open."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = False
        mock_vc_cls.return_value = mock_cap

        info = CameraDeviceHandler.probe_device(99)
        self.assertIsNone(info)

    @patch.object(CameraDeviceHandler, "probe_device")
    def test_discover_usb_cameras(self, mock_probe):
        """Verify discover_usb_cameras aggregates valid probed devices."""
        mock_probe.side_effect = lambda idx: (
            {"index": idx, "name": f"USB Camera {idx}", "resolution": "640x480", "valid": True}
            if idx == 1 else None
        )
        cams = CameraDeviceHandler.discover_usb_cameras(max_devices=3)
        self.assertEqual(len(cams), 1)
        self.assertEqual(cams[0]["index"], 1)

    @patch.object(CameraDeviceHandler, "probe_device")
    def test_find_first_working_camera(self, mock_probe):
        """Verify find_first_working_camera returns the first valid index."""
        mock_probe.side_effect = lambda idx: (
            {"index": idx, "name": f"USB Camera {idx}", "resolution": "1920x1080", "valid": True}
            if idx == 1 else None
        )
        first_idx = CameraDeviceHandler.find_first_working_camera(max_devices=3)
        self.assertEqual(first_idx, 1)

    @patch.object(CameraDeviceHandler, "find_first_working_camera", return_value=1)
    def test_resolve_camera_source_real(self, mock_first):
        """Verify resolve_camera_source('real') returns discovered hardware index."""
        res = resolve_camera_source("real")
        self.assertEqual(res, 1)

    def test_resolve_camera_source_passthrough(self):
        """Verify non-auto sources are preserved as expected."""
        self.assertEqual(resolve_camera_source(0), 0)
        self.assertEqual(resolve_camera_source("2"), 2)
        self.assertEqual(resolve_camera_source("synthetic"), "synthetic")
        self.assertEqual(resolve_camera_source("rtsp://10.0.0.1:554/live"), "rtsp://10.0.0.1:554/live")


if __name__ == "__main__":
    unittest.main()

