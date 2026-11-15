#!/usr/bin/env python
"""Unit tests for Step 1 Milestone 2: CameraConfigStore legacy mock healing and telemetry status."""

import json
import os
import tempfile
import threading
import unittest
from types import SimpleNamespace

from dashboard.services.camera_config_store import (
    CameraConfigStore,
    heal_non_synthetic_mock_cameras,
)
from dashboard.services.stream_worker import StreamWorker, _resolve_detector_telemetry


class _DummyHomography:
    is_calibrated = False

    @staticmethod
    def track_to_ground(bbox: list[int]) -> tuple[float, float]:
        return 0.0, 0.0


def _make_dummy_manager(**extra: object) -> SimpleNamespace:
    base = {
        "camera_id": "cam_test",
        "homography": _DummyHomography(),
        "overlays": {},
        "analytics": None,
        "event_bus": None,
        "cfg": {},
        "detector": object(),
        "_lock": threading.RLock(),
    }
    base.update(extra)
    return SimpleNamespace(**base)


class TestCameraConfigHealing(unittest.TestCase):
    """Verify heal_non_synthetic_mock_cameras and CameraConfigStore persistence."""

    def test_heal_upgrades_non_synthetic_sources_and_drops_docker_notice(self) -> None:
        configs = {
            "vid_01": {"id": "vid_01", "source": "/app/data/videos/sample.mp4", "type": "video_file", "detector": "mock"},
            "usb_0": {"id": "usb_0", "source": "0", "type": "usb", "detector": "mock"},
            "rtsp_1": {"id": "rtsp_1", "source": "rtsp://10.0.0.5/stream1", "type": "rtsp", "detector": "mock"},
            "hik_usb": {"id": "hik_usb", "source": "1", "type": "hikvision", "detector": "mock"},
            "synthetic_01": {"id": "synthetic_01", "source": "synthetic", "type": "hikvision", "detector": "mock"},
            "docker_notice": {"id": "docker_notice", "source": "synthetic", "type": "hikvision", "detector": "mock"},
        }

        changed = heal_non_synthetic_mock_cameras(configs)

        self.assertTrue(changed)
        for cid in ("vid_01", "usb_0", "rtsp_1", "hik_usb"):
            self.assertEqual(configs[cid]["detector"], "yolov8")
        self.assertEqual(configs["synthetic_01"]["detector"], "mock")
        self.assertNotIn("docker_notice", configs)

    def test_heal_returns_false_when_only_synthetic_mock_present(self) -> None:
        configs = {
            "synthetic_01": {
                "id": "synthetic_01",
                "source": "synthetic",
                "type": "synthetic",
                "detector": "mock",
            },
            "cam_real": {
                "id": "cam_real",
                "source": "0",
                "type": "usb",
                "detector": "yolov8",
            },
        }

        changed = heal_non_synthetic_mock_cameras(configs)
        self.assertFalse(changed)
        self.assertEqual(configs["synthetic_01"]["detector"], "mock")
        self.assertEqual(configs["cam_real"]["detector"], "yolov8")

    def test_store_load_cameras_heals_and_persists_in_isolated_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "cameras.json")
            raw_entries = [
                {
                    "id": "vid_sample",
                    "source": "/videos/demo.mp4",
                    "type": "video_file",
                    "detector": "mock",
                },
                {
                    "id": "docker_notice",
                    "source": "synthetic",
                    "type": "hikvision",
                    "detector": "mock",
                },
                {
                    "id": "synthetic_01",
                    "source": "synthetic",
                    "type": "synthetic",
                    "detector": "mock",
                },
            ]
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(raw_entries, f)

            store = CameraConfigStore(config_file=cfg_path)
            loaded, seeded = store.load_cameras()

            self.assertFalse(seeded)
            self.assertEqual(loaded["vid_sample"]["detector"], "yolov8")
            self.assertEqual(loaded["synthetic_01"]["detector"], "mock")
            self.assertNotIn("docker_notice", loaded)

            with open(cfg_path, "r", encoding="utf-8") as f:
                persisted = {item["id"]: item for item in json.load(f)}
            self.assertEqual(persisted["vid_sample"]["detector"], "yolov8")
            self.assertNotIn("docker_notice", persisted)

    def test_repo_cameras_json_has_no_non_synthetic_mock_or_docker_notice(self) -> None:
        repo_cfg = os.path.join("configs", "cameras.json")
        if not os.path.exists(repo_cfg):
            self.skipTest("configs/cameras.json not present (gitignored runtime config)")
        with open(repo_cfg, "r", encoding="utf-8") as f:
            entries = json.load(f)
        by_id = {entry["id"]: entry for entry in entries}
        self.assertNotIn("docker_notice", by_id)
        self.assertIn("synthetic_01", by_id)
        self.assertEqual(by_id["synthetic_01"]["detector"], "mock")
        for cid, entry in by_id.items():
            if cid != "synthetic_01":
                self.assertNotEqual(entry["detector"], "mock", f"{cid} still uses mock")


class TestStreamWorkerDetectorTelemetry(unittest.TestCase):
    """Verify detector_model and detector_status fields in StreamWorker telemetry."""

    def test_build_telemetry_reads_pipeline_bundle_status_variants(self) -> None:
        for model, status in [("yolov8", "ready"), ("mock", "simulation"), ("yolov8", "unavailable")]:
            bundle = SimpleNamespace(
                config=SimpleNamespace(detector_model=model),
                detector_status=status,
            )
            manager = _make_dummy_manager(_pipeline_bundle=bundle)
            worker = StreamWorker(manager)
            payload = worker._build_telemetry({}, 100.0, 30.0, (480, 640, 3), 1)
            self.assertEqual(payload["detector_model"], model)
            self.assertEqual(payload["detector_status"], status)

    def test_resolve_detector_telemetry_fallback_branches(self) -> None:
        no_det_mgr = _make_dummy_manager(detector=None, cfg={"detector": {"model": "yolov8"}})
        self.assertEqual(_resolve_detector_telemetry(no_det_mgr), ("yolov8", "unavailable"))

        sim_mgr = _make_dummy_manager(detector=SimpleNamespace(name="mock"), cfg={})
        self.assertEqual(_resolve_detector_telemetry(sim_mgr), ("mock", "simulation"))

        real_mgr = _make_dummy_manager(detector=SimpleNamespace(name="yolov8"), cfg={})
        self.assertEqual(_resolve_detector_telemetry(real_mgr), ("yolov8", "ready"))


if __name__ == "__main__":
    unittest.main()
