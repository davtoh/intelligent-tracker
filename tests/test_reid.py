#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for visual feature extractors and Re-ID embeddings (intelligent_tracker/reid.py).
"""

import unittest
import numpy as np

from intelligent_tracker.reid import (
    cosine_similarity,
    batch_cosine_similarity,
    ColorHistogramExtractor,
    OnnxReIDExtractor,
    MockFeatureExtractor,
    ReIDExtractorFactory,
)


class TestReID(unittest.TestCase):

    def test_cosine_similarity(self):
        """Test single and batch cosine similarity properties."""
        v1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        v2 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        v3 = np.array([0.0, 1.0, 0.0], dtype=np.float32)

        # Identical vectors -> similarity = 1.0
        self.assertAlmostEqual(cosine_similarity(v1, v2), 1.0, places=5)
        # Orthogonal vectors -> similarity = 0.0
        self.assertAlmostEqual(cosine_similarity(v1, v3), 0.0, places=5)

        # Batch similarity
        gallery = np.vstack([v1, v3, np.array([0.7071, 0.7071, 0.0], dtype=np.float32)])
        sims = batch_cosine_similarity(gallery, v1)
        self.assertEqual(len(sims), 3)
        self.assertAlmostEqual(sims[0], 1.0, places=4)
        self.assertAlmostEqual(sims[1], 0.0, places=4)
        self.assertAlmostEqual(sims[2], 0.7071, places=3)

    def test_color_histogram_extractor(self):
        """Test spatial HSV color histogram extraction and L2 normalization."""
        extractor = ColorHistogramExtractor(spatial_grid=(3, 1), h_bins=8, s_bins=4, v_bins=4)
        self.assertEqual(extractor.embedding_dim, 3 * 1 * (8 * 4 * 4))

        # Red image crop
        red_crop = np.zeros((100, 50, 3), dtype=np.uint8)
        red_crop[:, :] = [0, 0, 255]  # BGR Red

        # Blue image crop
        blue_crop = np.zeros((100, 50, 3), dtype=np.uint8)
        blue_crop[:, :] = [255, 0, 0]  # BGR Blue

        feat_red1 = extractor.extract_crop(red_crop)
        feat_red2 = extractor.extract_crop(red_crop)
        feat_blue = extractor.extract_crop(blue_crop)

        # Vector is L2 normalized
        self.assertAlmostEqual(np.linalg.norm(feat_red1), 1.0, places=5)
        self.assertAlmostEqual(np.linalg.norm(feat_blue), 1.0, places=5)

        # Same color produces identical embeddings
        sim_red_red = cosine_similarity(feat_red1, feat_red2)
        self.assertAlmostEqual(sim_red_red, 1.0, places=4)

        # Different colors produce lower similarity
        sim_red_blue = cosine_similarity(feat_red1, feat_blue)
        self.assertLess(sim_red_blue, 0.5)

    def test_spatial_vertical_sensitivity(self):
        """Test that spatial grid distinguishes top vs bottom color inverted clothing."""
        extractor = ColorHistogramExtractor(spatial_grid=(3, 1), h_bins=16, s_bins=8, v_bins=8)

        # Person A: Red shirt (top), Blue pants (bottom)
        person_a = np.zeros((90, 30, 3), dtype=np.uint8)
        person_a[:45, :] = [0, 0, 255]  # Red top
        person_a[45:, :] = [255, 0, 0]  # Blue bottom

        # Person B: Blue shirt (top), Red pants (bottom)
        person_b = np.zeros((90, 30, 3), dtype=np.uint8)
        person_b[:45, :] = [255, 0, 0]  # Blue top
        person_b[45:, :] = [0, 0, 255]  # Red bottom

        feat_a = extractor.extract_crop(person_a)
        feat_b = extractor.extract_crop(person_b)

        sim = cosine_similarity(feat_a, feat_b)
        # Even though global colors are the same, spatial vertical separation keeps similarity lower
        self.assertLess(sim, 0.85)

    def test_extract_with_frame_and_bbox(self):
        """Test safe extraction from full frame with bounded coordinates."""
        extractor = ColorHistogramExtractor()
        frame = np.zeros((200, 200, 3), dtype=np.uint8)
        frame[40:100, 50:110] = [0, 255, 0]  # Green patch

        # Normal bbox
        feat = extractor.extract(frame, bbox=(50, 40, 60, 60))
        self.assertEqual(len(feat), extractor.embedding_dim)
        self.assertAlmostEqual(np.linalg.norm(feat), 1.0, places=4)

        # Clamping out-of-bounds bbox
        feat_clamped = extractor.extract(frame, bbox=(-20, -10, 100, 100))
        self.assertEqual(len(feat_clamped), extractor.embedding_dim)

    def test_onnx_reid_extractor_fallback(self):
        """Test OnnxReIDExtractor falls back gracefully to ColorHistogramExtractor when model missing."""
        onnx_extractor = OnnxReIDExtractor(model_path="nonexistent_model.onnx", fallback_to_color=True)
        crop = np.full((128, 64, 3), 128, dtype=np.uint8)
        feat = onnx_extractor.extract_crop(crop)
        self.assertIsInstance(feat, np.ndarray)
        self.assertGreater(len(feat), 0)
        self.assertAlmostEqual(np.linalg.norm(feat), 1.0, places=4)

    def test_mock_feature_extractor(self):
        """Test MockFeatureExtractor determinism and dimensionality."""
        mock_ext = MockFeatureExtractor(embedding_dim=32)
        self.assertEqual(mock_ext.embedding_dim, 32)

        crop = np.full((50, 50, 3), 100, dtype=np.uint8)
        f1 = mock_ext.extract_crop(crop)
        f2 = mock_ext.extract_crop(crop)

        np.testing.assert_allclose(f1, f2, rtol=1e-5)
        self.assertAlmostEqual(np.linalg.norm(f1), 1.0, places=4)

    def test_factory_creation(self):
        """Test factory registration and instantiation."""
        ext_color = ReIDExtractorFactory.create("color")
        self.assertIsInstance(ext_color, ColorHistogramExtractor)

        ext_mock = ReIDExtractorFactory.create("mock", embedding_dim=24)
        self.assertIsInstance(ext_mock, MockFeatureExtractor)
        self.assertEqual(ext_mock.embedding_dim, 24)

        with self.assertRaises(ValueError):
            ReIDExtractorFactory.create("unknown_extractor")


if __name__ == "__main__":
    unittest.main()
