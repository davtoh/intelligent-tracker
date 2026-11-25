"""Milestone 1 backend integration seam tests for Step 1."""

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from dashboard.services.alerts_query_service import query_merged_events
from dashboard.services.analytics_query_service import list_all_sighting_sources
from dashboard.services.async_inference_worker import AsyncInferenceWorker
from dashboard.services.camera_config_store import CameraConfigStore
from dashboard.services.events_admin_service import clear_events
from dashboard.services.file_detection_replay import FileDetectionReplayProvider
from dashboard.services.gallery_health_service import inspect_gallery_health
from dashboard.services.stream_telemetry import _extract_track_telemetry
from dashboard.services.video_run_relabel_service import relabel_video_runs_on_entity_mutation
from intelligent_tracker.config_merge import deep_merge
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.enrollment import UniversalEnrollmentManager
from intelligent_tracker.events.bus import EventBus
from intelligent_tracker.events.types import BaseEvent
from intelligent_tracker.pipeline.config import PipelineConfig, load_pipeline_config
from intelligent_tracker.reid.gallery_reembed import reembed_mismatched_signatures
from intelligent_tracker.reid.profile import resolve_reid_profile
from intelligent_tracker.scenarios import ScenarioManager


class TestStep1BackendSeams(unittest.TestCase):
    """Isolated tests covering Milestone 1 P0 backend integration seams."""

    def _make_temp_db(self) -> tuple[str, TrackerDB]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = os.path.join(tmp.name, "test.db")
        db = TrackerDB(db_path)
        self.addCleanup(db.close)
        return tmp.name, db

    def test_resolve_reid_profile_default_yaml_and_advisory_warning(self) -> None:
        default_cfg = load_pipeline_config("configs/default.yaml")
        self.assertEqual(default_cfg.get("reid", {}).get("model"), "dual")
        profile = resolve_reid_profile(default_cfg)
        self.assertEqual(profile.model_name, "dual")
        self.assertEqual(profile.expected_dim, 608)
        with self.assertLogs("intelligent_tracker.reid.profile", level="WARNING") as cm:
            overridden = resolve_reid_profile({"reid": {"model": "color"}})
        self.assertEqual(overridden.model_name, "dual")
        self.assertTrue(any("advisory" in msg.lower() for msg in cm.output))

    def test_gallery_health_and_startup_reembed(self) -> None:
        tmpdir, db = self._make_temp_db()
        eid = db.add_entity(name="Alice", category="person")
        crop_path = os.path.join(tmpdir, "alice.jpg")
        cv2.imwrite(crop_path, np.full((64, 32, 3), 128, dtype=np.uint8))
        db.add_signature(eid, np.ones(96, dtype=np.float32), crop_path=crop_path)
        with self.assertLogs("intelligent_tracker.repositories.signature_repo", level="WARNING"):
            mat, *_ = db.get_gallery_embeddings(expected_dim=608)
        self.assertEqual(mat.shape, (0, 608))
        self.assertEqual(db._last_gallery_mismatch_count, 1)
        health_before = inspect_gallery_health(db)
        self.assertFalse(health_before["healthy"])
        fake_ext = MagicMock()
        fake_ext.extract.return_value = np.ones(608, dtype=np.float32)
        res = reembed_mismatched_signatures(db, extractor=fake_ext, expected_dim=608)
        self.assertEqual(res["reembedded"], 1)
        self.assertTrue(inspect_gallery_health(db)["healthy"])

    def test_stream_telemetry_includes_entity_id(self) -> None:
        trk = SimpleNamespace(
            bbox=(10, 20, 30, 40), centroid=(25.0, 40.0), velocity=(0.0, 0.0),
            label="person", confidence=0.9, dwell_time=1.2, entity_id=42,
            entity_name="Alice", category="person", state="confirmed",
        )
        homo = MagicMock()
        homo.track_to_ground.return_value = (1.5, 2.5)
        rows = _extract_track_telemetry({7: trk}, homo)
        self.assertEqual(rows[0]["entity_id"], 42)
        self.assertEqual(rows[0]["entity_name"], "Alice")

    def test_deep_merge_null_class_clear_and_agnostic_nms_cfg(self) -> None:
        base = {"detector": {"model": "mock", "confidence": 0.25, "classes": ["person"]}}
        merged = deep_merge(base, {"detector": {"confidence": 0.4}})
        self.assertEqual(merged["detector"]["classes"], ["person"])
        self.assertEqual(merged["detector"]["confidence"], 0.4)
        cleared = deep_merge(base, {"detector": {"classes": None}})
        self.assertIsNone(cleared["detector"]["classes"])
        cfg = PipelineConfig.from_dict({"detector": {"agnostic_nms": False}})
        self.assertFalse(cfg.detector_agnostic_nms)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = CameraConfigStore(os.path.join(tmp.name, "cams.json"))
        store.build_and_store_entry("cam1", "Cam 1", "synthetic", classes=["person"])
        found, restart, updated = store.update_entry("cam1", classes=None)
        self.assertTrue(found and restart)
        self.assertIsNone(updated["classes"])

    def test_replay_signature_matching_and_async_monotonic_fallback(self) -> None:
        _, db = self._make_temp_db()
        db.save_video_run(
            "clip.mp4", report={}, config={"detector": "yolov8", "confidence": 0.25, "classes": ["person"]},
            frame_detections=[{"frame": 0, "time": 0.0, "tracks": [{"track_id": 1, "bbox": [0, 0, 10, 10]}]}],
        )
        vs = SimpleNamespace(is_file=True, source="clip.mp4", source_fps=30.0)
        miss = FileDetectionReplayProvider(db, vs, detector_signature={"detector": "onnx", "confidence": 0.5, "classes": ["car"]})
        self.assertFalse(miss.ensure_loaded())
        hit = FileDetectionReplayProvider(db, vs, detector_signature={"detector": "yolov8", "confidence": 0.25, "classes": ["person"]})
        self.assertTrue(hit.ensure_loaded())
        captured: list[float] = []
        worker = AsyncInferenceWorker(lambda *_: None)
        worker._execute_step = lambda f, w, m, s: captured.append(m)
        worker._pending = (np.zeros((4, 4, 3), dtype=np.uint8), 1_700_000_000.0, 1)
        with patch("dashboard.services.async_inference_worker.time.monotonic", return_value=123.45):
            if len(worker._pending) == 3:
                f, w, s = worker._pending
                worker._execute_step(f, w, 123.45, s)
        self.assertEqual(captured, [123.45])

    def test_event_bus_write_through_sqlite_ssot_and_bulk_clear(self) -> None:
        _, db = self._make_temp_db()
        bus = EventBus()
        self.addCleanup(bus.stop)
        bus.set_write_through_handler(lambda ev: db.index_timeline_event(
            timestamp=ev.timestamp, event_type=ev.event_type, camera_id=ev.camera_id,
            title=ev.event_type, summary="test", metadata={"severity": "warning"},
        ))
        bus.publish(BaseEvent(event_type="zone_breach", camera_id="cam_a", timestamp=100.0), sync=True)
        res = query_merged_events(SimpleNamespace(event_bus=bus), db, paginated=True)
        self.assertEqual(len(res["items"]), 1)
        eid = res["items"][0]["id"]
        cleared = clear_events(db, event_ids=[eid])
        self.assertEqual(cleared["deleted"], 1)
        res_after = query_merged_events(SimpleNamespace(event_bus=bus), db, paginated=True)
        self.assertEqual(len(res_after["items"]), 0)

    def test_sightings_provenance_enrollment_seed_relabel_and_sources(self) -> None:
        tmpdir, db = self._make_temp_db()
        cols = {r[1] for r in db._conn.execute("PRAGMA table_info(sightings)").fetchall()}
        self.assertIn("camera_id", cols)
        self.assertIn("run_id", cols)
        fake_ext = MagicMock()
        fake_ext.extract_crop.return_value = np.ones(608, dtype=np.float32)
        mgr = UniversalEnrollmentManager(db=db, extractor=fake_ext, crops_dir=tmpdir)
        out = mgr.enroll(name="Bob", crop=np.full((32, 32, 3), 200, dtype=np.uint8), camera_id="cam_front")
        sightings = db.get_sightings(entity_id=out["entity_id"])
        self.assertGreaterEqual(len(sightings), 1)
        self.assertEqual(sightings[0]["camera_id"], "cam_front")
        saved = db.save_video_run(
            "demo.mp4", report={},
            frame_detections=[{"frame": 0, "time": 0.0, "tracks": [{"track_id": 9, "bbox": [1, 2, 10, 10]}]}],
        )
        relabel_video_runs_on_entity_mutation(
            db, updated_entity_id=out["entity_id"], video_filename="demo.mp4", track_id=9,
        )
        run_sightings = db.get_sightings(entity_id=out["entity_id"], video_filename="demo.mp4")
        self.assertTrue(any(s.get("run_id") == saved["run_id"] for s in run_sightings))
        sources = list_all_sighting_sources(db, pool=SimpleNamespace(camera_configs={"cam_extra": {}}))
        self.assertTrue(any(s["source"] == "cam_extra" for s in sources))

    def test_scenario_storage_per_shape_yaml_upsert(self) -> None:
        tmpdir, db = self._make_temp_db()
        db.save_zone("cam1", "existing_zone", [[0, 0], [10, 0], [10, 10], [0, 10]])
        yaml_path = os.path.join(tmpdir, "scenarios.yaml")
        with open(yaml_path, "w", encoding="utf-8") as f:
            f.write(
                "cameras:\n  cam1:\n    zones:\n      - name: new_yaml_zone\n"
                "        polygon: [[20, 20], [40, 20], [40, 40], [20, 40]]\n"
            )
        scen = ScenarioManager(config_path=yaml_path, db=db)
        self.assertIn("existing_zone", scen.cameras["cam1"]["zones"])
        self.assertIn("new_yaml_zone", scen.cameras["cam1"]["zones"])
