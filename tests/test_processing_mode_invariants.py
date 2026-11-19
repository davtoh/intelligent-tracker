#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit tests for ProcessingModeService E4/E5/E6 invariants and camera armed schema."""

import os
import tempfile
import unittest

from dashboard.schemas import CameraAddRequest, CameraUpdateRequest
from dashboard.services.camera_config_store import CameraConfigStore
from dashboard.services.processing_mode_service import ProcessingModeService


class TestProcessingModeInvariants(unittest.TestCase):
    """Verify vision step independence (E4), hibernation (E5), and armed vs paused (E6)."""

    def test_e4_vision_step_independent_of_subscriber_count(self) -> None:
        for mode in ("focus_only", "full_realtime", "capture_only", "paused"):
            svc = ProcessingModeService(mode=mode, focused_camera_id="cam_01", active_tab="live")
            expected_cam1 = svc.should_run_vision_step("cam_01", is_recording=False)
            expected_cam2 = svc.should_run_vision_step("cam_02", is_recording=False)
            self.assertEqual(expected_cam1, mode in ("focus_only", "full_realtime"))
            self.assertEqual(expected_cam2, mode == "full_realtime")

    def test_e5_unarmed_hibernation_across_all_modes(self) -> None:
        svc = ProcessingModeService(mode="focus_only", focused_camera_id="cam_01", active_tab="live")
        self.assertFalse(svc.should_hibernate_camera("cam_01", subscriber_count=0, in_camera_pool=True))
        self.assertTrue(svc.should_hibernate_camera("cam_02", subscriber_count=0, in_camera_pool=True))
        self.assertFalse(svc.should_hibernate_camera("cam_02", subscriber_count=1, in_camera_pool=True))

        svc.update(mode="capture_only")
        self.assertTrue(svc.should_hibernate_camera("cam_01", subscriber_count=0, in_camera_pool=True))
        self.assertFalse(svc.should_hibernate_camera("cam_01", subscriber_count=1, in_camera_pool=True))

        svc.update(mode="full_realtime")
        self.assertFalse(svc.should_hibernate_camera("cam_02", subscriber_count=0, in_camera_pool=True))
        self.assertTrue(svc.should_hibernate_camera("cam_99", subscriber_count=0, in_camera_pool=False))

    def test_e6_armed_never_hibernates_except_paused_and_recording_always_wins(self) -> None:
        for mode in ("focus_only", "capture_only", "full_realtime"):
            svc = ProcessingModeService(mode=mode, focused_camera_id="cam_01", active_tab="analytics")
            self.assertFalse(
                svc.should_hibernate_camera("cam_02", subscriber_count=0, in_camera_pool=True, is_armed=True)
            )
        svc_paused = ProcessingModeService(mode="paused", focused_camera_id="cam_01", active_tab="live")
        self.assertTrue(
            svc_paused.should_hibernate_camera("cam_01", subscriber_count=2, in_camera_pool=True, is_armed=True)
        )
        self.assertFalse(
            svc_paused.should_hibernate_camera(
                "cam_01", subscriber_count=0, is_recording=True, in_camera_pool=True, is_armed=True
            )
        )

    def test_camera_schema_and_config_store_armed_default(self) -> None:
        add_req = CameraAddRequest(id="cam_02", name="Back Door", source="synthetic")
        self.assertFalse(add_req.armed)
        upd_req = CameraUpdateRequest(armed=True)
        self.assertTrue(upd_req.armed)

        with tempfile.TemporaryDirectory() as tmpdir:
            store = CameraConfigStore(config_file=os.path.join(tmpdir, "cameras.json"))
            entry = store.build_and_store_entry("cam_02", "Back Door", "synthetic", armed=True)
            self.assertTrue(entry["armed"])
            found, needs_restart, updated = store.update_entry("cam_02", armed=False)
            self.assertTrue(found)
            self.assertFalse(needs_restart)
            self.assertFalse(updated["armed"])


if __name__ == "__main__":
    unittest.main()
