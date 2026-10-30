"""
Intelligent Tracker Dashboard - Video Files & Scrubber Router.

Handles local video recordings, file upload, H.264 transcoding, video serving,
and offline batch analytics.
"""

from __future__ import annotations

import os
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Query, Request
from fastapi.responses import FileResponse

import dashboard.dependencies as deps
from dashboard.services.video_transcoder import VideoTranscodeService
from dashboard.camera_pool import CameraPool
from intelligent_tracker.database import TrackerDB

logger = logging.getLogger("intelligent_tracker.dashboard.videos")

router = APIRouter(tags=["Videos"])

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DIR = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(PROJECT_DIR, "data")
VIDEOS_DIR = os.path.join(DATA_DIR, "videos")
os.makedirs(VIDEOS_DIR, exist_ok=True)


@router.get("/api/videos")
async def list_videos():
    """List uploaded and local video recordings in data/videos/."""
    files = []
    if os.path.exists(VIDEOS_DIR):
        for f in os.listdir(VIDEOS_DIR):
            if f.lower().endswith((".mp4", ".avi", ".mkv", ".mov")):
                full = os.path.join(VIDEOS_DIR, f)
                stat = os.stat(full)
                probe = VideoTranscodeService.probe_video_file(full)
                files.append({
                    "filename": f,
                    "path": full,
                    "size_bytes": stat.st_size,
                    "size_mb": round(stat.st_size / (1024 * 1024), 2),
                    "modified": stat.st_mtime,
                    "video_url": f"/videos/{f}",
                    "codec": probe.get("codec", "unknown"),
                    "web_compatible": probe.get("web_compatible", False),
                    "resolution": f"{probe.get('width', 0)}x{probe.get('height', 0)}" if probe.get("width") else "unknown",
                    "duration": probe.get("duration", 0),
                    "fps": probe.get("fps", 0),
                })
    return files


@router.post("/api/videos/upload")
async def upload_video(file: UploadFile = File(...), auto_transcode: bool = Query(False)):
    """Upload a video recording (.mp4, .avi, .mkv, .mov) into data/videos/."""
    valid_exts = (".mp4", ".avi", ".mkv", ".mov")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in valid_exts:
        raise HTTPException(status_code=400, detail=f"Unsupported format '{ext}'. Must be {valid_exts}")

    safe_name = os.path.basename(file.filename)
    dest_path = os.path.join(VIDEOS_DIR, safe_name)

    with open(dest_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)

    probe = VideoTranscodeService.probe_video_file(dest_path)
    is_web = probe.get("web_compatible", False)

    if auto_transcode and not is_web:
        base_name, _ = os.path.splitext(safe_name)
        transcoded_name = f"{base_name}_h264.mp4"
        transcoded_path = os.path.join(VIDEOS_DIR, transcoded_name)
        try:
            VideoTranscodeService.transcode(dest_path, transcoded_path, timeout=120.0)
            safe_name = transcoded_name
            dest_path = transcoded_path
            probe = VideoTranscodeService.probe_video_file(dest_path)
        except Exception as e:
            logger.warning("Auto-transcode failed: %s", e)

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
async def transcode_video(filename: str, target_resolution: Optional[str] = "1080p"):
    """
    Transcodes a video recording (e.g. HEVC/H.265 or AVI) to web-optimized H.264 MP4.
    """
    safe_name = os.path.basename(filename)
    path = os.path.join(VIDEOS_DIR, safe_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Video file not found")

    base_name, _ = os.path.splitext(safe_name)
    output_filename = f"{base_name}_h264.mp4"
    output_path = os.path.join(VIDEOS_DIR, output_filename)

    try:
        res = VideoTranscodeService.transcode(path, output_path, target_resolution=target_resolution)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "success",
        "original_filename": safe_name,
        "output_filename": output_filename,
        "video_url": f"/videos/{output_filename}",
        "size_mb": res.get("size_mb", 0.0),
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
async def add_video_as_camera(filename: str, camera_id: Optional[str] = None, name: Optional[str] = None):
    """Dynamically register an uploaded video file as an active camera stream."""
    safe_name = os.path.basename(filename)
    path = os.path.join(VIDEOS_DIR, safe_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Video file not found")

    base_id = os.path.splitext(safe_name)[0].replace(" ", "_").replace("-", "_")
    cam_id = camera_id or f"vid_{base_id}"
    cam_name = name or f"Video ({safe_name})"

    pool = deps.get_camera_pool()
    if not pool:
        pool = CameraPool()
        deps.set_camera_pool(pool)

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
    mgr = deps.get_active_stream_manager()
    db = mgr.db if (mgr and mgr.db) else deps.get_db()

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

