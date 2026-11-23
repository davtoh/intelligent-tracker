"""Unit and integration tests for persistent coasting, occlusion, and Re-ID retention."""

import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock

import numpy as np

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.detectors import Detection, MockDetector
from intelligent_tracker.matcher import GalleryMatcher
from intelligent_tracker.pipeline import FrameProcessor, PipelineConfig, PipelineEngine
from intelligent_tracker.reid import ColorHistogramExtractor
from intelligent_tracker.tracker import CentroidTracker, SortTracker, Track, check_track_occlusions
from intelligent_tracker.world import WorldEntityBridge, WorldGraph


class TestPersistentCoastingAndOcclusion(unittest.TestCase):
    """Verify SortTracker, CentroidTracker, Track, and occlusion coasting transitions."""

    def test_track_min_hits_and_clutter_serialization(self) -> None:
        trk = Track(track_id=1, bbox=(10, 20, 40, 60), timestamp=1.0)
        self.assertFalse(hasattr(trk, "entity_id"))
        trk.update((12, 22, 40, 60), timestamp=1.1, min_hits=3)
        self.assertEqual(trk.state, "tentative")
        trk.update((14, 24, 40, 60), timestamp=1.2, min_hits=3)
        self.assertEqual(trk.state, "confirmed")
        trk.is_cluttered = True
        trk.clutter_partner_id = 7
        payload = trk.to_dict()
        self.assertIsNone(payload["entity_id"])
        self.assertFalse(hasattr(trk, "entity_id"))
        self.assertTrue(payload["is_cluttered"])
        self.assertEqual(payload["clutter_partner_id"], 7)

    def test_sort_tracker_coasting_and_attribute_preservation(self) -> None:
        tracker = SortTracker(max_age=20, min_hits=2, iou_threshold=0.2, coast_frames=5, coast_seconds=1.5)
        t0 = 100.0
        tracker.update([Detection((100, 100, 50, 80), 0, 0.9, "person")], timestamp=t0)
        res1 = tracker.update([Detection((105, 100, 50, 80), 0, 0.9, "person")], timestamp=t0 + 0.1, confirmed_only=True)
        self.assertEqual(len(res1), 1)
        tid = next(iter(res1))
        self.assertEqual(res1[tid].state, "confirmed")
        res1[tid].entity_id = 42
        res1[tid].entity_name = "Alice"

        # Drop detection -> coasting with predicted Kalman box and preserved entity_id
        res2 = tracker.update([], timestamp=t0 + 0.2, confirmed_only=True)
        self.assertIn(tid, res2)
        self.assertEqual(res2[tid].state, "coasting")
        self.assertEqual(res2[tid].missed_frames, 1)
        self.assertEqual(res2[tid].entity_id, 42)

        # Re-detect -> confirmed again with same Track instance & entity_id
        res3 = tracker.update([Detection((112, 100, 50, 80), 0, 0.9, "person")], timestamp=t0 + 0.3, confirmed_only=True)
        self.assertIn(tid, res3)
        self.assertEqual(res3[tid].state, "confirmed")
        self.assertEqual(res3[tid].missed_frames, 0)
        self.assertEqual(res3[tid].entity_id, 42)

        # Expire past max_age -> pruned from _active_tracks and track_metadata
        for step in range(25):
            tracker.update([], timestamp=t0 + 1.0 + step * 0.2)
        self.assertNotIn(tid, tracker._active_tracks)
        self.assertNotIn(tid, tracker.track_metadata)

    def test_centroid_tracker_coast_seconds_and_occlusion_state(self) -> None:
        tracker = CentroidTracker(max_disappeared=20, min_hits=2, coast_frames=2, coast_seconds=1.5)
        t0 = 200.0
        tracker.update([Detection((50, 50, 60, 80), 0, 0.9, "person")], timestamp=t0)
        res1 = tracker.update([Detection((55, 50, 60, 80), 0, 0.9, "person")], timestamp=t0 + 0.1, confirmed_only=True)
        tid = next(iter(res1))

        # Miss beyond coast_frames=2, still within coast_seconds=1.5
        for i in range(1, 5):
            res_miss = tracker.update([], timestamp=t0 + 0.1 + i * 0.1, confirmed_only=True)
            self.assertIn(tid, res_miss)
            self.assertEqual(res_miss[tid].state, "coasting")

        # Overlapping partner triggers occluded state on coasting track
        other = Track(track_id=99, bbox=res_miss[tid].bbox, timestamp=t0 + 0.6)
        check_track_occlusions({tid: res_miss[tid], 99: other}, iou_threshold=0.3, timestamp=t0 + 0.6)
        self.assertTrue(res_miss[tid].is_cluttered)
        self.assertEqual(res_miss[tid].state, "occluded")


