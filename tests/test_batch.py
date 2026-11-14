#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for offline video recording indexer & occurrence analytics (intelligent_tracker/batch.py).
"""

import os
import shutil
import tempfile
import unittest
import cv2
import numpy as np

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.batch import VideoIndexer
from intelligent_tracker.video import PipelineVideoWriter


class TestVideoIndexer(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "batch_tracker.db")
        self.db = TrackerDB(self.db_path)

        # Create a small synthetic video file
        self.video_path = os.path.join(self.temp_dir, "synthetic_test.mp4")
        with PipelineVideoWriter(self.video_path, fps=10.0, resolution=(320, 240)) as writer:
            for f in range(20):
                frame = np.full((240, 320, 3), 40, dtype=np.uint8)
                # Draw moving green rectangle
                x = 30 + f * 4
                cv2.rectangle(frame, (x, 50), (x + 40, 110), (0, 255, 0), -1)
                writer.write(frame)

        # Enroll the synthetic green entity in the database
        ref_frame = np.full((240, 320, 3), 40, dtype=np.uint8)
        cv2.rectangle(ref_frame, (50, 50), (90, 110), (0, 255, 0), -1)
        self.db.enroll_entity(
            name="Target Green",
            category="staff",
            frame=ref_frame,
            bbox=(50, 50, 40, 60),
            extractor=None,
        )

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_process_video_and_generate_report(self):
        """Test batch indexing of video and occurrence analytics reporting."""
        indexer = VideoIndexer(
            db=self.db,
            detector_name="mock",
            reid_name="color",
            sample_rate=2,
        )

        res = indexer.process_video(self.video_path, verbose=False)
        self.assertEqual(res["total_frames_in_file"], 20)
        self.assertEqual(res["processed_frames"], 10)  # sample_rate = 2

        # Generate occurrence report
        report = indexer.generate_occurrence_report()
        self.assertEqual(report["entities_analyzed"], 1)

        # Export report to JSON and CSV
        json_path = os.path.join(self.temp_dir, "report.json")
        csv_path = os.path.join(self.temp_dir, "report.csv")
        indexer.export_report(report, json_path=json_path, csv_path=csv_path)

        self.assertTrue(os.path.isfile(json_path))
        self.assertTrue(os.path.isfile(csv_path))

    def test_missing_video_raises(self):
        """Indexing a nonexistent video path should raise FileNotFoundError."""
        indexer = VideoIndexer(db=self.db, detector_name="mock")
        with self.assertRaises(FileNotFoundError):
            indexer.process_video("nonexistent_video.mp4")


if __name__ == "__main__":
    unittest.main()
