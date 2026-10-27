#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for GroundPlaneHomography & BEV Minimap (intelligent_tracker/homography.py).
"""

import os
import unittest
import numpy as np

from intelligent_tracker.homography import GroundPlaneHomography
from intelligent_tracker.geometry import ZoneROI
from intelligent_tracker.tracker import Track


class TestGroundPlaneHomography(unittest.TestCase):

    def setUp(self):
        # 4 source points in image pixels (e.g. trapezoid representing perspective roadway)
        self.src_points = [
            (100.0, 100.0),
            (500.0, 100.0),
            (600.0, 400.0),
            (0.0, 400.0),
        ]
        # Target metric rectangle on ground plane (e.g. 10m wide x 20m long)
        self.dst_points = [
            (0.0, 0.0),
            (10.0, 0.0),
            (10.0, 20.0),
            (0.0, 20.0),
        ]
        self.homo = GroundPlaneHomography(
            src_points=self.src_points,
            dst_points=self.dst_points,
            metric_width=10.0,
            metric_height=20.0,
            camera_id="cam_test",
        )

    def test_initialization_and_calibration(self):
        """Test homography matrix is properly computed and invertible."""
        self.assertTrue(self.homo.is_calibrated)
        self.assertIsNotNone(self.homo.H)
        self.assertEqual(self.homo.H.shape, (3, 3))
        self.assertIsNotNone(self.homo.H_inv)
        self.assertEqual(self.homo.H_inv.shape, (3, 3))
        self.assertEqual(self.homo.camera_id, "cam_test")

    def test_uncalibrated_behavior(self):
        """Uncalibrated homography should return identity / original coordinates."""
        uncal = GroundPlaneHomography(camera_id="cam_uncal")
        self.assertFalse(uncal.is_calibrated)
        pt = (123.0, 456.0)
        self.assertEqual(uncal.camera_to_ground(pt), pt)
        self.assertEqual(uncal.ground_to_camera(pt), pt)

    def test_invalid_source_points(self):
        """Supplying fewer or more than 4 points should raise ValueError."""
        with self.assertRaises(ValueError):
            self.homo.set_calibration([(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)])

    def test_perspective_transform_forward_and_inverse(self):
        """Test that corner points map to their calibrated ground locations and invert back."""
        for src, dst in zip(self.src_points, self.dst_points):
            gx, gy = self.homo.camera_to_ground(src)
            self.assertAlmostEqual(gx, dst[0], places=2)
            self.assertAlmostEqual(gy, dst[1], places=2)

            # Inverse mapping
            cx, cy = self.homo.ground_to_camera((gx, gy))
            self.assertAlmostEqual(cx, src[0], places=2)
            self.assertAlmostEqual(cy, src[1], places=2)

    def test_track_to_ground_contact_point(self):
        """Test bounding box bottom-center contact point mapping: (x + w/2, y + h)."""
        # Bbox: x=550, y=350, w=100, h=50 -> contact point = (600, 400), which corresponds to src_points[2]
        bbox = (550.0, 350.0, 100.0, 50.0)
        gx, gy = self.homo.track_to_ground(bbox)
        self.assertAlmostEqual(gx, self.dst_points[2][0], places=2)
        self.assertAlmostEqual(gy, self.dst_points[2][1], places=2)

    def test_transform_polygon(self):
        """Test sequence of polygon vertices transforms correctly."""
        poly = [self.src_points[0], self.src_points[1], self.src_points[2]]
        ground_poly = self.homo.transform_polygon(poly)
        self.assertEqual(len(ground_poly), 3)
        self.assertAlmostEqual(ground_poly[0][0], self.dst_points[0][0], places=2)
        self.assertAlmostEqual(ground_poly[0][1], self.dst_points[0][1], places=2)

    def test_render_bev_minimap(self):
        """Test top-down Bird's-Eye-View canvas image rendering."""
        # Create a mock track
        trk = Track(track_id=42, bbox=(250, 200, 50, 100))
        trk.label = "person"
        trk.velocity = (1.2, -0.4)

        zone = ZoneROI(
            polygon=[self.src_points[0], self.src_points[1], self.src_points[2], self.src_points[3]],
            name="Loading Dock",
            color=(0, 255, 0),
        )

        canvas = self.homo.render_bev_minimap(
            tracks={42: trk},
            zones={"Loading Dock": zone},
            canvas_size=(300, 300),
            margin=30,
        )

        self.assertIsNotNone(canvas)
        self.assertEqual(canvas.shape, (300, 300, 3))
        self.assertEqual(canvas.dtype, np.uint8)

    def test_serialization_to_dict_and_from_dict(self):
        """Test to_dict and from_dict roundtrip."""
        data = self.homo.to_dict()
        self.assertEqual(data["camera_id"], "cam_test")
        self.assertTrue(data["is_calibrated"])
        self.assertEqual(data["metric_width"], 10.0)
        self.assertEqual(data["metric_height"], 20.0)
        self.assertEqual(len(data["src_points"]), 4)
        self.assertEqual(len(data["dst_points"]), 4)

        loaded = GroundPlaneHomography.from_dict(data)
        self.assertTrue(loaded.is_calibrated)
        self.assertEqual(loaded.camera_id, "cam_test")
        self.assertEqual(loaded.metric_width, 10.0)
        self.assertEqual(loaded.metric_height, 20.0)
        np.testing.assert_allclose(loaded.H, self.homo.H, atol=1e-5)


if __name__ == "__main__":
    unittest.main()
