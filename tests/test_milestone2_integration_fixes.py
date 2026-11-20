"""Regression tests for Milestone 2 integration, replay, WorldGraph, and DI fixes."""

import ast
import os
import tempfile
import threading
import unittest
from unittest.mock import MagicMock

import cv2
import numpy as np
from fastapi.testclient import TestClient

from dashboard.app import create_app
from dashboard.dependencies import clear_app_state, set_shutting_down
from dashboard.services.async_inference_worker import AsyncInferenceWorker, build_live_step_result
from dashboard.services.cached_replay_provider import CachedReplayProvider
from dashboard.services.file_detection_replay import FileDetectionReplayProvider
from dashboard.services.roi_recognition_service import RoiRecognitionService
from dashboard.services.stream_recording import StreamRecordingMixin
from dashboard.services.stream_worker import StreamWorker
from intelligent_tracker.batch import VideoIndexer
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.detectors import MockDetector
from intelligent_tracker.pipeline.analytics_scheduler import AnalyticsScheduler
from intelligent_tracker.pipeline.config import PipelineConfig
from intelligent_tracker.pipeline.engine import PipelineEngine
from intelligent_tracker.pipeline.frame_processor import FrameProcessor, FrameStepResult
from intelligent_tracker.scenarios import ScenarioManager
from intelligent_tracker.tracker.track import Track
from intelligent_tracker.world import WorldGraph


class _DummyRecordingHost(StreamRecordingMixin):
    """Minimal StreamRecordingMixin host with VideoSource-like source_fps."""

    def __init__(self, source_fps: float) -> None:
        self.video_source = type("VS", (), {"source_fps": source_fps, "measured_fps": source_fps})()
        self.cfg = {"video": {"framerate": 20.0}}
        self.width, self.height = 320, 240
        self._lock = threading.RLock()
        self._is_hibernating = False
        self._latest_telemetry = {}
        self._recording_controller = MagicMock()
        self._recording_controller.start.return_value = {"status": "recording"}

    def _resume_video_source(self) -> None:
        pass


