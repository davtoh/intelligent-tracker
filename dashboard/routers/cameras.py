"""
Intelligent Tracker Dashboard - Camera Management & Multi-Camera VMS Router.

Handles camera discovery, CRUD, RTSP presets, stream toggling, dynamic overlays,
freeze-frames, and REST telemetry snapshots for Hub integration.
"""

from __future__ import annotations

import base64
import logging
from typing import Optional

import cv2
from fastapi import APIRouter, HTTPException

from dashboard.camera_pool import CameraPool
from dashboard.schemas import (
    CameraAddRequest,
    CameraUpdateRequest,
    CameraTestRequest,
    OverlayUpdateRequest,
)
import dashboard.dependencies as deps
from intelligent_tracker.discovery import (
    discover_all_cameras,
    test_camera_connection,
    build_preset_rtsp_url,
    CAMERA_PRESETS,
)

logger = logging.getLogger("intelligent_tracker.dashboard.cameras")

router = APIRouter(tags=["Cameras"])


@router.get("/cameras")
@router.get("/api/cameras")
async def list_cameras():
    """List configured and active video streams."""
    pool = deps.get_camera_pool()
    if pool and pool.camera_configs:
        return pool.list_cameras()

    mgr = deps.get_active_stream_manager()
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


@router.post("/api/cameras")
async def add_camera(req: CameraAddRequest):
    """Dynamically register a new camera stream in the CameraPool."""
    pool = deps.get_camera_pool()
    if not pool:
        pool = CameraPool()
        deps.set_camera_pool(pool)

    mgr = pool.add_camera(
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
    return {"status": "success", "camera": pool.camera_configs.get(req.id)}


@router.get("/api/cameras/discover")
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


@router.post("/api/cameras/test")
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

    if isinstance(target_source, str) and target_source.isdigit():
        target_source = int(target_source)

    res = test_camera_connection(target_source)
    res["resolved_source"] = str(target_source)
    return res


@router.get("/api/cameras/presets")
async def get_presets_route():
    """Retrieve pre-configured vendor RTSP URL templates."""
    return CAMERA_PRESETS


@router.get("/api/cameras/{camera_id}")
async def get_camera_info(camera_id: str):
    """Retrieve configuration and health diagnostics for a specific camera channel."""
    pool = deps.get_camera_pool()
    if not pool or camera_id not in pool.camera_configs:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")

    cfg = pool.camera_configs[camera_id]
    mgr = pool.streams.get(camera_id)
    telemetry = mgr.get_latest_telemetry() if mgr else {}
    return {
        **cfg,
        "telemetry": telemetry,
        "is_running": mgr.is_running if mgr else False,
    }


@router.get("/api/cameras/{camera_id}/telemetry")
async def get_camera_telemetry_snapshot(camera_id: str):
    """
    Retrieve real-time telemetry snapshot (bounding boxes, tracking states, zones, tripwires)
    for central Enterprise Cloud Hub canvas overlay proxying.
    """
    pool = deps.get_camera_pool()
    sm = deps.get_stream_manager()
    mgr = None
    if pool:
        if camera_id in pool.camera_configs or camera_id in pool.streams:
            mgr = pool.get_stream(camera_id)
    if not mgr and sm and sm.camera_id == camera_id:
        mgr = sm

    if not mgr:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")

    telemetry = mgr.get_latest_telemetry()
    res_str = "640x480"
    if mgr.video_source and hasattr(mgr.video_source, "width") and hasattr(mgr.video_source, "height"):
        res_str = f"{mgr.video_source.width}x{mgr.video_source.height}"

    return {
        "camera_id": camera_id,
        "status": telemetry.get("status", "online"),
        "fps": round(float(telemetry.get("fps", 0.0)), 1),
        "resolution": res_str,
        "active_tracks": telemetry.get("active_tracks", []),
        "zones": telemetry.get("zones", []),
        "tripwires": telemetry.get("tripwires", []),
    }


@router.put("/api/cameras/{camera_id}")
async def update_camera(camera_id: str, req: CameraUpdateRequest):
    """Update camera configuration dynamically without restarting server."""
    pool = deps.get_camera_pool()
    if not pool or camera_id not in pool.camera_configs:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")

    success = pool.update_camera(
        camera_id=camera_id,
        name=req.name,
        source=req.source,
        cam_type=req.type,
        enabled=req.enabled,
        detector=req.detector,
        tracker=req.tracker,
    )
    return {"status": "success" if success else "failed", "camera": pool.camera_configs.get(camera_id)}


@router.delete("/api/cameras/{camera_id}")
async def delete_camera(camera_id: str):
    """Stop stream and delete camera from pool and persistent configuration."""
    pool = deps.get_camera_pool()
    if not pool or camera_id not in pool.camera_configs:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")

    pool.remove_camera(camera_id)
    return {"status": "success", "deleted": camera_id}


@router.post("/api/cameras/{camera_id}/toggle")
async def toggle_camera_stream(camera_id: str, enabled: Optional[bool] = None):
    """Pause or resume processing for a specific camera channel."""
    pool = deps.get_camera_pool()
    if not pool or camera_id not in pool.camera_configs:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")

    new_state = pool.toggle_camera(camera_id, enabled)
    return {"status": "success", "camera_id": camera_id, "enabled": new_state}


@router.get("/api/cameras/{camera_id}/overlays")
async def get_camera_overlays(camera_id: str):
    """Retrieve overlay visibility flags for a camera stream."""
    mgr = deps.get_active_stream_manager(camera_id)
    if not mgr:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
    return mgr.get_overlays()


@router.post("/api/cameras/{camera_id}/overlays")
async def update_camera_overlays(camera_id: str, req: OverlayUpdateRequest):
    """Dynamically toggle bounding boxes, track IDs, dwell, velocity, zones, tripwires, heatmap, or BEV minimap."""
    mgr = deps.get_active_stream_manager(camera_id)
    if not mgr:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")

    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    new_overlays = mgr.set_overlays(updates)
    return {"status": "success", "camera_id": camera_id, "overlays": new_overlays}


@router.get("/api/cameras/{camera_id}/freeze_frame")
async def get_freeze_frame(camera_id: str):
    """Retrieve raw un-annotated video frame for interactive bbox selection & enrollment."""
    mgr = deps.get_active_stream_manager(camera_id)
    if not mgr:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
    raw = None
    with mgr._lock:
        if mgr._latest_raw_frame is not None:
            raw = mgr._latest_raw_frame.copy()
    if raw is None:
        raise HTTPException(status_code=503, detail=f"No video frame available for '{camera_id}' yet")
    h, w = raw.shape[:2]
    ret, buf = cv2.imencode(".jpg", raw, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not ret:
        raise HTTPException(status_code=500, detail="Failed to encode freeze frame")
    b64_str = base64.b64encode(buf.tobytes()).decode("utf-8")
    return {
        "camera_id": camera_id,
        "width": w,
        "height": h,
        "image_base64": f"data:image/jpeg;base64,{b64_str}",
    }
