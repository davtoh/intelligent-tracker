#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Modern Web Dashboard Application & Multi-Camera VMS.

FastAPI application providing:
- Multi-Camera VMS & Dynamic Stream Pool:
  - Live MJPEG video stream: `GET /stream/{camera_id}`
  - Real-time WebSocket telemetry: `WS /ws/{camera_id}`
  - Camera Pool Management: `GET /api/cameras`, `POST /api/cameras`, `PUT /api/cameras/{id}`, `DELETE /api/cameras/{id}`
  - Auto-Discovery: `GET /api/cameras/discover`, `POST /api/cameras/test`, `GET /api/cameras/presets`
- Local Video Recording Studio & Scrubber:
  - `GET /api/videos`, `POST /api/videos/upload`, `DELETE /api/videos/{filename}`
  - `POST /api/videos/{filename}/add_as_camera`, `POST /api/videos/{filename}/analyze`
  - HTML5 video serving: `GET /videos/{filename}`
- System State Persistence & One-Click Backup:
  - `GET /api/backup/export`, `POST /api/backup/import`
- REST API for zones, analytics, entity gallery, sighting timeline, and interactive click-to-tag:
  - `GET /cameras`, `GET /zones`, `GET /analytics/heatmap`, `POST /analytics/heatmap/toggle`
  - `GET /entities`, `POST /entities`, `GET /entities/{entity_id}`, `DELETE /entities/{entity_id}`
  - `GET /sightings`, `GET /events`, `POST /tag`, `GET /status`
- Modern single-page web UI served at `GET /`
"""

import os
import sys
import time
import io
import shutil
import tempfile
import asyncio
import logging
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

import numpy as np

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import psutil

from dashboard.stream_manager import StreamManager
from dashboard.camera_pool import CameraPool
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.backup import BackupManager
from intelligent_tracker.discovery import (
    discover_all_cameras,
    test_camera_connection,
    build_preset_rtsp_url,
    CAMERA_PRESETS,
)
from intelligent_tracker.scenarios import ScenarioManager
from intelligent_tracker.topology import SpatialTransitionLink
from intelligent_tracker.journey import TrajectoryJourneySearcher, JourneyVideoExporter

logger = logging.getLogger("intelligent_tracker.dashboard")

# Global CameraPool, StreamManager & ScenarioManager references
camera_pool: Optional[CameraPool] = None
stream_manager: Optional[StreamManager] = None
scenario_manager: Optional[ScenarioManager] = None


def get_active_stream_manager(camera_id: Optional[str] = None) -> Optional[StreamManager]:
    """Resolves the appropriate StreamManager instance for a camera ID or active default."""
    global stream_manager, camera_pool
    if camera_pool:
        mgr = camera_pool.get_stream(camera_id)
        if mgr:
            return mgr
    if stream_manager:
        return stream_manager
    if camera_pool:
        return camera_pool.primary_stream
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager starting and stopping the CameraPool, ScenarioManager and pipelines."""
    global stream_manager, camera_pool, scenario_manager
    logger.info("Initializing Intelligent Tracker CameraPool & ScenarioManager...")
    camera_pool = CameraPool()
    stream_manager = camera_pool.primary_stream
    scenario_manager = ScenarioManager()

    # Apply loaded scenarios to active streams
    if camera_pool:
        for sm in camera_pool.streams.values():
            scenario_manager.apply_to_stream_manager(sm)
    elif stream_manager:
        scenario_manager.apply_to_stream_manager(stream_manager)

    yield
    logger.info("Shutting down Intelligent Tracker CameraPool...")
    if camera_pool:
        camera_pool.stop_all()
    elif stream_manager:
        stream_manager.stop()


