#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Review Queue, Bidirectional Video Studio Sync & Reversible Audit Router.

Exposes ``/api/review/*`` endpoints with reversible ``review_decisions``
audit trails and bidirectional synchronization to ``video_runs``.
"""

import asyncio
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from dashboard.dependencies import (
    get_active_learning_mgr,
    get_camera_pool,
    get_db,
    reload_all_galleries,
)
from dashboard.schemas import (
    ReviewConfirmRequest,
    ReviewDismissRequest,
    ReviewEnrollNewRequest,
    ReviewReassignRequest,
)
from dashboard.schemas_review import ReviewUndoRequest
from dashboard.services.category_service import ensure_known_category, resolve_rsac_for_request
from dashboard.services.reversible_review_service import (
    execute_review_action_with_audit,
    undo_review_decision,
)
from intelligent_tracker.active_learning import ActiveLearningManager
from intelligent_tracker.database import TrackerDB

router = APIRouter(tags=["Review Queue & Sync"])


def _handle_review_result(res: dict[str, Any], target_id: int) -> None:
    """Raise standard HTTP errors for not_found, already_undone, or failed actions."""
    status = res.get("status")
    if status == "not_found":
        raise HTTPException(status_code=404, detail=f"Review target {target_id} not found")
    if status == "already_undone":
        raise HTTPException(status_code=409, detail=f"Decision {target_id} was already undone")
    if status == "failed":
        raise HTTPException(status_code=400, detail="Review action failed (missing entity or invalid state)")


def _resolve_confidence_engine(al_mgr: Any, pool: Any) -> Any:
    """Resolve shared ConfidenceEngine from ActiveLearningManager or CameraPool."""
    return getattr(al_mgr, "confidence_engine", None) or getattr(pool, "confidence_engine", None)


@router.get("/api/review/queue")
async def list_review_queue(
    status: str = Query("pending"),
    limit: int = Query(50, ge=1, le=200),
    db: TrackerDB = Depends(get_db),
) -> dict[str, Any]:
    """List active learning review items with bbox and source provenance."""
    items = await asyncio.to_thread(db.list_review_items, status=status, limit=limit)
    return {"status": "success", "count": len(items), "items": items}


@router.get("/api/review/decisions")
async def list_review_decisions(
    review_id: int | None = Query(default=None),
    include_undone: bool = Query(default=True),
    limit: int = Query(50, ge=1, le=200),
    db: TrackerDB = Depends(get_db),
) -> dict[str, Any]:
    """List audited active learning review decisions."""
    items = await asyncio.to_thread(
        db.list_review_decisions, review_id=review_id, include_undone=include_undone, limit=limit,
    )
    return {"status": "success", "count": len(items), "decisions": items}


@router.post("/api/review/decisions/{decision_id}/undo")
async def undo_review_decision_endpoint(
    decision_id: int,
    request: Request,
    req: ReviewUndoRequest | None = Body(default=None),
    al_mgr: ActiveLearningManager = Depends(get_active_learning_mgr),
    db: TrackerDB = Depends(get_db),
) -> dict[str, Any]:
    """Undo a specific ``review_decisions`` record by ID."""
    pool = get_camera_pool(request)
    res = await asyncio.to_thread(
        undo_review_decision, db, decision_id=decision_id,
        confidence_engine=_resolve_confidence_engine(al_mgr, pool),
        pool=pool, request=request, reload_galleries=reload_all_galleries,
        undone_by=(req.reviewer if req else "operator"),
    )
    _handle_review_result(res, decision_id)
    return res


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
    """Confirm a review item, record audit decision, reload galleries, and sync runs."""
    res = await asyncio.to_thread(
        execute_review_action_with_audit, db, al_mgr, action="confirm", item_id=item_id,
        request=request, reload_galleries=reload_all_galleries, pool=get_camera_pool(request),
        notes=(req.notes if req else None) or "",
    )
    _handle_review_result(res, item_id)
    return res


@router.post("/api/review/{item_id}/reassign")
async def reassign_review_item(
    item_id: int,
    req: ReviewReassignRequest,
    request: Request,
    al_mgr: ActiveLearningManager = Depends(get_active_learning_mgr),
    db: TrackerDB = Depends(get_db),
) -> dict[str, Any]:
    """Reassign a review item to another entity and sync matching ``video_runs``."""
    res = await asyncio.to_thread(
        execute_review_action_with_audit, db, al_mgr, action="reassign", item_id=item_id,
        request=request, reload_galleries=reload_all_galleries, pool=get_camera_pool(request),
        target_entity_id=req.target_entity_id, notes=req.notes or "",
    )
    _handle_review_result(res, item_id)
    return res


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
    res = await asyncio.to_thread(
        execute_review_action_with_audit, db, al_mgr, action="enroll_new", item_id=item_id,
        request=request, reload_galleries=reload_all_galleries, pool=get_camera_pool(request),
        name=req.name, category=cat, security_role=req.security_role or "", notes=req.notes or "",
    )
    _handle_review_result(res, item_id)
    return res


@router.post("/api/review/{item_id}/dismiss")
async def dismiss_review_item(
    item_id: int,
    request: Request,
    req: ReviewDismissRequest | None = Body(default=None),
    al_mgr: ActiveLearningManager = Depends(get_active_learning_mgr),
    db: TrackerDB = Depends(get_db),
) -> dict[str, Any]:
    """Dismiss a review item, record audit decision, and return sync metadata."""
    res = await asyncio.to_thread(
        execute_review_action_with_audit, db, al_mgr, action="dismiss", item_id=item_id,
        request=request, reload_galleries=reload_all_galleries, pool=get_camera_pool(request),
        notes=(req.notes if req else None) or "",
    )
    _handle_review_result(res, item_id)
    return res


@router.post("/api/review/{item_id}/undo")
async def undo_review_item(
    item_id: int,
    request: Request,
    req: ReviewUndoRequest | None = Body(default=None),
    al_mgr: ActiveLearningManager = Depends(get_active_learning_mgr),
    db: TrackerDB = Depends(get_db),
) -> dict[str, Any]:
    """Undo the latest active decision for a review queue item."""
    pool = get_camera_pool(request)
    res = await asyncio.to_thread(
        undo_review_decision, db, review_id=item_id,
        confidence_engine=_resolve_confidence_engine(al_mgr, pool),
        pool=pool, request=request, reload_galleries=reload_all_galleries,
        undone_by=(req.reviewer if req else "operator"),
    )
    _handle_review_result(res, item_id)
    return res
