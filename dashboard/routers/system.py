"""
Intelligent Tracker Dashboard - System Lifecycle, Backups & Diagnostics Router.

Handles configuration backup export/import, background process diagnostics,
super-user stream subscriber eviction, idle stream hibernation, and time-series metrics.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse

import dashboard.dependencies as deps
from intelligent_tracker.backup import BackupManager

logger = logging.getLogger("intelligent_tracker.dashboard.system")

router = APIRouter(tags=["System & Lifecycle"])


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
        pool = deps.get_camera_pool()
        if pool:
            pool.load_cameras()

        return {"status": "success", "details": result}
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


@router.get("/api/system/processes")
async def get_system_processes():
    """Diagnostic overview of background workers, threads, PIDs, and stream hibernation states."""
    lm = deps.get_lifecycle_manager()
    return lm.get_diagnostics()


@router.post("/api/system/streams/{camera_id}/evict")
async def evict_stream_subscribers(camera_id: str, reason: Optional[str] = Query("Admin eviction")):
    """Forcibly evict all active subscriber leases for a camera, putting it immediately into hibernation."""
    lm = deps.get_lifecycle_manager()
    res = lm.evict_subscribers(camera_id, reason=reason)
    if not res.get("success"):
        raise HTTPException(status_code=404, detail=res.get("error", "Failed to evict stream"))
    return res


@router.post("/api/system/hibernate_all")
async def hibernate_all_idle():
    """Audit all streams and force-hibernate any channel with zero active viewers."""
    lm = deps.get_lifecycle_manager()
    return lm.hibernate_all_idle()


@router.get("/api/system/metrics")
async def get_system_metrics_history(limit: int = Query(100, ge=1, le=1000)):
    """Retrieve historical time-series resource usage (CPU, RAM, stream count) for charting."""
    lm = deps.get_lifecycle_manager()
    return lm.get_metrics_history(limit=limit)


@router.get("/api/system/events")
async def get_system_lifecycle_events(camera_id: Optional[str] = None, limit: int = Query(50, ge=1, le=500)):
    """Retrieve historical stream lifecycle audit trail (START, HIBERNATE, RESUME, EVICT)."""
    lm = deps.get_lifecycle_manager()
    return lm.get_lifecycle_history(camera_id=camera_id, limit=limit)

