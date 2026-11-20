#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Interactive ROI Tagging & Recognition Router.

Exposes on-demand ROI recognition (`POST /api/tag/recognize-roi`) and
tag commitment (`POST /api/tag/commit`) for both live streams and recorded
Video Studio playback.
"""

import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from dashboard.dependencies import (
    CROPS_DIR,
    VIDEOS_DIR,
    get_active_stream_manager,
    get_camera_pool,
    get_db,
    reload_all_galleries,
)
from dashboard.services.roi_recognition_service import (
    RoiNotFoundError,
    RoiRecognitionService,
    RoiUnavailableError,
)

router = APIRouter(tags=["tagging"])


class RoiRecognizeRequest(BaseModel):
    """Request payload for on-demand ROI classification and Re-ID matching."""

    camera_id: str | None = None
    video_filename: str | None = None
    timestamp_sec: float | None = None
    bbox: list[int] | None = None
    crop_base64: str | None = None
    top_k: int = Field(3, ge=1, le=20)


class TagCommitRequest(BaseModel):
    """Request payload for committing a tagged ROI to the entity gallery."""

    entity_name: str = Field(..., min_length=1)
    category: str = Field("person")
    entity_id: int | None = None
    camera_id: str | None = None
    video_filename: str | None = None
    timestamp_sec: float | None = None
    bbox: list[int] | None = None
    crop_base64: str | None = None
    notes: str = Field("")
    track_id: int | None = None


def _build_service(request: Request, camera_id: str | None) -> RoiRecognitionService:
    """Construct RoiRecognitionService bound to request app state."""
    db = get_db(conn=request)
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    pool = get_camera_pool(conn=request)
    mgr = get_active_stream_manager(camera_id, conn=request) if camera_id else None
    return RoiRecognitionService(
        db=db,
        stream_manager=mgr,
        camera_pool=pool,
        videos_dir=VIDEOS_DIR,
        crops_dir=CROPS_DIR,
    )


@router.post("/api/tag/recognize-roi")
async def recognize_roi_endpoint(req: RoiRecognizeRequest, request: Request):
    """Classify an ROI crop and return top-K Re-ID gallery candidates."""
    svc = _build_service(request, req.camera_id)
    try:
        data = await asyncio.to_thread(
            svc.recognize_roi,
            camera_id=req.camera_id,
            video_filename=req.video_filename,
            timestamp_sec=req.timestamp_sec,
            bbox=req.bbox,
            crop_base64=req.crop_base64,
            top_k=req.top_k,
        )
        return {"status": "success", "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RoiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RoiUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/api/tag/commit")
async def commit_roi_tag_endpoint(req: TagCommitRequest, request: Request):
    """Commit an ROI tag, persist crop/signature/sighting, and reload galleries."""
    svc = _build_service(request, req.camera_id)
    try:
        data = await asyncio.to_thread(
            svc.commit_roi_tag,
            entity_name=req.entity_name,
            category=req.category,
            entity_id=req.entity_id,
            camera_id=req.camera_id,
            video_filename=req.video_filename,
            timestamp_sec=req.timestamp_sec,
            bbox=req.bbox,
            crop_base64=req.crop_base64,
            notes=req.notes,
            track_id=req.track_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RoiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RoiUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    await asyncio.to_thread(reload_all_galleries, conn=request)
    return {"status": "success", "data": data}