class TestGalleryAndWorldCoastingRetention(unittest.TestCase):
    """Verify GalleryMatcher zero feature pollution, WorldEntityBridge grace, and FrameProcessor sync."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = TrackerDB(os.path.join(self.tmp.name, "coast.db"))
        self.addCleanup(self.db.close)

    def test_gallery_skips_extraction_while_coasting_and_retains_reid(self) -> None:
        eid = self.db.add_entity("Bob", "staff")
        extractor = ColorHistogramExtractor(bins=(8, 8, 8))
        frame = np.full((240, 320, 3), 120, dtype=np.uint8)
        sig = extractor.extract(frame, (40, 40, 60, 80))
        self.db.add_signature(eid, sig)

        spy_extractor = MagicMock(wraps=extractor)
        spy_extractor.embedding_dim = extractor.embedding_dim
        matcher = GalleryMatcher(
            db=self.db, extractor=spy_extractor, reid_threshold=0.5,
            min_track_hits=1, coast_grace_seconds=2.0,
        )

        trk = Track(track_id=1, bbox=(40, 40, 60, 80), timestamp=10.0)
        trk.state = "confirmed"
        events = matcher.match_tracks({1: trk}, frame, source="cam_01", timestamp=10.0)
        self.assertEqual(len(events), 1)
        self.assertEqual(spy_extractor.extract.call_count, 1)

        # Coasting frame -> zero extract() calls, identity preserved
        trk.mark_missed()
        trk.state = "coasting"
        matcher.match_tracks({1: trk}, frame, source="cam_01", timestamp=10.5)
        self.assertEqual(spy_extractor.extract.call_count, 1)
        self.assertEqual(trk.entity_id, eid)

        # Brief complete absence (0.8s < 2.0s) retains feature buffer; >2.0s prunes it
        matcher.match_tracks({}, frame, source="cam_01", timestamp=11.3)
        self.assertIn(1, matcher._track_features)
        matcher.match_tracks({}, frame, source="cam_01", timestamp=13.0)
        self.assertNotIn(1, matcher._track_features)

    def test_world_bridge_retains_coasting_tracks_within_grace(self) -> None:
        graph = WorldGraph()
        bridge = WorldEntityBridge(graph, db=self.db, coasting_grace_seconds=2.0)
        eid = self.db.add_entity("Dana", "visitor")
        trk = Track(track_id=5, bbox=(20, 20, 40, 60), timestamp=50.0)
        bridge.sync_track_identification("cam_01", trk, eid, timestamp=50.0)

        pruned_early = bridge.prune_stale_tracks(
            camera_id="cam_01", active_track_ids={5}, coasting_track_ids={5}, timestamp=51.0,
        )
        self.assertEqual(pruned_early, [])
        self.assertIsNotNone(graph.get_node(f"entity:{eid}", node_type="entity"))

        pruned_expired = bridge.prune_stale_tracks(
            camera_id="cam_01", active_track_ids={5}, coasting_track_ids={5}, timestamp=52.5,
        )
        self.assertEqual(pruned_expired, [f"entity:{eid}"])
        self.assertIsNone(graph.get_node(f"entity:{eid}", node_type="entity"))

    def test_frame_processor_syncs_governance_attrs_without_mutating_coords(self) -> None:
        cfg = PipelineConfig(
            db_path=os.path.join(self.tmp.name, "proc.db"),
            detector_model="mock", reid_model="color", tracker_type="sort",
            min_hits=1, tracker_coast_frames=5, tracker_coast_seconds=1.5,
        )
        bundle = PipelineEngine.build(cfg)
        self.addCleanup(bundle.close)
        det = MockDetector(boxes=[(900, 466, 120, 166)])
        bundle.detector = det
        proc = FrameProcessor(bundle)
        hd = np.zeros((1080, 1920, 3), dtype=np.uint8)
        res = proc.step(hd, timestamp=time.time(), max_dim=1280)
        tid = next(iter(res.tracks))
        internal = bundle.tracker.tracks[tid]
        self.assertLess(internal.bbox[0], 1280)
        self.assertEqual(getattr(internal, "session_id", None), getattr(res.tracks[tid], "session_id", None))


if __name__ == "__main__":
    unittest.main()