app = FastAPI(
    title="Intelligent Tracker Web Dashboard & VMS",
    description="Edge AI Retail & Security Analytics Multi-Camera VMS Platform",
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure static & data directories exist
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
VIDEOS_DIR = os.path.join("data", "videos")
CROPS_DIR = os.path.join("data", "crops")
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(VIDEOS_DIR, exist_ok=True)
os.makedirs(CROPS_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# -----------------------------------------------------------------------------
# Pydantic Schemas for Requests
# -----------------------------------------------------------------------------
class EntityCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Entity full name or identifier")
    category: str = Field("person", description="Category: staff, vip, restricted, customer, person")
    notes: Optional[str] = Field("", description="Optional notes or security clearances")


class EntityUpdateRequest(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class TagRequest(BaseModel):
    entity_name: str = Field(..., min_length=1)
    category: str = Field("person")
    track_id: Optional[int] = None
    bbox: Optional[List[int]] = None
    notes: Optional[str] = ""
    camera_id: Optional[str] = "cam_01"


class CameraAddRequest(BaseModel):
    id: str = Field(..., min_length=1, description="Unique camera ID (e.g. cam_02)")
    name: str = Field(..., min_length=1, description="Friendly display label")
    source: str = Field(..., description="RTSP URL, video file path, or USB index")
    type: Optional[str] = "rtsp"
    detector: Optional[str] = "mock"
    tracker: Optional[str] = "centroid"
    enabled: Optional[bool] = True
    details: Optional[Dict[str, Any]] = None


class CameraUpdateRequest(BaseModel):
    name: Optional[str] = None
    source: Optional[str] = None
    type: Optional[str] = None
    enabled: Optional[bool] = None
    detector: Optional[str] = None
    tracker: Optional[str] = None


class CameraTestRequest(BaseModel):
    source: Optional[Any] = None
    preset: Optional[str] = None
    ip: Optional[str] = None
    port: Optional[int] = 554
    username: Optional[str] = ""
    password: Optional[str] = ""
    channel: Optional[int] = 1
    stream: Optional[str] = "main"


class ZoneCreateRequest(BaseModel):
    camera_id: str = Field("cam_01", description="Camera channel identifier")
    name: str = Field(..., min_length=1, description="Unique zone name")
    polygon: List[List[float]] = Field(..., min_length=3, description="List of [x, y] coordinates")
    category_filter: Optional[str] = Field("", description="Filter category (e.g. restricted, staff)")
    dwell_threshold: Optional[float] = Field(5.0, description="Dwell threshold in seconds")
    capacity_limit: Optional[int] = Field(None, description="Maximum occupant capacity limit")
    color: Optional[List[int]] = Field([0, 200, 100], description="BGR or RGB color list")


class TripwireCreateRequest(BaseModel):
    camera_id: str = Field("cam_01", description="Camera channel identifier")
    name: str = Field(..., min_length=1, description="Unique tripwire name")
    line_segment: List[List[float]] = Field(..., min_length=2, description="Two points: [[x1, y1], [x2, y2]]")
    bidirectional: Optional[bool] = Field(True, description="Detect crossing in both directions")
    color: Optional[List[int]] = Field([0, 255, 255], description="BGR or RGB color list")


class HomographyCalibrationRequest(BaseModel):
    camera_id: str = Field("cam_01", description="Camera channel identifier")
    src_points: List[List[float]] = Field(..., min_length=4, max_length=4, description="4 camera ground corners")
    dst_points: Optional[List[List[float]]] = Field(None, description="4 ground metric points")
    metric_width: Optional[float] = Field(10.0, description="Real world ground width in meters")
    metric_height: Optional[float] = Field(10.0, description="Real world ground height in meters")


class SpatialTransitionRequest(BaseModel):
    link_id: Optional[str] = Field(None, description="Optional custom link ID")
    source_camera: str = Field(..., description="Source camera ID")
    source_zone: str = Field(..., description="Source zone name")
    target_camera: str = Field(..., description="Target camera ID")
    target_zone: str = Field(..., description="Target zone name")
    t_min: Optional[float] = Field(2.0, description="Minimum expected transit time in seconds")
    t_max: Optional[float] = Field(15.0, description="Maximum expected transit time in seconds")
    prior_boost: Optional[float] = Field(0.35, description="Spatial predictive bonus to visual Re-ID score")
    bidirectional: Optional[bool] = Field(False, description="Bidirectional transition")
    active: Optional[bool] = Field(True, description="Whether link is active")


class OverlayUpdateRequest(BaseModel):
    bboxes: Optional[bool] = None
    track_ids: Optional[bool] = None
    dwell_timers: Optional[bool] = None
    velocity: Optional[bool] = None
    zones: Optional[bool] = None
    tripwires: Optional[bool] = None
    heatmap: Optional[bool] = None
    bev_minimap: Optional[bool] = None
    hud_bar: Optional[bool] = None


class JourneyExportRequest(BaseModel):
    entity_id: Optional[int] = None
    entity_name: Optional[str] = None
    track_id: Optional[int] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None


# -----------------------------------------------------------------------------
# Frontend Root
# -----------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Serve the modern single-page dashboard."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Intelligent Tracker Dashboard Initializing...</h1>")


# -----------------------------------------------------------------------------
# Video Streaming & WebSockets
# -----------------------------------------------------------------------------
@app.get("/stream/{camera_id}")
async def get_live_stream(camera_id: str):
    """
    Live MJPEG video streaming endpoint for a specific camera channel.
    Compatible with standard <img> tags: `<img src="/stream/cam_01" />`.
    """
    mgr = get_active_stream_manager(camera_id)
    if not mgr:
        raise HTTPException(status_code=503, detail=f"Stream for camera '{camera_id}' not initialized")

    async def frame_generator():
        while True:
            jpeg_bytes = mgr.get_latest_frame_jpeg()
            if jpeg_bytes:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + jpeg_bytes + b"\r\n"
                )
            await asyncio.sleep(0.04)  # ~25 FPS

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.websocket("/ws/{camera_id}")
async def websocket_telemetry_endpoint(websocket: WebSocket, camera_id: str):
    """
    WebSocket endpoint pushing real-time tracking, occupancy, and sighting telemetry.
    Supports client commands (e.g. toggle heatmap, ping).
    """
    await websocket.accept()
    mgr = get_active_stream_manager(camera_id)
    if not mgr:
        await websocket.close(code=1013, reason="Service unavailable")
        return

    queue: asyncio.Queue = asyncio.Queue(maxsize=20)
    loop = asyncio.get_running_loop()

    def sync_listener(data):
        loop.call_soon_threadsafe(
            lambda: queue.put_nowait(data) if not queue.full() else None
        )

    mgr.register_ws_subscriber(sync_listener)

    async def sender_task():
        try:
            while True:
                data = await queue.get()
                await websocket.send_json(data)
        except Exception:
            pass

    async def receiver_task():
        try:
            while True:
                msg = await websocket.receive_json()
                action = msg.get("action")
                if action == "toggle_heatmap":
                    res = mgr.toggle_heatmap()
                    await websocket.send_json({"type": "heatmap_state", "enabled": res})
                elif action == "ping":
                    await websocket.send_json({"type": "pong", "time": time.time()})
        except Exception:
            pass

    sender = asyncio.create_task(sender_task())
    receiver = asyncio.create_task(receiver_task())

    try:
        done, pending = await asyncio.wait(
            [sender, receiver],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    finally:
        mgr.unregister_ws_subscriber(sync_listener)


# -----------------------------------------------------------------------------
# REST API: Cameras & Multi-Camera VMS
# -----------------------------------------------------------------------------
@app.get("/cameras")
@app.get("/api/cameras")
async def list_cameras():
    """List configured and active video streams."""
    global camera_pool, stream_manager
    if camera_pool and camera_pool.camera_configs:
        return camera_pool.list_cameras()

    mgr = get_active_stream_manager()
    if not mgr:
        raise HTTPException(status_code=503, detail="Stream manager not initialized")

    telemetry = mgr.get_latest_telemetry()
    return [
        {
            "id": mgr.camera_id,
            "name": getattr(mgr, "name", f"Camera {mgr.camera_id.upper()}"),
            "status": telemetry.get("status", "online"),
            "fps": telemetry.get("fps", 0.0),
            "resolution": f"{mgr.video_source.width}x{mgr.video_source.height}"
            if mgr.video_source else "640x480",
            "active_tracks_count": len(telemetry.get("active_tracks", [])),
            "source_type": "synthetic" if mgr.video_source and mgr.video_source.is_synthetic else "physical",
        }
    ]


@app.post("/api/cameras")
async def add_camera(req: CameraAddRequest):
    """Dynamically register a new camera stream in the CameraPool."""
    global camera_pool
    if not camera_pool:
        camera_pool = CameraPool()

    mgr = camera_pool.add_camera(
        camera_id=req.id,
        name=req.name,
        source=req.source,
        cam_type=req.type or "rtsp",
        detector=req.detector,
        tracker=req.tracker,
        enabled=req.enabled if req.enabled is not None else True,
        autostart=True,
        details=req.details,
    )
    return {"status": "success", "camera": camera_pool.camera_configs.get(req.id)}


@app.get("/api/cameras/discover")
async def discover_cameras_route(
    include_usb: bool = True,
    include_onvif: bool = True,
    include_lan_rtsp: bool = True,
):
    """Probe physical USB webcams, ONVIF WS-Discovery, and local RTSP network cameras."""
    cams = discover_all_cameras(
        include_usb=include_usb,
        include_onvif=include_onvif,
        include_lan_rtsp=include_lan_rtsp,
        mock_fallback=True,
    )
    return [c.to_dict() for c in cams]


@app.post("/api/cameras/test")
async def test_camera_route(req: CameraTestRequest):
    """Test video source connectivity and return live preview snapshot."""
    target_source = req.source
    if req.preset and req.ip:
        target_source = build_preset_rtsp_url(
            preset=req.preset,
            ip=req.ip,
            port=req.port or 554,
            username=req.username or "",
            password=req.password or "",
            channel=req.channel or 1,
            stream=req.stream or "main",
        )
    if not target_source:
        target_source = "synthetic"

    # Handle numeric string for USB device index
    if isinstance(target_source, str) and target_source.isdigit():
        target_source = int(target_source)

    res = test_camera_connection(target_source)
    res["resolved_source"] = str(target_source)
    return res


@app.get("/api/cameras/presets")
async def get_presets_route():
    """Retrieve pre-configured vendor RTSP URL templates."""
    return CAMERA_PRESETS


@app.get("/api/cameras/{camera_id}")
async def get_camera_info(camera_id: str):
    """Retrieve configuration and health diagnostics for a specific camera channel."""
    if not camera_pool or camera_id not in camera_pool.camera_configs:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")

    cfg = camera_pool.camera_configs[camera_id]
    mgr = camera_pool.streams.get(camera_id)
    telemetry = mgr.get_latest_telemetry() if mgr else {}
    return {
        **cfg,
        "telemetry": telemetry,
        "is_running": mgr.is_running if mgr else False,
    }


@app.put("/api/cameras/{camera_id}")
async def update_camera(camera_id: str, req: CameraUpdateRequest):
    """Update camera configuration dynamically without restarting server."""
    if not camera_pool or camera_id not in camera_pool.camera_configs:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")

    success = camera_pool.update_camera(
        camera_id=camera_id,
        name=req.name,
        source=req.source,
        cam_type=req.type,
        enabled=req.enabled,
        detector=req.detector,
        tracker=req.tracker,
    )
    return {"status": "success" if success else "failed", "camera": camera_pool.camera_configs.get(camera_id)}


@app.delete("/api/cameras/{camera_id}")
async def delete_camera(camera_id: str):
    """Stop stream and delete camera from pool and persistent configuration."""
    if not camera_pool or camera_id not in camera_pool.camera_configs:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")

    camera_pool.remove_camera(camera_id)
    return {"status": "success", "deleted": camera_id}


@app.post("/api/cameras/{camera_id}/toggle")
async def toggle_camera_stream(camera_id: str, enabled: Optional[bool] = None):
    """Pause or resume processing for a specific camera channel."""
    if not camera_pool or camera_id not in camera_pool.camera_configs:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")

    new_state = camera_pool.toggle_camera(camera_id, enabled)
    return {"status": "success", "camera_id": camera_id, "enabled": new_state}


# -----------------------------------------------------------------------------
# REST API: Local Video Files & Scrubber
# -----------------------------------------------------------------------------
@app.get("/api/videos")
async def list_videos():
    """List uploaded and local video recordings in data/videos/."""
    files = []
    if os.path.exists(VIDEOS_DIR):
        for f in os.listdir(VIDEOS_DIR):
            if f.lower().endswith((".mp4", ".avi", ".mkv", ".mov")):
                full = os.path.join(VIDEOS_DIR, f)
                stat = os.stat(full)
                files.append({
                    "filename": f,
                    "path": full,
                    "size_bytes": stat.st_size,
                    "size_mb": round(stat.st_size / (1024 * 1024), 2),
                    "modified": stat.st_mtime,
                    "video_url": f"/videos/{f}",
                })
    return files


@app.post("/api/videos/upload")
async def upload_video(file: UploadFile = File(...)):
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

    stat = os.stat(dest_path)
    return {
        "status": "success",
        "filename": safe_name,
        "path": dest_path,
        "size_bytes": stat.st_size,
        "size_mb": round(stat.st_size / (1024 * 1024), 2),
        "video_url": f"/videos/{safe_name}",
    }


@app.delete("/api/videos/{filename}")
async def delete_video(filename: str):
    """Delete a recording from data/videos/."""
    safe_name = os.path.basename(filename)
    path = os.path.join(VIDEOS_DIR, safe_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Video file not found")
    os.remove(path)
    return {"status": "success", "deleted": safe_name}


@app.post("/api/videos/{filename}/add_as_camera")
async def add_video_as_camera(filename: str, camera_id: Optional[str] = None, name: Optional[str] = None):
    """Dynamically register an uploaded video file as an active camera stream."""
    safe_name = os.path.basename(filename)
    path = os.path.join(VIDEOS_DIR, safe_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Video file not found")

    base_id = os.path.splitext(safe_name)[0].replace(" ", "_").replace("-", "_")
    cam_id = camera_id or f"vid_{base_id}"
    cam_name = name or f"Video ({safe_name})"

    global camera_pool
    if not camera_pool:
        camera_pool = CameraPool()

    camera_pool.add_camera(
        camera_id=cam_id,
        name=cam_name,
        source=path,
        cam_type="video_file",
        detector="mock",
        tracker="centroid",
        enabled=True,
    )
    return {"status": "success", "camera_id": cam_id, "name": cam_name}


@app.post("/api/videos/{filename}/analyze")
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


@app.get("/videos/{filename}")
async def serve_video_stream(filename: str):
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


# -----------------------------------------------------------------------------
# REST API: State Persistence & Backup Migration
# -----------------------------------------------------------------------------
@app.get("/api/backup/export")
async def export_system_backup():
    """Package database records, crops, scenarios, and configs into a portable .zip archive."""
    mgr = BackupManager()
    backup_file = mgr.create_backup()
    return FileResponse(
        backup_file,
        media_type="application/zip",
        filename=os.path.basename(backup_file),
    )


@app.post("/api/backup/import")
async def import_system_backup(file: UploadFile = File(...)):
    """Import and restore full system configuration from uploaded .zip archive."""
    if not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip backup archives are supported")

    temp_dir = tempfile.mkdtemp(prefix="tracker_import_")
    temp_zip = os.path.join(temp_dir, os.path.basename(file.filename))

    try:
        with open(temp_zip, "wb") as buffer:
            content = await file.read()
            buffer.write(content)

        mgr = BackupManager()
        result = mgr.restore_backup(temp_zip)

        # Hot reload camera pool if initialized
        if camera_pool:
            camera_pool.load_cameras()

        return {"status": "success", "details": result}
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


# -----------------------------------------------------------------------------
# REST API: Zones, Heatmaps, Entities, Sightings & Tagging
# -----------------------------------------------------------------------------
@app.get("/zones")
async def list_zones(camera_id: Optional[str] = None):
    """List configured zones and their real-time occupancy counts."""
    mgr = get_active_stream_manager(camera_id)
    if not mgr or not mgr.analytics:
        return []
    zones = []
    for z in mgr.analytics.zones.values():
        zones.append({
            "name": z.name,
            "occupancy": z.occupancy,
            "capacity_limit": getattr(z, "capacity_limit", None),
            "dwell_threshold": z.dwell_threshold,
            "is_breached": getattr(z, "_threshold_breached", False),
            "color": z.color,
            "polygon": z.polygon.tolist() if hasattr(z.polygon, "tolist") else list(z.polygon),
        })
    return zones


@app.get("/analytics/heatmap")
async def get_heatmap(camera_id: Optional[str] = None, format: str = Query("image", description="'image' or 'json'")):
    """Retrieve the accumulated spatial occupancy density heatmap."""
    mgr = get_active_stream_manager(camera_id)
    if not mgr:
        raise HTTPException(status_code=503, detail="Stream manager not initialized")

    if format == "json":
        if not mgr.analytics or not mgr.analytics.heatmap:
            return {"density": []}
        return {
            "resolution": [mgr.analytics.heatmap.width, mgr.analytics.heatmap.height],
            "max_value": float(np.max(mgr.analytics.heatmap.density)),
            "mean_value": float(np.mean(mgr.analytics.heatmap.density)),
        }

    jpeg_bytes = mgr.get_heatmap_jpeg()
    return StreamingResponse(io.BytesIO(jpeg_bytes), media_type="image/jpeg")


@app.post("/analytics/heatmap/toggle")
async def toggle_heatmap(camera_id: Optional[str] = None, enabled: Optional[bool] = None):
    """Toggle live heatmap blending overlay on the camera feed."""
    mgr = get_active_stream_manager(camera_id)
    if not mgr:
        raise HTTPException(status_code=503, detail="Stream manager not initialized")
    res = mgr.toggle_heatmap(enabled)
    return {"draw_heatmap": res}


@app.get("/entities")
async def list_entities(category: Optional[str] = None):
    """List enrolled gallery identities with appearance counters and sample thumbnails."""
    mgr = get_active_stream_manager()
    if not mgr or not mgr.db:
        return []

    entities = mgr.db.list_entities(category=category)
    result = []
    for ent in entities:
        ent_dict = dict(ent)
        ent_id = ent_dict["id"]
        sightings = mgr.db.query_sightings(entity_id=ent_id, limit=1)
        sigs = mgr.db.get_signatures(entity_id=ent_id)

        with mgr.db._lock:
            cur = mgr.db._conn.cursor()
            try:
                cur.execute("SELECT COUNT(*) FROM sightings WHERE entity_id = ?", (ent_id,))
                count = cur.fetchone()[0]
            finally:
                cur.close()

        ent_dict["appearance_count"] = count
        ent_dict["signature_count"] = len(sigs)
        ent_dict["thumbnail_url"] = f"/crops/{os.path.basename(sigs[0]['crop_path'])}" if sigs and sigs[0].get("crop_path") else None
        ent_dict["last_seen"] = sightings[0]["timestamp"] if sightings else ent_dict["created_at"]
        result.append(ent_dict)

    return result


@app.post("/entities")
async def create_entity(req: EntityCreateRequest):
    """Enroll a new identity into the persistent Re-ID gallery database."""
    mgr = get_active_stream_manager()
    if not mgr or not mgr.db:
        raise HTTPException(status_code=503, detail="Database unavailable")

    existing = mgr.db.get_entity_by_name(req.name)
    if existing:
        raise HTTPException(status_code=409, detail=f"Entity with name '{req.name}' already exists (ID #{existing['id']})")

    entity_id = mgr.db.add_entity(name=req.name, category=req.category, notes=req.notes)
    return {"id": entity_id, "name": req.name, "category": req.category, "status": "active"}


@app.get("/entities/{entity_id}")
async def get_entity_details(entity_id: int):
    """Get single enrolled entity details with signatures and recent sightings."""
    mgr = get_active_stream_manager()
    if not mgr or not mgr.db:
        raise HTTPException(status_code=503, detail="Database unavailable")

    ent = mgr.db.get_entity(entity_id)
    if not ent:
        raise HTTPException(status_code=404, detail="Entity not found")

    sigs = mgr.db.get_signatures(entity_id)
    sightings = mgr.db.query_sightings(entity_id=entity_id, limit=20)

    res = dict(ent)
    res["signatures"] = [dict(s) for s in sigs]
    res["recent_sightings"] = [dict(s) for s in sightings]
    return res


@app.delete("/entities/{entity_id}")
async def delete_entity(entity_id: int):
    """Remove entity and its signatures from the gallery."""
    mgr = get_active_stream_manager()
    if not mgr or not mgr.db:
        raise HTTPException(status_code=503, detail="Database unavailable")

    success = mgr.db.delete_entity(entity_id)
    if not success:
        raise HTTPException(status_code=404, detail="Entity not found")

    if mgr.gallery_matcher:
        mgr.gallery_matcher.refresh_gallery()

    return {"deleted": True, "entity_id": entity_id}


@app.get("/sightings")
async def query_sightings(
    entity_id: Optional[int] = None,
    entity_name: Optional[str] = None,
    zone_id: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = 50,
):
    """Search historical sighting timeline records with entity, zone, and time filters."""
    mgr = get_active_stream_manager()
    if not mgr or not mgr.db:
        return []

    if entity_name and not entity_id:
        ent = mgr.db.get_entity_by_name(entity_name)
        if ent:
            entity_id = ent["id"]
        else:
            return []

    sightings = mgr.db.query_sightings(
        entity_id=entity_id,
        zone_id=zone_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )

    enriched = []
    for s in sightings:
        s_dict = dict(s)
        if s_dict.get("entity_id"):
            ent = mgr.db.get_entity(s_dict["entity_id"])
            s_dict["entity_name"] = ent["name"] if ent else "Unknown"
            s_dict["entity_category"] = ent["category"] if ent else "unknown"
        else:
            s_dict["entity_name"] = f"Track #{s_dict.get('track_id', 0)}"
            s_dict["entity_category"] = "unidentified"

        if s_dict.get("snapshot_path"):
            s_dict["snapshot_url"] = f"/crops/{os.path.basename(s_dict['snapshot_path'])}"
        enriched.append(s_dict)

    return enriched


@app.get("/events")
async def list_recent_events(limit: int = 50):
    """Get recent security and tracking alerts from EventBus ring buffer."""
    mgr = get_active_stream_manager()
    if not mgr or not mgr.event_bus:
        return []

    events = mgr.event_bus.get_recent_events(limit=limit)
    out = []
    for ev in events:
        if hasattr(ev, "to_dict"):
            out.append(ev.to_dict())
        elif hasattr(ev, "__dataclass_fields__"):
            from dataclasses import asdict
            out.append(asdict(ev))
        else:
            out.append({"event_type": getattr(ev, "event_type", "event")})
    return out


@app.post("/tag")
async def tag_bounding_box(req: TagRequest):
    """
    Interactive click-to-tag bounding box capability:
    Tags an active track or bounding box from browser, generates visual embedding,
    and enrolls into the Re-ID gallery database.
    """
    mgr = get_active_stream_manager(req.camera_id)
    if not mgr:
        raise HTTPException(status_code=503, detail="Stream manager not initialized")

    try:
        result = mgr.tag_entity(
            entity_name=req.entity_name,
            category=req.category,
            track_id=req.track_id,
            bbox=req.bbox,
            notes=req.notes or "",
        )
        return {"status": "success", "data": result}
    except Exception as e:
        logger.error("Tagging failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/crops/{filename}")
async def serve_crop_image(filename: str):
    """Serve crop thumbnail images."""
    file_path = os.path.join(CROPS_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="Crop image not found")


@app.get("/status")
async def system_status():
    """Comprehensive hardware telemetry and pipeline health metrics."""
    mgr = get_active_stream_manager()
    process = psutil.Process(os.getpid())
    mem_info = process.memory_info()

    uptime_sec = time.time() - (mgr.start_time if mgr else time.time())
    running = (camera_pool and any(s.is_running for s in camera_pool.streams.values())) or (mgr and mgr._running)

    return {
        "status": "online" if running else "stopped",
        "uptime_seconds": int(uptime_sec),
        "system": {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "ram_percent": psutil.virtual_memory().percent,
            "process_memory_mb": round(mem_info.rss / (1024 * 1024), 2),
        },
        "pipeline": {
            "camera_id": mgr.camera_id if mgr else "none",
            "cameras_active": len(camera_pool.streams) if camera_pool else 1,
            "fps": mgr._latest_telemetry.get("fps", 0.0) if mgr else 0.0,
            "detector": mgr.detector.__class__.__name__ if mgr and mgr.detector else "none",
            "tracker": mgr.tracker.__class__.__name__ if mgr and mgr.tracker else "none",
            "reid_extractor": mgr.reid_extractor.__class__.__name__ if mgr and mgr.reid_extractor else "none",
            "active_tracks": len(mgr._latest_telemetry.get("active_tracks", [])) if mgr else 0,
            "event_bus_events": mgr.event_bus.published_count if mgr and mgr.event_bus else 0,
        },
    }


# -----------------------------------------------------------------------------
# REST API: Scenario Studio, Space Awareness & Homography (Milestone 8)
# -----------------------------------------------------------------------------
def _get_scenario_mgr() -> ScenarioManager:
    global scenario_manager
    if scenario_manager is None:
        scenario_manager = ScenarioManager()
    return scenario_manager


@app.get("/api/scenarios")
async def get_all_scenarios():
    """Retrieve full scenario configuration across all cameras (zones, tripwires, homography, transitions)."""
    sm = _get_scenario_mgr()
    result = {
        "version": "1.0",
        "cameras": {},
        "spatial_transitions": [l.to_dict() for l in sm.topology.list_links() if not l.link_id.endswith("_rev")],
    }
    for cam_id, c_data in sm.cameras.items():
        result["cameras"][cam_id] = {
            "zones": [
                {
                    "name": z.name,
                    "polygon": z.polygon.tolist() if hasattr(z.polygon, "tolist") else list(z.polygon),
                    "dwell_threshold": z.dwell_threshold,
                    "capacity_limit": getattr(z, "capacity_limit", None),
                    "category_filter": getattr(z, "category_filter", ""),
                    "color": list(z.color),
                }
                for z in c_data["zones"].values()
            ],
            "tripwires": [
                {
                    "name": tw.name,
                    "line_segment": [list(tw.line_segment[0]), list(tw.line_segment[1])],
                    "bidirectional": tw.bidirectional,
                    "color": list(tw.color),
                }
                for tw in c_data["tripwires"].values()
            ],
            "homography": c_data["homography"].to_dict(),
        }
    return result


@app.get("/api/scenarios/{camera_id}")
async def get_camera_scenario(camera_id: str):
    """Retrieve scenario details for a specific camera channel."""
    sm = _get_scenario_mgr()
    c_data = sm._ensure_camera_entry(camera_id)
    return {
        "camera_id": camera_id,
        "zones": [
            {
                "name": z.name,
                "polygon": z.polygon.tolist() if hasattr(z.polygon, "tolist") else list(z.polygon),
                "dwell_threshold": z.dwell_threshold,
                "capacity_limit": getattr(z, "capacity_limit", None),
                "category_filter": getattr(z, "category_filter", ""),
                "color": list(z.color),
            }
            for z in c_data["zones"].values()
        ],
        "tripwires": [
            {
                "name": tw.name,
                "line_segment": [list(tw.line_segment[0]), list(tw.line_segment[1])],
                "bidirectional": tw.bidirectional,
                "color": list(tw.color),
            }
            for tw in c_data["tripwires"].values()
        ],
        "homography": c_data["homography"].to_dict(),
    }


@app.post("/api/scenarios/zones")
async def create_or_update_zone(req: ZoneCreateRequest):
    """Create or update a polygonal zone for a camera, persisting to YAML & SQLite."""
    sm = _get_scenario_mgr()
    color_tuple = tuple(req.color) if req.color and len(req.color) >= 3 else (0, 200, 100)
    zone = sm.save_zone(
        camera_id=req.camera_id,
        name=req.name,
        polygon=req.polygon,
        category_filter=req.category_filter or "",
        dwell_threshold=req.dwell_threshold or 5.0,
        capacity_limit=req.capacity_limit,
        color=color_tuple,
    )

    # Hot reload into active stream manager if camera is active
    mgr = get_active_stream_manager(req.camera_id)
    if mgr and mgr.analytics:
        mgr.analytics.add_zone(zone)

    return {
        "status": "success",
        "zone": {
            "camera_id": req.camera_id,
            "name": zone.name,
            "polygon": req.polygon,
            "dwell_threshold": zone.dwell_threshold,
            "capacity_limit": zone.capacity_limit,
            "category_filter": getattr(zone, "category_filter", ""),
            "color": list(zone.color),
        },
    }


@app.delete("/api/scenarios/zones/{camera_id}/{zone_name}")
async def delete_zone_route(camera_id: str, zone_name: str):
    """Delete a zone from a camera, updating memory, YAML, and SQLite."""
    sm = _get_scenario_mgr()
    deleted = sm.delete_zone(camera_id, zone_name)

    # Hot reload in active stream manager
    mgr = get_active_stream_manager(camera_id)
    if mgr and mgr.analytics and zone_name in mgr.analytics.zones:
        del mgr.analytics.zones[zone_name]

    return {"status": "success" if deleted else "not_found", "deleted": zone_name}


@app.post("/api/scenarios/tripwires")
async def create_or_update_tripwire(req: TripwireCreateRequest):
    """Create or update a directional tripwire line for a camera."""
    sm = _get_scenario_mgr()
    color_tuple = tuple(req.color) if req.color and len(req.color) >= 3 else (0, 255, 255)
    tw = sm.save_tripwire(
        camera_id=req.camera_id,
        name=req.name,
        line_segment=req.line_segment,
        bidirectional=req.bidirectional if req.bidirectional is not None else True,
        color=color_tuple,
    )

    # Hot reload into active stream manager if camera is active
    mgr = get_active_stream_manager(req.camera_id)
    if mgr and mgr.analytics:
        mgr.analytics.add_tripwire(tw)

    return {
        "status": "success",
        "tripwire": {
            "camera_id": req.camera_id,
            "name": tw.name,
            "line_segment": req.line_segment,
            "bidirectional": tw.bidirectional,
            "color": list(tw.color),
        },
    }


@app.delete("/api/scenarios/tripwires/{camera_id}/{tripwire_name}")
async def delete_tripwire_route(camera_id: str, tripwire_name: str):
    """Delete a tripwire line from a camera."""
    sm = _get_scenario_mgr()
    deleted = sm.delete_tripwire(camera_id, tripwire_name)

    mgr = get_active_stream_manager(camera_id)
    if mgr and mgr.analytics and tripwire_name in mgr.analytics.tripwires:
        del mgr.analytics.tripwires[tripwire_name]

    return {"status": "success" if deleted else "not_found", "deleted": tripwire_name}


@app.post("/api/scenarios/homography")
async def save_homography_route(req: HomographyCalibrationRequest):
    """Calibrate 4-point perspective ground plane homography matrix for camera."""
    sm = _get_scenario_mgr()
    try:
        homo = sm.save_homography(
            camera_id=req.camera_id,
            src_points=req.src_points,
            dst_points=req.dst_points,
            metric_width=req.metric_width or 10.0,
            metric_height=req.metric_height or 10.0,
        )

        # Apply to live stream manager if running
        mgr = get_active_stream_manager(req.camera_id)
        if mgr:
            mgr.homography = homo

        return {"status": "success", "homography": homo.to_dict()}
    except Exception as e:
        logger.error("Homography calibration failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/scenarios/homography/{camera_id}")
async def get_homography_route(camera_id: str):
    """Get ground plane homography calibration profile for a camera."""
    sm = _get_scenario_mgr()
    homo = sm.get_homography(camera_id)
    return homo.to_dict()


@app.delete("/api/scenarios/homography/{camera_id}")
async def delete_homography_route(camera_id: str):
    """Reset homography calibration for a camera channel."""
    sm = _get_scenario_mgr()
    c_entry = sm._ensure_camera_entry(camera_id)
    c_entry["homography"] = GroundPlaneHomography(camera_id=camera_id)
    if sm.db:
        sm.db.delete_homography_calibration(camera_id)
    sm.save_to_yaml()

    mgr = get_active_stream_manager(camera_id)
    if mgr:
        mgr.homography = c_entry["homography"]

    return {"status": "success", "deleted": camera_id}


@app.get("/api/scenarios/bev/{camera_id}")
async def get_bev_minimap_image(camera_id: str):
    """Retrieve live 2D Bird's-Eye-View (BEV) top-down minimap image."""
    mgr = get_active_stream_manager(camera_id)
    if mgr:
        jpeg_bytes = mgr.get_bev_minimap_jpeg()
        return StreamingResponse(io.BytesIO(jpeg_bytes), media_type="image/jpeg")

    sm = _get_scenario_mgr()
    homo = sm.get_homography(camera_id)
    c_entry = sm._ensure_camera_entry(camera_id)
    bev_img = homo.render_bev_minimap({}, zones=c_entry["zones"])
    ret, buf = cv2.imencode(".jpg", bev_img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    return StreamingResponse(io.BytesIO(buf.tobytes()), media_type="image/jpeg")


# -----------------------------------------------------------------------------
# REST API: Cross-Camera Topology
# -----------------------------------------------------------------------------
@app.get("/api/topology/transitions")
async def list_spatial_transitions():
    """List registered cross-camera spatial transition links."""
    sm = _get_scenario_mgr()
    return [l.to_dict() for l in sm.topology.list_links() if not l.link_id.endswith("_rev")]


@app.post("/api/topology/transitions")
async def create_spatial_transition(req: SpatialTransitionRequest):
    """Define a predictive spatial transition link between camera zones."""
    sm = _get_scenario_mgr()
    link_id = req.link_id or f"link_{req.source_camera}_{req.source_zone}_to_{req.target_camera}_{req.target_zone}".replace(" ", "_").lower()
    link = SpatialTransitionLink(
        link_id=link_id,
        source_camera=req.source_camera,
        source_zone=req.source_zone,
        target_camera=req.target_camera,
        target_zone=req.target_zone,
        t_min=req.t_min or 2.0,
        t_max=req.t_max or 15.0,
        prior_boost=req.prior_boost or 0.35,
        bidirectional=bool(req.bidirectional),
        active=bool(req.active),
    )
    sm.topology.add_link(link)
    if sm.db:
        sm.db.save_spatial_transition(
            link_id=link.link_id,
            source_camera=link.source_camera,
            source_zone=link.source_zone,
            target_camera=link.target_camera,
            target_zone=link.target_zone,
            t_min=link.t_min,
            t_max=link.t_max,
            prior_boost=link.prior_boost,
            bidirectional=link.bidirectional,
            active=link.active,
        )
    sm.save_to_yaml()
    return {"status": "success", "link": link.to_dict()}


@app.delete("/api/topology/transitions/{link_id}")
async def delete_spatial_transition(link_id: str):
    """Delete a spatial transition link by ID."""
    sm = _get_scenario_mgr()
    deleted = sm.topology.remove_link(link_id)
    if sm.db:
        db_del = sm.db.delete_spatial_transition(link_id)
        deleted = deleted or db_del
    if deleted:
        sm.save_to_yaml()
    return {"status": "success" if deleted else "not_found", "deleted": link_id}


@app.get("/api/topology/priors")
async def list_active_priors(camera_id: Optional[str] = None):
    """List currently active predictive spatial priors within valid transit windows."""
    sm = _get_scenario_mgr()
    now = time.time()
    priors = sm.topology.active_priors
    out = []
    for p in priors:
        if not p.is_expired_at(now):
            if not camera_id or p.target_camera == camera_id:
                out.append(p.to_dict())
    return out


# -----------------------------------------------------------------------------
# REST API: Trajectory Journey Search & Video Exporter
# -----------------------------------------------------------------------------
@app.get("/api/journey/search")
async def search_trajectory_journey(
    entity_id: Optional[int] = None,
    entity_name: Optional[str] = None,
    track_id: Optional[int] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
):
    """Reconstruct an entity's complete chronological trajectory across multiple cameras."""
    mgr = get_active_stream_manager()
    db = mgr.db if (mgr and mgr.db) else TrackerDB()
    searcher = TrajectoryJourneySearcher(db)
    journey = searcher.search_journey(
        entity_id=entity_id,
        entity_name=entity_name,
        track_id=track_id,
        start_time=start_time,
        end_time=end_time,
    )
    return journey.to_dict()


@app.post("/api/journey/export")
async def export_journey_video_route(req: JourneyExportRequest):
    """Slices and concatenates cross-camera video segments into a downloadable MP4 journey file."""
    mgr = get_active_stream_manager()
    db = mgr.db if (mgr and mgr.db) else TrackerDB()
    searcher = TrajectoryJourneySearcher(db)
    journey = searcher.search_journey(
        entity_id=req.entity_id,
        entity_name=req.entity_name,
        track_id=req.track_id,
        start_time=req.start_time,
        end_time=req.end_time,
    )

    if journey.total_hops == 0:
        raise HTTPException(status_code=404, detail="No sightings found to generate journey video")

    exporter = JourneyVideoExporter(output_dir=VIDEOS_DIR)
    exported_file = exporter.export_journey_video(journey)
    filename = os.path.basename(exported_file)

    return {
        "status": "success",
        "journey": journey.to_dict(),
        "video_file": filename,
        "video_url": f"/videos/{filename}",
    }


# -----------------------------------------------------------------------------
# REST API: Video Overlay Toolbar Controls
# -----------------------------------------------------------------------------
@app.get("/api/cameras/{camera_id}/overlays")
async def get_camera_overlays(camera_id: str):
    """Retrieve overlay visibility flags for a camera stream."""
    mgr = get_active_stream_manager(camera_id)
    if not mgr:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
    return mgr.get_overlays()


@app.post("/api/cameras/{camera_id}/overlays")
async def update_camera_overlays(camera_id: str, req: OverlayUpdateRequest):
    """Dynamically toggle bounding boxes, track IDs, dwell, velocity, zones, tripwires, heatmap, or BEV minimap."""
    mgr = get_active_stream_manager(camera_id)
    if not mgr:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")

    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    new_overlays = mgr.set_overlays(updates)
    return {"status": "success", "camera_id": camera_id, "overlays": new_overlays}

