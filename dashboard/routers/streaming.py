"""
Intelligent Tracker Dashboard - Video Streaming & WebSocket Telemetry Router.

Handles live MJPEG streaming, real-time WebSocket telemetry push,
root single-page application serving, and system hardware telemetry status.
"""

from __future__ import annotations

import os
import time
import uuid
import asyncio
import logging
from typing import Optional

import psutil
from fastapi import APIRouter, WebSocket, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse

import dashboard.dependencies as deps

logger = logging.getLogger("intelligent_tracker.dashboard.streaming")

router = APIRouter(tags=["Streaming"])

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")


@router.get("/", response_class=HTMLResponse)
async def serve_index():
    """Serve the modern single-page dashboard."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Intelligent Tracker Dashboard Initializing...</h1>")


@router.get("/stream/{camera_id}")
async def get_live_stream(camera_id: str, request: Request):
    """
    Live MJPEG video streaming endpoint for a specific camera channel.
    Compatible with standard <img> tags: `<img src="/stream/cam_01" />`.
    """
    mgr = deps.get_active_stream_manager(camera_id)
    if not mgr:
        raise HTTPException(status_code=503, detail=f"Stream for camera '{camera_id}' not initialized")

    sub_id = uuid.uuid4().hex

    async def frame_generator():
        mgr.add_subscriber(sub_id)
        try:
            while True:
                if await request.is_disconnected():
                    break
                mgr.heartbeat_subscriber(sub_id)
                jpeg_bytes = mgr.get_latest_frame_jpeg()
                if jpeg_bytes:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" + jpeg_bytes + b"\r\n"
                    )
                await asyncio.sleep(0.04)  # ~25 FPS
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            mgr.remove_subscriber(sub_id)

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.websocket("/ws/{camera_id}")
async def websocket_telemetry_endpoint(websocket: WebSocket, camera_id: str):
    """
    WebSocket endpoint pushing real-time tracking, occupancy, and sighting telemetry.
    Supports client commands (e.g. toggle heatmap, ping).
    """
    await websocket.accept()
    mgr = deps.get_active_stream_manager(camera_id)
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


@router.get("/status")
async def system_status():
    """Comprehensive hardware telemetry and pipeline health metrics."""
    mgr = deps.get_active_stream_manager()
    pool = deps.get_camera_pool()
    process = psutil.Process(os.getpid())
    mem_info = process.memory_info()

    uptime_sec = time.time() - (mgr.start_time if mgr else time.time())
    running = (pool and any(s.is_running for s in pool.streams.values())) or (mgr and mgr._running)

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
            "cameras_active": len(pool.streams) if pool else 1,
            "fps": mgr._latest_telemetry.get("fps", 0.0) if mgr else 0.0,
            "detector": mgr.detector.__class__.__name__ if mgr and mgr.detector else "none",
            "tracker": mgr.tracker.__class__.__name__ if mgr and mgr.tracker else "none",
            "reid_extractor": mgr.reid_extractor.__class__.__name__ if mgr and mgr.reid_extractor else "none",
            "active_tracks": len(mgr._latest_telemetry.get("active_tracks", [])) if mgr else 0,
            "event_bus_events": mgr.event_bus.published_count if mgr and mgr.event_bus else 0,
        },
    }

