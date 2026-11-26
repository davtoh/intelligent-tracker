"""Dashboard API Router for Alert/Event Facets, Acknowledge, Clear & Export."""

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from dashboard.dependencies import get_camera_pool, get_db
from dashboard.services.events_admin_service import (
    acknowledge_events,
    clear_events,
    delete_event,
    format_events_csv,
    get_event_facets,
)
from intelligent_tracker.database import TrackerDB

router = APIRouter(tags=["Events Admin"])


class AcknowledgeEventsRequest(BaseModel):
    event_id: Optional[int] = None
    event_ids: Optional[list[int]] = None
    mark_all: bool = False
    is_read: bool = True


class ClearEventsRequest(BaseModel):
    camera_id: Optional[str] = None
    severity: Optional[str] = None
    event_type: Optional[str] = None
    zone_id: Optional[str] = None
    read_only: bool = False


@router.get("/api/events/facets")
async def get_events_facets_route(request: Request, db: TrackerDB = Depends(get_db)):
    """Return distinct filter facets for the #alerts tab."""
    pool = get_camera_pool(conn=request)
    return await asyncio.to_thread(get_event_facets, db, pool)


@router.patch("/api/events/acknowledge")
async def acknowledge_events_route(req: AcknowledgeEventsRequest, db: TrackerDB = Depends(get_db)):
    """Mark one, many, or all timeline events as read or unread."""
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    ids = req.event_ids if req.event_ids is not None else ([req.event_id] if req.event_id is not None else None)
    return await asyncio.to_thread(acknowledge_events, db, event_ids=ids, mark_all=req.mark_all, is_read=req.is_read)


@router.delete("/api/events/{event_id}")
async def delete_event_route(event_id: int, db: TrackerDB = Depends(get_db)):
    """Delete a single timeline event by ID."""
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    res = await asyncio.to_thread(delete_event, db, event_id)
    if res is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return res


@router.post("/api/events/clear")
async def clear_events_route(req: ClearEventsRequest, db: TrackerDB = Depends(get_db)):
    """Bulk-clear timeline events matching optional filters."""
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return await asyncio.to_thread(
        clear_events, db, camera_id=req.camera_id, severity=req.severity,
        event_type=req.event_type, zone_id=req.zone_id, read_only=req.read_only,
    )


@router.get("/api/events/export")
async def export_events_route(
    format: str = Query("json"),
    camera_id: Optional[str] = None,
    severity: Optional[str] = None,
    event_type: Optional[str] = None,
    zone_id: Optional[str] = None,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    limit: int = Query(1000, ge=1, le=10000),
    db: TrackerDB = Depends(get_db),
):
    """Export filtered timeline events as downloadable CSV or JSON."""
    fmt = format.strip().lower()
    if fmt not in ("json", "csv"):
        raise HTTPException(status_code=400, detail="Unsupported export format; expected 'json' or 'csv'")
    rows = (
        await asyncio.to_thread(
            db.export_timeline_events, camera_id=camera_id, severity=severity,
            event_type=event_type, zone_id=zone_id, start_time=start_time, end_time=end_time, limit=limit,
        )
        if db is not None
        else []
    )
    if fmt == "csv":
        return Response(
            content=format_events_csv(rows),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="events_export.csv"'},
        )
    return JSONResponse(
        content=rows,
        headers={"Content-Disposition": 'attachment; filename="events_export.json"'},
    )
