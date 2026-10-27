#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for TrajectoryJourneySearcher & JourneyVideoExporter (intelligent_tracker/journey.py).
"""

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta

import cv2
import numpy as np

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.journey import (
    TrajectoryJourneySearcher,
    JourneyVideoExporter,
    JourneyHop,
    EntityJourney,
)


class TestTrajectoryJourney(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="journey_test_")
        self.db_path = os.path.join(self.test_dir, "test_tracker.db")
        self.video_dir = os.path.join(self.test_dir, "videos")
        os.makedirs(self.video_dir, exist_ok=True)

        self.db = TrackerDB(self.db_path)
        self.searcher = TrajectoryJourneySearcher(self.db)
        self.exporter = JourneyVideoExporter(output_dir=self.video_dir)

    def tearDown(self):
        if self.db:
            self.db.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_empty_journey_search(self):
        """Searching for non-existent entity should return an empty EntityJourney."""
        journey = self.searcher.search_journey(entity_name="Ghost")
        self.assertEqual(journey.total_hops, 0)
        self.assertEqual(journey.total_duration_seconds, 0.0)
        self.assertEqual(len(journey.hops), 0)

    def test_multi_camera_journey_reconstruction(self):
        """Reconstruct multi-hop journey across cameras with transit delay calculation."""
        # 1. Enroll entity
        eid = self.db.add_entity(name="Subject Alpha", category="visitor")

        # 2. Add sightings sequence:
        base_t = 1700000000.0
        # Cam 1 (Gate): t = base_t + 0 to base_t + 10
        t0 = datetime.fromtimestamp(base_t + 0.0).isoformat()
        t1 = datetime.fromtimestamp(base_t + 10.0).isoformat()
        self.db.add_sighting(entity_id=eid, track_id=1, source="cam_01", timestamp=t0, zone_id="Gate Entrance", bbox=[10, 10, 40, 40])
        self.db.add_sighting(entity_id=eid, track_id=1, source="cam_01", timestamp=t1, zone_id="Gate Entrance", bbox=[20, 20, 40, 40])

        # Transit of 20 seconds...
        # Cam 2 (Lobby): t = base_t + 30 to base_t + 45
        t2 = datetime.fromtimestamp(base_t + 30.0).isoformat()
        t3 = datetime.fromtimestamp(base_t + 45.0).isoformat()
        self.db.add_sighting(entity_id=eid, track_id=2, source="cam_02", timestamp=t2, zone_id="Lobby Front", bbox=[50, 50, 40, 40])
        self.db.add_sighting(entity_id=eid, track_id=2, source="cam_02", timestamp=t3, zone_id="Lobby Front", bbox=[60, 60, 40, 40])

        # Transit of 15 seconds...
        # Cam 3 (Elevator): t = base_t + 60 to base_t + 70
        t4 = datetime.fromtimestamp(base_t + 60.0).isoformat()
        t5 = datetime.fromtimestamp(base_t + 70.0).isoformat()
        self.db.add_sighting(entity_id=eid, track_id=3, source="cam_03", timestamp=t4, zone_id="Elevator Bank", bbox=[100, 100, 40, 40])
        self.db.add_sighting(entity_id=eid, track_id=3, source="cam_03", timestamp=t5, zone_id="Elevator Bank", bbox=[110, 110, 40, 40])

        # 3. Perform journey reconstruction
        journey = self.searcher.search_journey(entity_id=eid)

        self.assertEqual(journey.entity_name, "Subject Alpha")
        self.assertEqual(journey.total_hops, 3)
        self.assertEqual(len(journey.hops), 3)

        # Hop 0: Cam 1
        hop0 = journey.hops[0]
        self.assertEqual(hop0.camera_id, "cam_01")
        self.assertEqual(hop0.zone_id, "Gate Entrance")
        self.assertAlmostEqual(hop0.duration_seconds, 10.0, places=1)
        self.assertIsNone(hop0.transit_time_from_prev)

        # Hop 1: Cam 2
        hop1 = journey.hops[1]
        self.assertEqual(hop1.camera_id, "cam_02")
        self.assertEqual(hop1.zone_id, "Lobby Front")
        self.assertAlmostEqual(hop1.duration_seconds, 15.0, places=1)
        self.assertAlmostEqual(hop1.transit_time_from_prev, 20.0, places=1)

        # Hop 2: Cam 3
        hop2 = journey.hops[2]
        self.assertEqual(hop2.camera_id, "cam_03")
        self.assertEqual(hop2.zone_id, "Elevator Bank")
        self.assertAlmostEqual(hop2.duration_seconds, 10.0, places=1)
        self.assertAlmostEqual(hop2.transit_time_from_prev, 15.0, places=1)

        # Check narrative
        self.assertIn("Subject Alpha journey (3 hops)", journey.summary_narrative)
        self.assertIn("CAM_01", journey.summary_narrative)
        self.assertIn("CAM_02", journey.summary_narrative)
        self.assertIn("CAM_03", journey.summary_narrative)

    def test_export_journey_video_synthesis(self):
        """Test synthesizing and encoding MP4 journey video file."""
        eid = self.db.add_entity(name="Bob Exporter", category="visitor")
        t0 = datetime.fromtimestamp(1700001000.0).isoformat()
        t1 = datetime.fromtimestamp(1700001005.0).isoformat()
        self.db.add_sighting(entity_id=eid, track_id=1, source="cam_01", timestamp=t0, bbox=[10, 10, 30, 30])
        self.db.add_sighting(entity_id=eid, track_id=1, source="cam_01", timestamp=t1, bbox=[15, 15, 30, 30])

        journey = self.searcher.search_journey(entity_id=eid)
        self.assertEqual(journey.total_hops, 1)

        out_file = self.exporter.export_journey_video(
            journey=journey,
            output_filename="test_bob_journey.mp4",
            resolution=(320, 240),
            fps=10,
            seconds_per_hop=1.0,
        )

        self.assertTrue(os.path.exists(out_file))
        self.assertGreater(os.path.getsize(out_file), 1000)

        # Verify video can be opened with OpenCV VideoCapture
        cap = cv2.VideoCapture(out_file)
        self.assertTrue(cap.isOpened())
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.assertGreater(frame_count, 0)
        ret, frame = cap.read()
        self.assertTrue(ret)
        self.assertEqual(frame.shape, (240, 320, 3))
        cap.release()


if __name__ == "__main__":
    unittest.main()
