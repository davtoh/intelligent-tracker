#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for Intelligent Tracker Environment-Agnostic Camera & Path Resolver.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from intelligent_tracker.camera_resolver import CameraPathResolver


class TestCameraPathResolver(unittest.TestCase):
    """Test suite for path normalization, file search fallbacks, and dynamic hardware resolution."""

    def test_normalize_source_path_container(self):
        """Verify /app/ prefixes are stripped when running on host."""
        with patch("intelligent_tracker.camera_device.CameraDeviceHandler.is_container_environment", return_value=False):
            res = CameraPathResolver.normalize_source_path("/app/data/videos/test.mp4")
            self.assertEqual(res, "data/videos/test.mp4")

            res_rel = CameraPathResolver.normalize_source_path("app/data/videos/test.mp4")
            self.assertEqual(res_rel, "data/videos/test.mp4")

            res_bs = CameraPathResolver.normalize_source_path("data\\videos\\test.mp4")
            self.assertEqual(res_bs, "data/videos/test.mp4")

    def test_resolve_file_source_missing(self):
        """Verify non-existent files return FILE_NOT_FOUND and list probed candidates."""
        resolved, err, attempted = CameraPathResolver.resolve_file_source("/app/data/videos/non_existent_video_999.mp4")
        self.assertIsNone(resolved)
        self.assertEqual(err, "FILE_NOT_FOUND")
        self.assertGreater(len(attempted), 1)

    def test_resolve_camera_source_synthetic(self):
        """Verify synthetic, mock, and network RTSP streams pass through cleanly."""
        src, meta = CameraPathResolver.resolve_camera_source("synthetic")
        self.assertEqual(src, "synthetic")
        self.assertEqual(meta.get("resolved_by"), "synthetic")

        src_rtsp, meta_rtsp = CameraPathResolver.resolve_camera_source("rtsp://192.168.1.50:554/live")
        self.assertEqual(src_rtsp, "rtsp://192.168.1.50:554/live")
        self.assertEqual(meta_rtsp.get("resolved_by"), "network_stream")

    def test_resolve_camera_source_dynamic_device_name_match(self):
        """Verify device friendly name re-maps shifted DirectShow index."""
        fake_names = ["OBS Virtual Camera", "GoPro Webcam", "USB Camera 2"]
        with patch("intelligent_tracker.camera_device.CameraDeviceHandler.get_device_names", return_value=fake_names):
            # Stored as index 0, but device_name is "GoPro Webcam" (currently index 1)
            src, meta = CameraPathResolver.resolve_camera_source("0", device_name="GoPro Webcam")
            self.assertEqual(src, 1)
            self.assertEqual(meta.get("resolved_by"), "device_name_match")
            self.assertEqual(meta.get("original_index"), 0)

    def test_resolve_camera_source_real_skips_virtual_devices(self):
        """Verify 'real' auto-detect never falls back to virtual loopback devices."""
        fake_names = ["OBS Virtual Camera", "GoPro Webcam"]
        with patch("intelligent_tracker.camera_device.CameraDeviceHandler.get_device_names", return_value=fake_names):
            with patch("intelligent_tracker.camera_device.CameraDeviceHandler.find_first_working_camera", return_value=None):
                # When probe returns None, fallback must select index 1 (GoPro), not index 0 (OBS)
                src, meta = CameraPathResolver.resolve_camera_source("real")
                self.assertEqual(src, 1)
                self.assertEqual(meta.get("device_name"), "GoPro Webcam")
                self.assertEqual(meta.get("resolved_by"), "physical_registry_fallback")


if __name__ == "__main__":
    unittest.main()

