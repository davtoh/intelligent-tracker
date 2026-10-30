"""
Intelligent Tracker Dashboard - RSAC, Universal Enrollment & Active Learning Router.

Handles Role-Based Spatial Access Control (RSAC), Active Learning triage queue,
universal biometric enrollment, pet whitelist, and descriptor version rollbacks.
"""

from __future__ import annotations

import os
import base64
import logging
from typing import Optional

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Query

import dashboard.dependencies as deps
from dashboard.schemas import (
    EnrollmentRequest,
    ReviewConfirmRequest,
    ReviewReassignRequest,
    ReviewEnrollNewRequest,
    ReviewDismissRequest,
    CustomCategoryCreateRequest,
    RSACRuleCreateRequest,
    PetWhitelistRequest,
    RollbackRequest,
)

logger = logging.getLogger("intelligent_tracker.dashboard.rsac")

router = APIRouter(tags=["RSAC & Enrollment"])


@router.post("/api/enroll")
async def enroll_entity_route(req: EnrollmentRequest):
    """Universal Artifact & Face Enrollment from freeze-frame crop, base64 payload, or image."""
    mgr = deps.get_active_stream_manager(req.camera_id)
    crop_img = None

    if req.crop_base64:
        data_str = req.crop_base64
        if "," in data_str:
            data_str = data_str.split(",", 1)[1]
        try:
            raw_bytes = base64.b64decode(data_str)
            arr = np.frombuffer(raw_bytes, dtype=np.uint8)
            crop_img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to decode base64 crop: {e}")
        if crop_img is None:
            raise HTTPException(status_code=400, detail="Failed to decode provided crop_base64")
    elif req.bbox:
        if not mgr:
            raise HTTPException(status_code=404, detail=f"Camera '{req.camera_id}' not found")
        with mgr._lock:
            frame = mgr._latest_raw_frame.copy() if mgr._latest_raw_frame is not None else None
        if frame is None:
            raise HTTPException(status_code=503, detail="No active camera frame available for cropping")
        x, y, w, h = req.bbox
        fh, fw = frame.shape[:2]
        x1, y1 = max(0, int(x)), max(0, int(y))
        x2, y2 = min(fw, int(x + w)), min(fh, int(y + h))
        if x2 <= x1 or y2 <= y1:
            raise HTTPException(status_code=400, detail="Invalid bounding box coordinates")
        crop_img = frame[y1:y2, x1:x2]
    else:
        raise HTTPException(status_code=400, detail="Either bbox or crop_base64 must be provided")

    enrollment_mgr = deps.get_enrollment_mgr()
    res = enrollment_mgr.enroll(
        name=req.name,
        category=req.category or "person",
        crop=crop_img,
        notes=req.notes or "",
        security_role=req.security_role or "",
        is_anchor=req.is_anchor if req.is_anchor is not None else True,
    )
    deps.reload_all_galleries()
    return res


@router.get("/api/active-learning/queue")
async def list_active_learning_queue(
    status: str = Query("pending", description="Filter by status: pending, confirmed, reassigned, dismissed, enrolled_new"),
    limit: int = Query(50, ge=1, le=200),
):
    """Retrieve items from the Human-in-the-Loop Active Learning Review Queue."""
    db = deps.get_db()
    items = db.list_review_items(status=status, limit=limit)
    return {"status": "success", "count": len(items), "items": items}


@router.get("/api/active-learning/{item_id}")
async def get_active_learning_item(item_id: int):
    """Retrieve details for a single active learning review candidate."""
    db = deps.get_db()
    item = db.get_review_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Review item {item_id} not found")
    return item


@router.post("/api/active-learning/{item_id}/confirm")
async def confirm_active_learning_item(item_id: int, req: ReviewConfirmRequest = ReviewConfirmRequest()):
    """Operator Confirm (Ground Truth): promote candidate crop as a Locked Anchor for the entity."""
    al_mgr = deps.get_active_learning_mgr()
    res = al_mgr.confirm_candidate(item_id=item_id, notes=req.notes)
    if res.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"Review item {item_id} not found")
    deps.reload_all_galleries()
    return res


@router.post("/api/active-learning/{item_id}/reassign")
async def reassign_active_learning_item(item_id: int, req: ReviewReassignRequest):
    """Operator Reassign: assign candidate crop as a Locked Anchor for a different entity."""
    al_mgr = deps.get_active_learning_mgr()
    res = al_mgr.reassign_candidate(item_id=item_id, target_entity_id=req.target_entity_id, notes=req.notes)
    if res.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"Review item {item_id} not found")
    deps.reload_all_galleries()
    return res


@router.post("/api/active-learning/{item_id}/enroll-new")
async def enroll_new_from_active_learning(item_id: int, req: ReviewEnrollNewRequest):
    """Operator Enroll New: register candidate crop as a newly created entity."""
    al_mgr = deps.get_active_learning_mgr()
    res = al_mgr.enroll_as_new(
        item_id=item_id,
        name=req.name,
        category=req.category or "person",
        security_role=req.security_role or "",
        notes=req.notes or "",
    )
    if res.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"Review item {item_id} not found")
    deps.reload_all_galleries()
    return res


