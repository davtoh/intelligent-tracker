"""Unit and integration tests for gallery confidence signals and periodic FTS sighting indexing."""

import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.matcher import GalleryMatcher
from intelligent_tracker.matching._gallery_signals import (
    compute_modality_scores,
    compute_reid_ambiguity,
    compute_topology_prior_signal,
)
from intelligent_tracker.memory import ConfidenceEngine, EventFTSIndex
from intelligent_tracker.pipeline import PipelineEngine
from intelligent_tracker.reid import BaseFeatureExtractor
from intelligent_tracker.tracker import Track
from intelligent_tracker.world import CameraNode, WorldEntityBridge, WorldGraph


class _StubSubExtractor(BaseFeatureExtractor):
    """Fixed-dimension stub extractor for testing dual-modality slicing."""

    def __init__(self, dim: int, vec: np.ndarray) -> None:
        self._dim = dim
        self._vec = vec.astype(np.float32)

    @property
    def embedding_dim(self) -> int:
        return self._dim

    def extract_crop(self, crop: np.ndarray) -> np.ndarray:
        return self._vec.copy()


class _StubDualExtractor(BaseFeatureExtractor):
    """Lightweight dual extractor stub exposing primary_extractor and face_extractor."""

    def __init__(self, body_vec: np.ndarray, face_vec: np.ndarray) -> None:
        self.primary_extractor = _StubSubExtractor(len(body_vec), body_vec)
        self.face_extractor = _StubSubExtractor(len(face_vec), face_vec)
        self._fused = np.concatenate([body_vec, face_vec]).astype(np.float32)
        norm = float(np.linalg.norm(self._fused))
        if norm > 1e-7:
            self._fused = self._fused / norm

    @property
    def embedding_dim(self) -> int:
        return int(self._fused.shape[0])

    def extract_crop(self, crop: np.ndarray) -> np.ndarray:
        return self._fused.copy()


