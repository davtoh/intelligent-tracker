"""Golden headless parity tests for FrameProcessor.step() across CLI and Dashboard configs."""

from argparse import Namespace
import os
import tempfile
import unittest
from unittest.mock import MagicMock

import numpy as np

from intelligent_tracker.events import EntityIdentifiedEvent, RestrictedEntityAlert
from intelligent_tracker.pipeline import FrameProcessor, FrameStepResult, PipelineEngine


def _make_synthetic_frames(count: int = 12, width: int = 640, height: int = 480) -> list[np.ndarray]:
    """Create deterministic BGR frames for headless pipeline stepping."""
    frames: list[np.ndarray] = []
    for idx in range(count):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:, :, 0] = (idx * 17) % 255
        frame[50:170, 50 + idx * 5 : 110 + idx * 5] = (40, 200, 90)
        frames.append(frame)
    return frames


def _shared_raw_config(db_path: str, tracker_type: str) -> dict:
    """Return a shared config dictionary with zone and tripwire in MockDetector's path."""
    return {
        "video": {
            "source": "synthetic",
            "resolution": "640x480",
            "framerate": 30,
        },
        "detector": {
            "model": "mock",
            "confidence": 0.9,
        },
        "tracker": {
            "type": tracker_type,
            "max_disappeared": 10,
            "min_hits": 1,
            "iou_threshold": 0.3,
        },
        "reid": {
            "model": "color",
            "threshold": 0.5,
        },
        "database": {
            "path": db_path,
        },
        "analytics": {
            "camera_id": "cam_parity",
            "heatmap_enabled": False,
            "tripwires": [
                {
                    "name": "entry_line",
                    "line": [[105, 40], [105, 240]],
                    "bidirectional": True,
                }
            ],
            "zones": [
                {
                    "name": "lobby",
                    "polygon": [[75, 90], [100, 90], [100, 160], [75, 160]],
                    "dwell_threshold": 0.1,
                }
            ],
        },
    }