@router.post("/api/active-learning/{item_id}/dismiss")
async def dismiss_active_learning_item(item_id: int, req: ReviewDismissRequest = ReviewDismissRequest()):
    """Operator Dismiss: reject candidate crop without modifying Re-ID gallery."""
    al_mgr = deps.get_active_learning_mgr()
    res = al_mgr.dismiss_candidate(item_id=item_id, notes=req.notes)
    if res.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"Review item {item_id} not found")
    return res


@router.get("/api/rsac/categories")
async def list_custom_categories():
    """List custom semantic categories and display badges."""
    rsac = deps.get_rsac_mgr()
    return rsac.list_categories()


@router.post("/api/rsac/categories")
async def create_custom_category(req: CustomCategoryCreateRequest):
    """Register or update custom category badge."""
    rsac = deps.get_rsac_mgr()
    cat = rsac.register_category(
        cat_id=req.id,
        name=req.name,
        color=req.color or "#3B82F6",
        badge_icon=req.badge_icon or "",
        description=req.description or "",
    )
    deps.reload_all_galleries()
    return {"status": "success", "category": cat.to_dict()}


@router.delete("/api/rsac/categories/{category_id}")
async def delete_custom_category(category_id: str):
    """Delete a custom category."""
    rsac = deps.get_rsac_mgr()
    deleted = rsac.delete_category(category_id)
    deps.reload_all_galleries()
    return {"status": "success" if deleted else "not_found", "deleted": category_id}


@router.get("/api/rsac/rules")
async def list_rsac_rules(camera_id: Optional[str] = None):
    """List Role-Based Spatial Access Control zone rules."""
    rsac = deps.get_rsac_mgr()
    return rsac.list_rules(camera_id=camera_id)


@router.post("/api/rsac/rules")
async def set_rsac_rule(req: RSACRuleCreateRequest):
    """Create or update Role-Based Spatial Access Control rule for a camera zone."""
    rsac = deps.get_rsac_mgr()
    rule = rsac.set_rule(
        camera_id=req.camera_id,
        zone_id=req.zone_id,
        allowed_categories=req.allowed_categories or [],
        denied_categories=req.denied_categories or [],
        schedules=req.schedules or [],
        entity_overrides=req.entity_overrides or {},
        alarm_on_breach=req.alarm_on_breach if req.alarm_on_breach is not None else True,
    )
    deps.reload_all_galleries()
    return {"status": "success", "rule": rule.to_dict()}


@router.delete("/api/rsac/rules")
async def delete_rsac_rule(camera_id: str = Query(...), zone_id: str = Query(...)):
    """Delete an RSAC zone rule."""
    rsac = deps.get_rsac_mgr()
    deleted = rsac.delete_rule(camera_id, zone_id)
    deps.reload_all_galleries()
    return {"status": "success" if deleted else "not_found", "camera_id": camera_id, "zone_id": zone_id}


@router.get("/api/pets/whitelist")
async def get_pet_whitelist():
    """List whitelisted pet labels and categories that suppress perimeter alarms."""
    rsac = deps.get_rsac_mgr()
    return {"whitelist": rsac.get_pet_whitelist()}


@router.post("/api/pets/whitelist")
async def add_pet_whitelist(req: PetWhitelistRequest):
    """Add label or category to pet alarm suppression whitelist."""
    rsac = deps.get_rsac_mgr()
    rsac.add_pet_whitelist(req.label, notes=req.notes or "")
    deps.reload_all_galleries()
    return {"status": "success", "whitelist": rsac.get_pet_whitelist()}


@router.delete("/api/pets/whitelist/{label}")
async def remove_pet_whitelist(label: str):
    """Remove label or category from pet alarm suppression whitelist."""
    rsac = deps.get_rsac_mgr()
    rsac.remove_pet_whitelist(label)
    deps.reload_all_galleries()
    return {"status": "success", "whitelist": rsac.get_pet_whitelist()}


@router.get("/api/entities/{entity_id}/versions")
async def get_entity_versions(entity_id: int):
    """Retrieve complete descriptor version snapshot history for an entity."""
    db = deps.get_db()
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
async def rollback_entity_descriptor(entity_id: int, version: int, req: RollbackRequest = RollbackRequest()):
    """Roll back entity visual descriptor to a prior verified snapshot version."""
    db = deps.get_db()
    ok = db.rollback_descriptor(entity_id=entity_id, version=version)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Version {version} not found for entity {entity_id}")
    deps.reload_all_galleries()
    return {
        "status": "success",
        "entity_id": entity_id,
        "rolled_back_to_version": version,
        "notes": req.notes,
    }

