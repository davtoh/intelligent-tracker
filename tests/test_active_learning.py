#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Unit Tests for Human-in-the-Loop Active Learning (Milestone 9).
"""

import os
import tempfile
import unittest
import numpy as np

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.events import EventBus, ReviewItemQueuedEvent
from intelligent_tracker.active_learning import ActiveLearningManager


class DummyMatcher:
    def __init__(self):
        self.reloaded = False

    def reload_gallery(self):
        self.reloaded = True

    def extract_features(self, crop):
        return np.ones(128, dtype=np.float32) / np.sqrt(128)


class TestActiveLearning(unittest.TestCase):
    """Test suite for ActiveLearningManager triage, debouncing, and operator actions."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_al.db")
        self.crops_dir = os.path.join(self.tmp_dir, "crops")
        os.makedirs(self.crops_dir, exist_ok=True)
        self.db = TrackerDB(self.db_path)
        self.event_bus = EventBus(capacity=100)
        self.matcher = DummyMatcher()

        self.al_mgr = ActiveLearningManager(
            db=self.db,
            matcher=self.matcher,
            min_confidence=0.45,
            max_confidence=0.70,
            debounce_interval=5.0,
            crops_dir=self.crops_dir,
            event_bus=self.event_bus,
        )

        # Seed an entity
        self.entity_id = self.db.add_entity(name="Alice", category="person")

    def tearDown(self):
        self.db.close()
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_queue_candidate_and_debounce(self):
        """Test candidate triage into review queue and debounce prevention."""
        dummy_crop = np.zeros((100, 100, 3), dtype=np.uint8)

        # Candidate with ambiguous similarity 0.58
        queued_item = self.al_mgr.maybe_queue_candidate(
            camera_id="cam_01",
            track_id=10,
            crop=dummy_crop,
            similarity=0.58,
            matched_entity_id=self.entity_id,
            matched_entity_name="Alice",
            bbox=(10, 10, 100, 100),
            timestamp=100.0,
        )
        self.assertIsNotNone(queued_item)
        self.assertEqual(queued_item["status"], "pending")
        self.assertEqual(queued_item["track_id"], 10)

        # Event bus received ReviewItemQueuedEvent
        recent_events = self.event_bus.get_recent_events(limit=5)
        self.assertEqual(len(recent_events), 1)
        self.assertIsInstance(recent_events[0], ReviewItemQueuedEvent)
        self.assertEqual(recent_events[0].track_id, 10)

        # Immediate next frame at timestamp 101.0 should be debounced
        debounced_item = self.al_mgr.maybe_queue_candidate(
            camera_id="cam_01",
            track_id=10,
            crop=dummy_crop,
            similarity=0.59,
            matched_entity_id=self.entity_id,
            timestamp=101.0,
        )
        self.assertIsNone(debounced_item)

        # After debounce interval expires (106.0 > 100.0 + 5.0), another candidate can be queued
        queued_item_2 = self.al_mgr.maybe_queue_candidate(
            camera_id="cam_01",
            track_id=10,
            crop=dummy_crop,
            similarity=0.57,
            matched_entity_id=self.entity_id,
            timestamp=106.0,
        )
        self.assertIsNotNone(queued_item_2)

    def test_confirm_candidate_promotes_locked_anchor(self):
        """Confirming candidate promotes crop as a locked ground-truth anchor."""
        dummy_crop = np.zeros((80, 80, 3), dtype=np.uint8)
        item = self.al_mgr.maybe_queue_candidate(
            camera_id="cam_01",
            track_id=20,
            crop=dummy_crop,
            similarity=0.55,
            matched_entity_id=self.entity_id,
            matched_entity_name="Alice",
            timestamp=200.0,
        )

        res = self.al_mgr.confirm_candidate(item_id=item["id"], notes="Verified by operator")
        self.assertEqual(res["status"], "confirmed")
        self.assertTrue(self.matcher.reloaded)

        # Verify signature created with locked anchor
        signatures = self.db.get_entity_signatures(self.entity_id)
        self.assertGreaterEqual(len(signatures), 1)
        latest_sig = signatures[-1]
        self.assertEqual(latest_sig["is_anchor"], 1)
        self.assertEqual(latest_sig["locked"], 1)

    def test_reassign_candidate(self):
        """Reassigning candidate transfers visual crop to target entity."""
        target_entity_id = self.db.add_entity(name="Bob", category="staff")
        dummy_crop = np.zeros((80, 80, 3), dtype=np.uint8)

        item = self.al_mgr.maybe_queue_candidate(
            camera_id="cam_01",
            track_id=30,
            crop=dummy_crop,
            similarity=0.52,
            matched_entity_id=self.entity_id,
            matched_entity_name="Alice",
            timestamp=300.0,
        )

        res = self.al_mgr.reassign_candidate(
            item_id=item["id"],
            target_entity_id=target_entity_id,
            notes="Mistaken identity corrected",
        )
        self.assertEqual(res["status"], "reassigned")

        # Bob received the signature
        bob_sigs = self.db.get_entity_signatures(target_entity_id)
        self.assertEqual(len(bob_sigs), 1)
        self.assertEqual(bob_sigs[0]["is_anchor"], 1)

    def test_enroll_as_new(self):
        """Enrolling as new creates a fresh entity profile with initial locked signature."""
        dummy_crop = np.zeros((80, 80, 3), dtype=np.uint8)
        item = self.al_mgr.maybe_queue_candidate(
            camera_id="cam_01",
            track_id=40,
            crop=dummy_crop,
            similarity=0.48,
            timestamp=400.0,
        )

        res = self.al_mgr.enroll_as_new(
            item_id=item["id"],
            name="Charlie",
            category="visitor",
            security_role="lvl_1",
            notes="New visitor enrolled from review",
        )
        self.assertEqual(res["status"], "enrolled_new")
        new_id = res["entity_id"]
        charlie = self.db.get_entity(new_id)
        self.assertIsNotNone(charlie)
        self.assertEqual(charlie["name"], "Charlie")

    def test_dismiss_candidate(self):
        """Dismissing candidate marks status as dismissed without mutating gallery."""
        dummy_crop = np.zeros((80, 80, 3), dtype=np.uint8)
        item = self.al_mgr.maybe_queue_candidate(
            camera_id="cam_01",
            track_id=50,
            crop=dummy_crop,
            similarity=0.46,
            matched_entity_id=self.entity_id,
            timestamp=500.0,
        )

        res = self.al_mgr.dismiss_candidate(item_id=item["id"], notes="Ambiguous shadow")
        self.assertEqual(res["status"], "dismissed")

        # Ensure review item status updated in DB
        db_item = self.db.get_review_item(item["id"])
        self.assertEqual(db_item["status"], "dismissed")


if __name__ == "__main__":
    unittest.main()
