#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Regression tests for Step 2 Milestone 2: Class-Consistency, Appearance & Replay Continuity."""

from types import SimpleNamespace
import unittest
import numpy as np

from dashboard.services.cached_replay_provider import CachedReplayProvider
from dashboard.services.file_detection_replay import FileDetectionReplayProvider
from intelligent_tracker.analytics import AnalyticsEngine
from intelligent_tracker.geometry.zone_roi import ZoneROI
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.detectors import Detection
from intelligent_tracker.matcher import GalleryMatcher
from intelligent_tracker.reid import MockFeatureExtractor
from intelligent_tracker.tracker import CentroidTracker, SortTracker, Track


class TestClassAndAppearanceAssociation(unittest.TestCase):
    """Verify class-consistent tracking, appearance cross-over recovery, and replay coasting."""

    def test_sort_blocks_person_chair_swap_and_allows_object_fallback(self) -> None:
        sort = SortTracker(max_age=5, min_hits=1, iou_threshold=0.3)
        t1 = sort.update([Detection(bbox=(100, 100, 50, 100), class_id=0, confidence=0.9, label="person")], timestamp=1.0)
        pid = next(iter(t1.keys()))

        # Chair overlaps person's exact bbox -> must NOT hijack person's track ID
        t2 = sort.update([Detection(bbox=(100, 100, 50, 100), class_id=56, confidence=0.9, label="chair")], timestamp=1.1)
        self.assertNotIn(pid, t2)
        self.assertEqual(len(t2), 1)
        cid = next(iter(t2.keys()))
        self.assertNotEqual(cid, pid)
        self.assertEqual(t2[cid].label, "chair")

        # Generic 'object' fallback still associates with existing track
        t3 = sort.update([(100, 100, 50, 100)], timestamp=1.2)
        self.assertEqual(len(t3), 1)

    def test_centroid_blocks_person_chair_swap_across_iou_and_distance(self) -> None:
        ct = CentroidTracker(max_disappeared=5, min_hits=1, max_distance=120.0, iou_threshold=0.2)
        t1 = ct.update([Detection(bbox=(100, 100, 50, 100), class_id=0, confidence=0.9, label="person")], timestamp=1.0)
        pid = next(iter(t1.keys()))

        # Overlapping chair (stage 1) and nearby chair (stage 2) must NOT steal person track ID
        t2 = ct.update([Detection(bbox=(102, 102, 50, 100), class_id=56, confidence=0.9, label="chair")], timestamp=1.1)
        self.assertNotIn(pid, t2)
        self.assertEqual(len(t2), 1)
        self.assertEqual(next(iter(t2.values())).label, "chair")

    def test_appearance_assists_crossover_recovery_sort_and_centroid(self) -> None:
        emb_a = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        emb_b = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)

        for tracker_cls in (SortTracker, CentroidTracker):
            tracker = tracker_cls(min_hits=1, iou_threshold=0.3)
            d1_a = SimpleNamespace(bbox=(100, 100, 60, 100), class_id=0, confidence=0.9, label="person", embedding=emb_a)
            d1_b = SimpleNamespace(bbox=(130, 100, 60, 100), class_id=0, confidence=0.9, label="person", embedding=emb_b)
            res1 = tracker.update([d1_a, d1_b], timestamp=1.0)
            id_a = [tid for tid, trk in res1.items() if trk.bbox[0] == 100][0]
            id_b = [tid for tid, trk in res1.items() if trk.bbox[0] == 130][0]

            # Cross-over: det with emb_a is closer to B's box, det with emb_b closer to A's box
            d2_a = SimpleNamespace(bbox=(125, 100, 60, 100), class_id=0, confidence=0.9, label="person", embedding=emb_a)
            d2_b = SimpleNamespace(bbox=(105, 100, 60, 100), class_id=0, confidence=0.9, label="person", embedding=emb_b)
            res2 = tracker.update([d2_a, d2_b], timestamp=1.1)
            self.assertIn(id_a, res2)
            self.assertIn(id_b, res2)
            self.assertGreater(res2[id_a].bbox[0], res2[id_b].bbox[0])

    def test_gallery_matcher_class_guard_and_session_relink_on_sampling_gap(self) -> None:
        db = TrackerDB(":memory:")
        self.addCleanup(db.close)
        extractor = MockFeatureExtractor(embedding_dim=16)
        matcher = GalleryMatcher(db=db, extractor=extractor, reid_threshold=0.65, min_track_hits=2)

        frame = np.zeros((200, 200, 3), dtype=np.uint8)
        frame[20:80, 20:80] = [0, 255, 0]
        feat = extractor.extract(frame, (20, 20, 60, 60))

        # Enroll a chair with identical visual patch
        chair_eid = db.add_entity(name="OfficeChair", category="chair")
        db.add_signature(chair_eid, feat)
        matcher.reload_gallery()

        # A 'person' track at the same patch must NOT match 'chair' gallery entity
        person_trk = Track(track_id=1, bbox=(20, 20, 60, 60), label="person", timestamp=10.0)
        person_trk.hits = 2
        events = matcher.match_tracks({1: person_trk}, frame, source="cam0", timestamp=10.0)
        self.assertEqual(len(events), 0)
        self.assertFalse(hasattr(person_trk, "entity_id"))
        self.assertIsNotNone(person_trk.last_embedding)
        sess_id = person_trk.session_id
        self.assertIsNotNone(sess_id)

        # Simulate VideoIndexer sampling gap -> new confirmed track (hits=1) reappears nearby
        matcher.match_tracks({}, frame, source="cam0", timestamp=11.0)
        reappear_trk = Track(track_id=99, bbox=(24, 22, 60, 60), label="person", timestamp=12.0)
        reappear_trk.hits = 1
        reappear_trk.state = "confirmed"
        matcher.match_tracks({99: reappear_trk}, frame, source="cam0", timestamp=12.0)
        self.assertEqual(reappear_trk.session_id, sess_id)

        # Enrolling 'staff' matches 'person' track
        staff_eid = db.add_entity(name="Alice", category="staff")
        db.add_signature(staff_eid, feat)
        matcher.reload_gallery()
        person_trk2 = Track(track_id=2, bbox=(20, 20, 60, 60), label="person", timestamp=13.0)
        person_trk2.hits = 2
        events2 = matcher.match_tracks({2: person_trk2}, frame, source="cam0", timestamp=13.0)
        self.assertEqual(len(events2), 1)
        self.assertEqual(events2[0].entity_id, staff_eid)

    def test_cached_replay_short_gap_coasting_and_strict_file_lookup(self) -> None:
        db = TrackerDB(":memory:")
        self.addCleanup(db.close)
        dets = [
            {
                "frame": 0,
                "time": 0.0,
                "tracks": [{"id": 7, "bbox": [90, 90, 40, 60], "centroid": [110, 120], "velocity": [10.0, 0.0], "label": "person"}],
            },
            {
                "frame": 20,
                "time": 0.67,
                "tracks": [{"id": 7, "bbox": [96, 90, 40, 60], "centroid": [116, 120], "label": "person"}],
            },
        ]
        db.save_video_run(
            "clip.mp4", report={"frames_processed": 2}, config={"sample_rate": 4},
            frame_detections=dets, source_resolution=[320, 240], source_fps=30.0,
        )
        vs = SimpleNamespace(is_file=True, source="clip.mp4", source_fps=30.0)
        analytics = AnalyticsEngine()
        analytics.add_zone(ZoneROI([(50, 50), (200, 50), (200, 200), (50, 200)], name="lobby"))
        bundle = SimpleNamespace(camera_id="cam_replay", analytics=analytics, gallery_matcher=None, world_bridge=None, rsac_rules=None)

        provider = CachedReplayProvider(db, vs, bundle=bundle, tolerance_s=0.1, replay_coast_seconds=0.5)
        frame = np.zeros((240, 320, 3), dtype=np.uint8)

        # Frame at t=0.0s -> real track, enters zone
        res0 = provider.build_step_result(frame, now=100.0, frame_seq=0, media_time_s=0.0)
        self.assertIsNotNone(res0)
        self.assertIn(7, res0.tracks)
        self.assertIn(7, analytics.zones["lobby"].current_occupants)

        # Frame at t=0.25s -> missing in DB, strict FileDetectionReplayProvider returns {}
        self.assertEqual(provider.replay.lookup_tracks(8, frame.shape, media_time_s=0.25), {})
        # CachedReplayProvider coasts track 7 within 0.5s -> no false zone exit!
        res_gap = provider.build_step_result(frame, now=100.25, frame_seq=8, media_time_s=0.25)
        self.assertIn(7, res_gap.tracks)
        self.assertEqual(res_gap.tracks[7].state, "coasting")
        self.assertIn(7, analytics.zones["lobby"].current_occupants)

        # Frame at t=0.55s -> exceeds 0.5s coast budget -> tracks empty
        res_expired = provider.build_step_result(frame, now=100.55, frame_seq=17, media_time_s=0.55)
        self.assertEqual(res_expired.tracks, {})

        # Loop wrap resets coast cache cleanly
        provider.build_step_result(frame, now=100.67, frame_seq=20, media_time_s=0.67)
        res_loop = provider.build_step_result(frame, now=101.0, frame_seq=1, media_time_s=0.03)
        self.assertEqual(provider.loop_reset_count, 1)
        self.assertIn(7, res_loop.tracks)


if __name__ == "__main__":
    unittest.main()
