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
from dashboard.services.analytics_query_service import build_heatmap_json, resolve_bucket_sec
from intelligent_tracker.database import TrackerDB

logger = logging.getLogger("intelligent_tracker.dashboard.routers.analytics")

router = APIRouter(tags=["Analytics & Timeline"])


@router.get("/analytics/flows")
async def get_traffic_flows(
    camera_id: Optional[str] = None,
    range_sec: int = Query(3600, ge=60, le=30 * 86400),
    end_time: Optional[float] = None,
    bucket_sec: Optional[int] = Query(None, ge=1, le=86400),
    db: TrackerDB = Depends(get_db),
):
    """Aggregate time-bucketed tripwire/zone traffic flows and sightings."""
    is_live = end_time is None
    resolved_end = float(end_time) if end_time is not None else time.time()
    resolved_bucket = resolve_bucket_sec(range_sec, bucket_sec)
    start_time = resolved_end - float(range_sec)
    if db is None:
        return {
            "camera_id": camera_id or None, "start_time": start_time, "end_time": resolved_end,
            "bucket_sec": resolved_bucket, "buckets": [],
            "totals": {"inflow": 0, "outflow": 0, "total": 0, "sightings": 0}, "is_live": is_live,
        }
    res = await asyncio.to_thread(
        db.get_traffic_flows, start_time, resolved_end, resolved_bucket, camera_id
    )
    res["is_live"] = is_live
    return res


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


def _create_entity_sync(db, req: EntityCreateRequest) -> dict:
    """Create a new entity if not already enrolled."""
    existing = db.get_entity_by_name(req.name)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Entity with name '{req.name}' already exists (ID #{existing['id']})",
        )
    entity_id = db.add_entity(name=req.name, category=req.category, notes=req.notes)
    return {"id": entity_id, "name": req.name, "category": req.category, "status": "active"}


@router.post("/entities")
async def create_entity(
    req: EntityCreateRequest,
    db: TrackerDB = Depends(get_db),
):
    """Enroll a new identity into the persistent Re-ID gallery database."""
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return await asyncio.to_thread(_create_entity_sync, db, req)


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


def _enrich_sighting(s: dict, db) -> dict:
    """Enrich sighting with entity details and thumbnail URL (with entity avatar fallback)."""
    s_dict = dict(s)
    ent_id = s_dict.get("entity_id")
    if ent_id:
        ent = db.get_entity(ent_id)
        s_dict["entity_name"] = ent["name"] if ent else "Unknown"
        s_dict["entity_category"] = ent["category"] if ent else "unknown"
    else:
        s_dict["entity_name"] = f"Track #{s_dict.get('track_id', 0)}"
        s_dict["entity_category"] = "unidentified"

    if s_dict.get("snapshot_path"):
        s_dict["snapshot_url"] = f"/crops/{os.path.basename(s_dict['snapshot_path'])}"
    elif ent_id and hasattr(db, "get_signatures"):
        sigs = db.get_signatures(entity_id=ent_id)
        for sig in sigs:
            cp = str(sig.get("crop_path") or "").strip()
            if cp:
                s_dict["snapshot_url"] = f"/crops/{os.path.basename(cp)}"
                break
    return s_dict


def _fetch_sightings_sync(
    db,
    entity_id: Optional[int],
    entity_name: Optional[str],
    zone_id: Optional[str],
    start_time: Optional[str],
    end_time: Optional[str],
    limit: int,
) -> list[dict]:
    """Resolve optional entity name filter and enrich matching sightings."""
    if entity_name and not entity_id:
        ent = db.get_entity_by_name(entity_name)
        if not ent:
            return []
        entity_id = ent["id"]
    sightings = db.query_sightings(
        entity_id=entity_id,
        zone_id=zone_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )
    return [_enrich_sighting(s, db) for s in sightings]


@router.get("/sightings")
async def query_sightings(
    entity_id: Optional[int] = None,
    entity_name: Optional[str] = None,
    zone_id: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = 50,
    db: TrackerDB = Depends(get_db),
):
    """Search historical sighting timeline records with entity, zone, and time filters."""
    if db is None:
        return []
    return await asyncio.to_thread(
        _fetch_sightings_sync,
        db,
        entity_id,
        entity_name,
        zone_id,
        start_time,
        end_time,
        limit,
    )


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

    try:
        result = await asyncio.to_thread(
            mgr.tag_entity,
            entity_name=req.entity_name,
            category=req.category,
            track_id=req.track_id,
            bbox=req.bbox,
            notes=req.notes or "",
        )
        return {"status": "success", "data": result}
    except Exception as e:
        logger.error("Tagging failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
