#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Video Files, Uploads, Scrubber & Transcoding API Router.

Provides endpoints for video file listing, chunked uploads, background H.264
transcoding, dynamic camera registration, and HTML5 video streaming/seeking.
"""

import logging
import os
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from dashboard.camera_pool import CameraPool
from dashboard.dependencies import (
    VIDEOS_DIR,
    get_camera_pool,
    set_camera_pool,
)
from dashboard.routers.video_jobs import router as video_jobs_router
from dashboard.schemas import VideoAddAsCameraRequest
from dashboard.services.video_jobs_service import get_video_job_manager
from dashboard.services.video_transcoder import VideoTranscodeService

logger = logging.getLogger("intelligent_tracker.dashboard.routers.videos")

router = APIRouter(tags=["Videos & Scrubber"])
# Compose async jobs router (transcoding, analytics, job progress polling, cancellation)
router.include_router(video_jobs_router)

def _handle_auto_transcode(dest_path: str, safe_name: str) -> tuple[str, str, dict]:
    """Transcode uploaded video to H.264 if not web compatible."""
    base_name, _ = os.path.splitext(safe_name)
    transcoded_name = f"{base_name}_h264.mp4"
    transcoded_path = os.path.join(VIDEOS_DIR, transcoded_name)
    try:
        VideoTranscodeService.transcode_to_h264(
            dest_path, transcoded_path, timeout=120.0
        )
        probe = VideoTranscodeService.probe_video(transcoded_path)
        return transcoded_name, transcoded_path, probe
    except Exception as e:
        logger.warning("Auto-transcode failed: %s", e)
        return safe_name, dest_path, VideoTranscodeService.probe_video(dest_path)


@router.get("/api/videos")
async def list_videos():
    """List uploaded and local video recordings in data/videos/."""
    files = []
    if os.path.exists(VIDEOS_DIR):
        for f in os.listdir(VIDEOS_DIR):
            if f.lower().endswith((".mp4", ".avi", ".mkv", ".mov")):
                full = os.path.join(VIDEOS_DIR, f)
                stat = os.stat(full)
                probe = VideoTranscodeService.probe_video(full)
                files.append({
                    "filename": f,
                    "path": full,
                    "size_bytes": stat.st_size,
                    "size_mb": round(stat.st_size / (1024 * 1024), 2),
                    "modified": stat.st_mtime,
                    "video_url": f"/videos/{f}",
                    "codec": probe.get("codec", "unknown"),
                    "web_compatible": probe.get("web_compatible", False),
                    "resolution": (
                        f"{probe.get('width', 0)}x{probe.get('height', 0)}"
                        if probe.get("width")
                        else "unknown"
                    ),
                    "duration": probe.get("duration", 0),
                    "fps": probe.get("fps", 0),
                })
    return files


@router.post("/api/videos/upload")
async def upload_video(
    file: UploadFile = File(...), auto_transcode: bool = Query(False)
):
    """Upload a video recording (.mp4, .avi, .mkv, .mov) into data/videos/."""
    valid_exts = (".mp4", ".avi", ".mkv", ".mov")
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in valid_exts:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format '{ext}'. Must be {valid_exts}",
        )

    safe_name = os.path.basename(file.filename)
    dest_path = os.path.join(VIDEOS_DIR, safe_name)

    with open(dest_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)

    probe = VideoTranscodeService.probe_video(dest_path)
    is_web = probe.get("web_compatible", False)

    if auto_transcode and not is_web:
        safe_name, dest_path, probe = _handle_auto_transcode(dest_path, safe_name)

    stat = os.stat(dest_path)
    return {
        "status": "success",
        "filename": safe_name,
        "path": dest_path,
        "size_bytes": stat.st_size,
        "size_mb": round(stat.st_size / (1024 * 1024), 2),
        "video_url": f"/videos/{safe_name}",
        "codec": probe.get("codec", "unknown"),
        "web_compatible": probe.get("web_compatible", False),
    }


@router.delete("/api/videos/{filename}")
async def delete_video(filename: str):
    """Delete a recording from data/videos/."""
    safe_name = os.path.basename(filename)
    path = os.path.join(VIDEOS_DIR, safe_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Video file not found")
    job_mgr = get_video_job_manager()
    job_mgr.cancel_active_job_for_file(safe_name, wait_timeout=2.0)
    os.remove(path)
    return {"status": "success", "deleted": safe_name}


@router.post("/api/videos/{filename}/add_as_camera")
async def add_video_as_camera(
    filename: str,
    camera_id: Optional[str] = None,
    name: Optional[str] = None,
    detector: Optional[str] = Query("yolov8", description="Detector architecture (e.g. yolov8, mock)"),
    tracker: Optional[str] = Query("centroid", description="Tracker algorithm (e.g. centroid, sort)"),
    confidence: Optional[float] = Query(0.40, ge=0.01, le=1.0, description="Confidence threshold"),
    classes: Optional[str] = Query(None, description="Comma-separated class filter (e.g. person,car)"),
    req: Optional[VideoAddAsCameraRequest] = None,
):
    """Dynamically register an uploaded video file as an active camera stream."""
    safe_name = os.path.basename(filename)
    path = os.path.join(VIDEOS_DIR, safe_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Video file not found")

    base_id = os.path.splitext(safe_name)[0].replace(" ", "_").replace("-", "_")
    cam_id = (req.camera_id if req and req.camera_id else None) or camera_id or f"vid_{base_id}"
    cam_name = (req.name if req and req.name else None) or name or f"Video ({safe_name})"
    det = (req.detector if req and req.detector else None) or detector or "yolov8"
    trk = (req.tracker if req and req.tracker else None) or tracker or "centroid"
    conf = (req.confidence if req and req.confidence is not None else None) or confidence or 0.40
    raw_classes = (req.classes if req and req.classes is not None else None) or classes

    if isinstance(raw_classes, str):
        target_classes = [c.strip() for c in raw_classes.split(",") if c.strip()]
    elif isinstance(raw_classes, (list, tuple, set)):
        target_classes = [str(c).strip() for c in raw_classes if str(c).strip()]
    else:
        target_classes = None

    pool = get_camera_pool()
    if not pool:
        pool = CameraPool()
        set_camera_pool(pool)

    pool.add_camera(
        camera_id=cam_id,
        name=cam_name,
        source=path,
        cam_type="video_file",
        detector=det,
        tracker=trk,
        confidence=conf,
        classes=target_classes,
        enabled=True,
    )
    return {
        "status": "success",
        "camera_id": cam_id,
        "name": cam_name,
        "detector": det,
        "confidence": conf,
        "classes": target_classes,
    }


@router.api_route("/videos/{filename}", methods=["GET", "HEAD"])
async def serve_video_stream(filename: str, request: Request):
    """Serve local video recording supporting HTML5 video scrubber seeking."""
    safe_name = os.path.basename(filename)
    path = os.path.join(VIDEOS_DIR, safe_name)
    if os.path.exists(path):
        media_type = "video/mp4"
        if safe_name.endswith(".mkv"):
            media_type = "video/x-matroska"
        elif safe_name.endswith(".avi"):
            media_type = "video/x-msvideo"
        return FileResponse(path, media_type=media_type)
    raise HTTPException(status_code=404, detail="Video file not found")

