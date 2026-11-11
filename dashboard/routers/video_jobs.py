#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Asynchronous video processing jobs router (transcoding and batch analytics)."""

import logging
import os
import subprocess
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from dashboard.dependencies import (
    VIDEOS_DIR,
    get_active_stream_manager,
)
from dashboard.schemas import VideoAnalyzeRequest
from dashboard.services.progressive_stream_store import (
    append_progressive_chunk,
    build_job_stream_response,
    finalize_progressive_stream,
)
from dashboard.services.video_jobs_service import get_video_job_manager
from dashboard.services.video_report_store import (
    get_detection_stream,
    is_same_recording_alias,
    list_report_runs,
    save_report_run,
)
from dashboard.services.video_transcoder import VideoTranscodeService
from intelligent_tracker.batch import VideoIndexer
from intelligent_tracker.database import TrackerDB

logger = logging.getLogger("intelligent_tracker.dashboard.routers.video_jobs")

router = APIRouter(tags=["Video Jobs & Analytics"])

@router.post("/api/videos/{filename}/transcode")
async def transcode_video(
    filename: str,
    target_resolution: Optional[str] = "1080p",
    async_mode: bool = Query(True),
    force: bool = Query(False),
):
    """Transcodes a video recording (e.g. HEVC/H.265 or AVI) to web-optimized H.264 MP4."""
    safe_name = os.path.basename(filename)
    path = os.path.join(VIDEOS_DIR, safe_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Video file not found")

    pair = VideoTranscodeService.get_h264_pair_info(path)
    output_filename = pair["output_filename"]
    output_path = pair["output_path"]

    job_mgr = get_video_job_manager()
    active_job = job_mgr.get_active_job_for_file(safe_name)
    if active_job is not None:
        return JSONResponse(
            status_code=409,
            content={
                "error": "conflict",
                "message": f"A {active_job.job_type} job is already active for video '{safe_name}'.",
                "active_job": active_job.to_dict(),
            },
        )

    if not force and os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
        stat = os.stat(output_path)
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "already_exists": True,
                "original_filename": safe_name,
                "output_filename": output_filename,
                "video_url": f"/videos/{output_filename}",
                "size_bytes": stat.st_size,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
            },
        )

    if async_mode:
        def _runner(job, stop_event, progress_cb):
            VideoTranscodeService.transcode_to_h264_async(
                input_path=path,
                output_path=output_path,
                target_resolution=target_resolution,
                progress_callback=progress_cb,
                stop_event=stop_event,
            )
            st = os.stat(output_path)
            return {
                "original_filename": safe_name,
                "output_filename": output_filename,
                "video_url": f"/videos/{output_filename}",
                "size_mb": round(st.st_size / (1024 * 1024), 2),
            }

        job = job_mgr.submit_job(
            job_type="transcode",
            filename=safe_name,
            runner_fn=_runner,
            initial_metrics={"output_filename": output_filename},
        )
        return JSONResponse(
            status_code=202,
            content={
                "status": "accepted",
                "job_id": job.job_id,
                "job": job.to_dict(),
                "output_filename": output_filename,
                "video_url": f"/videos/{output_filename}",
            },
        )

    try:
        VideoTranscodeService.transcode_to_h264(
            input_path=path,
            output_path=output_path,
            target_resolution=target_resolution,
            timeout=300.0,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504, detail="Transcoding timed out on large file."
        )
    except Exception as e:
        logger.error("Transcode failed for %s: %s", safe_name, e)
        raise HTTPException(status_code=500, detail=str(e))

    stat = os.stat(output_path)
    return {
        "status": "success",
        "original_filename": safe_name,
        "output_filename": output_filename,
        "video_url": f"/videos/{output_filename}",
        "size_mb": round(stat.st_size / (1024 * 1024), 2),
    }


@router.get("/api/videos/jobs/{job_id}")
async def get_video_job(job_id: str):
    """Query status and progress of an asynchronous video processing job."""
    job_mgr = get_video_job_manager()
    job = job_mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return job.to_dict()


@router.get("/api/videos/jobs")
async def list_video_jobs(
    filename: Optional[str] = Query(None),
    active_only: bool = Query(False),
):
    """List recent and active video processing jobs."""
    job_mgr = get_video_job_manager()
    return [j.to_dict() for j in job_mgr.list_jobs(filename=filename, active_only=active_only)]


@router.post("/api/videos/jobs/{job_id}/cancel")
async def cancel_video_job(job_id: str):
    """Request early cancellation of a running or pending video job."""
    job_mgr = get_video_job_manager()
    job = job_mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    job_mgr.cancel_job(job_id, wait_timeout=2.0)
    return {"status": "cancelling", "job_id": job_id}


