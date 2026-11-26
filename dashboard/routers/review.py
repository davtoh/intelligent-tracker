#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Review Queue & Bidirectional Video Studio Sync Router.

Exposes ``/api/review/*`` endpoints with bidirectional synchronization to
``video_runs`` without exceeding the line budget on ``dashboard/routers/rsac.py``.
"""

import asyncio
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from dashboard.dependencies import (
    get_active_learning_mgr,
    get_db,
    reload_all_galleries,
)
from dashboard.schemas import (
    ReviewConfirmRequest,
    ReviewDismissRequest,
    ReviewEnrollNewRequest,
    ReviewReassignRequest,
)
from dashboard.services.category_service import ensure_known_category, resolve_rsac_for_request
from dashboard.services.review_sync_service import sync_review_resolution_to_video_runs
from intelligent_tracker.active_learning import ActiveLearningManager
from intelligent_tracker.database import TrackerDB

router = APIRouter(tags=["Review Queue & Sync"])


def _handle_review_result(res: dict[str, Any], item_id: int) -> None:
    """Raise standard HTTP errors for not_found or failed review actions."""
    if res.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"Review item {item_id} not found")
    if res.get("status") == "failed":
        raise HTTPException(status_code=400, detail="Review action failed (missing entity or invalid state)")


@router.get("/api/review/queue")
async def list_review_queue(
    status: str = Query("pending"),
    limit: int = Query(50, ge=1, le=200),
    db: TrackerDB = Depends(get_db),
) -> dict[str, Any]:
    """List active learning review items with bbox and source provenance."""
    items = await asyncio.to_thread(db.list_review_items, status=status, limit=limit)
    return {"status": "success", "count": len(items), "items": items}


@router.get("/api/review/{item_id}")
async def get_review_item_detail(
    item_id: int,
    db: TrackerDB = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve a single review queue item."""
    item = await asyncio.to_thread(db.get_review_item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Review item {item_id} not found")
    return item


@router.post("/api/review/{item_id}/confirm")
async def confirm_review_item(
    item_id: int,
    request: Request,
    req: ReviewConfirmRequest | None = Body(default=None),
    al_mgr: ActiveLearningManager = Depends(get_active_learning_mgr),
    db: TrackerDB = Depends(get_db),
) -> dict[str, Any]:
    """Confirm a review item, reload galleries, and sync matching ``video_runs``."""
    item = await asyncio.to_thread(db.get_review_item, item_id)
    notes = (req.notes if req else None) or ""
    res = await asyncio.to_thread(al_mgr.confirm_candidate, item_id=item_id, notes=notes)
    _handle_review_result(res, item_id)
    await asyncio.to_thread(reload_all_galleries, conn=request)
    sync_meta = await asyncio.to_thread(
        sync_review_resolution_to_video_runs,
        db,
        item=item,
        action="confirm",
        entity_id=res.get("entity_id"),
    )
    return {**res, "sync": sync_meta}


@router.post("/api/review/{item_id}/reassign")
async def reassign_review_item(
    item_id: int,
    req: ReviewReassignRequest,
    request: Request,
    al_mgr: ActiveLearningManager = Depends(get_active_learning_mgr),
    db: TrackerDB = Depends(get_db),
) -> dict[str, Any]:
    """Reassign a review item to another entity and sync matching ``video_runs``."""
    item = await asyncio.to_thread(db.get_review_item, item_id)
    res = await asyncio.to_thread(
        al_mgr.reassign_candidate,
        item_id=item_id,
        target_entity_id=req.target_entity_id,
        notes=req.notes or "",
    )
    _handle_review_result(res, item_id)
    await asyncio.to_thread(reload_all_galleries, conn=request)
    sync_meta = await asyncio.to_thread(
        sync_review_resolution_to_video_runs,
        db,
        item=item,
        action="reassign",
        entity_id=req.target_entity_id,
    )
    return {**res, "sync": sync_meta}


@router.post("/api/review/{item_id}/enroll-new")
async def enroll_new_review_item(
    item_id: int,
    req: ReviewEnrollNewRequest,
    request: Request,
    al_mgr: ActiveLearningManager = Depends(get_active_learning_mgr),
    db: TrackerDB = Depends(get_db),
) -> dict[str, Any]:
    """Enroll a review item as a new entity and sync matching ``video_runs``."""
    cat = await asyncio.to_thread(
        lambda: ensure_known_category(resolve_rsac_for_request(request, db=db), req.category)
    )
    item = await asyncio.to_thread(db.get_review_item, item_id)
    res = await asyncio.to_thread(
        al_mgr.enroll_as_new,
        item_id=item_id,
        name=req.name,
        category=cat,
        security_role=req.security_role or "",
        notes=req.notes or "",
    )
    _handle_review_result(res, item_id)
    await asyncio.to_thread(reload_all_galleries, conn=request)
    sync_meta = await asyncio.to_thread(
        sync_review_resolution_to_video_runs,
        db,
        item=item,
        action="enroll_new",
        entity_id=res.get("entity_id"),
        entity_name=req.name,
        category=cat,
    )
    return {**res, "sync": sync_meta}


@router.post("/api/review/{item_id}/dismiss")
async def dismiss_review_item(
    item_id: int,
    req: ReviewDismissRequest | None = Body(default=None),
    al_mgr: ActiveLearningManager = Depends(get_active_learning_mgr),
    db: TrackerDB = Depends(get_db),
) -> dict[str, Any]:
    """Dismiss a review item and return sync metadata."""
    item = await asyncio.to_thread(db.get_review_item, item_id)
    notes = (req.notes if req else None) or ""
    res = await asyncio.to_thread(al_mgr.dismiss_candidate, item_id=item_id, notes=notes)
    _handle_review_result(res, item_id)
    sync_meta = await asyncio.to_thread(
        sync_review_resolution_to_video_runs,
        db,
        item=item,
        action="dismiss",
    )
    return {**res, "sync": sync_meta}
