#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Asynchronous video processing jobs router (transcoding and batch analytics)."""

import logging
import os
import subprocess
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from dashboard.dependencies import VIDEOS_DIR
from dashboard.schemas import VideoAnalyzeRequest
from dashboard.services.progressive_stream_store import build_job_stream_response
from dashboard.services.video_analytics_service import (
    parse_analyze_options,
    run_sync_analytics,
    submit_async_analytics_job,
)
from dashboard.services.video_jobs_service import get_video_job_manager
from dashboard.services.video_report_store import (
    clear_report_runs,
    delete_report_run,
    get_detection_stream,
    is_same_recording_alias,
    list_report_runs,
)
from dashboard.services.video_transcoder import VideoTranscodeService

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

    opts = parse_analyze_options(sample_rate, detector, confidence, classes, async_mode, req)
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

    if opts["is_async"]:
        job = submit_async_analytics_job(job_mgr, safe_name, path, opts)
        return JSONResponse(
            status_code=202,
            content={"status": "accepted", "job_id": job.job_id, "job": job.to_dict()},
        )

    report = run_sync_analytics(safe_name, path, opts)
    return {"status": "success", "report": report}


@router.get("/api/videos/{filename}/reports")
async def get_video_reports(filename: str):
    """Retrieve historical stacked analytics reports for a recorded video file."""
    safe_name = os.path.basename(filename)
    runs = list_report_runs(safe_name)
    return runs


@router.delete("/api/videos/{filename}/reports/{run_id}")
async def delete_video_report_run(filename: str, run_id: str):
    """Delete a single historical report run and its detections stream across recording aliases."""
    safe_name = os.path.basename(filename)
    safe_run_id = os.path.basename(run_id)
    if not delete_report_run(safe_name, safe_run_id):
        raise HTTPException(status_code=404, detail=f"Report run '{safe_run_id}' not found for '{safe_name}'")
    return {"status": "success", "filename": safe_name, "deleted_run_id": safe_run_id}


@router.delete("/api/videos/{filename}/reports")
async def clear_video_report_runs(filename: str):
    """Delete all historical report runs and detections streams across recording aliases."""
    safe_name = os.path.basename(filename)
    cleared_count = clear_report_runs(safe_name)
    return {"status": "success", "filename": safe_name, "cleared_count": cleared_count}


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



