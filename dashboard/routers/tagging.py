#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Interactive ROI Tagging & Recognition Router.

Exposes on-demand ROI recognition (`POST /api/tag/recognize-roi`) and
tag commitment (`POST /api/tag/commit`) for both live streams and recorded
Video Studio playback.
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.params import Depends as DependsParam
from pydantic import BaseModel, Field

from dashboard.dependencies import (
    CROPS_DIR,
    VIDEOS_DIR,
    get_active_stream_manager,
    get_camera_pool,
    get_db,
    reload_all_galleries,
)
from dashboard.services.category_service import ensure_known_category, resolve_rsac_for_request
from dashboard.services.negative_exemplar_service import NegativeExemplarService
from dashboard.services.roi_recognition_service import (
    RoiNotFoundError,
    RoiRecognitionService,
    RoiUnavailableError,
)

router = APIRouter(tags=["tagging"])
_UNSET = object()


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


class TagDiscourageRequest(BaseModel):
    """Request payload for recording a negative or false-positive exemplar."""

    entity_id: int | None = None
    label: str = Field("")
    camera_id: str | None = None
    video_filename: str | None = None
    timestamp_sec: float | None = None
    bbox: list[int] | None = None
    crop_base64: str | None = None
    notes: str = Field("")
    track_id: int | None = None


def _build_service(
    request: Request,
    camera_id: str | None,
    db: object = _UNSET,
    pool: object = _UNSET,
) -> RoiRecognitionService:
    """Construct RoiRecognitionService bound to request app state or injected DI."""
    resolved_db = get_db(conn=request) if (db is _UNSET or isinstance(db, DependsParam)) else db
    if resolved_db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    resolved_pool = get_camera_pool(conn=request) if (pool is _UNSET or isinstance(pool, DependsParam)) else pool
    mgr = get_active_stream_manager(camera_id, conn=request) if camera_id else None
    app_state = getattr(getattr(request, "app", None), "state", None)
    ce = getattr(mgr, "confidence_engine", None) or getattr(resolved_pool, "confidence_engine", None) or getattr(app_state, "confidence_engine", None)
    fts = getattr(mgr, "event_fts_index", None) or getattr(resolved_pool, "event_fts_index", None) or getattr(app_state, "event_fts_index", None)
    return RoiRecognitionService(
        db=resolved_db,
        stream_manager=mgr,
        camera_pool=resolved_pool,
        videos_dir=VIDEOS_DIR,
        crops_dir=CROPS_DIR,
        confidence_engine=ce,
        fts_index=fts,
    )


@router.post("/api/tag/recognize-roi")
async def recognize_roi_endpoint(
    req: RoiRecognizeRequest,
    request: Request,
    db=Depends(get_db),
    pool=Depends(get_camera_pool),
):
    """Classify an ROI crop and return top-K Re-ID gallery candidates."""
    svc = _build_service(request, req.camera_id, db=db, pool=pool)
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


def _relabel_after_commit(svc: object, data: object, req: TagCommitRequest) -> None:
    """Relabel video_runs after ROI tag commit when DB and entity/track metadata exist."""
    db = getattr(svc, "db", None)
    if db is None:
        return
    from dashboard.services.video_run_relabel_service import relabel_video_runs_on_entity_mutation

    eid = data.get("entity_id") if isinstance(data, dict) else req.entity_id
    if eid is not None or (req.video_filename and req.track_id is not None):
        relabel_video_runs_on_entity_mutation(
            db,
            pool=getattr(svc, "camera_pool", None),
            updated_entity_id=int(eid) if eid is not None else None,
            video_filename=req.video_filename,
            track_id=req.track_id,
        )


def _validate_tag_category(
    request: Request, svc: object, camera_id: str | None, category: str | None
) -> str:
    """Validate ROI tag category against custom_categories."""
    svc_db = getattr(svc, "db", None)
    rsac = resolve_rsac_for_request(request, db=svc_db, camera_id=camera_id)
    return ensure_known_category(rsac, category)


