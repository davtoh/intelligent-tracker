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
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
import psutil

from dashboard.dependencies import (
    get_active_stream_manager,
    get_camera_pool,
    get_lifecycle_manager,
)
from intelligent_tracker.backup import BackupManager

logger = logging.getLogger("intelligent_tracker.dashboard.routers.system")

router = APIRouter(tags=["System & Diagnostics"])


@router.get("/status")
async def system_status():
    """Comprehensive hardware telemetry and pipeline health metrics."""
    mgr = get_active_stream_manager()
    pool = get_camera_pool()
    process = psutil.Process(os.getpid())
    mem_info = process.memory_info()

    uptime_sec = time.time() - (mgr.start_time if mgr else time.time())
    running = (pool and any(s.is_running for s in pool.streams.values())) or (
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
            "cameras_active": len(pool.streams) if pool else 1,
            "fps": mgr._latest_telemetry.get("fps", 0.0) if mgr else 0.0,
            "detector": mgr.detector.__class__.__name__ if mgr and mgr.detector else "none",
            "tracker": mgr.tracker.__class__.__name__ if mgr and mgr.tracker else "none",
            "reid_extractor": (
                mgr.reid_extractor.__class__.__name__
                if mgr and mgr.reid_extractor
                else "none"
            ),
            "active_tracks": len(mgr._latest_telemetry.get("active_tracks", [])) if mgr else 0,
            "event_bus_events": mgr.event_bus.published_count if mgr and mgr.event_bus else 0,
        },
    }


@router.get("/api/backup/export")
async def export_system_backup():
    """Package database records, crops, scenarios, and configs into a portable .zip archive."""
    mgr = BackupManager()
    backup_file = mgr.create_backup()
    return FileResponse(
        backup_file,
        media_type="application/zip",
        filename=os.path.basename(backup_file),
    )


@router.post("/api/backup/import")
async def import_system_backup(file: UploadFile = File(...)):
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

        mgr = BackupManager()
        result = mgr.restore_backup(temp_zip)

        pool = get_camera_pool()
        if pool:
            pool.load_cameras()

        return {"status": "success", "details": result}
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


@router.get("/api/system/processes")
async def get_system_processes():
    """Diagnostic overview of background workers, threads, PIDs, and stream hibernation states."""
    lm = get_lifecycle_manager()
    return lm.get_diagnostics()


@router.get("/api/system/capabilities")
async def get_system_capabilities():
    """Expose available detectors, trackers, Re-ID extractors, target classes, and presets."""
    from intelligent_tracker.detectors import DetectorFactory
    from intelligent_tracker.detectors.coco_classes import COCO_CLASSES
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

    primary_detectors = [
        d for d in ["yolov8", "yolo11", "haar", "face_yunet", "movementdetector", "color", "mock"]
        if d in detectors
    ]
    if not primary_detectors:
        primary_detectors = detectors[:6]

    return {
        "detectors": detectors,
        "primary_detectors": primary_detectors,
        "trackers": trackers,
        "reid_extractors": reid_extractors,
        "coco_classes": COCO_CLASSES,
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
    camera_id: str, reason: Optional[str] = Query("Admin eviction")
):
    """Forcibly evict all active subscriber leases for a camera, putting it immediately into hibernation."""
    lm = get_lifecycle_manager()
    res = lm.evict_subscribers(camera_id, reason=reason)
    if not res.get("success"):
        raise HTTPException(
            status_code=404, detail=res.get("error", "Failed to evict stream")
        )
    return res


@router.post("/api/system/hibernate_all")
async def hibernate_all_idle():
    """Audit all streams and force-hibernate any channel with zero active viewers."""
    lm = get_lifecycle_manager()
    return lm.hibernate_all_idle()


@router.get("/api/system/metrics")
async def get_system_metrics_history(limit: int = Query(100, ge=1, le=1000)):
    """Retrieve historical time-series resource usage (CPU, RAM, stream count) for charting."""
    lm = get_lifecycle_manager()
    return lm.get_metrics_history(limit=limit)


@router.get("/api/system/events")
async def get_system_lifecycle_events(
    camera_id: Optional[str] = None, limit: int = Query(50, ge=1, le=500)
):
    """Retrieve historical stream lifecycle audit trail (START, HIBERNATE, RESUME, EVICT)."""
    lm = get_lifecycle_manager()
    return lm.get_lifecycle_history(camera_id=camera_id, limit=limit)

