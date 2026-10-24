#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for GalleryMatcher & Re-Appearance Engine (intelligent_tracker/matcher.py).
"""

from __future__ import division, print_function, absolute_import

import unittest
import numpy as np

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.reid import MockFeatureExtractor
from intelligent_tracker.tracker import Track
from intelligent_tracker.matcher import GalleryMatcher, EntityIdentifiedEvent


class TestGalleryMatcher(unittest.TestCase):

    def setUp(self):
        self.db = TrackerDB(":memory:")
        self.extractor = MockFeatureExtractor(embedding_dim=16)
        self.matcher = GalleryMatcher(
            db=self.db,
            extractor=self.extractor,
            reid_threshold=0.70,
            feature_history_len=5,
            sighting_interval=2.0,
            min_track_hits=2,
        )

    def tearDown(self):
        self.db.close()

    def test_empty_gallery(self):
        """Empty gallery should not identify any tracks."""
        frame = np.full((100, 100, 3), 120, dtype=np.uint8)
        trk = Track(track_id=1, bbox=(10, 10, 40, 40))
        trk.hits = 3

        events = self.matcher.match_tracks({1: trk}, frame)
        self.assertEqual(len(events), 0)
        self.assertFalse(hasattr(trk, "entity_id"))

    def test_track_identification_and_event(self):
        """Enrolled entity should be recognized when matching track appears."""
        # 1. Create synthetic frame with distinct object
        frame = np.zeros((200, 200, 3), dtype=np.uint8)
        frame[20:80, 20:80] = [0, 255, 0]  # Green patch

        # 2. Enroll entity in database
        eid = self.db.add_entity(name="Alice", category="staff")
        feat = self.extractor.extract(frame, (20, 20, 60, 60))
        self.db.add_signature(eid, feat)
        self.matcher.reload_gallery()

        self.assertEqual(self.matcher.gallery_size, 1)

        # 3. Present track at the same visual location
        trk = Track(track_id=5, bbox=(20, 20, 60, 60), timestamp=100.0)
        trk.hits = 3

        # Match tracks
        events = self.matcher.match_tracks({5: trk}, frame, source="cam0", timestamp=100.0)
        self.assertEqual(len(events), 1)

        ev = events[0]
        self.assertIsInstance(ev, EntityIdentifiedEvent)
        self.assertEqual(ev.entity_id, eid)
        self.assertEqual(ev.name, "Alice")
        self.assertEqual(ev.track_id, 5)
        self.assertGreaterEqual(ev.similarity, 0.99)

        # Track should be decorated with entity metadata
        self.assertEqual(trk.entity_id, eid)
        self.assertEqual(trk.entity_name, "Alice")
        self.assertGreaterEqual(trk.reid_score, 0.99)

        # Sighting should be recorded in database
        sightings = self.db.get_sightings(entity_id=eid)
        self.assertEqual(len(sightings), 1)
        self.assertEqual(sightings[0]["track_id"], 5)
        self.assertEqual(sightings[0]["source"], "cam0")

    def test_sighting_debouncing(self):
        """Sightings should be throttled according to sighting_interval."""
        frame = np.full((100, 100, 3), 50, dtype=np.uint8)
        eid = self.db.add_entity(name="Bob", category="visitor")
        feat = self.extractor.extract(frame, (10, 10, 30, 30))
        self.db.add_signature(eid, feat)
        self.matcher.reload_gallery()

        trk = Track(track_id=10, bbox=(10, 10, 30, 30))
        trk.hits = 4

        # Frame 1 at t=10.0 -> Sighting logged
        self.matcher.match_tracks({10: trk}, frame, timestamp=10.0)
        self.assertEqual(len(self.db.get_sightings(entity_id=eid)), 1)

        # Frame 2 at t=10.5 -> Within cooldown (interval=2.0) -> No duplicate sighting
        self.matcher.match_tracks({10: trk}, frame, timestamp=10.5)
        self.assertEqual(len(self.db.get_sightings(entity_id=eid)), 1)

        # Frame 3 at t=12.5 -> Past cooldown -> Sighting logged
        self.matcher.match_tracks({10: trk}, frame, timestamp=12.5)
        self.assertEqual(len(self.db.get_sightings(entity_id=eid)), 2)

    def test_manual_reassignment(self):
        """Test manually reassigning a track to a different entity."""
        eid1 = self.db.add_entity(name="Unknown 1")
        eid2 = self.db.add_entity(name="VIP Charlie", category="vip")

        trk = Track(track_id=20, bbox=(10, 10, 30, 30))
        trk.hits = 3
        trk.entity_id = eid1
        trk.entity_name = "Unknown 1"

        reassigned = self.matcher.reassign_track(trk, eid2)
        self.assertTrue(reassigned)
        self.assertEqual(trk.entity_id, eid2)
        self.assertEqual(trk.entity_name, "VIP Charlie")
        self.assertEqual(trk.entity_category, "vip")


if __name__ == "__main__":
    unittest.main()
