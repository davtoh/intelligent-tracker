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

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from dashboard.camera_pool import CameraPool
from dashboard.dependencies import (
    VIDEOS_DIR,
    get_camera_pool,
)
from dashboard.routers.video_jobs import router as video_jobs_router
from dashboard.schemas import VideoAddAsCameraRequest
from dashboard.services.video_jobs_service import get_video_job_manager
from dashboard.services.video_transcoder import VideoTranscodeService
from intelligent_tracker.camera_resolver import CameraPathResolver

logger = logging.getLogger("intelligent_tracker.dashboard.routers.videos")

router = APIRouter(tags=["Videos & Scrubber"])
# Compose async jobs router (transcoding, analytics, job progress polling, cancellation)
router.include_router(video_jobs_router)

def _handle_auto_transcode(dest_path: str, safe_name: str) -> tuple[str, str, dict]:
    """Transcode uploaded video to H.264 if not web compatible."""
    pair = VideoTranscodeService.get_h264_pair_info(dest_path)
    transcoded_name = pair["output_filename"]
    transcoded_path = pair["output_path"]
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
        for f in sorted(os.listdir(VIDEOS_DIR)):
            lower_name = f.lower()
            if lower_name.endswith((".mp4", ".avi", ".mkv", ".mov")) and not lower_name.endswith(".part.mp4"):
                full = os.path.join(VIDEOS_DIR, f)
                stat = os.stat(full)
                probe = VideoTranscodeService.probe_video(full)
                is_web = probe.get("web_compatible", False)
                pair = VideoTranscodeService.get_h264_pair_info(full)
                has_converted = (not is_web) and pair["has_converted_h264"]
                converted_name = pair["converted_filename"] if has_converted else None
                files.append({
                    "filename": f,
                    "path": full,
                    "size_bytes": stat.st_size,
                    "size_mb": round(stat.st_size / (1024 * 1024), 2),
                    "modified": stat.st_mtime,
                    "video_url": f"/videos/{f}",
                    "codec": probe.get("codec", "unknown"),
                    "web_compatible": is_web,
                    "has_converted_h264": has_converted,
                    "converted_filename": converted_name,
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


def _release_pool_video_streams(pool: Optional[CameraPool], safe_name: str) -> None:
    """Stop any active CameraPool streams referencing ``safe_name`` before file deletion."""
    if not pool or not hasattr(pool, "camera_configs"):
        return
    for cid, cfg in list(pool.camera_configs.items()):
        src = str(cfg.get("source", "")).strip().replace("\\", "/")
        if os.path.basename(src) == safe_name and cfg.get("enabled", True):
            pool.toggle_camera(cid, enabled=False)
    for cid, mgr in list((getattr(pool, "streams", None) or {}).items()):
        src = str(getattr(mgr, "_resolved_source", getattr(mgr, "source_override", ""))).replace("\\", "/")
        if os.path.basename(src) == safe_name and hasattr(mgr, "stop"):
            mgr.stop()


@router.delete("/api/videos/{filename}")
async def delete_video(
    filename: str,
    pool: Optional[CameraPool] = Depends(get_camera_pool),
):
    """Delete a recording from data/videos/ after releasing active jobs/streams."""
    safe_name = os.path.basename(filename)
    path = os.path.join(VIDEOS_DIR, safe_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Video file not found")
    get_video_job_manager().cancel_active_job_for_file(safe_name, wait_timeout=2.0)
    _release_pool_video_streams(pool, safe_name)
    try:
        os.remove(path)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=f"Video file '{safe_name}' is in use: {exc}") from exc
    return {"status": "success", "deleted": safe_name}


def _parse_video_camera_params(
    safe_name: str,
    camera_id: Optional[str],
    name: Optional[str],
    detector: Optional[str],
    tracker: Optional[str],
    confidence: Optional[float],
    classes: Optional[str],
    req: Optional[VideoAddAsCameraRequest],
) -> tuple[str, str, str, str, float, list[str] | None]:
    """Resolve query/body overrides for registering a video file as a camera."""
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
    return cam_id, cam_name, det, trk, float(conf), target_classes


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
    pool: Optional[CameraPool] = Depends(get_camera_pool),
):
    """Dynamically register an uploaded video file as an active camera stream."""
    safe_name = os.path.basename(filename)
    path = os.path.join(VIDEOS_DIR, safe_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Video file not found")
    if not pool:
        raise HTTPException(status_code=503, detail="Camera pool not initialized")

    cam_id, cam_name, det, trk, conf, target_classes = _parse_video_camera_params(
        safe_name, camera_id, name, detector, tracker, confidence, classes, req
    )
    pool.add_camera(
        camera_id=cam_id, name=cam_name, source=CameraPathResolver.normalize_source_path(path),
        cam_type="video_file", detector=det, tracker=trk, confidence=conf, classes=target_classes, enabled=True,
    )
    return {"status": "success", "camera_id": cam_id, "name": cam_name, "detector": det, "confidence": conf, "classes": target_classes}


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

