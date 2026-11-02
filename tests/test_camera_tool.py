#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for Camera Tool & Resource Manager (intelligent_tracker/camera_tool.py).
"""

import unittest
from unittest.mock import patch, MagicMock

import numpy as np

from intelligent_tracker.camera_device import CameraDeviceHandler
from intelligent_tracker.camera_tool import (
    inspect_camera_devices,
    find_camera_worker_processes,
    release_camera_resources,
)


class TestCameraTool(unittest.TestCase):

    def test_get_device_names_and_friendly_names(self):
        """Friendly names should be resolved or fall back cleanly to USB Camera {idx}."""
        names = CameraDeviceHandler.get_device_names()
        self.assertIsInstance(names, list)

        name_0 = CameraDeviceHandler.get_friendly_name(0)
        self.assertIsInstance(name_0, str)
        self.assertGreater(len(name_0), 0)

        # Large non-existent index falls back to USB Camera {idx}
        fallback_name = CameraDeviceHandler.get_friendly_name(99)
        self.assertEqual(fallback_name, "USB Camera 99")

    def test_virtual_device_classification(self):
        """Software virtual cameras should be correctly detected by keyword."""
        self.assertTrue(CameraDeviceHandler.is_virtual_device("OBS Virtual Camera"))
        self.assertTrue(CameraDeviceHandler.is_virtual_device("Unity Video Capture"))
        self.assertTrue(CameraDeviceHandler.is_virtual_device("DroidCam Source 1"))
        self.assertFalse(CameraDeviceHandler.is_virtual_device("GoPro Webcam"))
        self.assertFalse(CameraDeviceHandler.is_virtual_device("Logitech HD Pro Webcam C920"))
        self.assertFalse(CameraDeviceHandler.is_virtual_device("Integrated Camera"))

    def test_resolve_source_by_friendly_name(self):
        """Substrings matching known camera friendly names should resolve to numeric indices."""
        with patch.object(CameraDeviceHandler, "get_device_names", return_value=["OBS Virtual Camera", "GoPro Webcam"]):
            self.assertEqual(CameraDeviceHandler.resolve_source("gopro"), 1)
            self.assertEqual(CameraDeviceHandler.resolve_source("obs"), 0)
            self.assertEqual(CameraDeviceHandler.resolve_source("GoPro Webcam"), 1)
            self.assertEqual(CameraDeviceHandler.resolve_source("2"), 2)
            self.assertEqual(CameraDeviceHandler.resolve_source("synthetic"), "synthetic")

    def test_find_first_working_camera_prefer_physical(self):
        """Hardware cameras should be prioritized over virtual cameras when prefer_physical=True."""
        mock_obs = {"index": 0, "name": "OBS Virtual Camera", "is_virtual": True, "valid": True}
        mock_gopro = {"index": 1, "name": "GoPro Webcam", "is_virtual": False, "valid": True}

        def fake_probe(idx):
            if idx == 0:
                return mock_obs
            elif idx == 1:
                return mock_gopro
            return None

        with patch.object(CameraDeviceHandler, "probe_device", side_effect=fake_probe):
            # When prefer_physical=True, index 1 (GoPro) must be selected
            idx = CameraDeviceHandler.find_first_working_camera(max_devices=3, prefer_physical=True)
            self.assertEqual(idx, 1)

            # When prefer_physical=False, index 0 (OBS) is selected
            idx_first = CameraDeviceHandler.find_first_working_camera(max_devices=3, prefer_physical=False)
            self.assertEqual(idx_first, 0)

    def test_inspect_camera_devices(self):
        """inspect_camera_devices should return structured status dictionaries."""
        with patch.object(CameraDeviceHandler, "get_device_names", return_value=["Mock Cam"]):
            with patch.object(CameraDeviceHandler, "open_camera", return_value=(None, "FAILED")):
                devs = inspect_camera_devices(max_devices=2)
                self.assertEqual(len(devs), 2)
                self.assertEqual(devs[0]["index"], 0)
                self.assertEqual(devs[0]["name"], "Mock Cam")
                self.assertEqual(devs[0]["status"], "BUSY (LOCKED)")
                self.assertEqual(devs[1]["status"], "NOT PRESENT")

    def test_find_camera_worker_processes(self):
        """find_camera_worker_processes should safely iterate without throwing exceptions."""
        procs = find_camera_worker_processes()
        self.assertIsInstance(procs, list)

    def test_release_camera_resources(self):
        """release_camera_resources should execute cooldown safely."""
        res = release_camera_resources(kill_orphans=False)
        self.assertTrue(res["success"])
        self.assertGreaterEqual(res["cooldown_applied_seconds"], 0.2)

    def test_terminate_process_by_pid_not_found(self):
        """Terminating an invalid PID should fail gracefully without unhandled exceptions."""
        from intelligent_tracker.camera_tool import terminate_process_by_pid
        # PID 999999 is invalid
        result = terminate_process_by_pid(999999, force=True)
        self.assertFalse(result)

    def test_release_camera_by_index(self):
        """release_camera_by_index should trigger probe and report availability."""
        from intelligent_tracker.camera_tool import release_camera_by_index
        mock_dev = {"index": 1, "name": "GoPro", "valid": True}
        with patch.object(CameraDeviceHandler, "probe_device", return_value=mock_dev):
            res = release_camera_by_index(1, force=False)
            self.assertEqual(res["index"], 1)
            self.assertTrue(res["available"])


if __name__ == "__main__":
    unittest.main()
