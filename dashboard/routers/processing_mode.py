#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Processing Mode & Deferred Indexing API Router.

Provides endpoints to inspect and switch global backend processing modes
(``focus_only``, ``full_realtime``, ``capture_only``, ``paused``), focused
camera selection, and active UI tab gating.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from dashboard.camera_pool import CameraPool
from dashboard.dependencies import get_camera_pool
from dashboard.schemas import ProcessingModeStatusResponse, ProcessingModeUpdateRequest
from dashboard.services.processing_mode_service import get_processing_mode_service

router = APIRouter(prefix="/api/system", tags=["System & Diagnostics"])


@router.get("/processing-mode", response_model=ProcessingModeStatusResponse)
async def get_processing_mode(
    pool: Optional[CameraPool] = Depends(get_camera_pool),
):
    """Return the active processing mode, focused camera, and per-camera states."""
    service = get_processing_mode_service()
    return service.get_state(pool=pool)


@router.post("/processing-mode", response_model=ProcessingModeStatusResponse)
async def update_processing_mode(
    req: ProcessingModeUpdateRequest,
    pool: Optional[CameraPool] = Depends(get_camera_pool),
):
    """Update the backend processing mode, focused camera, or active UI tab."""
    service = get_processing_mode_service()
    try:
        service.update(
            mode=req.mode,
            focused_camera_id=req.focused_camera_id,
            active_tab=req.active_tab,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    service.apply_to_pool(pool)
    return service.get_state(pool=pool)
