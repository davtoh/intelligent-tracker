"""Step 5 Milestone 1 tests: FrameProcessor batch unification & video offset persistence."""

import os
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from intelligent_tracker.active_learning import ActiveLearningManager
from intelligent_tracker.batch import VideoIndexer
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.tracker import Track
from intelligent_tracker.video import PipelineVideoWriter


class TestStep5BatchFrameProcessor(unittest.TestCase):
    """Verify VideoIndexer delegates to FrameProcessor.step() and persists media offsets."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, "step5_batch.db")
        self.db = TrackerDB(self.db_path)
        self.addCleanup(self.db.close)
        self.crops_dir = os.path.join(self._tmp.name, "crops")
        self.video_path = os.path.join(self._tmp.name, "lobby_clip.mp4")
        with PipelineVideoWriter(self.video_path, fps=10.0, resolution=(320, 240)) as writer:
            for _ in range(12):
                frame = np.full((240, 320, 3), 40, dtype=np.uint8)
                cv2.rectangle(frame, (40, 40), (160, 200), (0, 255, 0), -1)
                writer.write(frame)

    def _enroll_green_target(self, extractor=None) -> int:
        ref = np.full((240, 320, 3), 40, dtype=np.uint8)
        cv2.rectangle(ref, (40, 40), (160, 200), (0, 255, 0), -1)
        res = self.db.enroll_entity(
            name="Green Target", category="staff", frame=ref, bbox=(50, 50, 60, 120), extractor=extractor,
        )
        return int(res["id"]) if isinstance(res, dict) else int(res)

    def test_video_schema_adds_review_queue_media_columns(self) -> None:
        """review_queue and sightings both carry video_filename and media_offset_sec."""
        with self.db._lock:
            rq_cols = {r[1] for r in self.db._conn.execute("PRAGMA table_info(review_queue);").fetchall()}
            sg_cols = {r[1] for r in self.db._conn.execute("PRAGMA table_info(sightings);").fetchall()}
        self.assertIn("video_filename", rq_cols)
        self.assertIn("media_offset_sec", rq_cols)
        self.assertIn("video_filename", sg_cols)
        self.assertIn("media_offset_sec", sg_cols)

    def test_db_add_sighting_and_review_item_persist_media_offsets(self) -> None:
        """TrackerDB.add_sighting and add_review_item store video_filename and media_offset_sec."""
        eid = self._enroll_green_target()
        sid = self.db.add_sighting(
            entity_id=eid, track_id=3, source="lobby_clip.mp4", timestamp=12.5,
            video_filename="lobby_clip.mp4", media_offset_sec=12.5,
        )
        rid = self.db.add_review_item(
            camera_id="lobby_clip.mp4", track_id=4, crop_path="crop.jpg",
            suggested_entity_id=eid, similarity=0.55,
            video_filename="lobby_clip.mp4", media_offset_sec=7.25,
        )
        sighting = self.db.get_sightings(entity_id=eid, limit=5)[0]
        review = [r for r in self.db.list_review_items(limit=10) if r["id"] == rid][0]
        self.assertEqual(sighting["id"], sid)
        self.assertEqual(sighting["video_filename"], "lobby_clip.mp4")
        self.assertAlmostEqual(float(sighting["media_offset_sec"]), 12.5, places=3)
        self.assertEqual(review["video_filename"], "lobby_clip.mp4")
        self.assertAlmostEqual(float(review["media_offset_sec"]), 7.25, places=3)

    def test_video_indexer_executes_via_frame_processor_step_and_persists_sightings(self) -> None:
        """VideoIndexer.process_video routes frames through FrameProcessor.step() and logs offsets."""
        from intelligent_tracker.pipeline.frame_processor import FrameProcessor

        indexer = VideoIndexer(
            db=self.db, detector_name="mock", reid_name="color", reid_threshold=0.3, sample_rate=2,
        )
        eid = self._enroll_green_target(extractor=indexer.extractor)
        indexer.matcher.refresh_gallery()
        orig_step = FrameProcessor.step
        with patch("intelligent_tracker.pipeline.frame_processor.FrameProcessor.step", autospec=True) as spy_step:
            spy_step.side_effect = lambda self_proc, frame, timestamp=None, **kw: orig_step(
                self_proc, frame, timestamp=timestamp, **kw
            )
            summary = indexer.process_video(self.video_path, verbose=False)

        self.assertEqual(summary["processed_frames"], 6)
        self.assertEqual(spy_step.call_count, 6)
        sightings = self.db.get_sightings(entity_id=eid, limit=20)
        self.assertGreater(len(sightings), 0)
        self.assertTrue(all(s["video_filename"] == "lobby_clip.mp4" for s in sightings))
        self.assertTrue(any(float(s["media_offset_sec"]) >= 0.0 for s in sightings))

    def test_active_learning_forwards_video_filename_and_offset(self) -> None:
        """ActiveLearningManager.consider_candidate persists video_filename and media_offset_sec."""
        eid = self._enroll_green_target()
        al = ActiveLearningManager(
            db=self.db, min_confidence=0.45, max_confidence=0.70,
            debounce_interval=10.0, crops_dir=self.crops_dir,
        )
        al.video_filename = "lobby_clip.mp4"
        frame = np.full((240, 320, 3), 60, dtype=np.uint8)
        track = Track(track_id=9, bbox=(40, 40, 50, 80))
        review_id = al.consider_candidate(
            track=track, frame=frame, similarity=0.58,
            suggested_entity_id=eid, suggested_name="Green Target",
            camera_id="lobby_clip.mp4", timestamp=4.2,
        )
        self.assertIsNotNone(review_id)
        item = [r for r in self.db.list_review_items(limit=10) if r["id"] == review_id][0]
        self.assertEqual(item["video_filename"], "lobby_clip.mp4")
        self.assertAlmostEqual(float(item["media_offset_sec"]), 4.2, places=3)


if __name__ == "__main__":
    unittest.main()
