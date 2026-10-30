"""
Intelligent Tracker Dashboard - Analytics, Sightings, Entities & Heatmaps Router.

Handles spatial occupancy heatmaps, persistent gallery entity CRUD,
sighting timeline queries, click-to-tag bounding box enrollment, and crop thumbnails.
"""

from __future__ import annotations

import os
import io
import logging
from typing import Optional

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse, FileResponse

import dashboard.dependencies as deps
from dashboard.schemas import EntityCreateRequest, TagRequest

logger = logging.getLogger("intelligent_tracker.dashboard.analytics")

router = APIRouter(tags=["Analytics"])

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DIR = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(PROJECT_DIR, "data")
CROPS_DIR = os.path.join(DATA_DIR, "crops")
os.makedirs(CROPS_DIR, exist_ok=True)


@router.get("/analytics/heatmap")
async def get_heatmap(camera_id: Optional[str] = None, format: str = Query("image", description="'image' or 'json'")):
    """Retrieve the accumulated spatial occupancy density heatmap."""
    mgr = deps.get_active_stream_manager(camera_id)
    if not mgr:
        raise HTTPException(status_code=503, detail="Stream manager not initialized")

    if format == "json":
        if not mgr.analytics or not mgr.analytics.heatmap:
            return {"density": []}
        return {
            "resolution": [mgr.analytics.heatmap.width, mgr.analytics.heatmap.height],
            "max_value": float(np.max(mgr.analytics.heatmap.density)),
            "mean_value": float(np.mean(mgr.analytics.heatmap.density)),
        }

    jpeg_bytes = mgr.get_heatmap_jpeg()
    return StreamingResponse(io.BytesIO(jpeg_bytes), media_type="image/jpeg")


@router.post("/analytics/heatmap/toggle")
async def toggle_heatmap(camera_id: Optional[str] = None, enabled: Optional[bool] = None):
    """Toggle live heatmap blending overlay on the camera feed."""
    mgr = deps.get_active_stream_manager(camera_id)
    if not mgr:
        raise HTTPException(status_code=503, detail="Stream manager not initialized")
    res = mgr.toggle_heatmap(enabled)
    return {"draw_heatmap": res}


@router.get("/entities")
async def list_entities(category: Optional[str] = None):
    """List enrolled gallery identities with appearance counters and sample thumbnails."""
    mgr = deps.get_active_stream_manager()
    if not mgr or not mgr.db:
        return []

    entities = mgr.db.list_entities(category=category)
    result = []
    for ent in entities:
        ent_dict = dict(ent)
        ent_id = ent_dict["id"]
        sightings = mgr.db.query_sightings(entity_id=ent_id, limit=1)
        sigs = mgr.db.get_signatures(entity_id=ent_id)

        with mgr.db._lock:
            cur = mgr.db._conn.cursor()
            try:
                cur.execute("SELECT COUNT(*) FROM sightings WHERE entity_id = ?", (ent_id,))
                count = cur.fetchone()[0]
            finally:
                cur.close()

        ent_dict["appearance_count"] = count
        ent_dict["signature_count"] = len(sigs)
        ent_dict["thumbnail_url"] = f"/crops/{os.path.basename(sigs[0]['crop_path'])}" if sigs and sigs[0].get("crop_path") else None
        ent_dict["last_seen"] = sightings[0]["timestamp"] if sightings else ent_dict["created_at"]
        result.append(ent_dict)

    return result


@router.post("/entities")
async def create_entity(req: EntityCreateRequest):
    """Enroll a new identity into the persistent Re-ID gallery database."""
    mgr = deps.get_active_stream_manager()
    if not mgr or not mgr.db:
        raise HTTPException(status_code=503, detail="Database unavailable")

    existing = mgr.db.get_entity_by_name(req.name)
    if existing:
        raise HTTPException(status_code=409, detail=f"Entity with name '{req.name}' already exists (ID #{existing['id']})")

    entity_id = mgr.db.add_entity(name=req.name, category=req.category, notes=req.notes)
    return {"id": entity_id, "name": req.name, "category": req.category, "status": "active"}


