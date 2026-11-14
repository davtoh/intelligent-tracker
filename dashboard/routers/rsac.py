#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Role-Based Spatial Access Control (RSAC) & Active Learning API Router.

Provides endpoints for Universal Entity Enrollment, Human-in-the-Loop Active
Learning Review Queue, RSAC custom categories and zone policies, pet alarm whitelisting,
and visual descriptor version history and rollbacks.
"""

import base64
import logging
import os
from typing import Optional

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from dashboard.dependencies import (
    get_active_learning_mgr,
    get_active_stream_manager,
    get_db,
    get_enrollment_mgr,
    get_rsac_mgr,
    reload_all_galleries,
)
from intelligent_tracker.active_learning import ActiveLearningManager
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.enrollment import UniversalEnrollmentManager
from intelligent_tracker.rsac import RSACManager
from dashboard.schemas import (
    CustomCategoryCreateRequest,
    EnrollmentRequest,
    PetWhitelistRequest,
    ReviewConfirmRequest,
    ReviewDismissRequest,
    ReviewEnrollNewRequest,
    ReviewReassignRequest,
    RollbackRequest,
    RSACRuleCreateRequest,
)

logger = logging.getLogger("intelligent_tracker.dashboard.routers.rsac")

router = APIRouter(tags=["RSAC & Active Learning"])


def _extract_crop_from_base64(data_str: str) -> np.ndarray:
    """Decode base64 image data into OpenCV BGR numpy array."""
    if "," in data_str:
        data_str = data_str.split(",", 1)[1]
    try:
        raw_bytes = base64.b64decode(data_str)
        arr = np.frombuffer(raw_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("cv2.imdecode returned None")
        return img
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to decode base64 crop: {e}")


def _extract_crop_from_frame(mgr, bbox: list[int]) -> np.ndarray:
    """Crop bounding box region from the stream manager's latest raw frame."""
    with mgr._lock:
        frame = mgr._latest_raw_frame.copy() if mgr._latest_raw_frame is not None else None
    if frame is None:
        raise HTTPException(status_code=503, detail="No active camera frame available for cropping")
    x, y, w, h = bbox
    fh, fw = frame.shape[:2]
    x1, y1 = max(0, int(x)), max(0, int(y))
    x2, y2 = min(fw, int(x + w)), min(fh, int(y + h))
    if x2 <= x1 or y2 <= y1:
        raise HTTPException(status_code=400, detail="Invalid bounding box coordinates")
    return frame[y1:y2, x1:x2]


@router.post("/api/enroll")
async def enroll_entity_route(
    req: EnrollmentRequest,
    request: Request,
    enrollment_mgr: UniversalEnrollmentManager = Depends(get_enrollment_mgr),
):
    """Universal Artifact & Face Enrollment from freeze-frame crop or base64 payload."""
    mgr = get_active_stream_manager(req.camera_id, conn=request)
    crop_img = None

    if req.crop_base64:
        crop_img = _extract_crop_from_base64(req.crop_base64)
    elif req.bbox:
        if not mgr:
            raise HTTPException(status_code=404, detail=f"Camera '{req.camera_id}' not found")
        crop_img = _extract_crop_from_frame(mgr, req.bbox)
    else:
        raise HTTPException(status_code=400, detail="Either bbox or crop_base64 must be provided")

    res = enrollment_mgr.enroll(
        name=req.name,
        category=req.category or "person",
        crop=crop_img,
        notes=req.notes or "",
        security_role=req.security_role or "",
        is_anchor=req.is_anchor if req.is_anchor is not None else True,
    )
    reload_all_galleries(conn=request)
    return res


@router.get("/api/active-learning/queue")
async def list_active_learning_queue(
    status: str = Query("pending", description="Filter by status: pending, confirmed, reassigned, dismissed, enrolled_new"),
    limit: int = Query(50, ge=1, le=200),
    db: TrackerDB = Depends(get_db),
):
    """Retrieve items from the Human-in-the-Loop Active Learning Review Queue."""
    items = db.list_review_items(status=status, limit=limit)
    return {"status": "success", "count": len(items), "items": items}


