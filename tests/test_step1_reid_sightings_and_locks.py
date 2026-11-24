#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Isolated unit and integration tests for Milestone 1 (Re-ID, sightings, relabeling, locks)."""

import json
import os
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

import cv2
import numpy as np

from dashboard.dependencies import get_scenario_mgr, set_scenario_manager
from dashboard.routers.analytics import _delete_entity_sync, _enrich_sighting
from dashboard.services.cached_replay_provider import CachedReplayProvider
from dashboard.services.camera_config_store import CameraConfigStore
from dashboard.services.camera_source_bootstrap import retry_camera_connection
from dashboard.services.pipeline_factory import StreamPipelineFactory
from dashboard.services.roi_recognition_service import RoiRecognitionService, _resolve_roi_models
from dashboard.services.video_analytics_service import _teardown_indexer_bus, create_video_indexer
from dashboard.services.video_run_relabel_service import relabel_video_runs_on_entity_mutation
from intelligent_tracker.array_utils import draw_contour_groups
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.enrollment import UniversalEnrollmentManager
from intelligent_tracker.matching._gallery_signals import emit_periodic_sighting
from intelligent_tracker.matching.gallery import GalleryMatcher
from intelligent_tracker.memory.confidence import ConfidenceEngine
from intelligent_tracker.reid import DualModelFeatureExtractor
from intelligent_tracker.tracker import Track
from intelligent_tracker.world.graph import WorldGraph


def _make_synthetic_mp4(path: str, frames: int = 4, w: int = 160, h: int = 120) -> None:
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (w, h))
    try:
        for i in range(frames):
            img = np.zeros((h, w, 3), dtype=np.uint8)
            cv2.rectangle(img, (20 + i * 5, 20), (80 + i * 5, 100), (0, 200, 120), -1)
            writer.write(img)
    finally:
        writer.release()


