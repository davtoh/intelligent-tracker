#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for intelligent_tracker.analytics & geometry (Tripwire, ZoneROI, OccupancyHeatmap, AnalyticsEngine).
"""

import os
import shutil
import tempfile
import unittest
import numpy as np

from intelligent_tracker.geometry import (
    Tripwire,
    ZoneROI,
    ZoneEvent,
    TripwireEvent,
    segments_intersect,
)
from intelligent_tracker.analytics import OccupancyHeatmap, AnalyticsEngine
from intelligent_tracker.tracker import Track


class TestAnalyticsAndGeometry(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_segments_intersect(self):
        # Cross (+)
        p1, p2 = (0, 5), (10, 5)
        p3, p4 = (5, 0), (5, 10)
        self.assertTrue(segments_intersect(p1, p2, p3, p4))

        # Parallel
        p1, p2 = (0, 0), (10, 0)
        p3, p4 = (0, 5), (10, 5)
        self.assertFalse(segments_intersect(p1, p2, p3, p4))

        # Non-intersecting segments whose infinite lines cross
        p1, p2 = (0, 0), (4, 4)
        p3, p4 = (5, 5), (10, 10)
        self.assertFalse(segments_intersect(p1, p2, p3, p4))

    def test_tripwire_crossing_and_direction(self):
        # Horizontal tripwire from (0, 100) to (200, 100)
        tw = Tripwire(line_segment=((0, 100), (200, 100)), name="door_line")
        self.assertEqual(tw.total_in, 0)
        self.assertEqual(tw.total_out, 0)

        # Cross moving downward (from y=90 to y=110)
        ev_in = tw.check_crossing(track_id=1, prev_centroid=(100, 90), curr_centroid=(100, 110), timestamp=10.0)
        self.assertIsNotNone(ev_in)
        self.assertEqual(ev_in.direction, "in")
        self.assertEqual(tw.total_in, 1)
        self.assertEqual(tw.total_out, 0)

        # Cross moving upward (from y=110 to y=90)
        ev_out = tw.check_crossing(track_id=2, prev_centroid=(100, 110), curr_centroid=(100, 90), timestamp=11.0)
        self.assertIsNotNone(ev_out)
        self.assertEqual(ev_out.direction, "out")
        self.assertEqual(tw.total_in, 1)
        self.assertEqual(tw.total_out, 1)

        # Movement that does not cross
        ev_none = tw.check_crossing(track_id=3, prev_centroid=(50, 40), curr_centroid=(60, 50))
        self.assertIsNone(ev_none)

        # Drawing test
        dummy_frame = np.zeros((200, 200, 3), dtype=np.uint8)
        rendered = tw.draw(dummy_frame)
        self.assertEqual(rendered.shape, (200, 200, 3))

    def test_zone_roi_lifecycle(self):
        # Square zone (50, 50) to (150, 150)
        polygon = [(50, 50), (150, 50), (150, 150), (50, 150)]
        zone = ZoneROI(polygon=polygon, name="test_zone", dwell_threshold=2.0)

        self.assertTrue(zone.contains_point((100, 100)))
        self.assertFalse(zone.contains_point((10, 10)))

        # Frame 1: Object enters zone
        t1 = Track(track_id=1, bbox=(90, 90, 20, 20), timestamp=100.0)
        events_f1 = zone.update({1: t1}, timestamp=100.0)
        self.assertEqual(len(events_f1), 1)
        self.assertEqual(events_f1[0].event_type, "enter")
        self.assertEqual(zone.occupancy, 1)
        self.assertEqual(zone.total_entries, 1)

        # Frame 2: Object still inside, dwell threshold not yet reached (< 2.0s)
        t1.update(bbox=(92, 92, 20, 20), timestamp=101.0)
        events_f2 = zone.update({1: t1}, timestamp=101.0)
        self.assertEqual(len(events_f2), 0)
        self.assertEqual(zone.occupancy, 1)

        # Frame 3: Object still inside, dwell threshold met (>= 2.0s)
        t1.update(bbox=(95, 95, 20, 20), timestamp=102.5)
        events_f3 = zone.update({1: t1}, timestamp=102.5)
        self.assertEqual(len(events_f3), 1)
        self.assertEqual(events_f3[0].event_type, "dwell")
        self.assertAlmostEqual(events_f3[0].dwell_time, 2.5, places=1)

        # Frame 4: Object leaves zone
        t1.update(bbox=(200, 200, 20, 20), timestamp=103.5)
        events_f4 = zone.update({1: t1}, timestamp=103.5)
        self.assertEqual(len(events_f4), 1)
        self.assertEqual(events_f4[0].event_type, "exit")
        self.assertEqual(zone.occupancy, 0)
        self.assertEqual(zone.total_exits, 1)
        self.assertAlmostEqual(events_f4[0].dwell_time, 3.5, places=1)

        # Drawing test
        dummy_frame = np.zeros((200, 200, 3), dtype=np.uint8)
        rendered = zone.draw(dummy_frame)
        self.assertEqual(rendered.shape, (200, 200, 3))

    def test_occupancy_heatmap(self):
        hm = OccupancyHeatmap(width=200, height=200, decay_rate=0.9, radius=15)
        self.assertEqual(hm.density.max(), 0.0)

        # Add target
        t = Track(track_id=1, bbox=(90, 90, 20, 20))
        hm.update([t])
        self.assertGreater(hm.density.max(), 0.5)

        # Peak should be at centroid (100, 100)
        peak_y, peak_x = np.unravel_index(np.argmax(hm.density), hm.density.shape)
        self.assertEqual((peak_x, peak_y), (100, 100))

        # Temporal decay test
        val_before = hm.density.max()
        hm.update([])  # Empty update applies decay
        val_after = hm.density.max()
        self.assertLess(val_after, val_before)

        # Overlay drawing test
        dummy_frame = np.ones((200, 200, 3), dtype=np.uint8) * 128
        drawn = hm.draw(dummy_frame)
        self.assertEqual(drawn.shape, (200, 200, 3))

        # PNG Export
        png_path = os.path.join(self.temp_dir, "heatmap.png")
        self.assertTrue(hm.export_image(png_path, frame=dummy_frame))
        self.assertTrue(os.path.exists(png_path))
        self.assertGreater(os.path.getsize(png_path), 0)

        # CSV Export
        csv_path = os.path.join(self.temp_dir, "heatmap.csv")
        self.assertTrue(hm.export_csv(csv_path, grid_cells_x=10, grid_cells_y=10))
        self.assertTrue(os.path.exists(csv_path))
        self.assertGreater(os.path.getsize(csv_path), 0)

        # Reset
        hm.reset()
        self.assertEqual(hm.density.max(), 0.0)

    def test_analytics_engine_orchestration(self):
        tw = Tripwire(line_segment=((0, 100), (200, 100)), name="line1")
        zone = ZoneROI(polygon=[(50, 50), (150, 50), (150, 150), (50, 150)], name="zone1", dwell_threshold=1.0)

        engine = AnalyticsEngine(
            zones=[zone],
            tripwires=[tw],
            heatmap_enabled=True,
            resolution=(200, 200),
        )

        # Step 1: Object created inside zone and above tripwire
        t1 = Track(track_id=1, bbox=(90, 80, 20, 20), timestamp=10.0)
        res1 = engine.update({1: t1}, timestamp=10.0)
        self.assertEqual(res1["total_active_tracks"], 1)
        self.assertEqual(res1["zone_occupancy"]["zone1"], 1)
        self.assertEqual(res1["new_events_count"], 1)  # Enter zone

        # Step 2: Object moves across tripwire while still in zone
        t1.update(bbox=(90, 110, 20, 20), timestamp=10.5)
        res2 = engine.update({1: t1}, timestamp=10.5)
        # Should detect tripwire crossing
        self.assertEqual(tw.total_in, 1)

        # Drawing test
        dummy_frame = np.zeros((200, 200, 3), dtype=np.uint8)
        rendered = engine.draw(dummy_frame, tracks={1: t1}, fps=30.0)
        self.assertEqual(rendered.shape, (200, 200, 3))

        # Summary JSON export
        report_path = os.path.join(self.temp_dir, "summary.json")
        summary = engine.export_summary(report_path)
        self.assertTrue(os.path.exists(report_path))
        self.assertIn("zones", summary)
        self.assertIn("tripwires", summary)
        self.assertEqual(summary["tripwires"]["line1"]["total_in"], 1)

    def test_zone_continuity_during_coasting(self):
        """Zone dwell and occupancy should remain continuous without false exits during predictive coasting."""
        polygon = [(50, 50), (150, 50), (150, 150), (50, 150)]
        zone = ZoneROI(polygon=polygon, name="secure_zone", dwell_threshold=2.0)

        # 1. Track enters zone
        t1 = Track(track_id=1, bbox=(90, 90, 20, 20), timestamp=10.0)
        events1 = zone.update({1: t1}, timestamp=10.0)
        self.assertEqual(len(events1), 1)
        self.assertEqual(events1[0].event_type, "enter")
        self.assertEqual(zone.occupancy, 1)

        # 2. Detector loses sight, track enters predicting / dead-reckoning state
        t1.predict(timestamp=11.0)
        self.assertEqual(t1.state, "predicting")
        events2 = zone.update({1: t1}, timestamp=11.0)
        # Should NOT emit premature exit event
        self.assertEqual(len(events2), 0)
        self.assertEqual(zone.occupancy, 1)
        self.assertEqual(zone.total_exits, 0)

        # 3. Coasting continues past dwell threshold (2.0s since entry at 10.0)
        t1.predict(timestamp=12.5)
        events3 = zone.update({1: t1}, timestamp=12.5)
        self.assertEqual(len(events3), 1)
        self.assertEqual(events3[0].event_type, "dwell")
        self.assertAlmostEqual(events3[0].dwell_time, 2.5, places=1)
        self.assertEqual(zone.total_exits, 0)


if __name__ == "__main__":
    unittest.main()
