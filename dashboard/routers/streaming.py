#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Video Streaming & Telemetry WebSockets Router.

Provides real-time MJPEG live streaming and bi-directional WebSocket telemetry
channels with low-latency disconnect detection and viewer session management.
"""

import asyncio
import logging
import time
import uuid

from fastapi import APIRouter, HTTPException, Request, WebSocket

from dashboard.dependencies import (
    get_active_stream_manager,
    get_shutdown_event,
    is_shutting_down,
)

logger = logging.getLogger("intelligent_tracker.dashboard.routers.streaming")

router = APIRouter(tags=["Streaming"])


@router.get("/stream/{camera_id}")
async def get_live_stream(camera_id: str, request: Request):
    """
    Live MJPEG video streaming endpoint for a specific camera channel.
    Compatible with standard <img> tags: `<img src="/stream/cam_01" />`.
    """
    from fastapi.responses import StreamingResponse

    mgr = get_active_stream_manager(camera_id)
    if not mgr:
        raise HTTPException(
            status_code=503,
            detail=f"Stream for camera '{camera_id}' not initialized",
        )

    sub_id = uuid.uuid4().hex

    async def frame_generator():
        mgr.add_subscriber(sub_id)
        shutdown_evt = get_shutdown_event()
        try:
            while not is_shutting_down() and not shutdown_evt.is_set():
                if await request.is_disconnected():
                    break
                mgr.heartbeat_subscriber(sub_id)
                jpeg_bytes = mgr.get_latest_frame_jpeg()
                if jpeg_bytes:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" + jpeg_bytes + b"\r\n"
                    )
                try:
                    await asyncio.wait_for(shutdown_evt.wait(), timeout=0.04)
                    break
                except asyncio.TimeoutError:
                    pass
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            mgr.remove_subscriber(sub_id)

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


async def _run_ws_sender(websocket: WebSocket, queue: asyncio.Queue) -> None:
    """Forward queued telemetry payloads to connected WebSocket client."""
    try:
        while True:
            data = await queue.get()
            await websocket.send_json(data)
    except Exception:
        pass


async def _run_ws_receiver(websocket: WebSocket, mgr) -> None:
    """Handle incoming client commands (e.g. heatmap toggles, pings)."""
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


@router.websocket("/ws/{camera_id}")
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

    sender = asyncio.create_task(_run_ws_sender(websocket, queue))
    receiver = asyncio.create_task(_run_ws_receiver(websocket, mgr))
    shutdown_evt = get_shutdown_event()
    shutdown_task = asyncio.create_task(shutdown_evt.wait())

    try:
        done, pending = await asyncio.wait(
            [sender, receiver, shutdown_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    finally:
        shutdown_task.cancel()
        mgr.unregister_ws_subscriber(sync_listener)

