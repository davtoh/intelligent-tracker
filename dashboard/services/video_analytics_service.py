#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Batch Video Analytics Execution & Report Finalization Service."""

import logging
from typing import Any

from dashboard.dependencies import get_active_stream_manager
from dashboard.schemas import VideoAnalyzeRequest
from dashboard.services.progressive_stream_store import (
    append_progressive_chunk,
    finalize_progressive_stream,
)
from dashboard.services.video_jobs_service import VideoJob, VideoJobManager
from dashboard.services.video_report_store import save_report_run
from intelligent_tracker.batch import VideoIndexer
from intelligent_tracker.database import TrackerDB

logger = logging.getLogger("intelligent_tracker.dashboard.services.video_analytics_service")


def parse_analyze_options(
    sample_rate: int,
    detector: str | None,
    confidence: float | None,
    classes: str | None,
    async_mode: bool | None,
    req: VideoAnalyzeRequest | None,
) -> dict[str, Any]:
    """Normalize query and JSON body options for batch video analytics."""
    sr = req.sample_rate if (req and req.sample_rate is not None) else sample_rate
    det = req.detector if (req and req.detector is not None) else (detector or "yolov8")
    conf = req.confidence if (req and req.confidence is not None) else (confidence if confidence is not None else 0.40)
    raw_classes = (req.classes if req and req.classes is not None else None) or classes

    if isinstance(raw_classes, str):
        target_classes = [c.strip() for c in raw_classes.split(",") if c.strip()]
    elif isinstance(raw_classes, (list, tuple, set)):
        target_classes = [str(c).strip() for c in raw_classes if str(c).strip()]
    else:
        target_classes = None

    is_async = req.async_mode if (req and req.async_mode is not None) else None
    if is_async is None:
        is_async = bool(async_mode)

    return {
        "sample_rate": sr,
        "detector": det,
        "confidence": conf,
        "classes": target_classes,
        "is_async": is_async,
    }


def _resolve_db() -> TrackerDB:
    mgr = get_active_stream_manager()
    if mgr and mgr.db and getattr(mgr.db, "_conn", None) is not None:
        return mgr.db
    return TrackerDB("data/tracker.db")


def create_video_indexer(db: TrackerDB, opts: dict[str, Any]) -> VideoIndexer:
    """Instantiate VideoIndexer with graceful mock fallback if detector weights fail to load."""
    det = opts["detector"]
    try:
        return VideoIndexer(
            db=db,
            detector_name=det,
            sample_rate=opts["sample_rate"],
            conf_threshold=opts["confidence"],
            classes=opts["classes"],
        )
    except Exception as err:
        logger.warning("VideoIndexer initialization with detector '%s' failed (%s), falling back to mock", det, err)
        return VideoIndexer(
            db=db,
            detector_name="mock",
            sample_rate=opts["sample_rate"],
            conf_threshold=opts["confidence"],
            classes=opts["classes"],
        )


def finalize_analytics_report(
    indexer: VideoIndexer,
    summary: dict[str, Any],
    safe_name: str,
    config_meta: dict[str, Any],
) -> dict[str, Any]:
    """Assemble occurrence report metrics and persist stacked report + detection stream."""
    report = indexer.generate_occurrence_report()
    report["frames_processed"] = summary.get("processed_frames", 0)
    report["total_detections"] = summary.get("total_detections", 0)
    report["total_sightings"] = summary.get("identifications_count", 0)
    report["unique_entities_identified"] = len(summary.get("unique_entities_identified", []))
    report["source_resolution"] = summary.get("source_resolution")
    report["source_fps"] = summary.get("source_fps")
    report["execution_summary"] = summary

    run_rec = save_report_run(
        filename=safe_name,
        report=report,
        config=config_meta,
        frame_detections=summary.get("frame_detections"),
        source_resolution=summary.get("source_resolution"),
        source_fps=summary.get("source_fps"),
    )
    report["run_id"] = run_rec.get("run_id")
    return report


def submit_async_analytics_job(
    job_mgr: VideoJobManager,
    safe_name: str,
    path: str,
    opts: dict[str, Any],
) -> VideoJob:
    """Submit a background VideoIndexer job with progressive detection streaming."""
    db = _resolve_db()
    config_meta = {
        "detector": opts["detector"],
        "sample_rate": opts["sample_rate"],
        "confidence": opts["confidence"],
        "classes": opts["classes"],
    }

    def _runner(job, stop_event, progress_cb):
        indexer = create_video_indexer(db, opts)
        try:
            summary = indexer.process_video(
                video_path=path,
                verbose=False,
                progress_callback=progress_cb,
                stop_event=stop_event,
                frame_flush_callback=lambda chunk, meta: append_progressive_chunk(
                    job.job_id, safe_name, chunk, meta
                ),
            )
            return finalize_analytics_report(indexer, summary, safe_name, config_meta)
        finally:
            finalize_progressive_stream(job.job_id)

    return job_mgr.submit_job(
        job_type="analytics",
        filename=safe_name,
        runner_fn=_runner,
        initial_metrics=config_meta,
    )


def run_sync_analytics(safe_name: str, path: str, opts: dict[str, Any]) -> dict[str, Any]:
    """Execute synchronous VideoIndexer analytics and return persisted report."""
    db = _resolve_db()
    config_meta = {
        "detector": opts["detector"],
        "sample_rate": opts["sample_rate"],
        "confidence": opts["confidence"],
        "classes": opts["classes"],
    }
    indexer = create_video_indexer(db, opts)
    summary = indexer.process_video(video_path=path, verbose=False)
    return finalize_analytics_report(indexer, summary, safe_name, config_meta)

