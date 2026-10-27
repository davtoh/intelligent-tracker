#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Unit Tests for Universal Artifact & Face Enrollment (Milestone 9).
"""

import os
import tempfile
import unittest
import numpy as np

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.reid import ColorHistogramExtractor, DualModelFeatureExtractor
from intelligent_tracker.enrollment import UniversalEnrollmentManager


class MockMatcher:
    def __init__(self):
        self.reloaded = False

    def reload_gallery(self):
        self.reloaded = True


class TestUniversalEnrollment(unittest.TestCase):
    """Test suite for UniversalEnrollmentManager."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_enroll.db")
        self.crops_dir = os.path.join(self.tmp_dir, "crops")
        os.makedirs(self.crops_dir, exist_ok=True)
        self.db = TrackerDB(self.db_path)
        self.matcher = MockMatcher()
        self.extractor = ColorHistogramExtractor(bins=(8, 8, 8))

        self.enrollment_mgr = UniversalEnrollmentManager(
            db=self.db,
            extractor=self.extractor,
            crops_dir=self.crops_dir,
            matcher=self.matcher,
        )

    def tearDown(self):
        self.db.close()
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_enroll_with_crop(self):
        """Enroll an entity directly from an image crop."""
        crop = np.zeros((120, 80, 3), dtype=np.uint8)
        crop[:, :] = (0, 120, 255)  # Orange

        res = self.enrollment_mgr.enroll(
            name="Delivery Van #4",
            category="delivery_truck",
            crop=crop,
            notes="Courier vehicle route A",
            security_role="delivery",
            is_anchor=True,
        )

        self.assertEqual(res["status"], "success")
        self.assertIn("entity_id", res)
        self.assertTrue(self.matcher.reloaded)

        ent_id = res["entity_id"]
        entity = self.db.get_entity(ent_id)
        self.assertIsNotNone(entity)
        self.assertEqual(entity["name"], "Delivery Van #4")
        self.assertEqual(entity["category"], "delivery_truck")

        # Verify signature has is_anchor and locked set
        sigs = self.db.get_entity_signatures(ent_id)
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]["is_anchor"], 1)
        self.assertEqual(sigs[0]["locked"], 1)

        # Verify initial descriptor snapshot version 1
        versions = self.db.get_descriptor_versions(ent_id)
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]["version"], 1)
        self.assertEqual(versions[0]["is_anchor"], 1)

    def test_enroll_with_frame_and_bbox(self):
        """Enroll an entity by specifying full frame and bounding box coordinates."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[50:150, 100:200] = (255, 0, 0)  # Blue box

        res = self.enrollment_mgr.enroll(
            name="Alice Resident",
            category="vip",
            frame=frame,
            bbox=(100, 50, 100, 100),
            notes="Penthouse resident",
            security_role="resident",
        )

        self.assertEqual(res["status"], "success")
        ent_id = res["entity_id"]
        entity = self.db.get_entity(ent_id)
        self.assertEqual(entity["name"], "Alice Resident")
        self.assertEqual(entity["category"], "vip")

    def test_dual_model_feature_extractor(self):
        """Verify DualModelFeatureExtractor fuses primary body and face embeddings."""
        extractor = DualModelFeatureExtractor()
        sample_img = np.zeros((160, 80, 3), dtype=np.uint8)
        sample_img[20:60, 20:60] = 200  # Synthesize bright facial region

        feat = extractor.extract(sample_img)
        self.assertIsInstance(feat, np.ndarray)
        self.assertEqual(feat.dtype, np.float32)
        # Vector must be L2 normalized
        norm = np.linalg.norm(feat)
        self.assertAlmostEqual(float(norm), 1.0, places=4)


if __name__ == "__main__":
    unittest.main()
