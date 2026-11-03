#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for DeduplicatingLogger and CameraHealthManager log throttling.
"""

import logging
import unittest
from unittest.mock import MagicMock

from dashboard.services.camera_diagnostics import CameraHealthManager
from dashboard.services.logger_manager import DeduplicatingLogger


class TestLoggerManager(unittest.TestCase):
    """Test suite for DeduplicatingLogger and log flooding prevention."""

    def setUp(self):
        self.dedup = DeduplicatingLogger()
        self.dedup.reset()

    def tearDown(self):
        self.dedup.reset()

    def test_log_once_suppresses_identical_messages(self):
        """Verify identical consecutive messages on the same key are suppressed."""
        mock_logger = MagicMock(spec=logging.Logger)
        key = "test_key_1"
        msg = "Error opening camera %s"
        arg = "cam_01"

        # First call should emit log
        emitted1 = self.dedup.warning_once(key, msg, arg, target_logger=mock_logger)
        self.assertTrue(emitted1)
        self.assertEqual(mock_logger.log.call_count, 1)

        # Immediate second call with identical payload should be suppressed
        emitted2 = self.dedup.warning_once(key, msg, arg, target_logger=mock_logger)
        self.assertFalse(emitted2)
        self.assertEqual(mock_logger.log.call_count, 1)

        # Third call with 100 iterations in a loop
        for _ in range(100):
            self.dedup.warning_once(key, msg, arg, target_logger=mock_logger)
        self.assertEqual(mock_logger.log.call_count, 1)

    def test_log_once_emits_when_message_changes(self):
        """Verify a different error message under the same key is emitted immediately."""
        mock_logger = MagicMock(spec=logging.Logger)
        key = "camera_error:cam_02"

        # First error: FILE_NOT_FOUND
        emitted1 = self.dedup.warning_once(key, "File not found: %s", "video.mp4", target_logger=mock_logger)
        self.assertTrue(emitted1)
        self.assertEqual(mock_logger.log.call_count, 1)

        # State changes to DEVICE_LOCKED
        emitted2 = self.dedup.warning_once(key, "Device locked: %s", "index 0", target_logger=mock_logger)
        self.assertTrue(emitted2)
        self.assertEqual(mock_logger.log.call_count, 2)

    def test_reset_enables_new_emission_after_recovery(self):
        """Verify resetting a key allows the same message to be re-emitted on subsequent failure."""
        mock_logger = MagicMock(spec=logging.Logger)
        key = "camera_error:cam_03"

        emitted1 = self.dedup.error_once(key, "Connection timeout", target_logger=mock_logger)
        self.assertTrue(emitted1)
        self.assertEqual(mock_logger.log.call_count, 1)

        # Reset after recovery
        self.dedup.reset(key)

        # New failure with same message logs again
        emitted2 = self.dedup.error_once(key, "Connection timeout", target_logger=mock_logger)
        self.assertTrue(emitted2)
        self.assertEqual(mock_logger.log.call_count, 2)

    def test_camera_health_manager_deduplicates_repeated_errors(self):
        """Verify CameraHealthManager.set_error() suppresses log spam across 50 iterations."""
        health_mgr = CameraHealthManager()
        cam_id = "test_flood_cam"
        DeduplicatingLogger().reset(f"camera_error:{cam_id}")

        with self.assertLogs("intelligent_tracker.dashboard.services.camera_diagnostics", level="WARNING") as cm:
            for _ in range(50):
                health_mgr.set_error(
                    camera_id=cam_id,
                    error_msg="Video file not found: /data/test.mp4",
                    error_code="FILE_NOT_FOUND",
                )

        # Crucial check: despite 50 calls in high-speed loop, exactly ONE warning was logged!
        warning_logs = [record for record in cm.output if "reported error (FILE_NOT_FOUND)" in record]
        self.assertEqual(len(warning_logs), 1)

        # Failure count in report still faithfully tracks total consecutive attempts
        rep = health_mgr.get_health(cam_id)
        self.assertEqual(rep.failure_count, 50)
        self.assertEqual(rep.status, "error")


if __name__ == "__main__":
    unittest.main()