@router.get("/api/active-learning/{item_id}")
async def get_active_learning_item(
    item_id: int,
    db: TrackerDB = Depends(get_db),
):
    """Retrieve details for a single active learning review candidate."""
    item = db.get_review_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Review item {item_id} not found")
    return item


@router.post("/api/active-learning/{item_id}/confirm")
async def confirm_active_learning_item(
    item_id: int,
    request: Request,
    req: ReviewConfirmRequest = ReviewConfirmRequest(),
    al_mgr: ActiveLearningManager = Depends(get_active_learning_mgr),
):
    """Operator Confirm (Ground Truth): promote candidate crop as a Locked Anchor for the entity."""
    res = al_mgr.confirm_candidate(item_id=item_id, notes=req.notes)
    if res.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"Review item {item_id} not found")
    reload_all_galleries(conn=request)
    return res


@router.post("/api/active-learning/{item_id}/reassign")
async def reassign_active_learning_item(
    item_id: int,
    req: ReviewReassignRequest,
    request: Request,
    al_mgr: ActiveLearningManager = Depends(get_active_learning_mgr),
):
    """Operator Reassign: assign candidate crop as a Locked Anchor for a different entity."""
    res = al_mgr.reassign_candidate(item_id=item_id, target_entity_id=req.target_entity_id, notes=req.notes)
    if res.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"Review item {item_id} not found")
    reload_all_galleries(conn=request)
    return res


@router.post("/api/active-learning/{item_id}/enroll-new")
async def enroll_new_from_active_learning(
    item_id: int,
    req: ReviewEnrollNewRequest,
    request: Request,
    al_mgr: ActiveLearningManager = Depends(get_active_learning_mgr),
):
    """Operator Enroll New: register candidate crop as a newly created entity."""
    res = al_mgr.enroll_as_new(
        item_id=item_id,
        name=req.name,
        category=req.category or "person",
        security_role=req.security_role or "",
        notes=req.notes or "",
    )
    if res.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"Review item {item_id} not found")
    reload_all_galleries(conn=request)
    return res


@router.post("/api/active-learning/{item_id}/dismiss")
async def dismiss_active_learning_item(
    item_id: int,
    req: ReviewDismissRequest = ReviewDismissRequest(),
    al_mgr: ActiveLearningManager = Depends(get_active_learning_mgr),
):
    """Operator Dismiss: reject candidate crop without modifying Re-ID gallery."""
    res = al_mgr.dismiss_candidate(item_id=item_id, notes=req.notes)
    if res.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"Review item {item_id} not found")
    return res


@router.get("/api/rsac/categories")
async def list_custom_categories(rsac: RSACManager = Depends(get_rsac_mgr)):
    """List custom semantic categories and display badges."""
    return rsac.list_categories()


@router.post("/api/rsac/categories")
async def create_custom_category(
    req: CustomCategoryCreateRequest,
    request: Request,
    rsac: RSACManager = Depends(get_rsac_mgr),
):
    """Register or update custom category badge."""
    cat = rsac.register_category(
        cat_id=req.id,
        name=req.name,
        color=req.color or "#3B82F6",
        badge_icon=req.badge_icon or "",
        description=req.description or "",
    )
    reload_all_galleries(conn=request)
    return {"status": "success", "category": cat.to_dict()}


@router.delete("/api/rsac/categories/{category_id}")
async def delete_custom_category(
    category_id: str,
    request: Request,
    rsac: RSACManager = Depends(get_rsac_mgr),
):
    """Delete a custom category."""
    deleted = rsac.delete_category(category_id)
    reload_all_galleries(conn=request)
    return {"status": "success" if deleted else "not_found", "deleted": category_id}


@router.get("/api/rsac/rules")
async def list_rsac_rules(
    camera_id: Optional[str] = None,
    rsac: RSACManager = Depends(get_rsac_mgr),
):
    """List Role-Based Spatial Access Control zone rules."""
    return rsac.list_rules(camera_id=camera_id)