class TestFrameProcessorParity(unittest.TestCase):
    """Verify FrameProcessor.step() parity between CLI and Dashboard configs."""

    def _make_temp_dir(self) -> str:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        return tmpdir.name

    def test_cli_vs_dashboard_parity_centroid_and_sort(self) -> None:
        frames = _make_synthetic_frames(count=12)
        for tracker_type in ("centroid", "sort"):
            with self.subTest(tracker_type=tracker_type):
                tmpdir = self._make_temp_dir()
                cli_db = os.path.join(tmpdir, f"cli_{tracker_type}.db")
                dash_db = os.path.join(tmpdir, f"dash_{tracker_type}.db")

                cli_args = Namespace(
                    source="synthetic",
                    detector="mock",
                    tracker=tracker_type,
                    reid="color",
                    resolution="640x480",
                    db=cli_db,
                    conf=0.9,
                    classes=None,
                    output=None,
                    headless=True,
                )
                cli_bundle = PipelineEngine.from_cli_args(
                    cli_args,
                    cfg=_shared_raw_config(cli_db, tracker_type),
                )
                cli_bundle.config.enable_governance = True
                dash_bundle = PipelineEngine.from_dict(
                    _shared_raw_config(dash_db, tracker_type),
                    enable_governance=True,
                    enable_event_bus_fallback=True,
                )
                self.addCleanup(cli_bundle.close)
                self.addCleanup(dash_bundle.close)

                # Enroll identical entity in both isolated DBs to verify Re-ID parity
                emb = np.ones((1, 512), dtype=np.float32)
                if cli_bundle.db is not None:
                    eid = cli_bundle.db.add_entity("ParitySubject", "general")
                    cli_bundle.db.add_signature(eid, emb)
                if dash_bundle.db is not None:
                    eid = dash_bundle.db.add_entity("ParitySubject", "general")
                    dash_bundle.db.add_signature(eid, emb)

                cli_proc = FrameProcessor(cli_bundle)
                dash_proc = FrameProcessor(dash_bundle)

                cli_results: list[FrameStepResult] = []
                dash_results: list[FrameStepResult] = []
                for idx, frame in enumerate(frames):
                    ts = 1000.0 + idx * 0.1
                    cli_results.append(cli_proc.step(frame, timestamp=ts))
                    dash_results.append(dash_proc.step(frame, timestamp=ts))

                self.assertEqual(len(cli_results[-1].detections), len(dash_results[-1].detections))
                self.assertGreater(len(cli_results[-1].tracks), 0)
                self.assertEqual(len(cli_results[-1].tracks), len(dash_results[-1].tracks))

                cli_summary = cli_bundle.analytics.export_summary()
                dash_summary = dash_bundle.analytics.export_summary()
                self.assertEqual(cli_summary["tripwires"], dash_summary["tripwires"])
                self.assertEqual(cli_summary["zones"], dash_summary["zones"])
                self.assertIsNotNone(dash_bundle.rsac_manager)
                self.assertIsNotNone(dash_bundle.active_learning)
                self.assertIsNotNone(dash_bundle.enrollment_manager)

    def test_frame_processor_resize_and_validation(self) -> None:
        tmpdir = self._make_temp_dir()
        bundle = PipelineEngine.from_dict(
            {
                "video": {"source": "synthetic", "resolution": [640, 480]},
                "detector": {"model": "mock"},
                "tracker": {"type": "centroid"},
                "reid": {"model": ""},
                "database": {"path": os.path.join(tmpdir, "resize.db")},
            }
        )
        self.addCleanup(bundle.close)
        proc = FrameProcessor(bundle)

        with self.assertRaises(ValueError):
            proc.step(None)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            proc.step(np.empty((0, 0, 3), dtype=np.uint8))

        large = np.zeros((1080, 1920, 3), dtype=np.uint8)
        res = proc.step(large, timestamp=10.0, max_dim=640)
        self.assertEqual(res.frame.shape[:2], (360, 640))
        self.assertGreater(res.fps, 0.0)
        self.assertEqual(res.frame_count, 1)

        res2 = proc.step(large, timestamp=10.1, target_size=(320, 240))
        self.assertEqual(res2.frame.shape[:2], (240, 320))
        self.assertEqual(res2.frame_count, 2)

        proc.reset_fps()
        self.assertEqual(proc.frame_count, 0)
        self.assertEqual(proc.measured_fps, 0.0)

    def test_frame_processor_reid_events_and_topology_exit(self) -> None:
        tmpdir = self._make_temp_dir()
        bundle = PipelineEngine.from_dict(
            {
                "video": {"source": "synthetic", "resolution": "640x480"},
                "detector": {"model": "mock"},
                "tracker": {"type": "centroid"},
                "reid": {"model": ""},
                "database": {"path": os.path.join(tmpdir, "events.db")},
                "analytics": {"camera_id": "cam_gate"},
            },
            enable_event_bus_fallback=True,
        )
        self.addCleanup(bundle.close)

        published: list[object] = []
        mock_bus = MagicMock()
        mock_bus.publish.side_effect = published.append
        bundle.event_bus = mock_bus

        fake_event = EntityIdentifiedEvent(
            camera_id="",
            track_id=1,
            entity_id=42,
            name="RestrictedVIP",
            category="restricted",
            similarity=0.92,
        )
        mock_matcher = MagicMock()
        mock_matcher.topology = None
        mock_matcher.match_tracks.return_value = [fake_event]
        bundle.gallery_matcher = mock_matcher

        mock_topology = MagicMock()
        bundle.analytics.update = MagicMock(
            return_value={
                "new_events": [
                    {"event_type": "zone_exit", "zone_id": "lobby", "track_id": 1}
                ]
            }
        )

        proc = FrameProcessor(bundle, topology=mock_topology)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = proc.step(frame, timestamp=1234.5)

        self.assertEqual(len(result.identifications), 1)
        mock_topology.record_zone_exit.assert_called_once()
        self.assertIs(mock_matcher.topology, mock_topology)
        self.assertEqual(len(published), 2)
        self.assertIsInstance(published[0], EntityIdentifiedEvent)
        self.assertIsInstance(published[1], RestrictedEntityAlert)


if __name__ == "__main__":
    unittest.main()
