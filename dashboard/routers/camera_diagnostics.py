#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Camera Diagnostics & Lock Management API Router.

Provides:
- Per-camera detailed diagnostic health inspection and stack trace retrieval.
- Targeted camera hardware lock release and worker process termination.
- Instant camera source probing and multi-channel system health summaries.
"""

import logging
from typing import Dict, Any

from fastapi import APIRouter, HTTPException

from dashboard.dependencies import get_camera_pool
from dashboard.services.camera_diagnostics import CameraHealthManager
from intelligent_tracker.camera_device import CameraDeviceHandler

logger = logging.getLogger("intelligent_tracker.dashboard.routers.camera_diagnostics")

router = APIRouter(prefix="/api/cameras", tags=["Camera Diagnostics"])


def _resolve_pool():
    pool = get_camera_pool()
    if not pool:
        from dashboard.camera_pool import CameraPool
        from dashboard.dependencies import set_camera_pool
        pool = CameraPool(autostart=False)
        set_camera_pool(pool)
    return pool


@router.get("/diagnostics/summary")
async def get_diagnostics_summary() -> Dict[str, Any]:
    """Summary of operational health across all registered camera streams."""
    pool = _resolve_pool()
    cameras = pool.list_cameras() if pool else []
    total = len(cameras)
    online = sum(1 for c in cameras if c.get("status") == "online")
    errors = sum(1 for c in cameras if c.get("status") == "error")
    paused = sum(1 for c in cameras if c.get("status") == "paused")

    health_mgr = CameraHealthManager()
    reports = health_mgr.list_reports()

    return {
        "total_cameras": total,
        "online_count": online,
        "error_count": errors,
        "paused_count": paused,
        "reports": reports,
    }


@router.get("/{camera_id}/diagnostics")
async def get_camera_diagnostics(camera_id: str) -> Dict[str, Any]:
    """Fetch structured health telemetry, stack traces, and suggested fixes for a camera."""
    pool = _resolve_pool()
    cfg = pool.camera_configs.get(camera_id) if pool else None

    health_mgr = CameraHealthManager()
    report = health_mgr.get_health(camera_id).to_dict()

    if cfg:
        report["name"] = cfg.get("name", camera_id)
        report["source"] = cfg.get("source")
        report["type"] = cfg.get("type", "rtsp")
        report["device_name"] = cfg.get("device_name") or (cfg.get("details") or {}).get("device_name")
        report["enabled"] = cfg.get("enabled", True)
    elif report.get("status") == "unknown":
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found in VMS pool")

    return report


@router.post("/{camera_id}/release")
async def release_camera_device(camera_id: str) -> Dict[str, Any]:
    """Release DirectShow COM or worker process lock holding this camera's hardware index."""
    pool = _resolve_pool()
    cfg = pool.camera_configs.get(camera_id) if pool else None
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found in VMS pool")

    source = cfg.get("source")
    health_mgr = CameraHealthManager()
    release_result = health_mgr.release_device_lock(source)

    # Re-probe device and update health
    if str(source).isdigit() or isinstance(source, int):
        idx = int(source)
        dev_info = CameraDeviceHandler.probe_device(idx)
        if dev_info:
            health_mgr.set_online(camera_id, fps=dev_info.get("fps", 30.0), diagnostics=dev_info)
            release_result["device_status"] = "AVAILABLE"
            release_result["probe"] = dev_info
        else:
            release_result["device_status"] = "UNAVAILABLE"

    return {
        "status": "success",
        "camera_id": camera_id,
        "source": source,
        "release_result": release_result,
    }


@router.post("/{camera_id}/probe")
async def probe_camera_channel(camera_id: str) -> Dict[str, Any]:
    """Perform real-time hardware or network probe on a registered camera channel."""
    pool = _resolve_pool()
    cfg = pool.camera_configs.get(camera_id) if pool else None
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found in VMS pool")

    source = cfg.get("source")
    device_name = cfg.get("device_name") or (cfg.get("details") or {}).get("device_name")

    from intelligent_tracker.camera_resolver import CameraPathResolver
    resolved_source, meta = CameraPathResolver.resolve_camera_source(source, device_name=device_name)

    probe_result = {
        "original_source": source,
        "resolved_source": resolved_source,
        "metadata": meta,
    }

    if isinstance(resolved_source, int):
        dev_info = CameraDeviceHandler.probe_device(resolved_source)
        probe_result["hardware_probe"] = dev_info
        probe_result["operational"] = bool(dev_info and dev_info.get("valid"))
    else:
        from intelligent_tracker.discovery import test_camera_connection
        test_res = test_camera_connection(str(resolved_source))
        probe_result["network_probe"] = test_res
        probe_result["operational"] = bool(test_res.get("success"))

    return {
        "status": "success",
        "camera_id": camera_id,
        "probe": probe_result,
    }

