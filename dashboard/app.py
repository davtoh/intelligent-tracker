#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Modern Web Dashboard Application.

FastAPI application providing:
- Live MJPEG video stream: `GET /stream/{camera_id}`
- Real-time WebSocket telemetry: `WS /ws/{camera_id}`
- REST API for cameras, zones, analytics, entity gallery, sighting timeline, and interactive click-to-tag:
  - `GET /cameras`
  - `GET /zones`
  - `GET /analytics/heatmap`
  - `POST /analytics/heatmap/toggle`
  - `GET /entities`
  - `POST /entities`
  - `GET /entities/{entity_id}`
  - `DELETE /entities/{entity_id}`
  - `GET /sightings`
  - `GET /events`
  - `POST /tag`
  - `GET /status`
- Modern single-page web UI served at `GET /`
"""

from __future__ import division, print_function, absolute_import

import os
import sys
import time
import io
import asyncio
import logging
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

import numpy as np

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import psutil

from dashboard.stream_manager import StreamManager

logger = logging.getLogger("intelligent_tracker.dashboard")

# Global StreamManager reference
stream_manager: Optional[StreamManager] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager starting and stopping the background pipeline."""
    global stream_manager
    logger.info("Initializing Intelligent Tracker StreamManager...")
    stream_manager = StreamManager()
    stream_manager.start()
    yield
    logger.info("Shutting down Intelligent Tracker StreamManager...")
    if stream_manager:
        stream_manager.stop()


