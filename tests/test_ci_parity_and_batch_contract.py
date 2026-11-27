"""CI parity and batch detector contract tests (Milestones 1 & 2)."""

import os
import tempfile
import types
import unittest

import cv2
import numpy as np

from dashboard.services.entity_tagger import _to_avatar_url
from dashboard.services.roi_recognition_helpers import record_roi_side_effects
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


class _StubHysteresis:
    """Minimal hysteresis stub recording force_bind calls."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def force_bind(
        self, track_id: int, entity_id: int, name: str, category: str,
        *, avatar_url: str | None = None, track: object = None,
    ) -> None:
        self.calls.append({
            "track_id": track_id, "entity_id": entity_id,
            "name": name, "category": category,
            "avatar_url": avatar_url, "track": track,
        })


def _make_roi_harness(
    track_id: int,
) -> tuple[types.SimpleNamespace, types.SimpleNamespace, _StubHysteresis, types.SimpleNamespace]:
    """Build lightweight stream/gallery/track stubs for record_roi_side_effects."""
    live_track = types.SimpleNamespace(avatar_url=None)
    tracker = types.SimpleNamespace(tracks={track_id: live_track})
    hysteresis = _StubHysteresis()
    gallery = types.SimpleNamespace(
        refresh_gallery=lambda: None,
        hysteresis=hysteresis,
        _identified_tracks={},
        entity_avatars={},
    )
    mgr = types.SimpleNamespace(
        tracker=tracker, gallery_matcher=gallery, world_bridge=None,
    )
    return mgr, live_track, hysteresis, gallery


class TestCrossPlatformAvatarUrlAndRoiPropagation(unittest.TestCase):
    """Verify POSIX/Windows crop paths normalize to /crops/<basename> without host leakage."""

    def test_to_avatar_url_normalizes_posix_windows_and_passthrough_urls(self) -> None:
        """_to_avatar_url handles /tmp POSIX paths, Windows drive paths, and URL passthroughs."""
        cases = [
            ("/tmp/crops/abc.jpg", "/crops/abc.jpg"),
            ("/var/tmp/runner/crops/abc.jpg", "/crops/abc.jpg"),
            (r"C:\crops\abc.jpg", "/crops/abc.jpg"),
            (r"C:\Users\ci\data\crops\abc.jpg", "/crops/abc.jpg"),
            ("data/crops/abc.jpg", "/crops/abc.jpg"),
            ("/crops/abc.jpg", "/crops/abc.jpg"),
            ("https://cdn.example.com/avatars/abc.jpg", "https://cdn.example.com/avatars/abc.jpg"),
            ("http://cdn.example.com/avatars/abc.jpg", "http://cdn.example.com/avatars/abc.jpg"),
            ("data:image/jpeg;base64,Zm9v", "data:image/jpeg;base64,Zm9v"),
            (None, None),
            ("", None),
            ("   ", None),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(_to_avatar_url(raw), expected)

    def test_record_roi_side_effects_propagates_posix_and_windows_avatar_urls(self) -> None:
        """record_roi_side_effects propagates normalized /crops/<name> URLs to track and gallery."""
        emb = np.ones(8, dtype=np.float32)
        db = types.SimpleNamespace(record_descriptor_version=lambda **_kw: None)
        ce = types.SimpleNamespace(record_human_feedback=lambda **_kw: None)
        fts = types.SimpleNamespace(index_sighting=lambda **_kw: None)

        for label, crop_path, expected_url, use_pool in (
            ("posix_tmp", "/tmp/crops/posix_abc.jpg", "/crops/posix_abc.jpg", False),
            ("windows_drive", r"C:\crops\win_abc.jpg", "/crops/win_abc.jpg", True),
        ):
            with self.subTest(case=label):
                mgr, live_track, hysteresis, gallery = _make_roi_harness(track_id=7)
                pool = types.SimpleNamespace(get_stream=lambda cid, m=mgr: m if cid == "cam_01" else None)
                svc = types.SimpleNamespace(
                    db=db, confidence_engine=ce, fts_index=fts,
                    stream_manager=None if use_pool else mgr,
                    camera_pool=pool if use_pool else None,
                )
                record_roi_side_effects(
                    svc, entity_id=42, entity_name="Alice", category="person", emb=emb,
                    crop_path=crop_path, notes="ci parity", source="cam_01",
                    track_id=7, camera_id="cam_01", video_filename="clip.mp4", media_offset_sec=1.5,
                )
                self.assertEqual(live_track.avatar_url, expected_url)
                self.assertEqual(gallery._identified_tracks[7]["avatar_url"], expected_url)
                self.assertEqual(len(hysteresis.calls), 1)
                self.assertEqual(hysteresis.calls[0]["avatar_url"], expected_url)


if __name__ == "__main__":
    unittest.main()
