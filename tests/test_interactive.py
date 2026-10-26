#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for interactive screen selection & tagging (intelligent_tracker/interactive.py).
"""

import unittest
import numpy as np

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.reid import MockFeatureExtractor
from intelligent_tracker.matcher import GalleryMatcher
from intelligent_tracker.tracker import Track
from intelligent_tracker.geometry import Tripwire, ZoneROI
from intelligent_tracker.analytics import AnalyticsEngine
from intelligent_tracker.interactive import InteractiveController


class TestInteractiveController(unittest.TestCase):

    def setUp(self):
        self.db = TrackerDB(":memory:")
        self.extractor = MockFeatureExtractor(embedding_dim=16)
        self.matcher = GalleryMatcher(db=self.db, extractor=self.extractor)
        self.analytics = AnalyticsEngine(resolution=(640, 480))
        self.controller = InteractiveController(
            window_name="TestWindow",
            db=self.db,
            extractor=self.extractor,
            matcher=self.matcher,
            analytics=self.analytics,
        )

    def tearDown(self):
        self.db.close()

    def test_mouse_click_select_and_deselect(self):
        """Clicking inside a track bbox selects it; clicking empty space deselects."""
        trk = Track(track_id=42, bbox=(100, 100, 50, 50))
        self.controller.current_tracks = {42: trk}

        # Click inside bbox (120, 120)
        self.controller.on_mouse(0, 120, 120, 0, None)  # 0 is not LBUTTONDOWN
        self.assertIsNone(self.controller.selected_track_id)

        import cv2
        self.controller.on_mouse(cv2.EVENT_LBUTTONDOWN, 120, 120, 0, None)
        self.assertEqual(self.controller.selected_track_id, 42)

        # Click outside bbox (10, 10)
        self.controller.on_mouse(cv2.EVENT_LBUTTONDOWN, 10, 10, 0, None)
        self.assertIsNone(self.controller.selected_track_id)

    def test_interactive_tripwire_drawing(self):
        """Clicking 2 points in tripwire mode creates a Tripwire in analytics."""
        import cv2
        self.controller.draw_mode = "tripwire"
        self.assertEqual(len(self.analytics.tripwires), 0)

        # Click Point A
        self.controller.on_mouse(cv2.EVENT_LBUTTONDOWN, 50, 50, 0, None)
        self.assertEqual(len(self.controller.drawing_points), 1)

        # Click Point B
        self.controller.on_mouse(cv2.EVENT_LBUTTONDOWN, 200, 50, 0, None)
        self.assertEqual(len(self.analytics.tripwires), 1)
        self.assertEqual(self.controller.draw_mode, "none")
        self.assertEqual(len(self.controller.drawing_points), 0)

    def test_interactive_zone_drawing(self):
        """Clicking points and double clicking closes a Zone in analytics."""
        import cv2
        self.controller.draw_mode = "zone"
        self.assertEqual(len(self.analytics.zones), 0)

        self.controller.on_mouse(cv2.EVENT_LBUTTONDOWN, 10, 10, 0, None)
        self.controller.on_mouse(cv2.EVENT_LBUTTONDOWN, 100, 10, 0, None)
        self.controller.on_mouse(cv2.EVENT_LBUTTONDOWN, 100, 100, 0, None)
        self.controller.on_mouse(cv2.EVENT_LBUTTONDOWN, 10, 100, 0, None)

        self.assertEqual(len(self.controller.drawing_points), 4)

        # Finish zone via double click
        self.controller.on_mouse(cv2.EVENT_LBUTTONDBLCLK, 10, 100, 0, None)
        self.assertEqual(len(self.analytics.zones), 1)
        self.assertEqual(self.controller.draw_mode, "none")

    def test_render_overlay(self):
        """Overlay rendering should render inspector card when track selected."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        trk = Track(track_id=1, bbox=(50, 50, 60, 60))
        trk.entity_name = "Inspector Gadget"
        trk.reid_score = 0.95
        self.controller.current_tracks = {1: trk}
        self.controller.selected_track_id = 1

        annotated = self.controller.render_overlay(frame)
        self.assertEqual(annotated.shape, frame.shape)
        # Verify frame was modified (rendered card & bounding box)
        self.assertFalse(np.array_equal(annotated, frame))


if __name__ == "__main__":
    unittest.main()
