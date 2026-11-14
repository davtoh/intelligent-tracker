#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit Tests for Split Human-in-the-Loop Active Learning (Step 5 Milestone 1)."""

import os
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np

from intelligent_tracker.active_learning import ActiveLearningManager
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.events import EventBus, ReviewItemQueuedEvent


class DummyExtractor:
    def extract_crop(self, crop):
        return np.ones(16, dtype=np.float32) * 0.25


class DummyMatcher:
    def __init__(self, with_extractor: bool = True):
        self.reloaded = False
        self.extractor = DummyExtractor() if with_extractor else None

    def reload_gallery(self):
        self.reloaded = True


class TestActiveLearning(unittest.TestCase):
    """Test suite for ActiveLearningManager triage, debouncing, and operator actions."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.db_path = os.path.join(self.tmp_dir.name, "test_al.db")
        self.crops_dir = os.path.join(self.tmp_dir.name, "crops")
        self.db = TrackerDB(self.db_path)
        self.addCleanup(self.db.close)
        self.event_bus = EventBus(capacity=100)
        self.matcher = DummyMatcher()
        self.feedback_events: list[dict] = []

        self.al_mgr = ActiveLearningManager(
            db=self.db,
            matcher=self.matcher,
            min_confidence=0.45,
            max_confidence=0.70,
            debounce_interval=5.0,
            crops_dir=self.crops_dir,
            event_bus=self.event_bus,
            on_feedback=self.feedback_events.append,
        )
        self.entity_id = self.db.add_entity(name="Alice", category="person")

    def test_queue_candidate_and_debounce(self):
        """Test candidate triage into review queue, boundary checks, and debounce."""
        dummy_crop = np.zeros((100, 100, 3), dtype=np.uint8)
        self.assertIsNone(
            self.al_mgr.maybe_queue_candidate("cam_01", 10, dummy_crop, similarity=0.44, timestamp=90.0)
        )
        self.assertIsNone(
            self.al_mgr.maybe_queue_candidate("cam_01", 10, dummy_crop, similarity=0.70, timestamp=91.0)
        )
        self.assertIsNone(
            self.al_mgr.maybe_queue_candidate("cam_01", 10, np.zeros((2, 2, 3), dtype=np.uint8), 0.55, timestamp=92.0)
        )

        queued_item = self.al_mgr.maybe_queue_candidate(
            camera_id="cam_01", track_id=10, crop=dummy_crop, similarity=0.58,
            matched_entity_id=self.entity_id, matched_entity_name="Alice",
            bbox=(10, 10, 100, 100), timestamp=100.0,
        )
        self.assertIsNotNone(queued_item)
        self.assertEqual(queued_item["status"], "pending")
        self.assertEqual(queued_item["track_id"], 10)
        self.assertEqual(len(self.al_mgr.list_pending()), 1)

        recent_events = self.event_bus.get_recent_events(limit=5)
        self.assertEqual(len(recent_events), 1)
        self.assertIsInstance(recent_events[0], ReviewItemQueuedEvent)

        self.assertIsNone(
            self.al_mgr.maybe_queue_candidate("cam_01", 10, dummy_crop, 0.59, self.entity_id, timestamp=101.0)
        )
        queued_2 = self.al_mgr.maybe_queue_candidate(
            "cam_01", 10, dummy_crop, 0.57, self.entity_id, timestamp=106.0
        )
        self.assertIsNotNone(queued_2)

    def test_consider_candidate_frame_crop_and_guards(self):
        """Test consider_candidate bounding-box cropping, guards, and debounce."""
        frame = np.full((120, 160, 3), 128, dtype=np.uint8)
        track = SimpleNamespace(track_id=77, bbox=(20, 20, 50, 60))

        self.assertIsNone(self.al_mgr.consider_candidate(track, frame, similarity=0.80, timestamp=50.0))
        self.assertIsNone(self.al_mgr.consider_candidate(SimpleNamespace(track_id=78, bbox=None), frame, 0.55, timestamp=50.0))
        self.assertIsNone(self.al_mgr.consider_candidate(SimpleNamespace(track_id=79, bbox=(0, 0, 2, 2)), frame, 0.55, timestamp=50.0))

        review_id = self.al_mgr.consider_candidate(
            track=track, frame=frame, similarity=0.60,
            suggested_entity_id=self.entity_id, suggested_name="Alice",
            suggested_category="person", camera_id="cam_02", timestamp=60.0,
        )
        self.assertIsNotNone(review_id)
        item = self.db.get_review_item(review_id)
        self.assertTrue(os.path.isfile(item["crop_path"]))
        emb = self.al_mgr._extract_crop_embedding(item["crop_path"])
        self.assertIsNotNone(emb)
        self.assertIsNone(self.al_mgr._extract_crop_embedding(os.path.join(self.crops_dir, "missing.jpg")))
        self.assertIsNone(self.al_mgr.consider_candidate(track, frame, 0.60, camera_id="cam_02", timestamp=61.0))

    def test_confirm_candidate_promotes_locked_anchor_and_feedback(self):
        """Confirming candidate promotes crop as a locked anchor and invokes on_feedback."""
        item = self.al_mgr.maybe_queue_candidate(
            "cam_01", 20, np.zeros((80, 80, 3), dtype=np.uint8), 0.55,
            matched_entity_id=self.entity_id, matched_entity_name="Alice", timestamp=200.0,
        )
        res = self.al_mgr.confirm_candidate(item_id=item["id"], notes="Verified")
        self.assertEqual(res["status"], "confirmed")
        self.assertTrue(self.matcher.reloaded)
        latest_sig = self.db.get_entity_signatures(self.entity_id)[-1]
        self.assertEqual((latest_sig["is_anchor"], latest_sig["locked"]), (1, 1))
        self.assertEqual(self.feedback_events[-1]["action"], "confirm")
        self.assertEqual(self.feedback_events[-1]["entity_id"], self.entity_id)

    def test_reassign_enroll_dismiss_and_error_branches(self):
        """Verify reassign, enroll_as_new, dismiss, legacy methods, and missing/invalid branches."""
        bob_id = self.db.add_entity(name="Bob", category="staff")
        crop = np.zeros((80, 80, 3), dtype=np.uint8)

        item_r = self.al_mgr.maybe_queue_candidate("cam_01", 30, crop, 0.52, self.entity_id, "Alice", timestamp=300.0)
        res_r = self.al_mgr.reassign_candidate(item_r["id"], bob_id, notes="Corrected")
        self.assertEqual(res_r["status"], "reassigned")
        self.assertEqual(len(self.db.get_entity_signatures(bob_id)), 1)
        self.assertEqual(self.feedback_events[-1]["previous_entity_id"], self.entity_id)

        item_e = self.al_mgr.maybe_queue_candidate("cam_01", 40, crop, 0.48, timestamp=400.0)
        res_e = self.al_mgr.enroll_as_new(item_e["id"], name="Charlie", category="visitor", security_role="lvl_1", notes="Guest")
        self.assertEqual(res_e["status"], "enrolled_new")
        self.assertEqual(self.db.get_entity(res_e["entity_id"])["name"], "Charlie")

        item_d = self.al_mgr.maybe_queue_candidate("cam_01", 50, crop, 0.46, self.entity_id, timestamp=500.0)
        res_d = self.al_mgr.dismiss_candidate(item_d["id"], notes="Shadow")
        self.assertEqual(res_d["status"], "dismissed")
        self.assertEqual(self.db.get_review_item(item_d["id"])["status"], "dismissed")

        # Missing & invalid branches + legacy direct methods
        self.assertEqual(self.al_mgr.confirm_candidate(99999)["status"], "not_found")
        self.assertEqual(self.al_mgr.confirm_candidate(item_e["id"])["status"], "failed")
        self.assertEqual(self.al_mgr.reassign_candidate(99999, bob_id)["status"], "not_found")
        self.assertEqual(self.al_mgr.reassign_candidate(item_d["id"], 99999)["status"], "failed")
        self.assertEqual(self.al_mgr.enroll_as_new(99999, "Nobody")["status"], "not_found")
        self.assertEqual(self.al_mgr.dismiss_candidate(99999)["status"], "not_found")
        self.assertFalse(self.al_mgr.confirm(99999))
        self.assertFalse(self.al_mgr.dismiss(99999))
        with self.assertRaises(AttributeError):
            _ = self.al_mgr.non_existent_method

    def test_feedback_callback_exception_is_isolated(self):
        """A failing on_feedback hook must not break operator DB resolution."""
        def broken_hook(_payload):
            raise RuntimeError("boom")

        mgr = ActiveLearningManager(
            db=self.db, matcher=DummyMatcher(with_extractor=False),
            debounce_interval=1.0, crops_dir=self.crops_dir, on_feedback=broken_hook,
        )
        item = mgr.maybe_queue_candidate(
            "cam_03", 99, np.zeros((32, 32, 3), dtype=np.uint8), 0.55, self.entity_id, timestamp=700.0
        )
        self.assertTrue(mgr.confirm(item["id"]))
        self.assertEqual(self.db.get_review_item(item["id"])["status"], "confirmed")


if __name__ == "__main__":
    unittest.main()