@router.post("/api/videos/{filename}/analyze")
async def analyze_video(
    filename: str,
    sample_rate: int = Query(1, ge=1),
    detector: Optional[str] = Query(None, description="Detector model name (e.g. yolov8, mock)"),
    confidence: Optional[float] = Query(None, ge=0.01, le=1.0, description="Detection confidence threshold"),
    classes: Optional[str] = Query(None, description="Comma-separated class filter names (e.g. person,car)"),
    async_mode: Optional[bool] = Query(None, description="Run analysis asynchronously in background"),
    req: Optional[VideoAnalyzeRequest] = None,
):
    """Run offline occurrence indexer and entity analytics on a video recording."""
    safe_name = os.path.basename(filename)
    path = os.path.join(VIDEOS_DIR, safe_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Video file not found")

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

    job_mgr = get_video_job_manager()
    active_job = job_mgr.get_active_job_for_file(safe_name)
    if active_job is not None:
        return JSONResponse(
            status_code=409,
            content={
                "error": "conflict",
                "message": f"A {active_job.job_type} job is already active for video '{safe_name}'.",
                "active_job": active_job.to_dict(),
            },
        )

    mgr = get_active_stream_manager()
    db = mgr.db if (mgr and mgr.db) else TrackerDB("data/tracker.db")

    def _create_indexer():
        try:
            return VideoIndexer(
                db=db,
                detector_name=det,
                sample_rate=sr,
                conf_threshold=conf,
                classes=target_classes,
            )
        except Exception as e:
            logger.warning(
                "VideoIndexer initialization with detector '%s' failed (%s), falling back to mock",
                det,
                e,
            )
            return VideoIndexer(
                db=db,
                detector_name="mock",
                sample_rate=sr,
                conf_threshold=conf,
                classes=target_classes,
            )

    config_meta = {
        "detector": det,
        "sample_rate": sr,
        "confidence": conf,
        "classes": target_classes,
    }

    def _finalize_report(indexer: VideoIndexer, summary: dict) -> dict:
        report = indexer.generate_occurrence_report()
        report["frames_processed"] = summary.get("processed_frames", 0)
        report["total_detections"] = summary.get("total_detections", 0)
        report["total_sightings"] = summary.get("identifications_count", 0)
        report["unique_entities_identified"] = len(summary.get("unique_entities_identified", []))
        report["source_resolution"] = summary.get("source_resolution")
        report["source_fps"] = summary.get("source_fps")
        report["execution_summary"] = summary

        # Persist stacked report and time-indexed detection stream to disk
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

    if is_async:
        def _runner(job, stop_event, progress_cb):
            indexer = _create_indexer()
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
                return _finalize_report(indexer, summary)
            finally:
                finalize_progressive_stream(job.job_id)

        job = job_mgr.submit_job(
            job_type="analytics",
            filename=safe_name,
            runner_fn=_runner,
            initial_metrics=config_meta,
        )
        return JSONResponse(
            status_code=202,
            content={"status": "accepted", "job_id": job.job_id, "job": job.to_dict()},
        )

    indexer = _create_indexer()
    summary = indexer.process_video(video_path=path, verbose=False)
    report = _finalize_report(indexer, summary)
    return {"status": "success", "report": report}


@router.get("/api/videos/{filename}/reports")
async def get_video_reports(filename: str):
    """Retrieve historical stacked analytics reports for a recorded video file."""
    safe_name = os.path.basename(filename)
    runs = list_report_runs(safe_name)
    return runs


@router.get("/api/videos/{filename}/jobs/{job_id}/stream")
async def stream_video_job_detections(
    filename: str,
    job_id: str,
    since: int = Query(0, ge=0),
):
    """Retrieve progressive frame detections while an analytics job is running."""
    safe_name = os.path.basename(filename)
    job = get_video_job_manager().get_job(job_id)
    if not job or not is_same_recording_alias(safe_name, job.filename):
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found for '{safe_name}'")
    return build_job_stream_response(job, safe_name, since=since)


@router.get("/api/videos/{filename}/reports/{run_id}/detections")
async def get_video_run_detections(filename: str, run_id: str):
    """Retrieve time-indexed frame detections stream for scrubber playback overlay."""
    safe_name = os.path.basename(filename)
    stream = get_detection_stream(safe_name, run_id)
    if stream is None:
        raise HTTPException(status_code=404, detail=f"No detections found for '{safe_name}' run '{run_id}'")
    return stream


@router.get("/api/videos/{filename}/detections")
async def get_latest_video_detections(filename: str):
    """Retrieve latest time-indexed frame detections stream for scrubber playback overlay."""
    safe_name = os.path.basename(filename)
    stream = get_detection_stream(safe_name, None)
    if stream is None:
        raise HTTPException(status_code=404, detail=f"No detections found for video '{safe_name}'")
    return stream



