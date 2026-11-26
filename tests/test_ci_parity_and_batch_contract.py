"""CI parity and batch detector contract tests (Milestone 1)."""

import os
import tempfile
import unittest

import cv2
import numpy as np

from intelligent_tracker.batch import VideoIndexer, _create_batch_detector
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.detectors import MockDetector
from intelligent_tracker.video import PipelineVideoWriter


def _write_synthetic_clip(path: str, num_frames: int = 6, fps: float = 10.0) -> None:
    """Create a tiny synthetic MP4 with a moving rectangle for headless batch tests."""
    with PipelineVideoWriter(path, fps=fps, resolution=(320, 240)) as writer:
        for idx in range(num_frames):
            frame = np.full((240, 320, 3), 25, dtype=np.uint8)
            x0 = 40 + idx * 12
            cv2.rectangle(frame, (x0, 50), (x0 + 60, 170), (0, 200, 90), -1)
            writer.write(frame)


class TestBatchDetectorConfidenceContract(unittest.TestCase):
    """Verify _create_batch_detector preserves caller confidence without silent clamps."""

    def test_create_batch_detector_preserves_mock_confidence(self) -> None:
        """_create_batch_detector('mock', 0.45, None) preserves 0.45 without clamping to 0.95."""
        det_mid = _create_batch_detector("mock", 0.45, None)
        self.assertIsInstance(det_mid, MockDetector)
        self.assertAlmostEqual(det_mid.confidence, 0.45, places=6)

        det_low = _create_batch_detector("mockdetector", 0.25, None)
        self.assertIsInstance(det_low, MockDetector)
        self.assertAlmostEqual(det_low.confidence, 0.25, places=6)

        det_high = _create_batch_detector("mock", 0.95, None)
        self.assertIsInstance(det_high, MockDetector)
        self.assertAlmostEqual(det_high.confidence, 0.95, places=6)

    def test_video_indexer_end_to_end_under_mock_detector_preserves_confidence(self) -> None:
        """VideoIndexer honors explicit MockDetector confidence and tracks frames end-to-end."""
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        video_path = os.path.join(tmpdir.name, "mock_batch.mp4")
        _write_synthetic_clip(video_path, num_frames=6, fps=10.0)
        db = TrackerDB(os.path.join(tmpdir.name, "batch_contract.db"))
        self.addCleanup(db.close)

        indexer = VideoIndexer(
            db=db,
            detector_name="mock",
            conf_threshold=0.85,
            sample_rate=1,
            video_filename="mock_batch.mp4",
        )
        self.addCleanup(indexer.close)
        self.assertIsInstance(indexer.detector, MockDetector)
        self.assertAlmostEqual(indexer.detector.confidence, 0.85, places=6)

        summary = indexer.process_video(video_path, verbose=False)
        self.assertEqual(summary["processed_frames"], 6)
        self.assertGreater(summary["total_detections"], 0)
        self.assertGreater(len(summary["frame_detections"]), 0)
        first_tracks = summary["frame_detections"][0]["tracks"]
        self.assertGreater(len(first_tracks), 0)
        self.assertAlmostEqual(float(first_tracks[0]["confidence"]), 0.85, places=2)

    def test_video_indexer_low_mock_confidence_is_not_silently_clamped(self) -> None:
        """Low MockDetector confidence (< SortTracker high_conf_threshold) is honored verbatim."""
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        video_path = os.path.join(tmpdir.name, "mock_low_conf.mp4")
        _write_synthetic_clip(video_path, num_frames=4, fps=10.0)
        db = TrackerDB(os.path.join(tmpdir.name, "batch_low_conf.db"))
        self.addCleanup(db.close)

        indexer = VideoIndexer(
            db=db,
            detector_name="mock",
            conf_threshold=0.20,
            sample_rate=1,
            video_filename="mock_low_conf.mp4",
        )
        self.addCleanup(indexer.close)
        self.assertAlmostEqual(indexer.detector.confidence, 0.20, places=6)

        summary = indexer.process_video(video_path, verbose=False)
        self.assertEqual(summary["processed_frames"], 4)
        self.assertEqual(summary["total_detections"], 4)
        self.assertEqual(summary["frame_detections"], [])


if __name__ == "__main__":
    unittest.main()
