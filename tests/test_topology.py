#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for CrossCameraTopology & Re-ID Spatial Prior Boosting (intelligent_tracker/topology.py).
"""

import time
import unittest
import numpy as np

from intelligent_tracker.topology import (
    SpatialTransitionLink,
    ActiveSpatialPrior,
    CrossCameraTopology,
)
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.reid import MockFeatureExtractor
from intelligent_tracker.tracker import Track
from intelligent_tracker.matcher import GalleryMatcher


class TestCrossCameraTopology(unittest.TestCase):

    def setUp(self):
        self.topology = CrossCameraTopology()
        self.link = SpatialTransitionLink(
            link_id="link_cam1_cam2",
            source_camera="cam_01",
            source_zone="Door Exit",
            target_camera="cam_02",
            target_zone="Door Entrance",
            t_min=2.0,
            t_max=10.0,
            prior_boost=0.35,
            bidirectional=True,
            active=True,
        )
        self.topology.add_link(self.link)

    def test_bidirectional_link_registration(self):
        """Registering a bidirectional link should also create the reverse link."""
        links = self.topology.list_links()
        self.assertEqual(len(links), 2)
        link_ids = [l.link_id for l in links]
        self.assertIn("link_cam1_cam2", link_ids)
        self.assertIn("link_cam1_cam2_rev", link_ids)

        rev = self.topology.links["link_cam1_cam2_rev"]
        self.assertEqual(rev.source_camera, "cam_02")
        self.assertEqual(rev.source_zone, "Door Entrance")
        self.assertEqual(rev.target_camera, "cam_01")
        self.assertEqual(rev.target_zone, "Door Exit")

    def test_remove_link(self):
        """Removing link should also remove the reverse link."""
        removed = self.topology.remove_link("link_cam1_cam2")
        self.assertTrue(removed)
        self.assertEqual(len(self.topology.list_links()), 0)

    def test_record_zone_exit_spawns_active_prior(self):
        """Zone exit event on source camera should instantiate ActiveSpatialPrior for target camera."""
        now = 1000.0
        priors = self.topology.record_zone_exit(
            camera_id="cam_01",
            zone_name="Door Exit",
            entity_name="Alice",
            entity_id=101,
            timestamp=now,
        )
        self.assertEqual(len(priors), 1)
        prior = priors[0]
        self.assertEqual(prior.entity_name, "Alice")
        self.assertEqual(prior.entity_id, 101)
        self.assertEqual(prior.target_camera, "cam_02")
        self.assertEqual(prior.target_zone, "Door Entrance")
        self.assertEqual(prior.window_start, 1002.0)
        self.assertEqual(prior.window_end, 1010.0)
        self.assertEqual(prior.prior_boost, 0.35)

    def test_transit_window_validation_and_expiration(self):
        """Priors should only be valid during [window_start, window_end] and expire after."""
        now = 1000.0
        priors = self.topology.record_zone_exit(
            camera_id="cam_01",
            zone_name="Door Exit",
            entity_name="Bob",
            entity_id=102,
            timestamp=now,
        )
        prior = priors[0]

        # Before transit window: t = 1001.0 (< 1002.0)
        self.assertFalse(prior.is_valid_at(1001.0))
        self.assertFalse(prior.is_expired_at(1001.0))

        # Inside transit window: t = 1005.0
        self.assertTrue(prior.is_valid_at(1005.0))
        self.assertFalse(prior.is_expired_at(1005.0))

        # After transit window: t = 1011.0 (> 1010.0)
        self.assertFalse(prior.is_valid_at(1011.0))
        self.assertTrue(prior.is_expired_at(1011.0))

    def test_get_active_priors_and_cleanup(self):
        """get_active_priors should return valid priors and purge expired ones."""
        now = 1000.0
        self.topology.record_zone_exit(
            camera_id="cam_01",
            zone_name="Door Exit",
            entity_name="Charlie",
            entity_id=103,
            timestamp=now,
        )
        # Query during transit window
        active = self.topology.get_active_priors("cam_02", "Door Entrance", timestamp=1005.0)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].entity_name, "Charlie")

        # Query after expiration
        expired = self.topology.get_active_priors("cam_02", "Door Entrance", timestamp=1020.0)
        self.assertEqual(len(expired), 0)
        # Active list in topology should now be pruned
        self.assertEqual(len(self.topology.active_priors), 0)

    def test_compute_weighted_similarity_boost(self):
        """Weighted similarity should apply prior_boost when entity matches active prior."""
        now = 1000.0
        self.topology.record_zone_exit(
            camera_id="cam_01",
            zone_name="Door Exit",
            entity_name="Diana",
            entity_id=104,
            timestamp=now,
        )

        # Visual similarity is 0.60 (below 0.70 threshold)
        vis_score = 0.60
        # Check during valid window: 0.60 + 0.35 boost = 0.95
        weighted, prior = self.topology.compute_weighted_similarity(
            visual_similarity=vis_score,
            candidate_entity_id=104,
            candidate_name="Diana",
            target_camera="cam_02",
            target_zone="Door Entrance",
            timestamp=1005.0,
        )
        self.assertIsNotNone(prior)
        self.assertAlmostEqual(weighted, 0.95, places=2)

        # For an unrelated candidate entity, no boost should be applied
        other_score, other_prior = self.topology.compute_weighted_similarity(
            visual_similarity=vis_score,
            candidate_entity_id=999,
            candidate_name="Unknown",
            target_camera="cam_02",
            target_zone="Door Entrance",
            timestamp=1005.0,
        )
        self.assertIsNone(other_prior)
        self.assertAlmostEqual(other_score, vis_score, places=2)

    def test_consume_prior(self):
        """Consumed prior is marked and no longer valid."""
        priors = self.topology.record_zone_exit(
            camera_id="cam_01",
            zone_name="Door Exit",
            entity_name="Eve",
            entity_id=105,
            timestamp=1000.0,
        )
        p_id = priors[0].prior_id
        consumed = self.topology.consume_prior(p_id)
        self.assertTrue(consumed)
        self.assertTrue(priors[0].consumed)
        self.assertFalse(priors[0].is_valid_at(1005.0))


class TestTopologyMatcherIntegration(unittest.TestCase):

    def setUp(self):
        self.db = TrackerDB(":memory:")
        self.extractor = MockFeatureExtractor(embedding_dim=16)
        self.topology = CrossCameraTopology()
        self.topology.add_link(
            SpatialTransitionLink(
                link_id="l1",
                source_camera="cam_01",
                source_zone="Exit",
                target_camera="cam_02",
                target_zone="Entrance",
                t_min=1.0,
                t_max=10.0,
                prior_boost=0.35,
            )
        )
        self.matcher = GalleryMatcher(
            db=self.db,
            extractor=self.extractor,
            reid_threshold=0.75,
            topology=self.topology,
            camera_id="cam_02",
        )

    def tearDown(self):
        self.db.close()

    def test_matcher_prior_elevation(self):
        """Entity identification in target camera is boosted above threshold by topological prior."""
        # 1. Enroll entity in DB
        eid = self.db.add_entity(name="Frank", category="staff")
        base_feature = np.zeros(16, dtype=np.float32)
        base_feature[0] = 1.0  # Unit vector along axis 0
        self.db.add_signature(eid, base_feature)
        self.matcher.reload_gallery()

        # 2. Candidate feature with cosine similarity ~0.65 (< 0.75 threshold)
        cand_feature = np.zeros(16, dtype=np.float32)
        cand_feature[0] = 0.65
        cand_feature[1] = np.sqrt(1.0 - 0.65**2)
        self.extractor.extract = lambda f, b: cand_feature

        trk = Track(track_id=10, bbox=(10, 10, 50, 50), timestamp=105.0)
        trk.hits = 3
        trk.current_zone = "Entrance"
        frame = np.zeros((100, 100, 3), dtype=np.uint8)

        # 3. Without prior: match should fail because 0.65 < 0.75
        events = self.matcher.match_tracks({10: trk}, frame, timestamp=105.0)
        self.assertEqual(len(events), 0)
        self.assertFalse(hasattr(trk, "entity_id"))

        # 4. Trigger zone exit on cam_01 at t=100.0 -> valid window on cam_02 is [101.0, 110.0]
        self.topology.record_zone_exit(
            camera_id="cam_01",
            zone_name="Exit",
            entity_name="Frank",
            entity_id=eid,
            timestamp=100.0,
        )

        # 5. Now matching track at t=105.0 in Entrance zone: score = min(1.0, 0.65 + 0.35) = 1.00 >= 0.75
        events2 = self.matcher.match_tracks({10: trk}, frame, timestamp=105.0)
        self.assertEqual(len(events2), 1)
        self.assertEqual(events2[0].entity_id, eid)
        self.assertEqual(trk.entity_id, eid)
        self.assertGreaterEqual(trk.reid_score, 0.75)


if __name__ == "__main__":
    unittest.main()