@router.post("/api/tag/commit")
async def commit_roi_tag_endpoint(
    req: TagCommitRequest,
    request: Request,
    db=Depends(get_db),
    pool=Depends(get_camera_pool),
):
    """Commit an ROI tag, persist crop/signature/sighting, and reload galleries."""
    svc = _build_service(request, req.camera_id, db=db, pool=pool)
    cat = await asyncio.to_thread(_validate_tag_category, request, svc, req.camera_id, req.category)
    try:
        data = await asyncio.to_thread(
            svc.commit_roi_tag,
            entity_name=req.entity_name,
            category=cat,
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
    await asyncio.to_thread(_relabel_after_commit, svc, data, req)
    await asyncio.to_thread(reload_all_galleries, conn=request)
    return {"status": "success", "data": data}


def _build_negative_service(
    request: Request, camera_id: str | None, db: object = _UNSET, pool: object = _UNSET
) -> NegativeExemplarService:
    """Construct NegativeExemplarService bound to request app state or DI."""
    resolved_db = get_db(conn=request) if (db is _UNSET or isinstance(db, DependsParam)) else db
    if resolved_db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    resolved_pool = get_camera_pool(conn=request) if (pool is _UNSET or isinstance(pool, DependsParam)) else pool
    mgr = get_active_stream_manager(camera_id, conn=request) if camera_id else None
    app_state = getattr(getattr(request, "app", None), "state", None)
    ce = getattr(mgr, "confidence_engine", None) or getattr(resolved_pool, "confidence_engine", None) or getattr(app_state, "confidence_engine", None)
    return NegativeExemplarService(
        db=resolved_db, stream_manager=mgr, camera_pool=resolved_pool,
        videos_dir=VIDEOS_DIR, crops_dir=CROPS_DIR, confidence_engine=ce,
    )


@router.post("/api/tag/discourage")
async def discourage_roi_endpoint(
    req: TagDiscourageRequest, request: Request, db=Depends(get_db), pool=Depends(get_camera_pool)
):
    """Record a negative or false-positive exemplar and reload galleries."""
    svc = _build_negative_service(request, req.camera_id, db=db, pool=pool)
    try:
        data = await asyncio.to_thread(
            svc.discourage_roi, entity_id=req.entity_id, label=req.label, camera_id=req.camera_id,
            video_filename=req.video_filename, timestamp_sec=req.timestamp_sec, bbox=req.bbox,
            crop_base64=req.crop_base64, notes=req.notes, track_id=req.track_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RoiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RoiUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    from dashboard.services.video_run_relabel_service import relabel_video_runs_on_entity_mutation

    eid = data.get("entity_id") if isinstance(data, dict) else req.entity_id
    if eid is not None or (req.video_filename and req.track_id is not None):
        await asyncio.to_thread(
            relabel_video_runs_on_entity_mutation,
            svc.db,
            pool=svc.camera_pool,
            discouraged_entity_id=int(eid) if eid is not None else -1,
            video_filename=req.video_filename,
            track_id=req.track_id,
        )
    await asyncio.to_thread(reload_all_galleries, conn=request)
    return {"status": "success", "data": data}


@router.get("/api/tag/negatives")
async def list_negatives_endpoint(
    request: Request, entity_id: int | None = None, db=Depends(get_db), pool=Depends(get_camera_pool)
):
    """List persisted negative exemplars."""
    svc = _build_negative_service(request, None, db=db, pool=pool)
    items = await asyncio.to_thread(svc.list_negatives, entity_id=entity_id)
    return {"status": "success", "data": items}


@router.delete("/api/tag/negatives/{exemplar_id}")
async def delete_negative_endpoint(
    exemplar_id: int, request: Request, db=Depends(get_db), pool=Depends(get_camera_pool)
):
    """Delete a persisted negative exemplar and reload galleries."""
    svc = _build_negative_service(request, None, db=db, pool=pool)
    deleted = await asyncio.to_thread(svc.delete_negative, exemplar_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Negative exemplar {exemplar_id} not found")
    await asyncio.to_thread(reload_all_galleries, conn=request)
    return {"status": "success", "deleted": True}
