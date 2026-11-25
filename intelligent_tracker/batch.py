#!/usr/bin/env python
"""
Offline Video Recording Indexer & Occurrence Analytics Module.

Provides sampled-frame batch ingestion for recorded video files (.mp4, .avi, .mkv)
through the canonical ``FrameProcessor`` pipeline, logging sightings, spatial
analytics, RSAC alerts, and active-learning candidates into SQLite ``TrackerDB``.
"""

import logging
import os
import threading
import time
from typing import Any, Callable

import cv2

from intelligent_tracker.analytics import AnalyticsEngine
from intelligent_tracker.batch_reporting import (
    build_final_report,
    emit_progress,
    export_occurrence_report,
    flush_meta,
    format_occurrence_report,
    open_video_capture as _open_video_capture,
    print_occurrence_report,
    read_video_timestamp as _read_video_timestamp,
    record_step_occurrences as _record_step_occurrences,
    run_batch_cli,
)
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.detectors import DetectorFactory
from intelligent_tracker.matcher import GalleryMatcher
from intelligent_tracker.memory import ConfidenceEngine
from intelligent_tracker.pipeline.bundle import PipelineBundle
from intelligent_tracker.pipeline.config import PipelineConfig
from intelligent_tracker.pipeline.frame_processor import FrameProcessor, FrameStepResult
from intelligent_tracker.reid import ReIDExtractorFactory
from intelligent_tracker.tracker import TrackerFactory
from intelligent_tracker.world import WorldGraph

logger = logging.getLogger(__name__)


def _create_batch_detector(detector_name: str, conf_threshold: float, classes: list[str] | None) -> Any:
    """Instantiate configured object detector for batch video processing."""
    det_kwargs: dict[str, Any] = {}
    det_clean = str(detector_name).lower().strip()
    if det_clean in ("yolov8", "yolov8n", "yolo11", "yolo11n", "onnx"):
        det_kwargs["conf_threshold"] = conf_threshold
        if classes:
            det_kwargs["classes"] = classes
    elif det_clean in ("mock", "mockdetector"):
        det_kwargs["confidence"] = conf_threshold
    return DetectorFactory.create(detector_name, **det_kwargs)


def _dispatch_frame_flush(
    callback: Callable[[list[dict[str, Any]], dict[str, Any]], None] | None,
    frame_detections: list[dict[str, Any]],
    last_flushed_idx: int,
    meta: dict[str, Any],
) -> int:
    """Emit newly collected frame detections to a progressive stream listener."""
    if callback is None:
        return last_flushed_idx
    chunk = list(frame_detections[last_flushed_idx:])
    try:
        callback(chunk, meta)
    except Exception as cb_err:
        logger.debug("Frame flush callback error: %s", cb_err)
    return len(frame_detections)


def _step_video_frame(processor: FrameProcessor, frame: Any, timestamp: float) -> FrameStepResult:
    """Execute one canonical ``FrameProcessor.step`` cycle on an offline frame."""
    return processor.step(frame, timestamp=timestamp)


