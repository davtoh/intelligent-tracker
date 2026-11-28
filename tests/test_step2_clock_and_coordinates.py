"""Tests for Step 2 Milestone 1: dual-clock domain separation, 1280px coordinate rescaling, and heatmap sizing."""

import os
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

import cv2
import numpy as np

from dashboard.services.async_inference_worker import AsyncInferenceWorker, build_live_step_result
from dashboard.services.frame_overlay import FrameOverlayRenderer
from dashboard.services.multiview.thumbnail_cache import ThumbnailCache
from intelligent_tracker.analytics.heatmap import OccupancyHeatmap
from intelligent_tracker.batch import VideoIndexer
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.detectors import MockDetector
from intelligent_tracker.matching._gallery_signals import emit_periodic_sighting
from intelligent_tracker.memory.fts_index import EventFTSIndex
from intelligent_tracker.pipeline.config import PipelineConfig
from intelligent_tracker.pipeline.engine import PipelineEngine
from intelligent_tracker.pipeline.frame_processor import FrameProcessor, FrameStepResult


class TestStep2ClockAndCoordinates(unittest.TestCase):
    """Verify P0-1 clock separation, P0-3 non-destructive rescaling, and P0-4 heatmap resize."""

    def test_async_worker_separates_wall_epoch_from_monotonic_scheduler(self) -> None:
        """AsyncInferenceWorker stamps Unix epoch on step() while passing monotonic to scheduler."""
        seen_step_ts: list[float] = []
        done = threading.Event()

        def _fake_step(frame: np.ndarray, timestamp: float, max_dim: int = 1280) -> FrameStepResult:
            seen_step_ts.append(timestamp)
            done.set()
            return FrameStepResult(frame=frame, tracks={1: SimpleNamespace(id=1)}, timestamp=timestamp)

        scheduler = MagicMock()
        worker = AsyncInferenceWorker(SimpleNamespace(step=_fake_step), scheduler=scheduler, camera_id="cam_1", is_armed=True)
        worker.start()
        self.addCleanup(worker.stop)

        worker.submit(np.zeros((64, 64, 3), dtype=np.uint8), timestamp=None, frame_seq=1)
        self.assertTrue(done.wait(timeout=2.0))
        res = worker.get_latest_result()
        self.assertIsNotNone(res)
        self.assertGreaterEqual(seen_step_ts[0], 1_000_000_000.0)
        self.assertGreaterEqual(float(getattr(res, "inference_timestamp", 0.0)), 1_000_000_000.0)
        start_now = scheduler.record_inference_start.call_args.kwargs["now"]
        self.assertLess(start_now, 1_000_000_000.0)

    def test_build_live_step_result_stamps_wall_epoch_and_schedules_monotonic(self) -> None:
        """build_live_step_result(now=None) uses wall epoch for step result and monotonic for scheduler."""
        scheduler = MagicMock()
        scheduler.should_schedule_frame.return_value = SimpleNamespace(
            should_run=False, priority_tier="P1", target_fps=10.0, motion_active=False, load_shed_stage="normal"
        )
        worker = AsyncInferenceWorker(SimpleNamespace(step=MagicMock()), scheduler=scheduler, camera_id="cam_2")
        res = build_live_step_result(worker, np.zeros((32, 32, 3), dtype=np.uint8), now=None, frame_seq=1, scheduler=scheduler, camera_id="cam_2")
        self.assertGreaterEqual(res.timestamp, 1_000_000_000.0)
        sched_ts = scheduler.should_schedule_frame.call_args[0][2]
        self.assertLess(sched_ts, 1_000_000_000.0)

    def test_thumbnail_cache_uses_monotonic_rate_gate_and_wall_ts_ms(self) -> None:
        """ThumbnailCache.update_frame(timestamp_s=None) keeps _last_encode_ts monotonic and ts_ms wall epoch."""
        cache = ThumbnailCache("cam_thumb")
        cache.acquire_lease("v1", 320, 5.0)
        updated = cache.update_frame(np.zeros((120, 160, 3), dtype=np.uint8), seq=1, timestamp_s=None)
        self.assertEqual(updated, [320])
        slot = cache.get_latest(320)
        self.assertIsNotNone(slot)
        self.assertGreaterEqual(slot.ts_ms, 1_000_000_000_000)
        self.assertLess(cache._last_encode_ts[320], 1_000_000_000.0)

    def test_video_indexer_passes_wall_epoch_and_records_media_offset(self) -> None:
        """VideoIndexer stamps base_epoch + video_ts on step() while keeping frame_detections relative."""
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        vid_path = os.path.join(tmpdir.name, "clip.mp4")
        writer = cv2.VideoWriter(vid_path, cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (320, 240))
        try:
            for _ in range(3):
                writer.write(np.zeros((240, 320, 3), dtype=np.uint8))
        finally:
            writer.release()

        db = TrackerDB(os.path.join(tmpdir.name, "batch.db"))
        self.addCleanup(db.close)
        indexer = VideoIndexer(
            db=db, detector_name="mock", reid_name="color", conf_threshold=0.95, video_filename="clip.mp4",
        )
        seen_ts: list[float] = []
        orig_step = FrameProcessor.step

        def _spy_step(proc_self: FrameProcessor, frame: np.ndarray, timestamp: float | None = None, **kw: object) -> FrameStepResult:
            if proc_self.bundle.db is db and timestamp is not None:
                seen_ts.append(float(timestamp))
            return orig_step(proc_self, frame, timestamp=timestamp, **kw)

        orig = FrameProcessor.step
        FrameProcessor.step = _spy_step
        try:
            report = indexer.process_video(vid_path, verbose=False)
        finally:
            FrameProcessor.step = orig

        self.assertEqual(len(seen_ts), 3)
        self.assertGreaterEqual(seen_ts[0], 1_000_000_000.0)
        self.assertLess(report["frame_detections"][0]["time"], 10.0)

    def test_emit_periodic_sighting_forwards_media_offset_to_fts_and_db(self) -> None:
        """emit_periodic_sighting writes real epoch timestamp and media_offset_sec to DB and FTS."""
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        db = TrackerDB(os.path.join(tmpdir.name, "sight.db"))
        self.addCleanup(db.close)
        eid = db.add_entity("Alice", "person")
        fts = EventFTSIndex(db=db)
        matcher = SimpleNamespace(
            db=db, sighting_interval=1.0, _last_sighting_time={},
            video_filename="clip.mp4", current_media_offset_sec=4.25, fts_index=fts,
        )
        trk = SimpleNamespace(track_id=1, bbox=(10, 10, 40, 80))
        wall_ts = time.time()
        ok = emit_periodic_sighting(
            matcher, entity_id=eid, name="Alice", category="person",
            track=trk, confidence=0.9, source="clip.mp4", zone_id="", timestamp=wall_ts,
        )
        self.assertTrue(ok)
        s_row = db.get_sightings(entity_id=eid, limit=1)[0]
        self.assertFalse(str(s_row["timestamp"]).startswith("1970-"))
        self.assertAlmostEqual(float(s_row["media_offset_sec"]), 4.25, places=2)
        fts_row = db._conn.execute("SELECT video_filename, media_offset_sec FROM world_timeline_events").fetchone()
        self.assertEqual(fts_row["video_filename"], "clip.mp4")
        self.assertAlmostEqual(float(fts_row["media_offset_sec"]), 4.25, places=2)

    def test_frame_processor_non_destructive_rescale_preserves_centroid_tracks(self) -> None:
        """FrameProcessor(max_dim=1280) rescales returned tracks without mutating CentroidTracker state."""
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        cfg = PipelineConfig(db_path=os.path.join(tmpdir.name, "p03.db"), detector_model="mock", reid_model="color", tracker_type="centroid")
        bundle = PipelineEngine.build(cfg)
        self.addCleanup(bundle.close)
        det = MockDetector(boxes=[(900, 466, 120, 166)])
        bundle.detector = det
        proc = FrameProcessor(bundle)
        hd = np.zeros((1080, 1920, 3), dtype=np.uint8)
        ids: list[int] = []
        for idx in range(5):
            det.preset_boxes = [(900 + idx * 10, 466, 120, 166)]
            res = proc.step(hd, timestamp=time.time() + idx * 0.1, max_dim=1280)
            ids.append(next(iter(res.tracks.keys())))
        self.assertEqual(len(set(ids)), 1)
        self.assertGreaterEqual(next(iter(res.tracks.values())).bbox[0], 1300)
        internal_trk = next(iter(bundle.tracker.tracks.values()))
        self.assertLess(internal_trk.bbox[0], 1280)

    def test_occupancy_heatmap_draw_resizes_across_resolutions(self) -> None:
        """OccupancyHeatmap.draw() and FrameOverlayRenderer.render() handle 640x480 -> 1280x720."""
        hm = OccupancyHeatmap(width=640, height=480)
        hm.update([SimpleNamespace(centroid=(320.0, 240.0))])
        hd_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        rendered = hm.draw(hd_frame, alpha=0.55)
        self.assertEqual(rendered.shape, (720, 1280, 3))
        self.assertGreater(int(np.sum(rendered)), 0)
        analytics = SimpleNamespace(heatmap=hm, zones={}, tripwires={})
        overlay_out = FrameOverlayRenderer.render(hd_frame, {}, {"heatmap": True}, "cam_hd", 10.0, time.time(), analytics=analytics, draw_heatmap=True)
        self.assertEqual(overlay_out.shape, (720, 1280, 3))