class TestStep1ReidSightingsAndLocks(unittest.TestCase):
    """Verify DualModel parity, relabeling, sighting crops, feedback, and lock-free pool ops."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, "test.db")
        self.crops_dir = os.path.join(self._tmp.name, "crops")
        os.makedirs(self.crops_dir, exist_ok=True)
        self.db = TrackerDB(self.db_path)
        self.addCleanup(self.db.close)

    def test_dual_model_parity_and_shared_video_indexer_singletons(self) -> None:
        ext = DualModelFeatureExtractor()
        ce = ConfidenceEngine(db=self.db)
        wg = WorldGraph()
        opts = {"detector": "mock", "sample_rate": 2, "confidence": 0.3, "classes": None}
        indexer = create_video_indexer(self.db, opts, safe_name="clip.mp4", confidence_engine=ce, world_graph=wg)
        self.addCleanup(lambda: _teardown_indexer_bus(indexer))
        self.addCleanup(indexer.close)
        self.assertIs(indexer.confidence_engine, ce)
        self.assertIs(indexer.world_graph, wg)
        self.assertEqual(indexer.extractor.embedding_dim, ext.embedding_dim)
        bundle = StreamPipelineFactory.build({"type": "demo", "detector": {"model": "mock"}}, self.db_path, "cam_test")
        if getattr(bundle, "pipeline_bundle", None) is not None:
            self.addCleanup(bundle.pipeline_bundle.close)
        self.assertEqual(bundle.reid_extractor.embedding_dim, ext.embedding_dim)

    def test_enroll_video_indexer_relabel_and_replay_invalidation(self) -> None:
        crop = np.full((64, 48, 3), 140, dtype=np.uint8)
        enr = UniversalEnrollmentManager(db=self.db, crops_dir=self.crops_dir)
        res = enr.enroll("Alice", "person", crop=crop)
        eid = int(res["entity_id"])
        mp4 = os.path.join(self._tmp.name, "clip.mp4")
        _make_synthetic_mp4(mp4, frames=4)
        indexer = create_video_indexer(
            self.db, {"detector": "mock", "sample_rate": 1, "confidence": 0.1, "classes": None}, safe_name="clip.mp4"
        )
        self.addCleanup(lambda: _teardown_indexer_bus(indexer))
        self.addCleanup(indexer.close)
        summary = indexer.process_video(mp4, verbose=False)
        run = self.db.save_video_run(
            "clip.mp4", {"summary": "ok"}, {}, frame_detections=summary.get("frame_detections") or [{"frame": 0, "tracks": [{"track_id": 1, "bbox": [10, 10, 50, 90]}]}],
        )
        mock_provider = MagicMock(spec=CachedReplayProvider)
        mock_stream = MagicMock(_cached_replay_provider=mock_provider, replay_provider=None)
        pool = MagicMock(_lock=threading.RLock(), streams={"cam_1": mock_stream})
        updated = relabel_video_runs_on_entity_mutation(
            self.db, pool=pool, updated_entity_id=eid, video_filename="clip.mp4", track_id=1,
        )
        self.assertGreaterEqual(updated, 1)
        mock_provider.invalidate.assert_called()
        stream_data = self.db.get_video_detection_stream("clip.mp4", run["run_id"])
        self.assertEqual(stream_data["frame_detections"][0]["tracks"][0]["entity_id"], eid)

    def test_mismatched_signature_recomputed_from_crop_path(self) -> None:
        crop_path = os.path.join(self.crops_dir, "legacy.jpg")
        cv2.imwrite(crop_path, np.full((64, 48, 3), 180, dtype=np.uint8))
        eid = self.db.add_entity("Bob", "person")
        self.db.add_signature(eid, np.ones(96, dtype=np.float32), crop_path=crop_path)
        matcher = GalleryMatcher(db=self.db, extractor=DualModelFeatureExtractor())
        self.assertEqual(matcher.gallery_size, 1)
        self.assertEqual(matcher.gallery_matrix.shape[1], matcher.extractor.embedding_dim)

    def test_sighting_crop_and_entity_avatar_fallback(self) -> None:
        crop_path = os.path.join(self.crops_dir, "avatar.jpg")
        cv2.imwrite(crop_path, np.full((48, 32, 3), 200, dtype=np.uint8))
        eid = self.db.add_entity("Carol", "person")
        self.db.add_signature(eid, np.ones(16, dtype=np.float32), crop_path=crop_path)
        matcher = GalleryMatcher(db=self.db, extractor=None, sighting_interval=5.0)
        matcher.crops_dir = self.crops_dir
        trk = Track(track_id=7, bbox=(10, 10, 50, 70), label="person")
        frame = np.full((120, 160, 3), 90, dtype=np.uint8)
        self.assertTrue(emit_periodic_sighting(
            matcher, entity_id=eid, name="Carol", category="person", track=trk,
            confidence=0.9, source="cam_1", zone_id="", timestamp=100.0, frame=frame,
        ))
        sightings = self.db.query_sightings(entity_id=eid, limit=5)
        self.assertTrue(sightings[0]["snapshot_path"])
        enriched_auto = _enrich_sighting(sightings[0], self.db)
        self.assertTrue(enriched_auto["snapshot_url"].startswith("/crops/sighting_"))
        enriched_fallback = _enrich_sighting({"entity_id": eid, "track_id": 7, "snapshot_path": ""}, self.db)
        self.assertEqual(enriched_fallback["snapshot_url"], "/crops/avatar.jpg")

    def test_confidence_reject_roi_matching_and_pool_delete_reload(self) -> None:
        ce = ConfidenceEngine(db=self.db)
        eid = self.db.add_entity("Dave", "person")
        state = ce.record_human_feedback(eid, "reject", camera_id="cam_1", zone_id="manual_discourage")
        self.assertEqual(state.rejection_count, 1)
        self.assertEqual(state.last_camera_id, "cam_1")
        _, reid = _resolve_roi_models(None, None)
        self.assertEqual(reid.embedding_dim, DualModelFeatureExtractor().embedding_dim)
        crop = np.full((64, 48, 3), 120, dtype=np.uint8)
        svc = RoiRecognitionService(db=self.db, crops_dir=self.crops_dir)
        emb = reid.extract_crop(crop)
        self.db.add_signature(eid, emb)
        res = svc.match_crop_to_gallery(crop, reid_extractor=reid, threshold=0.65)
        self.assertTrue(res["is_known"])
        self.db.add_negative_exemplar(embedding=emb, entity_id=eid, label="false_pos")
        suppressed = svc.match_crop_to_gallery(crop, reid_extractor=reid, threshold=0.65)
        self.assertFalse(suppressed["is_known"])
        pool = MagicMock(_lock=threading.RLock(), streams={})
        out = _delete_entity_sync(self.db, None, eid, pool=pool)
        self.assertTrue(out["deleted"])
        pool.reload_all_galleries.assert_called_once()

    def test_lock_free_config_store_retry_di_and_array_utils(self) -> None:
        cfg_path = os.path.join(self._tmp.name, "cameras.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump([{"id": "c1", "name": "C1", "source": "0", "type": "webcam", "detector": "mock", "enabled": False}], f)
        store = CameraConfigStore(config_file=cfg_path)
        cfgs, seeded = store.load_cameras()
        self.assertFalse(seeded)
        self.assertEqual(cfgs["c1"]["detector"], "yolov8")
        pool = MagicMock(_lock=threading.RLock(), camera_configs={"c1": {"id": "c1", "enabled": False}})
        pool.get_stream.return_value = MagicMock(is_running=True)
        res = retry_camera_connection(pool, "c1")
        self.assertEqual(res["camera_id"], "c1")
        pool.save_cameras.assert_called_once()
        mock_conn = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=self.db, world_graph=WorldGraph(), scenario_manager=None)))
        set_scenario_manager(None)
        self.addCleanup(lambda: set_scenario_manager(None))
        scen = get_scenario_mgr(mock_conn)
        self.assertIs(scen.db, self.db)
        vis = draw_contour_groups([[np.array([[10, 10], [30, 10], [30, 30]], dtype=np.int32)]], shape=(50, 50), binary=False)
        self.assertEqual(vis.shape, (50, 50, 3))
