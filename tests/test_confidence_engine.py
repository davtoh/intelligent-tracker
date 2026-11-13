"""Unit and Integration Tests for Long-Term ConfidenceEngine (Step 5 Milestone 2)."""

import os
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np

from intelligent_tracker.active_learning import ActiveLearningManager
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.memory import ConfidenceEngine, ConfidenceEvidence
from intelligent_tracker.pipeline import PipelineEngine
from intelligent_tracker.tracker import Track
from intelligent_tracker.world import CameraNode, WorldEntityBridge, WorldGraph


class DummyBrokenConfidenceEngine:
    def record_human_feedback(self, **_kwargs):
        raise RuntimeError("confidence failure")


class TestConfidenceEngine(unittest.TestCase):
    """Verify multi-modal calibration, decay, feedback, persistence, and wiring."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.db_path = os.path.join(self.tmpdir.name, "confidence.db")
        self.crops_dir = os.path.join(self.tmpdir.name, "crops")
        self.db = TrackerDB(self.db_path)
        self.addCleanup(self.db.close)
        self.alice_id = self.db.add_entity(name="Alice", category="staff")
        self.bob_id = self.db.add_entity(name="Bob", category="visitor")
        self.engine = ConfidenceEngine(
            db=self.db,
            streak_window_s=30.0,
            decay_grace_s=10.0,
            decay_half_life_s=60.0,
            decay_floor=0.10,
        )

    def test_cold_start_multimodal_streak_and_topology_prior_boost(self) -> None:
        """Consistent face+body sightings, streak, and topology prior raise confidence."""
        self.assertIsNone(self.engine.get_state(self.alice_id))
        self.assertEqual(self.engine.get_confidence(self.alice_id), 0.0)

        s_body_only = self.engine.record_observation(
            entity_id=self.bob_id, body_score=0.72, camera_id="cam_01", timestamp=100.0,
        )
        s_multimodal = self.engine.record_observation(
            ConfidenceEvidence(
                entity_id=self.alice_id, face_score=0.82, body_score=0.72,
                camera_id="cam_01", zone_id="entry", timestamp=100.0,
            )
        )
        self.assertGreater(s_multimodal.confidence, s_body_only.confidence)
        self.assertEqual(s_multimodal.streak_count, 1)

        s_streak = self.engine.record_observation(
            entity_id=self.alice_id, face_score=0.82, body_score=0.72,
            camera_id="cam_01", zone_id="entry", timestamp=105.0,
        )
        self.assertEqual(s_streak.streak_count, 2)
        self.assertGreater(s_streak.confidence, s_multimodal.confidence)

        s_prior = self.engine.record_observation(
            entity_id=self.alice_id, face_score=0.82, body_score=0.72,
            topology_prior=0.35, camera_id="cam_02", zone_id="hall", timestamp=110.0,
        )
        self.assertGreater(s_prior.confidence, s_streak.confidence)
        self.assertLessEqual(s_prior.confidence, 1.0)

    def test_ambiguity_penalty_recovery_and_staleness_decay(self) -> None:
        """Ambiguity lowers confidence, clean matches recover, and staleness decays."""
        s_clean = self.engine.record_observation(
            entity_id=self.alice_id, visual_similarity=0.82, camera_id="cam_01", timestamp=100.0,
        )
        s_ambig = self.engine.record_observation(
            entity_id=self.alice_id, visual_similarity=0.78, ambiguity=0.70,
            camera_id="cam_01", timestamp=102.0,
        )
        self.assertLess(s_ambig.confidence, s_clean.confidence)
        self.assertEqual(s_ambig.streak_count, 1)
        self.assertGreater(s_ambig.ambiguity_penalty, 0.0)

        s_recovered = self.engine.record_observation(
            entity_id=self.alice_id, visual_similarity=0.85, camera_id="cam_01", timestamp=104.0,
        )
        self.assertLess(s_recovered.ambiguity_penalty, s_ambig.ambiguity_penalty)
        self.assertGreater(s_recovered.confidence, s_ambig.confidence)

        # Within grace window -> unchanged; past half-life -> decayed toward floor.
        self.assertAlmostEqual(
            self.engine.get_confidence(self.alice_id, timestamp=110.0),
            s_recovered.confidence,
            places=5,
        )
        decayed_1hl = self.engine.get_confidence(self.alice_id, timestamp=174.0)
        decayed_3hl = self.engine.get_confidence(self.alice_id, timestamp=294.0)
        self.assertLess(decayed_1hl, s_recovered.confidence)
        self.assertLess(decayed_3hl, decayed_1hl)
        self.assertGreaterEqual(decayed_3hl, 0.10)

        # Observation after streak_window_s resets streak back to 1.
        s_reset = self.engine.record_observation(
            entity_id=self.alice_id, visual_similarity=0.85, camera_id="cam_01", timestamp=200.0,
        )
        self.assertEqual(s_reset.streak_count, 1)

    def test_persistence_across_tracker_db_restarts_and_list_states(self) -> None:
        """Calibrated state persists to SQLite and reloads on fresh TrackerDB + engine."""
        self.engine.record_observation(
            entity_id=self.alice_id, face_score=0.86, body_score=0.78,
            camera_id="cam_01", zone_id="lobby", timestamp=500.0,
        )
        self.engine.record_observation(
            entity_id=self.bob_id, visual_similarity=0.52,
            camera_id="cam_02", zone_id="gate", timestamp=500.0,
        )
        expected = self.engine.get_state(self.alice_id, timestamp=505.0)
        self.db.close()

        reloaded_db = TrackerDB(self.db_path)
        self.addCleanup(reloaded_db.close)
        reloaded_engine = ConfidenceEngine(
            db=reloaded_db, decay_grace_s=10.0, decay_half_life_s=60.0, decay_floor=0.10,
        )
        restored = reloaded_engine.get_state(self.alice_id, timestamp=505.0)
        self.assertIsNotNone(restored)
        self.assertAlmostEqual(restored.confidence, expected.confidence, places=5)
        self.assertEqual(restored.last_camera_id, "cam_01")
        self.assertEqual(restored.last_zone_id, "lobby")

        filtered = reloaded_engine.list_states(min_confidence=0.70, timestamp=505.0)
        self.assertEqual([s.entity_id for s in filtered], [self.alice_id])

    def test_active_learning_human_feedback_and_error_isolation(self) -> None:
        """Confirm/reassign/enroll/dismiss adjust confidence; broken engine won't break AL."""
        self.engine.record_observation(
            entity_id=self.alice_id, visual_similarity=0.60, camera_id="cam_01", timestamp=100.0,
        )
        self.engine.record_observation(
            entity_id=self.bob_id, visual_similarity=0.60, camera_id="cam_01", timestamp=100.0,
        )
        alice_before = self.engine.get_confidence(self.alice_id, timestamp=101.0)
        bob_before = self.engine.get_confidence(self.bob_id, timestamp=101.0)

        al_mgr = ActiveLearningManager(
            db=self.db, debounce_interval=0.0, crops_dir=self.crops_dir, confidence_engine=self.engine,
        )
        crop = np.zeros((64, 64, 3), dtype=np.uint8)
        item_c = al_mgr.maybe_queue_candidate("cam_01", 1, crop, 0.58, self.alice_id, "Alice", timestamp=102.0)
        self.assertEqual(al_mgr.confirm_candidate(item_c["id"])["status"], "confirmed")
        alice_after_confirm = self.engine.get_confidence(self.alice_id)
        self.assertGreater(alice_after_confirm, alice_before)

        item_r = al_mgr.maybe_queue_candidate("cam_01", 2, crop, 0.56, self.alice_id, "Alice", timestamp=103.0)
        self.assertEqual(al_mgr.reassign_candidate(item_r["id"], self.bob_id)["status"], "reassigned")
        self.assertGreater(self.engine.get_confidence(self.bob_id), bob_before)
        self.assertLess(self.engine.get_confidence(self.alice_id), alice_after_confirm)

        item_d = al_mgr.maybe_queue_candidate("cam_01", 3, crop, 0.55, self.bob_id, "Bob", timestamp=104.0)
        bob_before_dismiss = self.engine.get_confidence(self.bob_id)
        self.assertEqual(al_mgr.dismiss_candidate(item_d["id"])["status"], "dismissed")
        self.assertLess(self.engine.get_confidence(self.bob_id), bob_before_dismiss)

        item_e = al_mgr.maybe_queue_candidate("cam_01", 4, crop, 0.50, timestamp=105.0)
        res_e = al_mgr.enroll_as_new(item_e["id"], name="Charlie", category="guest")
        self.assertGreater(self.engine.get_confidence(res_e["entity_id"]), 0.70)

        # Direct payload callback, None entity, invalid action, and broken engine isolation
        self.assertIsNone(self.engine.record_human_feedback(None, "dismiss"))
        with self.assertRaises(ValueError):
            self.engine.record_human_feedback(self.alice_id, "invalid_action")
        self.assertIsNotNone(
            self.engine.handle_active_learning_feedback({"action": "confirm", "entity_id": self.alice_id, "item": {"similarity": 0.65}})
        )

        safe_al = ActiveLearningManager(
            db=self.db, debounce_interval=0.0, crops_dir=self.crops_dir,
            confidence_engine=DummyBrokenConfidenceEngine(),
        )
        item_safe = safe_al.maybe_queue_candidate("cam_01", 5, crop, 0.55, self.alice_id, "Alice", timestamp=106.0)
        self.assertTrue(safe_al.confirm(item_safe["id"]))

    def test_world_entity_bridge_and_pipeline_engine_wiring(self) -> None:
        """WorldEntityBridge updates WorldEntity.confidence and PipelineEngine wires subsystems."""
        graph = WorldGraph()
        graph.register_camera(CameraNode(camera_id="cam_01", name="Lobby"))
        bridge = WorldEntityBridge(graph, db=self.db, sync_interval=0.0, confidence_engine=self.engine)

        trk = Track(track_id=7, bbox=(10, 10, 40, 80), label="person", timestamp=200.0)
        trk.face_score = 0.84
        trk.body_score = 0.76
        trk.topology_prior = 0.25
        we1 = bridge.sync_track_identification(
            "cam_01", trk, self.alice_id, confidence=0.80, zone_id="entry", timestamp=200.0,
        )
        self.assertEqual(we1.confidence_breakdown["streak_count"], 1)
        we2 = bridge.sync_camera_tracks("cam_01", {7: trk}, zone_lookup={7: "entry"}, timestamp=201.0)[0]
        self.assertEqual(we2.confidence_breakdown["streak_count"], 2)
        self.assertGreater(we2.confidence, we1.confidence)

        # Non-existent entity_id (FK constraint) must not crash tracking
        ghost_trk = Track(track_id=8, bbox=(10, 10, 40, 80), label="person", timestamp=202.0)
        we_ghost = bridge.sync_track_identification("cam_01", ghost_trk, 999999, confidence=0.70, timestamp=202.0)
        self.assertGreater(we_ghost.confidence, 0.0)

        # Throttled persist_interval branch
        throttled = ConfidenceEngine(db=self.db, persist_interval=60.0)
        throttled.record_observation(entity_id=self.alice_id, visual_similarity=0.75, timestamp=300.0)
        throttled.record_observation(entity_id=self.alice_id, visual_similarity=0.80, timestamp=301.0)

        # PipelineEngine wiring (governance on + off)
        bundle_on = PipelineEngine.from_dict(
            {"camera_id": "cam_pipe", "detector": {"model": "mock"}},
            db_path=self.db_path, source_override=None, enable_governance=True,
        )
        self.addCleanup(bundle_on.close)
        self.assertIsNotNone(bundle_on.confidence_engine)
        self.assertIs(bundle_on.world_bridge.confidence_engine, bundle_on.confidence_engine)
        self.assertIs(bundle_on.active_learning.confidence_engine, bundle_on.confidence_engine)

        bundle_off = PipelineEngine.from_dict(
            {"camera_id": "cam_nogov", "detector": {"model": "mock"}},
            db_path=None, source_override=None, enable_governance=False,
        )
        self.addCleanup(bundle_off.close)
        self.assertIsNotNone(bundle_off.confidence_engine)
        self.assertIs(bundle_off.world_bridge.confidence_engine, bundle_off.confidence_engine)


if __name__ == "__main__":
    unittest.main()

