#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Video Files, Uploads, Scrubber & Transcoding API Router.

Provides endpoints for video file listing, chunked uploads, background H.264
transcoding, dynamic camera registration, and HTML5 video streaming/seeking.
"""

import logging
import os
import subprocess
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from dashboard.camera_pool import CameraPool
from dashboard.dependencies import (
    VIDEOS_DIR,
    get_active_stream_manager,
    get_camera_pool,
    set_camera_pool,
)
from dashboard.services.video_transcoder import VideoTranscodeService
from intelligent_tracker.database import TrackerDB

logger = logging.getLogger("intelligent_tracker.dashboard.routers.videos")

router = APIRouter(tags=["Videos & Scrubber"])


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


@router.post("/api/videos/{filename}/transcode")
async def transcode_video(
    filename: str, target_resolution: Optional[str] = "1080p"
):
    """Transcodes a video recording (e.g. HEVC/H.265 or AVI) to web-optimized H.264 MP4."""
    safe_name = os.path.basename(filename)
    path = os.path.join(VIDEOS_DIR, safe_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Video file not found")

    base_name, _ = os.path.splitext(safe_name)
    output_filename = f"{base_name}_h264.mp4"
    output_path = os.path.join(VIDEOS_DIR, output_filename)

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


@router.delete("/api/videos/{filename}")
async def delete_video(filename: str):
    """Delete a recording from data/videos/."""
    safe_name = os.path.basename(filename)
    path = os.path.join(VIDEOS_DIR, safe_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Video file not found")
    os.remove(path)
    return {"status": "success", "deleted": safe_name}


@router.post("/api/videos/{filename}/add_as_camera")
async def add_video_as_camera(
    filename: str,
    camera_id: Optional[str] = None,
    name: Optional[str] = None,
):
    """Dynamically register an uploaded video file as an active camera stream."""
    safe_name = os.path.basename(filename)
    path = os.path.join(VIDEOS_DIR, safe_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Video file not found")

    base_id = os.path.splitext(safe_name)[0].replace(" ", "_").replace("-", "_")
    cam_id = camera_id or f"vid_{base_id}"
    cam_name = name or f"Video ({safe_name})"

    pool = get_camera_pool()
    if not pool:
        pool = CameraPool()
        set_camera_pool(pool)

    pool.add_camera(
        camera_id=cam_id,
        name=cam_name,
        source=path,
        cam_type="video_file",
        detector="mock",
        tracker="centroid",
        enabled=True,
    )
    return {"status": "success", "camera_id": cam_id, "name": cam_name}


@router.post("/api/videos/{filename}/analyze")
async def analyze_video(filename: str, sample_rate: int = 1):
    """Run offline occurrence indexer and entity analytics on a video recording."""
    safe_name = os.path.basename(filename)
    path = os.path.join(VIDEOS_DIR, safe_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Video file not found")

    from intelligent_tracker.batch import BatchVideoIndexer

    mgr = get_active_stream_manager()
    db = mgr.db if (mgr and mgr.db) else TrackerDB("data/tracker.db")

    indexer = BatchVideoIndexer(
        video_path=path,
        db=db,
        detector=mgr.detector if mgr else None,
        sample_rate=sample_rate,
        headless=True,
    )
    report = indexer.process()
    return {"status": "success", "report": report}


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