class TestMilestone2IntegrationFixes(unittest.TestCase):
    """Verify Milestone 2 pipeline, replay, WorldGraph, FTS5, and DI fixes."""

    def _make_tmpdir(self) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return tmp.name

    def test_capture_worker_uses_monotonic_clock_only(self) -> None:
        """CaptureWorkerMixin must not mix time.time() with time.monotonic()."""
        path = os.path.join("intelligent_tracker", "video", "capture_worker.py")
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        calls = [
            f"{node.func.value.id}.{node.func.attr}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "time"
        ]
        self.assertNotIn("time.time", calls)
        self.assertIn("time.monotonic", calls)

    def test_stream_worker_capture_only_skips_annotated_and_uses_vs_fps(self) -> None:
        """capture_only skips annotated encoding and falls back to vs.measured_fps."""
        mgr = MagicMock()
        mgr.camera_id = "cam_a"
        mgr._lock = threading.RLock()
        mgr._latest_raw_jpeg = b"raw"
        mgr._latest_jpeg = b"ann"
        mgr.has_raw_subscribers = False
        mgr.has_annotated_subscribers = True
        mgr._processing_mode_service = type("Svc", (), {"mode": "capture_only"})()
        mgr._recording_controller = None
        mgr.video_source = type("VS", (), {"measured_fps": 24.5})()
        worker = StreamWorker(mgr)
        worker._encode_annotated_frame = MagicMock()
        frame = np.zeros((60, 80, 3), dtype=np.uint8)
        worker._process_single_frame(FrameStepResult(frame=frame, fps=0.0, frame_count=1, timestamp=1.0))
        worker._encode_annotated_frame.assert_not_called()
        self.assertEqual(mgr._latest_telemetry["fps"], 24.5)

    def test_stream_recording_reads_source_fps(self) -> None:
        """StreamRecordingMixin.start_recording uses video_source.source_fps."""
        host = _DummyRecordingHost(source_fps=15.0)
        host.start_recording(filename="rec.mp4")
        _, kwargs = host._recording_controller.start.call_args
        self.assertEqual(kwargs["fps"], 15.0)

    def test_track_to_dict_emits_entity_id_and_category(self) -> None:
        """Track.to_dict() must include entity_id, category, and entity_category."""
        trk = Track(track_id=3, bbox=(10, 20, 30, 40), label="person", entity_id=9, entity_category="vip")
        data = trk.to_dict()
        self.assertEqual(data["entity_id"], 9)
        self.assertEqual(data["entity_category"], "vip")
        self.assertEqual(data["category"], "vip")

    def test_cached_replay_syncs_world_bridge_when_run_reid_false(self) -> None:
        """CachedReplayProvider(run_reid=False) must still sync WorldEntityBridge."""
        tmp = self._make_tmpdir()
        db = TrackerDB(os.path.join(tmp, "rep.db"))
        self.addCleanup(db.close)
        cfg = PipelineConfig(db_path=os.path.join(tmp, "rep.db"), detector_model="mock", reid_model="color")
        bundle = PipelineEngine.build(cfg)
        self.addCleanup(bundle.close)
        vs = type("VS", (), {"is_file": True, "source": "clip.mp4", "source_fps": 10.0})()
        db.save_video_run(
            video_filename="clip.mp4", report={"entities": [], "alerts": []},
            frame_detections=[{"frame": 0, "time": 0.0, "tracks": [{"track_id": 1, "bbox": [10, 10, 40, 40], "entity_id": 4}]}],
            source_fps=10.0,
        )
        crp = CachedReplayProvider(db, vs, bundle=bundle, run_reid=False)
        crp.build_step_result(np.zeros((120, 160, 3), dtype=np.uint8), now=5.0, frame_seq=1, media_time_s=0.0)
        self.assertEqual(len(bundle.world_graph.snapshot()["entities"]), 1)

    def test_file_detection_replay_reloads_after_empty_db(self) -> None:
        """FileDetectionReplayProvider.ensure_loaded() must not lock out future runs."""
        tmp = self._make_tmpdir()
        db = TrackerDB(os.path.join(tmp, "ttl.db"))
        self.addCleanup(db.close)
        vs = type("VS", (), {"is_file": True, "source": "clip.mp4", "source_fps": 10.0})()
        rep = FileDetectionReplayProvider(db, vs)
        self.assertFalse(rep.ensure_loaded())
        db.save_video_run(
            video_filename="clip.mp4", report={"entities": [], "alerts": []},
            frame_detections=[{"frame": 0, "time": 0.0, "tracks": []}], source_fps=10.0,
        )
        self.assertTrue(rep.ensure_loaded())

    def test_async_worker_records_replay_tier_in_scheduler(self) -> None:
        """Replay execution must mark PriorityTier.REPLAY in AnalyticsScheduler."""
        scheduler = AnalyticsScheduler()
        worker = AsyncInferenceWorker(processor=MagicMock(), scheduler=scheduler, camera_id="cam_r")
        provider = MagicMock()
        provider.build_step_result.return_value = FrameStepResult(frame=np.zeros((20, 20, 3), dtype=np.uint8))
        build_live_step_result(
            worker, np.zeros((20, 20, 3), dtype=np.uint8), now=1.0, frame_seq=1,
            replay_provider=provider, scheduler=scheduler, camera_id="cam_r",
        )
        self.assertEqual(scheduler.get_camera_summary("cam_r")["priority_tier"], "REPLAY")

    def test_frame_processor_rescales_tracks_above_max_dim(self) -> None:
        """FrameProcessor.step(..., max_dim=1280) rescales tracks back to source dims."""
        tmp = self._make_tmpdir()
        cfg = PipelineConfig(db_path=os.path.join(tmp, "fp.db"), detector_model="mock", reid_model="color")
        bundle = PipelineEngine.build(cfg)
        self.addCleanup(bundle.close)
        bundle.detector = MockDetector(boxes=[(900, 400, 120, 200)])
        proc = FrameProcessor(bundle)
        res = proc.step(np.zeros((1080, 1920, 3), dtype=np.uint8), timestamp=1.0, max_dim=1280)
        self.assertTrue(res.tracks)
        first_trk = next(iter(res.tracks.values()))
        self.assertGreaterEqual(first_trk.bbox[0], 1340)

    def test_scenario_manager_syncs_zones_tripwires_to_world_graph(self) -> None:
        """ScenarioManager.load_scenarios() must populate WorldGraph zones & tripwires."""
        tmp = self._make_tmpdir()
        db = TrackerDB(os.path.join(tmp, "scen.db"))
        self.addCleanup(db.close)
        db.save_zone("cam1", "Entry", [[0, 0], [100, 0], [100, 100], [0, 100]])
        db.save_tripwire("cam1", "Line", [[0, 50], [100, 50]])
        wg = WorldGraph()
        ScenarioManager(config_path=os.path.join(tmp, "s.yaml"), db=db, world_graph=wg)
        snap = wg.snapshot()
        self.assertEqual(len(snap["zones"]), 1)
        self.assertEqual(len(snap["tripwires"]), 1)

    def test_timeline_persists_video_offset_and_events_merges_db(self) -> None:
        """world_timeline_events stores video_filename/media_offset_sec and GET /events merges DB."""
        tmp = self._make_tmpdir()
        db_path = os.path.join(tmp, "ev.db")
        db = TrackerDB(db_path)
        db.index_timeline_event(
            summary="Offline alert", event_type="intrusion_alert", camera_id="clip.mp4",
            metadata={"video_filename": "clip.mp4", "media_offset_sec": 4.2},
        )
        row = db._conn.execute("SELECT video_filename, media_offset_sec FROM world_timeline_events").fetchone()
        db.close()
        self.assertEqual((row[0], row[1]), ("clip.mp4", 4.2))
        cfg_path = os.path.join(tmp, "cameras.json")
        with open(cfg_path, "w", encoding="utf-8") as fh:
            fh.write('{"cameras": {}}')
        env = {"TRACKER_DB_PATH": db_path, "CAMERAS_CONFIG_PATH": cfg_path, "SCENARIOS_CONFIG_PATH": os.path.join(tmp, "s.yaml")}
        with unittest.mock.patch.dict(os.environ, env, clear=False):
            set_shutting_down(False)
            app = create_app()
            with TestClient(app) as client:
                r = client.get("/events")
                self.assertEqual(r.status_code, 200)
                self.assertTrue(any(ev.get("video_filename") == "clip.mp4" for ev in r.json()))
            clear_app_state(app)

    def test_roi_recognition_persists_media_offset_and_batch_hooks(self) -> None:
        """RoiRecognitionService saves media_offset_sec and VideoIndexer wires WorldGraph."""
        tmp = self._make_tmpdir()
        vid = os.path.join(tmp, "clip.mp4")
        writer = cv2.VideoWriter(vid, cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (160, 120))
        for _ in range(5):
            writer.write(np.zeros((120, 160, 3), dtype=np.uint8))
        writer.release()
        db = TrackerDB(os.path.join(tmp, "roi.db"))
        self.addCleanup(db.close)
        svc = RoiRecognitionService(db=db, videos_dir=tmp, crops_dir=os.path.join(tmp, "crops"))
        res = svc.commit_roi_tag(entity_name="TagA", video_filename="clip.mp4", timestamp_sec=1.5, bbox=[10, 10, 40, 60])
        self.assertEqual(db.get_sightings(entity_id=res["entity_id"], limit=5)[0]["media_offset_sec"], 1.5)
        indexer = VideoIndexer(db=db, detector_name="mock", reid_name="color", video_filename="clip.mp4")
        proc = indexer._build_frame_processor("clip.mp4", video_filename="clip.mp4")
        self.assertIsNotNone(proc.bundle.world_graph)
        self.assertIsNotNone(proc.bundle.confidence_engine)


if __name__ == "__main__":
    unittest.main()
