#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Unit Tests for Occlusion Reasoning, Bounded EMA & Rollback (Milestone 9).
"""

import os
import tempfile
import unittest
import numpy as np

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.tracker import Track, check_track_occlusions
from intelligent_tracker.reid import ColorHistogramExtractor
from intelligent_tracker.matcher import GalleryMatcher


class TestOcclusionAndEMA(unittest.TestCase):
    """Test suite for track occlusion reasoning, bounded EMA adaptation, and memory rollback."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_ema.db")
        self.db = TrackerDB(self.db_path)
        self.extractor = ColorHistogramExtractor(bins=(8, 8, 8))
        self.matcher = GalleryMatcher(
            db=self.db,
            extractor=self.extractor,
            reid_threshold=0.65,
            ema_alpha=0.08,
            max_drift_threshold=0.65,
        )

    def tearDown(self):
        self.db.close()
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_check_track_occlusions(self):
        """Verify IoU overlap detection flags and unflags cluttered tracks."""
        # Two tracks with high overlap (IoU ~ 0.5)
        # Track 1: [50, 50, 100, 100], area = 10000
        # Track 2: [80, 50, 100, 100], intersection = 70 * 100 = 7000, union = 20000 - 7000 = 13000 -> IoU = 0.538
        t1 = Track(track_id=1, centroid=(100, 100), bbox=(50, 50, 100, 100))
        t2 = Track(track_id=2, centroid=(130, 100), bbox=(80, 50, 100, 100))
        tracks = {1: t1, 2: t2}

        check_track_occlusions(tracks, iou_threshold=0.3, separation_iou=0.1, timestamp=10.0)
        self.assertTrue(t1.is_cluttered)
        self.assertTrue(t2.is_cluttered)
        self.assertEqual(t1.clutter_partner_id, 2)
        self.assertEqual(t2.clutter_partner_id, 1)

        # Move Track 2 away so IoU becomes 0.0
        t2.bbox = (250, 50, 100, 100)
        t2.centroid = (300, 100)

        check_track_occlusions(tracks, iou_threshold=0.3, separation_iou=0.1, timestamp=12.0)
        self.assertFalse(t1.is_cluttered)
        self.assertFalse(t2.is_cluttered)
        self.assertIsNone(t1.clutter_partner_id)
        self.assertIsNone(t2.clutter_partner_id)

    def test_clutter_freezes_reid_updates(self):
        """When track.is_cluttered is True, Re-ID feature accumulation is frozen."""
        t1 = Track(track_id=1, centroid=(100, 100), bbox=(50, 50, 100, 100))
        t1.is_cluttered = True
        tracks = {1: t1}

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        events = self.matcher.match_tracks(tracks, frame)
        # No re-id events should be emitted for cluttered track
        self.assertEqual(len(events), 0)

    def test_bounded_ema_adaptation_and_drift_rejection(self):
        """Verify bounded EMA adaptation occurs for consistent observations but rejects drift."""
        # Enroll an entity with locked anchor
        ent_id = self.db.add_entity(name="Alice", category="vip")
        anchor_vec = np.zeros(512, dtype=np.float32)
        anchor_vec[0] = 1.0  # Unit vector along index 0

        self.db.add_entity_signature(
            entity_id=ent_id,
            feature_vector=anchor_vec,
            is_anchor=1,
            locked=1,
        )
        self.db.record_descriptor_version(
            entity_id=ent_id,
            feature_vector=anchor_vec,
            version=1,
            update_reason="locked_anchor",
            is_anchor=1,
        )
        self.matcher.reload_gallery()

        # Step 1: Slightly varied observation (similarity ~ 0.95 with anchor)
        obs_vec_close = np.copy(anchor_vec)
        obs_vec_close[1] = 0.3
        obs_vec_close /= np.linalg.norm(obs_vec_close)

        updated_ok = self.matcher._apply_bounded_ema_update(
            entity_id=ent_id,
            candidate_features=obs_vec_close,
            track_confidence=0.9,
        )
        self.assertTrue(updated_ok)

        # Step 2: Drastic appearance change (similarity ~ 0.0 with anchor)
        obs_vec_drift = np.zeros(512, dtype=np.float32)
        obs_vec_drift[100] = 1.0  # Orthogonal vector

        updated_drift = self.matcher._apply_bounded_ema_update(
            entity_id=ent_id,
            candidate_features=obs_vec_drift,
            track_confidence=0.9,
        )
        # Should be rejected because similarity to locked anchor drops below drift threshold (0.65)
        self.assertFalse(updated_drift)

    def test_descriptor_snapshot_and_rollback(self):
        """Test snapshot creation and rolling back to version 1."""
        ent_id = self.db.add_entity(name="Bob", category="staff")
        v1_vec = np.zeros(128, dtype=np.float32)
        v1_vec[0] = 1.0

        sig_id = self.db.add_entity_signature(
            entity_id=ent_id,
            feature_vector=v1_vec,
            is_anchor=1,
            locked=1,
        )
        self.db.record_descriptor_version(
            entity_id=ent_id,
            feature_vector=v1_vec,
            version=1,
            update_reason="initial_locked_anchor",
            is_anchor=1,
        )

        # Mutate signature to v2 (corrupted/drifted state)
        v2_vec = np.zeros(128, dtype=np.float32)
        v2_vec[50] = 1.0
        self.db.update_entity_signature(signature_id=sig_id, feature_vector=v2_vec)
        self.db.record_descriptor_version(
            entity_id=ent_id,
            feature_vector=v2_vec,
            version=2,
            update_reason="corrupted_drift",
            is_anchor=0,
        )

        # Check that version history has 2 versions
        versions = self.db.get_descriptor_versions(ent_id)
        self.assertEqual(len(versions), 2)

        # Roll back to version 1
        rollback_ok = self.db.rollback_descriptor(entity_id=ent_id, version=1)
        self.assertTrue(rollback_ok)

        # Verify signature has been restored to v1_vec
        restored_sigs = self.db.get_entity_signatures(ent_id)
        self.assertEqual(len(restored_sigs), 1)
        restored_vec = restored_sigs[0]["feature_vector"]
        self.assertAlmostEqual(float(np.dot(restored_vec, v1_vec)), 1.0, places=4)


if __name__ == "__main__":
    unittest.main()