class TestGallerySignals(unittest.TestCase):
    """Verify modality sub-scores, ambiguity margins, topology prior signals, and FTS sighting hooks."""

    def test_reid_ambiguity_handles_same_entity_duplicates_and_rivals(self) -> None:
        """Ambiguity ignores extra signatures of the winning entity and scores close rivals."""
        self.assertEqual(compute_reid_ambiguity(np.array([0.90]), 0, [1]), 0.0)
        self.assertEqual(compute_reid_ambiguity(np.array([0.92, 0.91]), 0, [1, 1]), 0.0)
        self.assertEqual(compute_reid_ambiguity(np.array([0.90, 0.30]), 0, [1, 2]), 0.0)
        self.assertEqual(compute_reid_ambiguity(np.array([0.30, -0.50]), 0, [1, 2]), 0.0)

        high_amb = compute_reid_ambiguity(np.array([0.80, 0.76]), 0, [1, 2], margin_scale=0.20)
        self.assertAlmostEqual(high_amb, 0.80, places=4)
        exact_tie = compute_reid_ambiguity(np.array([0.80, 0.80]), 0, [1, 2], margin_scale=0.20)
        self.assertAlmostEqual(exact_tie, 1.0, places=4)

    def test_modality_scores_and_topology_prior_signal(self) -> None:
        """Dual extractors compute body+face cosines; zero face vectors stay 0.0."""
        body = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        face = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)
        dual = _StubDualExtractor(body, face)
        q_vec = dual.extract_crop(np.zeros((10, 10, 3), dtype=np.uint8))

        face_s, body_s = compute_modality_scores(dual, q_vec, q_vec, 0.99)
        self.assertAlmostEqual(face_s, 1.0, places=4)
        self.assertAlmostEqual(body_s, 1.0, places=4)

        no_face_gal = np.concatenate([body, np.zeros_like(face)]).astype(np.float32)
        face_zero, body_only = compute_modality_scores(dual, q_vec, no_face_gal, 0.7)
        self.assertEqual(face_zero, 0.0)
        self.assertAlmostEqual(body_only, 1.0, places=4)

        single_f, single_b = compute_modality_scores(_StubSubExtractor(4, body), body, body, 0.82)
        self.assertEqual(single_f, 0.0)
        self.assertAlmostEqual(single_b, 0.82, places=4)

        self.assertEqual(compute_topology_prior_signal(None, 0.7, 0.7), 0.0)
        prior_obj = SimpleNamespace(prior_boost=0.12, probability=0.45)
        self.assertAlmostEqual(compute_topology_prior_signal(prior_obj, 0.70, 0.82), 0.12, places=4)

    def test_gallery_matcher_wires_signals_and_indexes_periodic_sightings(self) -> None:
        """GalleryMatcher forwards signals to ConfidenceEngine and indexes debounced FTS sightings."""
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        db = TrackerDB(os.path.join(tmpdir.name, "signals.db"))
        self.addCleanup(db.close)

        alice_id = db.add_entity("Alice", category="staff")
        bob_id = db.add_entity("Bob", category="visitor")
        body_a = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        face_a = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)
        ext = _StubDualExtractor(body_a, face_a)
        alice_vec = ext.extract_crop(np.zeros((16, 16, 3), dtype=np.uint8))
        # Close rival for Bob (similarity ~0.95) to create non-zero ambiguity
        bob_vec = np.array([0.95, 0.0, 0.10, 0.0, 0.0, 0.85, 0.0, 0.0], dtype=np.float32)
        bob_vec = bob_vec / float(np.linalg.norm(bob_vec))
        db.add_signature(alice_id, alice_vec)
        db.add_signature(bob_id, bob_vec)

        conf_engine = ConfidenceEngine(db=db, persist_interval=0.0)
        fts = EventFTSIndex(db=db, auto_attach=False)
        graph = WorldGraph()
        graph.register_camera(CameraNode(camera_id="cam_01", name="Entry"))
        bridge = WorldEntityBridge(graph, confidence_engine=conf_engine)
        matcher = GalleryMatcher(
            db=db,
            extractor=ext,
            reid_threshold=0.50,
            min_track_hits=1,
            sighting_interval=5.0,
            camera_id="cam_01",
            world_bridge=bridge,
            fts_index=fts,
        )

        frame = np.full((64, 64, 3), 128, dtype=np.uint8)
        trk = Track(track_id=10, bbox=(5, 5, 30, 50), label="person", timestamp=100.0)
        trk.hits = 2
        ev = matcher.match_track(trk, frame, source="cam_01", timestamp=100.0, zone_id="lobby")
        self.assertIsNotNone(ev)
        self.assertGreater(trk.face_score, 0.9)
        self.assertGreater(trk.body_score, 0.9)
        self.assertGreater(trk.reid_ambiguity, 0.0)

        hits_1 = db.search_timeline_events(query="Alice", event_type="sighting")
        self.assertEqual(len(hits_1), 1)
        self.assertEqual(hits_1[0]["zone_id"], "lobby")

        # Inside sighting_interval -> debounced (no second sighting row)
        matcher.match_track(trk, frame, source="cam_01", timestamp=102.0, zone_id="lobby")
        self.assertEqual(len(db.search_timeline_events(query="Alice", event_type="sighting")), 1)

        # Past sighting_interval -> indexes second sighting
        matcher.match_track(trk, frame, source="cam_01", timestamp=106.0, zone_id="lobby")
        self.assertEqual(len(db.search_timeline_events(query="Alice", event_type="sighting")), 2)

        # FTS index error isolation must not break matching or DB sightings
        with patch.object(fts, "index_sighting", side_effect=RuntimeError("fts boom")):
            matcher.match_track(trk, frame, source="cam_01", timestamp=112.0, zone_id="lobby")
        self.assertEqual(len(db.get_sightings(entity_id=alice_id)), 3)

    def test_pipeline_reid_none_with_governance_skips_onnx_model_load(self) -> None:
        """Disabling Re-ID (model='none') must not instantiate OnnxReIDExtractor for enrollment."""
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        db_path = os.path.join(tmpdir.name, "no_onnx.db")
        with patch("intelligent_tracker.reid.onnx_extractor.OnnxReIDExtractor.__init__", side_effect=AssertionError("ONNX should not load")):
            bundle = PipelineEngine.from_dict(
                {"video": {"source": "synthetic"}, "detector": {"model": "mock"}, "reid": {"model": "none"}},
                db_path=db_path,
                enable_governance=True,
                enable_event_bus_fallback=True,
            )
            self.addCleanup(bundle.close)
        self.assertIsNotNone(bundle.enrollment_manager)
        self.assertIsNotNone(bundle.gallery_matcher) if bundle.reid_extractor else self.assertIsNone(bundle.gallery_matcher)


if __name__ == "__main__":
    unittest.main()
