#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - World Intelligence, Confidence & Semantic Query Router.

Exposes REST endpoints backed by ``WorldQueryEngine``, ``ConfidenceEngine``,
and ``TrackerDB`` FTS5 timeline search.
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from dashboard.dependencies import get_db, get_world_query_engine
from dashboard.schemas import WorldQueryRequest
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.memory import ConfidenceEngine, WorldQueryEngine

router = APIRouter(prefix="/api/world", tags=["World Intelligence & Query"])


def _build_confidence_payload(
    entity_id: int,
    engine: WorldQueryEngine,
    db: TrackerDB,
    timestamp: Optional[float],
) -> dict[str, Any]:
    """Assemble calibrated confidence state and entity metadata or raise 404."""
    entity = db.get_entity(entity_id) if db is not None else None
    conf_engine = engine.confidence_engine or ConfidenceEngine(db=db)
    state = conf_engine.get_state(entity_id, timestamp=timestamp)
    if entity is None and state is None:
        raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found")
    payload: dict[str, Any] = state.to_dict() if state is not None else {
        "entity_id": entity_id,
        "confidence": 0.0,
        "face_score": 0.0,
        "body_score": 0.0,
        "streak_count": 0,
        "observation_count": 0,
        "confirmation_count": 0,
        "rejection_count": 0,
        "ambiguity_penalty": 0.0,
        "last_camera_id": "",
        "last_zone_id": "",
        "last_seen_at": 0.0,
        "evidence": {},
    }
    payload["has_confidence_state"] = state is not None
    if entity is not None:
        payload["entity_name"] = entity.get("name", "")
        payload["category"] = entity.get("category", "")
    return payload


@router.post("/query")
async def query_world(
    req: WorldQueryRequest,
    engine: WorldQueryEngine = Depends(get_world_query_engine),
) -> dict[str, Any]:
    """Answer a natural-language or structured query over FTS5, confidence, and WorldGraph."""
    clean_query = req.query.strip()
    if not clean_query:
        raise HTTPException(status_code=400, detail="Query string must not be empty")
    result = engine.ask(
        clean_query,
        entity_id=req.entity_id,
        camera_id=req.camera_id,
        zone_id=req.zone_id,
        event_type=req.event_type,
        start_time=req.start_time,
        end_time=req.end_time,
        limit=req.limit,
        include_world_snapshot=req.include_world_snapshot,
    )
    return result.to_dict()


@router.get("/confidence/{entity_id}")
async def get_entity_confidence(
    entity_id: int,
    timestamp: Optional[float] = Query(None, description="Optional UNIX timestamp for decay evaluation"),
    engine: WorldQueryEngine = Depends(get_world_query_engine),
    db: TrackerDB = Depends(get_db),
) -> dict[str, Any]:
    """Return calibrated long-term confidence state for a tracked entity."""
    return _build_confidence_payload(entity_id, engine, db, timestamp)


@router.get("/timeline")
async def search_world_timeline(
    q: str = Query("", description="Full-text search query"),
    query: Optional[str] = Query(None, description="Alias for q"),
    entity_id: Optional[int] = None,
    camera_id: Optional[str] = None,
    zone_id: Optional[str] = None,
    event_type: Optional[str] = None,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    limit: int = Query(25, ge=1, le=200),
    require_all: bool = False,
    db: TrackerDB = Depends(get_db),
) -> dict[str, Any]:
    """Search FTS5 semantic timeline events with optional structured filters."""
    search_text = (q or query or "").strip()
    events = db.search_timeline_events(
        query=search_text,
        entity_id=entity_id,
        camera_id=camera_id,
        zone_id=zone_id,
        event_type=event_type,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        require_all=require_all,
    )
    return {"query": search_text, "count": len(events), "events": events}

