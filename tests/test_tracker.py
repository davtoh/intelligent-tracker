#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for intelligent_tracker.tracker (Track, CentroidTracker, SortTracker, TrackerFactory).
"""

from __future__ import division, print_function, absolute_import

import unittest
from intelligent_tracker.tracker import (
    Track,
    CentroidTracker,
    SortTracker,
    TrackerFactory,
    compute_iou,
    compute_iou_matrix,
)
from intelligent_tracker.detectors import Detection


class TestTracker(unittest.TestCase):

    def test_compute_iou(self):
        # Identical boxes
        box1 = (10, 10, 50, 50)
        self.assertAlmostEqual(compute_iou(box1, box1), 1.0, places=4)

        # Disjoint boxes
        box2 = (100, 100, 50, 50)
        self.assertEqual(compute_iou(box1, box2), 0.0)

        # 50% overlap horizontally
        box3 = (35, 10, 50, 50)
        iou = compute_iou(box1, box3)
        self.assertGreater(iou, 0.0)
        self.assertLess(iou, 1.0)

    def test_compute_iou_matrix(self):
        boxesA = [(0, 0, 10, 10), (20, 20, 10, 10)]
        boxesB = [(0, 0, 10, 10), (100, 100, 10, 10)]
        mat = compute_iou_matrix(boxesA, boxesB)
        self.assertEqual(mat.shape, (2, 2))
        self.assertAlmostEqual(mat[0, 0], 1.0, places=4)
        self.assertEqual(mat[0, 1], 0.0)
        self.assertEqual(mat[1, 0], 0.0)
        self.assertEqual(mat[1, 1], 0.0)

    def test_track_representation(self):
        t = Track(track_id=1, bbox=(50, 50, 40, 60), label="person", confidence=0.9, timestamp=100.0)
        self.assertEqual(t.track_id, 1)
        self.assertEqual(t.bbox, (50, 50, 40, 60))
        self.assertEqual(t.centroid, (70.0, 80.0))
        self.assertEqual(t.label, "person")
        self.assertEqual(t.hits, 1)
        self.assertEqual(t.missed_frames, 0)
        self.assertEqual(len(t.history), 1)

        # Update position
        t.update(bbox=(55, 52, 40, 60), timestamp=100.5)
        self.assertEqual(t.hits, 2)
        self.assertEqual(t.centroid, (75.0, 82.0))
        self.assertEqual(len(t.history), 2)
        self.assertGreater(t.dwell_time, 0.0)

        # Serialization
        d = t.to_dict()
        self.assertIn("track_id", d)
        self.assertIn("centroid", d)
        self.assertIn("velocity", d)

    def test_centroid_tracker_lifecycle(self):
        tracker = CentroidTracker(max_disappeared=3, min_hits=2, max_distance=100.0)

        # Frame 1: Detection arrives -> tentative track
        det1 = [Detection(bbox=(100, 100, 50, 80), class_id=0, confidence=0.95, label="person")]
        tracks = tracker.update(det1, timestamp=1.0, confirmed_only=False)
        self.assertEqual(len(tracks), 1)
        track_id = list(tracks.keys())[0]
        self.assertEqual(tracks[track_id].state, "tentative")

        # Confirmed-only should be empty
        confirmed = tracker._get_active_tracks(confirmed_only=True)
        self.assertEqual(len(confirmed), 0)

        # Frame 2: Same detection slightly moved -> confirmed track
        det2 = [Detection(bbox=(105, 102, 50, 80), class_id=0, confidence=0.94, label="person")]
        tracks2 = tracker.update(det2, timestamp=1.1, confirmed_only=True)
        self.assertEqual(len(tracks2), 1)
        self.assertIn(track_id, tracks2)
        self.assertEqual(tracks2[track_id].state, "confirmed")
        self.assertEqual(tracks2[track_id].hits, 2)

        # Frame 3: No detections -> missed frame
        tracks3 = tracker.update([], timestamp=1.2, confirmed_only=False)
        self.assertEqual(len(tracks3), 0)  # Active in current frame is 0
        self.assertEqual(tracker.tracks[track_id].missed_frames, 1)

        # Frames 4-6: Missing continuously until deregistration
        tracker.update([], timestamp=1.3)
        tracker.update([], timestamp=1.4)
        tracker.update([], timestamp=1.5)
        # Exceeded max_disappeared (3) -> track removed
        self.assertNotIn(track_id, tracker.tracks)

    def test_centroid_tracker_multiple_objects(self):
        tracker = CentroidTracker(max_disappeared=5, min_hits=1)

        dets_f1 = [
            Detection(bbox=(50, 50, 30, 30), class_id=0, confidence=0.9, label="person"),
            Detection(bbox=(300, 300, 40, 40), class_id=1, confidence=0.85, label="car"),
        ]
        t1 = tracker.update(dets_f1)
        self.assertEqual(len(t1), 2)

        # Frame 2: both targets moved slightly
        dets_f2 = [
            Detection(bbox=(55, 53, 30, 30), class_id=0, confidence=0.9, label="person"),
            Detection(bbox=(305, 302, 40, 40), class_id=1, confidence=0.85, label="car"),
        ]
        t2 = tracker.update(dets_f2)
        self.assertEqual(len(t2), 2)
        # Ensure track IDs were preserved
        self.assertEqual(set(t1.keys()), set(t2.keys()))

    def test_sort_tracker(self):
        sort_tracker = SortTracker(max_age=5, min_hits=1, iou_threshold=0.2)
        dets = [
            Detection(bbox=(100, 100, 40, 40), class_id=0, confidence=0.9, label="person")
        ]
        res1 = sort_tracker.update(dets)
        self.assertEqual(len(res1), 1)
        tid = list(res1.keys())[0]

        # Second frame
        dets2 = [
            Detection(bbox=(102, 101, 40, 40), class_id=0, confidence=0.9, label="person")
        ]
        res2 = sort_tracker.update(dets2)
        self.assertEqual(len(res2), 1)
        self.assertIn(tid, res2)

    def test_tracker_factory(self):
        available = TrackerFactory.available_trackers()
        self.assertIn("centroid", available)
        self.assertIn("sort", available)

        tr_centroid = TrackerFactory.create("centroid")
        self.assertIsInstance(tr_centroid, CentroidTracker)

        tr_sort = TrackerFactory.create("sort")
        self.assertIsInstance(tr_sort, SortTracker)

        with self.assertRaises(ValueError):
            TrackerFactory.create("invalid_tracker_name")


if __name__ == "__main__":
    unittest.main()