app = FastAPI(
    title="Intelligent Tracker Web Dashboard",
    description="Edge AI Retail & Security Analytics Live Monitoring Platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure static directories exist
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs("data/crops", exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# Pydantic Schemas for Requests
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
    Live MJPEG video streaming endpoint.
    Compatible with standard <img> tags: `<img src="/stream/cam_01" />`.
    """
    if not stream_manager:
        raise HTTPException(status_code=503, detail="Stream manager not initialized")

    async def frame_generator():
        while True:
            jpeg_bytes = stream_manager.get_latest_frame_jpeg(camera_id)
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
    if not stream_manager:
        await websocket.close(code=1013, reason="Service unavailable")
        return

    queue: asyncio.Queue = asyncio.Queue(maxsize=20)
    loop = asyncio.get_running_loop()

    def sync_listener(data):
        loop.call_soon_threadsafe(
            lambda: queue.put_nowait(data) if not queue.full() else None
        )

    stream_manager.register_ws_subscriber(sync_listener)

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
                    res = stream_manager.toggle_heatmap()
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
        stream_manager.unregister_ws_subscriber(sync_listener)


# -----------------------------------------------------------------------------
# REST API Endpoints
# -----------------------------------------------------------------------------
@app.get("/cameras")
async def list_cameras():
    """List configured and active video streams."""
    if not stream_manager:
        raise HTTPException(status_code=503, detail="Stream manager not initialized")

    telemetry = stream_manager.get_latest_telemetry()
    return [
        {
            "id": stream_manager.camera_id,
            "name": f"Camera {stream_manager.camera_id.upper()}",
            "status": telemetry.get("status", "online"),
            "fps": telemetry.get("fps", 0.0),
            "resolution": f"{stream_manager.video_source.width}x{stream_manager.video_source.height}"
            if stream_manager.video_source else "640x480",
            "active_tracks_count": len(telemetry.get("active_tracks", [])),
            "source_type": "synthetic" if stream_manager.video_source and stream_manager.video_source.is_synthetic else "physical",
        }
    ]


@app.get("/zones")
async def list_zones():
    """List configured zones and their real-time occupancy counts."""
    if not stream_manager or not stream_manager.analytics:
        return []
    zones = []
    for z in stream_manager.analytics.zones.values():
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
async def get_heatmap(format: str = Query("image", description="'image' or 'json'")):
    """Retrieve the accumulated spatial occupancy density heatmap."""
    if not stream_manager:
        raise HTTPException(status_code=503, detail="Stream manager not initialized")

    if format == "json":
        if not stream_manager.analytics or not stream_manager.analytics.heatmap:
            return {"density": []}
        return {
            "resolution": [stream_manager.analytics.heatmap.width, stream_manager.analytics.heatmap.height],
            "max_value": float(np.max(stream_manager.analytics.heatmap.density)),
            "mean_value": float(np.mean(stream_manager.analytics.heatmap.density)),
        }

    jpeg_bytes = stream_manager.get_heatmap_jpeg()
    return StreamingResponse(io.BytesIO(jpeg_bytes), media_type="image/jpeg")


@app.post("/analytics/heatmap/toggle")
async def toggle_heatmap(enabled: Optional[bool] = None):
    """Toggle live heatmap blending overlay on the camera feed."""
    if not stream_manager:
        raise HTTPException(status_code=503, detail="Stream manager not initialized")
    res = stream_manager.toggle_heatmap(enabled)
    return {"draw_heatmap": res}


@app.get("/entities")
async def list_entities(category: Optional[str] = None):
    """List enrolled gallery identities with appearance counters and sample thumbnails."""
    if not stream_manager or not stream_manager.db:
        return []

    entities = stream_manager.db.list_entities(category=category)
    result = []
    for ent in entities:
        ent_dict = dict(ent)
        ent_id = ent_dict["id"]
        # Query total sightings count
        sightings = stream_manager.db.query_sightings(entity_id=ent_id, limit=1)
        sigs = stream_manager.db.get_signatures(entity_id=ent_id)

        # Count total sightings
        with stream_manager.db._lock:
            cur = stream_manager.db._conn.cursor()
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
    if not stream_manager or not stream_manager.db:
        raise HTTPException(status_code=503, detail="Database unavailable")

    existing = stream_manager.db.get_entity_by_name(req.name)
    if existing:
        raise HTTPException(status_code=409, detail=f"Entity with name '{req.name}' already exists (ID #{existing['id']})")

    entity_id = stream_manager.db.add_entity(name=req.name, category=req.category, notes=req.notes)
    return {"id": entity_id, "name": req.name, "category": req.category, "status": "active"}


@app.get("/entities/{entity_id}")
async def get_entity_details(entity_id: int):
    """Get single enrolled entity details with signatures and recent sightings."""
    if not stream_manager or not stream_manager.db:
        raise HTTPException(status_code=503, detail="Database unavailable")

    ent = stream_manager.db.get_entity(entity_id)
    if not ent:
        raise HTTPException(status_code=404, detail="Entity not found")

    sigs = stream_manager.db.get_signatures(entity_id)
    sightings = stream_manager.db.query_sightings(entity_id=entity_id, limit=20)

    res = dict(ent)
    res["signatures"] = [dict(s) for s in sigs]
    res["recent_sightings"] = [dict(s) for s in sightings]
    return res


@app.delete("/entities/{entity_id}")
async def delete_entity(entity_id: int):
    """Remove entity and its signatures from the gallery."""
    if not stream_manager or not stream_manager.db:
        raise HTTPException(status_code=503, detail="Database unavailable")

    success = stream_manager.db.delete_entity(entity_id)
    if not success:
        raise HTTPException(status_code=404, detail="Entity not found")

    if stream_manager.gallery_matcher:
        stream_manager.gallery_matcher.refresh_gallery()

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
    """
    Search historical sighting timeline records with entity, zone, and time filters.
    """
    if not stream_manager or not stream_manager.db:
        return []

    # If entity_name specified, resolve to entity_id
    if entity_name and not entity_id:
        ent = stream_manager.db.get_entity_by_name(entity_name)
        if ent:
            entity_id = ent["id"]
        else:
            return []

    sightings = stream_manager.db.query_sightings(
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
            ent = stream_manager.db.get_entity(s_dict["entity_id"])
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
    if not stream_manager or not stream_manager.event_bus:
        return []

    events = stream_manager.event_bus.get_recent_events(limit=limit)
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
    if not stream_manager:
        raise HTTPException(status_code=503, detail="Stream manager not initialized")

    try:
        result = stream_manager.tag_entity(
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
    file_path = os.path.join("data", "crops", filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="Crop image not found")


@app.get("/status")
async def system_status():
    """Comprehensive hardware telemetry and pipeline health metrics."""
    process = psutil.Process(os.getpid())
    mem_info = process.memory_info()

    uptime_sec = time.time() - (stream_manager.start_time if stream_manager else time.time())

    return {
        "status": "online" if stream_manager and stream_manager._running else "stopped",
        "uptime_seconds": int(uptime_sec),
        "system": {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "ram_percent": psutil.virtual_memory().percent,
            "process_memory_mb": round(mem_info.rss / (1024 * 1024), 2),
        },
        "pipeline": {
            "camera_id": stream_manager.camera_id if stream_manager else "none",
            "fps": stream_manager._latest_telemetry.get("fps", 0.0) if stream_manager else 0.0,
            "detector": stream_manager.detector.__class__.__name__ if stream_manager and stream_manager.detector else "none",
            "tracker": stream_manager.tracker.__class__.__name__ if stream_manager and stream_manager.tracker else "none",
            "reid_extractor": stream_manager.reid_extractor.__class__.__name__ if stream_manager and stream_manager.reid_extractor else "none",
            "active_tracks": len(stream_manager._latest_telemetry.get("active_tracks", [])) if stream_manager else 0,
            "event_bus_events": stream_manager.event_bus.published_count if stream_manager and stream_manager.event_bus else 0,
        },
    }
