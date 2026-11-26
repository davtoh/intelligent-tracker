#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Analytics, Heatmap, Entities & Sighting Timeline API Router.

Provides endpoints for spatial density heatmaps, enrolled identity management,
Re-ID sightings search, EventBus notifications, click-to-tag enrollments, and crop thumbnails.
"""

import asyncio
import io
import logging
import os
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from dashboard.dependencies import get_active_stream_manager, get_camera_pool, get_db
from dashboard.schemas import EntityCreateRequest, TagRequest
from dashboard.services.alerts_query_service import query_merged_events
from dashboard.services.analytics_query_service import (
    build_heatmap_json,
    enrich_sighting,
    query_sightings_page,
    query_traffic_flows_service,
)
from dashboard.services.category_service import ensure_known_category, resolve_rsac_for_request
from intelligent_tracker.database import TrackerDB

logger = logging.getLogger("intelligent_tracker.dashboard.routers.analytics")

router = APIRouter(tags=["Analytics & Timeline"])


@router.get("/analytics/flows")
async def get_traffic_flows(
    camera_id: Optional[str] = None,
    zone_id: Optional[str] = None,
    event_type: Optional[str] = None,
    range_sec: int = Query(3600, ge=60, le=30 * 86400),
    end_time: Optional[float] = None,
    bucket_sec: Optional[int] = Query(None, ge=1, le=86400),
    page: Optional[int] = Query(None, ge=1),
    page_size: Optional[int] = Query(None, ge=1, le=500),
    db: TrackerDB = Depends(get_db),
):
    """Aggregate time-bucketed tripwire/zone traffic flows and sightings."""
    return await asyncio.to_thread(
        query_traffic_flows_service,
        db,
        camera_id=camera_id,
        zone_id=zone_id,
        event_type=event_type,
        range_sec=range_sec,
        end_time=end_time,
        bucket_sec=bucket_sec,
        page=page,
        page_size=page_size,
        now_ts=time.time(),
    )


@router.get("/analytics/heatmap")
async def get_heatmap(
    request: Request,
    camera_id: Optional[str] = None,
    format: str = Query("image", description="'image' or 'json'"),
):
    """Retrieve the accumulated spatial occupancy density heatmap."""
    mgr = get_active_stream_manager(camera_id, conn=request)
    if not mgr:
        raise HTTPException(status_code=503, detail="Stream manager not initialized")

    if format == "json":
        return build_heatmap_json(mgr, camera_id)

    jpeg_bytes = mgr.get_heatmap_jpeg()
    return StreamingResponse(io.BytesIO(jpeg_bytes), media_type="image/jpeg")


@router.post("/analytics/heatmap/toggle")
async def toggle_heatmap(
    request: Request,
    camera_id: Optional[str] = None,
    enabled: Optional[bool] = None,
):
    """Toggle live heatmap blending overlay on the camera feed."""
    mgr = get_active_stream_manager(camera_id, conn=request)
    if not mgr:
        raise HTTPException(status_code=503, detail="Stream manager not initialized")
    res = mgr.toggle_heatmap(enabled)
    return {"draw_heatmap": res}


def _fetch_entities_summary(db, category: Optional[str]) -> list[dict]:
    """Query entities with sighting counts and thumbnail metadata synchronously."""
    entities = db.list_entities(category=category)
    sighting_counts = db.query_sighting_counts([ent["id"] for ent in entities])
    result = []
    for ent in entities:
        ent_dict = dict(ent)
        ent_id = ent_dict["id"]
        sightings = db.query_sightings(entity_id=ent_id, limit=1)
        sigs = db.get_signatures(entity_id=ent_id)
        ent_dict["appearance_count"] = sighting_counts.get(ent_id, 0)
        ent_dict["signature_count"] = len(sigs)
        ent_dict["thumbnail_url"] = (
            f"/crops/{os.path.basename(sigs[0]['crop_path'])}"
            if sigs and sigs[0].get("crop_path")
            else None
        )
        ent_dict["last_seen"] = sightings[0]["timestamp"] if sightings else ent_dict["created_at"]
        result.append(ent_dict)
    return result


@router.get("/entities")
async def list_entities(
    category: Optional[str] = None,
    db: TrackerDB = Depends(get_db),
):
    """List enrolled gallery identities with appearance counters and sample thumbnails."""
    if db is None:
        return []
    return await asyncio.to_thread(_fetch_entities_summary, db, category)


def _create_entity_sync(db, req: EntityCreateRequest, request: Request) -> dict:
    """Create a new entity after validating its category against custom_categories."""
    rsac = resolve_rsac_for_request(request, db=db)
    cat = ensure_known_category(rsac, req.category)
    existing = db.get_entity_by_name(req.name)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Entity with name '{req.name}' already exists (ID #{existing['id']})",
        )
    entity_id = db.add_entity(name=req.name, category=cat, notes=req.notes)
    return {"id": entity_id, "name": req.name, "category": cat, "status": "active"}


@router.post("/entities")
async def create_entity(
    req: EntityCreateRequest,
    request: Request,
    db: TrackerDB = Depends(get_db),
):
    """Enroll a new identity into the persistent Re-ID gallery database."""
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return await asyncio.to_thread(_create_entity_sync, db, req, request)


def _fetch_entity_details(db, entity_id: int) -> dict:
    """Load entity metadata, signatures, and recent sightings synchronously."""
    ent = db.get_entity(entity_id)
    if not ent:
        raise HTTPException(status_code=404, detail="Entity not found")
    res = dict(ent)
    res["signatures"] = [dict(s) for s in db.get_signatures(entity_id)]
    res["recent_sightings"] = [dict(s) for s in db.query_sightings(entity_id=entity_id, limit=20)]
    return res


@router.get("/entities/{entity_id}")
async def get_entity_details(
    entity_id: int,
    db: TrackerDB = Depends(get_db),
):
    """Get single enrolled entity details with signatures and recent sightings."""
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return await asyncio.to_thread(_fetch_entity_details, db, entity_id)


def _delete_entity_sync(db, mgr, entity_id: int, pool=None) -> dict:
    """Delete entity from SQLite, scrub video_runs, and reload all pool galleries."""
    if not db.delete_entity(entity_id):
        raise HTTPException(status_code=404, detail="Entity not found")
    from dashboard.services.video_run_relabel_service import relabel_video_runs_on_entity_mutation

    relabel_video_runs_on_entity_mutation(db, pool=pool, deleted_entity_id=entity_id)
    if pool is not None:
        pool.reload_all_galleries()
    elif mgr and mgr.gallery_matcher:
        mgr.gallery_matcher.refresh_gallery()
    return {"deleted": True, "entity_id": entity_id}


@router.delete("/entities/{entity_id}")
async def delete_entity(
    entity_id: int,
    request: Request,
    db: TrackerDB = Depends(get_db),
):
    """Remove entity and its signatures from the gallery."""
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    mgr = get_active_stream_manager(conn=request)
    pool = get_camera_pool(conn=request)
    return await asyncio.to_thread(_delete_entity_sync, db, mgr, entity_id, pool)


_enrich_sighting = enrich_sighting


@router.get("/sightings")
async def query_sightings(
    entity_id: Optional[int] = None,
    entity_name: Optional[str] = None,
    source: Optional[str] = None,
    zone_id: Optional[str] = None,
    video_filename: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    paginated: bool = False,
    db: TrackerDB = Depends(get_db),
):
    """Search historical sighting timeline records with entity, source, zone, and pagination filters."""
    if db is None:
        if paginated or offset > 0:
            return {"items": [], "total": 0, "offset": offset, "limit": limit, "has_more": False}
        return []
    return await asyncio.to_thread(
        query_sightings_page,
        db,
        entity_id=entity_id,
        entity_name=entity_name,
        source=source,
        zone_id=zone_id,
        video_filename=video_filename,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
        paginated=paginated,
    )


@router.get("/sightings/sources")
async def list_sighting_sources(request: Request, db: TrackerDB = Depends(get_db)):
    """List distinct sighting sources merged with known cameras and videos."""
    from dashboard.dependencies import VIDEOS_DIR, get_camera_pool
    from dashboard.services.analytics_query_service import list_all_sighting_sources

    pool = get_camera_pool(conn=request)
    return await asyncio.to_thread(list_all_sighting_sources, db, pool=pool, videos_dir=VIDEOS_DIR)


@router.get("/events")
async def list_recent_events(
    request: Request,
    camera_id: Optional[str] = None,
    severity: Optional[str] = None,
    event_type: Optional[str] = None,
    zone_id: Optional[str] = None,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    paginated: bool = False,
    db: TrackerDB = Depends(get_db),
):
    """Get recent security and tracking alerts merged from EventBus and TrackerDB."""
    mgr = get_active_stream_manager(camera_id, conn=request) if camera_id else get_active_stream_manager(conn=request)
    return await asyncio.to_thread(
        query_merged_events,
        mgr,
        db,
        camera_id=camera_id,
        severity=severity,
        event_type=event_type,
        zone_id=zone_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
        paginated=paginated,
    )


@router.post("/tag")
async def tag_bounding_box(req: TagRequest, request: Request):
    """
    Interactive click-to-tag bounding box capability:
    Tags an active track or bounding box from browser, generates visual embedding,
    and enrolls into the Re-ID gallery database.
    """
    mgr = get_active_stream_manager(req.camera_id, conn=request)
    if not mgr:
        raise HTTPException(status_code=503, detail="Stream manager not initialized")

    cat = await asyncio.to_thread(
        lambda: ensure_known_category(resolve_rsac_for_request(request, camera_id=req.camera_id), req.category)
    )
    try:
        result = await asyncio.to_thread(
            mgr.tag_entity,
            entity_name=req.entity_name,
            category=cat,
            track_id=req.track_id,
            bbox=req.bbox,
            notes=req.notes or "",
        )
        return {"status": "success", "data": result}
    except Exception as e:
        logger.error("Tagging failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