class VideoIndexer:
    """Offline batch video processor and occurrence analytics indexer."""

    def __init__(
        self,
        db: TrackerDB | None = None,
        db_path: str = "data/tracker.db",
        detector_name: str = "yolov8",
        reid_name: str = "dual",
        reid_threshold: float = 0.65,
        tracker_type: str = "centroid",
        sample_rate: int = 1,
        conf_threshold: float = 0.25,
        classes: list[str] | None = None,
        analytics: AnalyticsEngine | None = None,
        rsac_manager: Any = None,
        active_learning: Any = None,
        event_bus: Any = None,
        frame_processor: FrameProcessor | None = None,
        video_filename: str = "",
        world_graph: Any = None,
        confidence_engine: Any = None,
        fts_index: Any = None,
        tracked_categories: list[str] | None = None,
    ) -> None:
        self._owns_db = db is None
        self.db = db if db is not None else TrackerDB(db_path)
        self._tracked_categories = tracked_categories
        try:
            self._init_components(
                detector_name, reid_name, reid_threshold, tracker_type, sample_rate,
                conf_threshold, classes, analytics, rsac_manager, active_learning,
                event_bus, frame_processor, video_filename, world_graph, confidence_engine, fts_index,
            )
        except Exception:
            self.close()
            raise

    def _init_components(
        self, detector_name: str, reid_name: str, reid_threshold: float, tracker_type: str,
        sample_rate: int, conf_threshold: float, classes: list[str] | None,
        analytics: AnalyticsEngine | None, rsac_manager: Any, active_learning: Any,
        event_bus: Any, frame_processor: FrameProcessor | None, video_filename: str,
        world_graph: Any, confidence_engine: Any, fts_index: Any,
    ) -> None:
        """Initialize detector, tracker, Re-ID extractor, matcher, and world hooks."""
        self.sample_rate = max(1, int(sample_rate))
        self._cfg_meta = (detector_name, reid_name, float(reid_threshold), tracker_type, float(conf_threshold), classes)
        self.rsac_manager, self.active_learning = rsac_manager, active_learning
        self.event_bus, self.frame_processor = event_bus, frame_processor
        self.video_filename = str(video_filename or "").strip()
        self.world_graph = world_graph if world_graph is not None else WorldGraph()
        self.confidence_engine = confidence_engine if confidence_engine is not None else ConfidenceEngine(db=self.db)
        self.fts_index = fts_index
        self.detector = _create_batch_detector(detector_name, conf_threshold, classes)
        self.tracker = TrackerFactory.create(tracker_type)
        from intelligent_tracker.reid.profile import resolve_reid_profile

        profile = resolve_reid_profile({"reid": {"model": reid_name, "threshold": reid_threshold}})
        self.extractor = ReIDExtractorFactory.create(profile.model_name or "dual")
        self.matcher = GalleryMatcher(
            db=self.db, extractor=self.extractor, reid_threshold=reid_threshold,
            sighting_interval=1.0, active_learning=active_learning,
            confidence_engine=self.confidence_engine, fts_index=self.fts_index,
            tracked_categories=getattr(self, "_tracked_categories", None),
        )
        self.analytics = analytics

    def close(self) -> None:
        """Close owned TrackerDB connection idempotently."""
        if getattr(self, "_owns_db", False) and getattr(self, "db", None) is not None:
            try:
                self.db.close()
            finally:
                self.db = None
                self._owns_db = False

    def __enter__(self) -> "VideoIndexer":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def _build_frame_processor(self, source_name: str, video_filename: str = "") -> FrameProcessor:
        """Build or configure the canonical ``FrameProcessor`` for offline video frames."""
        resolved_video = str(video_filename or self.video_filename or "").strip()
        if self.frame_processor is not None:
            bundle = self.frame_processor.bundle
            if bundle.gallery_matcher is not None:
                bundle.gallery_matcher.video_filename = resolved_video
                if self.fts_index is not None and getattr(bundle.gallery_matcher, "fts_index", None) is None:
                    bundle.gallery_matcher.fts_index = self.fts_index
            if bundle.active_learning is not None:
                bundle.active_learning.video_filename = resolved_video
            return self.frame_processor
        self.matcher.video_filename = resolved_video
        if self.fts_index is not None and getattr(self.matcher, "fts_index", None) is None:
            self.matcher.fts_index = self.fts_index
        if self.active_learning is not None:
            self.active_learning.video_filename = resolved_video
        det, reid, thresh, trk, conf, classes = self._cfg_meta
        cfg = PipelineConfig(
            camera_id=source_name, detector_model=det, tracker_type=trk,
            reid_model=reid, reid_threshold=thresh, detector_confidence=conf,
            detector_classes=classes, tracked_categories=getattr(self, "_tracked_categories", None),
        )
        bundle = PipelineBundle(
            config=cfg, db=self.db, detector=self.detector, tracker=self.tracker,
            analytics=self.analytics, reid_extractor=self.extractor, gallery_matcher=self.matcher,
            rsac_manager=self.rsac_manager, active_learning=self.active_learning, event_bus=self.event_bus,
            world_graph=self.world_graph, confidence_engine=self.confidence_engine,
            event_fts_index=self.fts_index,
        )
        return FrameProcessor(bundle=bundle)

    def process_video(
        self,
        video_path: str,
        source_label: str | None = None,
        max_frames: int = 0,
        verbose: bool = True,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        stop_event: threading.Event | None = None,
        frame_flush_callback: Callable[[list[dict[str, Any]], dict[str, Any]], None] | None = None,
        flush_interval: int = 30,
    ) -> dict[str, Any]:
        """Process a recorded video file through ``FrameProcessor.step()``."""
        cap, meta = _open_video_capture(video_path)
        source_name = source_label or os.path.basename(video_path)
        processor = self._build_frame_processor(source_name, os.path.basename(video_path))
        state: dict[str, Any] = {
            "processed_frames": 0, "read_frames": 0, "total_detections": 0,
            "matched_identifications": 0, "identified_entities": set(),
            "cancelled": False, "start_wall_time": time.time(), "last_cb_time": 0.0,
            "frame_detections": [], "last_flushed_idx": 0, "last_video_ts": 0.0,
        }
        try:
            self._run_capture_loop(
                cap, processor, meta, state, max_frames, stop_event,
                frame_flush_callback, max(1, int(flush_interval)), progress_callback, verbose,
            )
        finally:
            cap.release()
            del cap
        emit_progress(progress_callback, state, meta, verbose, final=True)
        _dispatch_frame_flush(
            frame_flush_callback, state["frame_detections"], state["last_flushed_idx"],
            flush_meta(meta, state, state["last_video_ts"], final=True),
        )
        return build_final_report(video_path, source_name, meta, state)

    def _process_sampled_frame(
        self, cap: cv2.VideoCapture, processor: FrameProcessor, frame: Any,
        meta: dict[str, Any], state: dict[str, Any],
        frame_flush_callback: Any, flush_step: int, progress_callback: Any, verbose: bool,
    ) -> None:
        """Step a single sampled frame through FrameProcessor and flush updates."""
        state["processed_frames"] += 1
        video_ts = _read_video_timestamp(cap, state["read_frames"], meta["fps"])
        state["last_video_ts"] = video_ts
        base_epoch = float(state["start_wall_time"])
        if processor.bundle.gallery_matcher is not None:
            processor.bundle.gallery_matcher.current_media_offset_sec = video_ts
        if processor.bundle.active_learning is not None:
            processor.bundle.active_learning.current_media_offset_sec = video_ts
        media_state = getattr(self, "_media_offset_state", None)
        if isinstance(media_state, dict):
            media_state["start_wall_time"], media_state["offset_sec"] = base_epoch, video_ts
        step_res = _step_video_frame(processor, frame, base_epoch + video_ts)
        _record_step_occurrences(
            step_res, state, state["read_frames"], meta["width"], meta["height"], video_ts=video_ts
        )
        if frame_flush_callback is not None and state["processed_frames"] % flush_step == 0:
            state["last_flushed_idx"] = _dispatch_frame_flush(
                frame_flush_callback, state["frame_detections"], state["last_flushed_idx"],
                flush_meta(meta, state, video_ts, final=False),
            )
        emit_progress(progress_callback, state, meta, verbose)

    def _run_capture_loop(
        self, cap: cv2.VideoCapture, processor: FrameProcessor, meta: dict[str, Any],
        state: dict[str, Any], max_frames: int, stop_event: threading.Event | None,
        frame_flush_callback: Any, flush_step: int, progress_callback: Any, verbose: bool,
    ) -> None:
        """Iterate sampled frames, step ``FrameProcessor``, and flush progressive updates."""
        while True:
            if stop_event is not None and stop_event.is_set():
                state["cancelled"] = True
                break
            ret, frame = cap.read()
            if not ret or frame is None:
                break
            if (meta["width"] <= 0 or meta["height"] <= 0) and hasattr(frame, "shape"):
                meta["height"], meta["width"] = int(frame.shape[0]), int(frame.shape[1])
            state["read_frames"] += 1
            if max_frames > 0 and state["read_frames"] > max_frames:
                break
            if (state["read_frames"] - 1) % self.sample_rate != 0:
                continue
            self._process_sampled_frame(
                cap, processor, frame, meta, state,
                frame_flush_callback, flush_step, progress_callback, verbose,
            )

    def generate_occurrence_report(
        self, entity_id: int | None = None, source: str | None = None, video_filename: str | None = None,
    ) -> dict[str, Any]:
        """Generate occurrence analytics and sighting timelines across entities."""
        vf = video_filename if video_filename is not None else (self.video_filename or None)
        return format_occurrence_report(self.db, entity_id=entity_id, source=source, video_filename=vf)

    def print_report(self, report: dict[str, Any]) -> None:
        """Format and print an occurrence analytics summary table to the console."""
        print_occurrence_report(report)

    def export_report(
        self, report: dict[str, Any], json_path: str | None = None, csv_path: str | None = None
    ) -> None:
        """Export occurrence report to JSON or CSV."""
        export_occurrence_report(report, json_path=json_path, csv_path=csv_path)


def main() -> None:
    """Run standalone batch video indexer CLI."""
    run_batch_cli()


if __name__ == "__main__":
    main()