@router.get("/entities/{entity_id}")
async def get_entity_details(entity_id: int):
    """Get single enrolled entity details with signatures and recent sightings."""
    mgr = deps.get_active_stream_manager()
    if not mgr or not mgr.db:
        raise HTTPException(status_code=503, detail="Database unavailable")

    ent = mgr.db.get_entity(entity_id)
    if not ent:
        raise HTTPException(status_code=404, detail="Entity not found")

    sigs = mgr.db.get_signatures(entity_id)
    sightings = mgr.db.query_sightings(entity_id=entity_id, limit=20)

    res = dict(ent)
    res["signatures"] = [dict(s) for s in sigs]
    res["recent_sightings"] = [dict(s) for s in sightings]
    return res


@router.delete("/entities/{entity_id}")
async def delete_entity(entity_id: int):
    """Remove entity and its signatures from the gallery."""
    mgr = deps.get_active_stream_manager()
    if not mgr or not mgr.db:
        raise HTTPException(status_code=503, detail="Database unavailable")

    success = mgr.db.delete_entity(entity_id)
    if not success:
        raise HTTPException(status_code=404, detail="Entity not found")

    if mgr.gallery_matcher:
        mgr.gallery_matcher.refresh_gallery()

    return {"deleted": True, "entity_id": entity_id}


@router.get("/sightings")
async def query_sightings(
    entity_id: Optional[int] = None,
    entity_name: Optional[str] = None,
    zone_id: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = 50,
):
    """Search historical sighting timeline records with entity, zone, and time filters."""
    mgr = deps.get_active_stream_manager()
    if not mgr or not mgr.db:
        return []

    if entity_name and not entity_id:
        ent = mgr.db.get_entity_by_name(entity_name)
        if ent:
            entity_id = ent["id"]
        else:
            return []

    sightings = mgr.db.query_sightings(
        entity_id=entity_id,
        zone_id=zone_id,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )

    enriched = []
    for s in sightings:
        s_dict = dict(s)
        if s_dict.get("entity_id"):
            ent = mgr.db.get_entity(s_dict["entity_id"])
            s_dict["entity_name"] = ent["name"] if ent else "Unknown"
            s_dict["entity_category"] = ent["category"] if ent else "unknown"
        else:
            s_dict["entity_name"] = f"Track #{s_dict.get('track_id', 0)}"
            s_dict["entity_category"] = "unidentified"

        if s_dict.get("snapshot_path"):
            s_dict["snapshot_url"] = f"/crops/{os.path.basename(s_dict['snapshot_path'])}"
        enriched.append(s_dict)

    return enriched


@router.get("/events")
async def list_recent_events(limit: int = 50):
    """Get recent security and tracking alerts from EventBus ring buffer."""
    mgr = deps.get_active_stream_manager()
    if not mgr or not mgr.event_bus:
        return []

    events = mgr.event_bus.get_recent_events(limit=limit)
    out = []
    for ev in events:
        if hasattr(ev, "to_dict"):
            out.append(ev.to_dict())
        elif hasattr(ev, "__dataclass_fields__"):
            from dataclasses import asdict
            out.append(asdict(ev))
        else:
            out.append({"event_type": getattr(ev, "event_type", "event")})
    return out


@router.post("/tag")
async def tag_bounding_box(req: TagRequest):
    """
    Interactive click-to-tag bounding box capability:
    Tags an active track or bounding box from browser, generates visual embedding,
    and enrolls into the Re-ID gallery database.
    """
    mgr = deps.get_active_stream_manager(req.camera_id)
    if not mgr:
        raise HTTPException(status_code=503, detail="Stream manager not initialized")

    try:
        result = mgr.tag_entity(
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


@router.get("/crops/{filename}")
async def serve_crop_image(filename: str):
    """Serve crop thumbnail images."""
    file_path = os.path.join(CROPS_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="Crop image not found")