@router.post("/api/rsac/rules")
async def set_rsac_rule(
    req: RSACRuleCreateRequest,
    request: Request,
    rsac: RSACManager = Depends(get_rsac_mgr),
):
    """Create or update Role-Based Spatial Access Control rule for a camera zone."""
    rule = rsac.set_rule(
        camera_id=req.camera_id,
        zone_id=req.zone_id,
        allowed_categories=req.allowed_categories or [],
        denied_categories=req.denied_categories or [],
        schedules=req.schedules or [],
        entity_overrides=req.entity_overrides or {},
        alarm_on_breach=req.alarm_on_breach if req.alarm_on_breach is not None else True,
    )
    reload_all_galleries(conn=request)
    return {"status": "success", "rule": rule.to_dict()}


@router.delete("/api/rsac/rules")
async def delete_rsac_rule(
    request: Request,
    camera_id: str = Query(...),
    zone_id: str = Query(...),
    rsac: RSACManager = Depends(get_rsac_mgr),
):
    """Delete an RSAC zone rule."""
    deleted = rsac.delete_rule(camera_id, zone_id)
    reload_all_galleries(conn=request)
    return {"status": "success" if deleted else "not_found", "camera_id": camera_id, "zone_id": zone_id}


@router.get("/api/pets/whitelist")
async def get_pet_whitelist(rsac: RSACManager = Depends(get_rsac_mgr)):
    """List whitelisted pet labels and categories that suppress perimeter alarms."""
    return {"whitelist": rsac.get_pet_whitelist()}


@router.post("/api/pets/whitelist")
async def add_pet_whitelist(
    req: PetWhitelistRequest,
    request: Request,
    rsac: RSACManager = Depends(get_rsac_mgr),
):
    """Add label or category to pet alarm suppression whitelist."""
    rsac.add_pet_whitelist(req.label, notes=req.notes or "")
    reload_all_galleries(conn=request)
    return {"status": "success", "whitelist": rsac.get_pet_whitelist()}


@router.delete("/api/pets/whitelist/{label}")
async def remove_pet_whitelist(
    label: str,
    request: Request,
    rsac: RSACManager = Depends(get_rsac_mgr),
):
    """Remove label or category from pet alarm suppression whitelist."""
    rsac.remove_pet_whitelist(label)
    reload_all_galleries(conn=request)
    return {"status": "success", "whitelist": rsac.get_pet_whitelist()}


@router.get("/api/entities/{entity_id}/versions")
async def get_entity_versions(entity_id: int, db: TrackerDB = Depends(get_db)):
    """Retrieve complete descriptor version snapshot history for an entity."""
    ent = db.get_entity(entity_id)
    if not ent:
        raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found")
    versions = db.get_descriptor_versions(entity_id)
    serialized = []
    for v in versions:
        vd = dict(v)
        if "embedding" in vd and hasattr(vd["embedding"], "tolist"):
            vd["embedding"] = vd["embedding"].tolist()
        if "feature_vector" in vd:
            del vd["feature_vector"]
        vd["version"] = vd.get("version_num")
        if vd.get("crop_path"):
            vd["crop_url"] = f"/crops/{os.path.basename(vd['crop_path'])}"
        serialized.append(vd)
    return {"status": "success", "entity_id": entity_id, "entity_name": ent.get("name"), "versions": serialized}


@router.post("/api/entities/{entity_id}/rollback/{version}")
async def rollback_entity_descriptor(
    entity_id: int,
    version: int,
    request: Request,
    req: RollbackRequest = RollbackRequest(),
    db: TrackerDB = Depends(get_db),
):
    """Roll back entity visual descriptor to a prior verified snapshot version."""
    ok = db.rollback_descriptor(entity_id=entity_id, version=version)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Version {version} not found for entity {entity_id}")
    reload_all_galleries(conn=request)
    return {
        "status": "success",
        "entity_id": entity_id,
        "rolled_back_to_version": version,
        "notes": req.notes,
    }

