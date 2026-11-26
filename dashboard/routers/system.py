#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - System & Diagnostics API Router.

Provides endpoints for system status, resource metrics, stream lifecycle
management (process eviction, hibernation), and database backup export/import.
"""

import logging
import os
import shutil
import tempfile
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from dashboard.services.camera_pool_queries import snapshot_pool_streams
import psutil

from dashboard.camera_pool import CameraPool
from dashboard.dependencies import (
    get_camera_pool,
    get_db,
    get_lifecycle_manager,
    get_rsac_mgr,
    get_stream_manager,
    resolve_stream_manager,
)
from dashboard.stream_manager import StreamManager
from intelligent_tracker.backup import BackupManager
from intelligent_tracker.lifecycle import StreamLifecycleManager
from intelligent_tracker.rsac import RSACManager

logger = logging.getLogger("intelligent_tracker.dashboard.routers.system")

router = APIRouter(tags=["System & Diagnostics"])


@router.get("/status")
async def system_status(
    pool: Optional[CameraPool] = Depends(get_camera_pool),
    sm: Optional[StreamManager] = Depends(get_stream_manager),
):
    """Comprehensive hardware telemetry and pipeline health metrics."""
    mgr = resolve_stream_manager(None, pool=pool, sm=sm)
    process = psutil.Process(os.getpid())
    mem_info = process.memory_info()

    streams = snapshot_pool_streams(pool)
    start_ts = getattr(mgr, "start_time", time.time()) if mgr else time.time()
    latest_telemetry = getattr(mgr, "_latest_telemetry", {}) if mgr else {}
    uptime_sec = time.time() - start_ts
    running = (pool and any(s.is_running for s in streams.values())) or (
        mgr and mgr._running
    )

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
            "cameras_active": len(streams) if pool else 1,
            "fps": latest_telemetry.get("fps", 0.0),
            "detector": mgr.detector.__class__.__name__ if mgr and mgr.detector else "none",
            "tracker": mgr.tracker.__class__.__name__ if mgr and mgr.tracker else "none",
            "reid_extractor": (
                mgr.reid_extractor.__class__.__name__
                if mgr and mgr.reid_extractor
                else "none"
            ),
            "active_tracks": len(latest_telemetry.get("active_tracks", [])),
            "event_bus_events": mgr.event_bus.published_count if mgr and mgr.event_bus else 0,
        },
    }


def _build_backup_manager(request: Request, db: Any = None, pool: Optional[CameraPool] = None) -> BackupManager:
    """Construct BackupManager wired to active DB, crops dir, and hot-reload callbacks."""
    db_path = getattr(db, "db_path", None) or os.getenv("TRACKER_DB_PATH") or os.path.join("data", "tracker.db")
    crops_dir = os.getenv("TRACKER_CROPS_DIR") or os.path.join("data", "crops")
    callbacks: list[Any] = []
    if pool is not None:
        callbacks.append(pool.reload_all_galleries)
    scen = getattr(getattr(getattr(request, "app", None), "state", None), "scenario_manager", None)
    if scen is not None and hasattr(scen, "reload"):
        callbacks.append(scen.reload)
    return BackupManager(db_path=db_path, crops_dir=crops_dir, hot_reload_callbacks=callbacks or None)


@router.get("/api/backup/export")
async def export_system_backup(
    request: Request,
    db: Any = Depends(get_db),
    pool: Optional[CameraPool] = Depends(get_camera_pool),
):
    """Package database records, crops, scenarios, and configs into a portable .zip archive."""
    mgr = _build_backup_manager(request, db=db, pool=pool)
    backup_file = mgr.create_backup()
    return FileResponse(
        backup_file,
        media_type="application/zip",
        filename=os.path.basename(backup_file),
    )


@router.post("/api/backup/import")
async def import_system_backup(
    request: Request,
    file: UploadFile = File(...),
    db: Any = Depends(get_db),
    pool: Optional[CameraPool] = Depends(get_camera_pool),
):
    """Import and restore full system configuration from uploaded .zip archive."""
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=400, detail="Only .zip backup archives are supported"
        )

    temp_dir = tempfile.mkdtemp(prefix="tracker_import_")
    temp_zip = os.path.join(temp_dir, os.path.basename(file.filename))

    try:
        with open(temp_zip, "wb") as buffer:
            content = await file.read()
            buffer.write(content)

        mgr = _build_backup_manager(request, db=db, pool=pool)
        result = mgr.restore_backup(temp_zip)

        if pool:
            pool.load_cameras()

        return {"status": "success", "details": result}
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


@router.get("/api/system/processes")
async def get_system_processes(
    lm: StreamLifecycleManager = Depends(get_lifecycle_manager),
):
    """Diagnostic overview of background workers, threads, PIDs, and stream hibernation states."""
    return lm.get_diagnostics()


def _discover_registered_backends() -> Dict[str, Any]:
    """Query Detector, Tracker, and ReID registries with safe fallback defaults."""
    from intelligent_tracker.detectors import DetectorFactory
    from intelligent_tracker.reid import ReIDExtractorFactory
    from intelligent_tracker.tracker import TrackerFactory

    try:
        detectors = DetectorFactory.available()
    except Exception as e:
        logger.warning("Failed to fetch available detectors: %s", e)
        detectors = ["yolov8", "mock"]
    try:
        trackers = TrackerFactory.available_trackers()
    except Exception as e:
        logger.warning("Failed to fetch available trackers: %s", e)
        trackers = ["centroid", "sort"]
    try:
        reid_extractors = list(getattr(ReIDExtractorFactory, "_registry", {}).keys())
    except Exception as e:
        logger.warning("Failed to fetch available reid extractors: %s", e)
        reid_extractors = ["color", "hsv", "onnx", "mock"]
    primary = [
        d for d in ["yolov8", "yolo11", "haar", "face_yunet", "movementdetector", "color", "mock"]
        if d in detectors
    ]
    return {
        "detectors": detectors,
        "primary_detectors": primary or detectors[:6],
        "trackers": trackers,
        "reid_extractors": reid_extractors,
    }


@router.get("/api/system/capabilities")
async def get_system_capabilities(
    rsac: Optional[RSACManager] = Depends(get_rsac_mgr),
):
    """Expose available detectors, trackers, Re-ID extractors, target classes, and presets."""
    from intelligent_tracker.detectors.coco_classes import COCO_CLASSES

    if rsac is not None and hasattr(rsac, "list_categories"):
        tracked_categories = rsac.list_categories()
    else:
        tracked_categories = RSACManager(db=None).list_categories()

    return {
        **_discover_registered_backends(),
        "coco_classes": COCO_CLASSES,
        "tracked_categories": tracked_categories,
        "default_classes": [
            "person", "car", "bicycle", "motorcycle", "bus", "truck", "dog", "cat"
        ],
        "class_presets": {
            "person": ["person"],
            "vehicles": ["car", "motorcycle", "bus", "truck", "bicycle"],
            "security": ["person", "car", "truck", "motorcycle", "backpack", "suitcase"],
            "all": [],
        },
        "source_presets": [
            {"label": "Real Physical Webcam (auto-detect)", "value": "real"},
            {"label": "USB Device #0", "value": "0"},
            {"label": "USB Device #1", "value": "1"},
            {"label": "Synthetic / Mock Source", "value": "synthetic"},
        ],
    }


@router.post("/api/system/streams/{camera_id}/evict")
async def evict_stream_subscribers(
    camera_id: str,
    reason: Optional[str] = Query("Admin eviction"),
    lm: StreamLifecycleManager = Depends(get_lifecycle_manager),
):
    """Forcibly evict all active subscriber leases for a camera, putting it immediately into hibernation."""
    res = lm.evict_subscribers(camera_id, reason=reason or "Admin eviction")
    if not res.get("success"):
        raise HTTPException(
            status_code=404, detail=res.get("error", "Failed to evict stream")
        )
    return res


@router.post("/api/system/hibernate_all")
async def hibernate_all_idle(
    lm: StreamLifecycleManager = Depends(get_lifecycle_manager),
):
    """Audit all streams and force-hibernate any channel with zero active viewers."""
    return lm.hibernate_all_idle()


@router.get("/api/system/metrics")
async def get_system_metrics_history(
    limit: int = Query(100, ge=1, le=1000),
    lm: StreamLifecycleManager = Depends(get_lifecycle_manager),
):
    """Retrieve historical time-series resource usage (CPU, RAM, stream count) for charting."""
    return lm.get_metrics_history(limit=limit)


@router.get("/api/system/events")
async def get_system_lifecycle_events(
    camera_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    lm: StreamLifecycleManager = Depends(get_lifecycle_manager),
):
    """Retrieve historical stream lifecycle audit trail (START, HIBERNATE, RESUME, EVICT)."""
    return lm.get_lifecycle_history(camera_id=camera_id, limit=limit)


@router.get("/api/system/models")
async def get_system_models(verify: bool = Query(True)):
    """Report registered ONNX model weights presence, sizes, and optional SHA-256 status."""
    from intelligent_tracker.detectors.model_loader import check_status

    return check_status(verify=verify, quiet=True)


@router.post("/api/system/models/verify")
async def verify_system_models(model_name: Optional[str] = Query(None)):
    """Verify SHA-256 checksums across registered ONNX model weights."""
    from intelligent_tracker.detectors.model_loader import check_status

    try:
        return check_status(model_name=model_name, verify=True, quiet=True)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class DebugObservationRequest(BaseModel):
    """Payload submitted by the client Debug Observation HUD."""

    note: str = Field(..., min_length=1, max_length=2000)
    tab: str = Field("", max_length=120)
    url: str = Field("", max_length=500)
    breadcrumbs: list[Dict[str, Any]] = Field(default_factory=list)
    viewport: Optional[Dict[str, Any]] = None


@router.get("/api/system/debug/summary")
async def get_debug_session_summary(
    min_level: str = Query("WARNING"),
    limit: int = Query(20, ge=1, le=200),
):
    """Return deduplicated error/warning summary, user observations, and debug mode status."""
    from dashboard.services.debug_session import is_debug_mode, summarize_debug_session

    summary = summarize_debug_session(min_level=min_level, limit=limit)
    summary["debug_mode"] = is_debug_mode()
    return summary


@router.post("/api/system/debug/observation")
async def record_debug_observation(payload: DebugObservationRequest):
    """Record a qualitative user observation with client breadcrumbs when IT_DEBUG_MODE=1."""
    from dashboard.services.debug_session import is_debug_mode, record_user_observation

    if not is_debug_mode():
        raise HTTPException(
            status_code=403,
            detail="Debug observation mode is disabled (set IT_DEBUG_MODE=1)",
        )
    try:
        obs = record_user_observation(
            note=payload.note,
            tab=payload.tab,
            url=payload.url,
            breadcrumbs=payload.breadcrumbs,
            viewport=payload.viewport,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "recorded", "observation": obs}


