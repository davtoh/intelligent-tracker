#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Custom Category Updates & Pre-Enrollment Collision Router.

Exposes PUT /api/rsac/categories/{category_id} and POST /api/enroll/check-collision
without expanding dashboard/routers/rsac.py past its modularity budget.
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from dashboard.dependencies import (
    get_active_stream_manager,
    get_enrollment_mgr,
    get_rsac_mgr,
    reload_all_galleries,
)
from dashboard.routers.rsac import _extract_crop_from_base64, _extract_crop_from_frame
from dashboard.schemas import CollisionCheckRequest, CustomCategoryUpdateRequest
from intelligent_tracker.enrollment import UniversalEnrollmentManager
from intelligent_tracker.rsac import RSACManager

router = APIRouter(tags=["RSAC & Enrollment Collision"])


@router.put("/api/rsac/categories/{category_id}")
async def update_custom_category(
    category_id: str,
    req: CustomCategoryUpdateRequest,
    request: Request,
    rsac: RSACManager = Depends(get_rsac_mgr),
):
    """Update an existing custom semantic category badge."""
    existing = await asyncio.to_thread(rsac.get_category, category_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Category '{category_id}' not found")
    cat = await asyncio.to_thread(
        rsac.register_category,
        cat_id=category_id,
        name=req.name,
        color=req.color or existing.color or "#3B82F6",
        badge_icon=req.badge_icon if req.badge_icon is not None else existing.badge_icon,
        description=req.description if req.description is not None else existing.description,
    )
    await asyncio.to_thread(reload_all_galleries, conn=request)
    return {"status": "updated", "category": cat.to_dict()}


@router.post("/api/enroll/check-collision")
async def check_enrollment_collision(
    req: CollisionCheckRequest,
    request: Request,
    enrollment_mgr: UniversalEnrollmentManager = Depends(get_enrollment_mgr),
):
    """Check whether a candidate enrollment crop collides with existing gallery entities."""
    if req.crop_base64:
        crop_img = await asyncio.to_thread(_extract_crop_from_base64, req.crop_base64)
    elif req.bbox and req.camera_id:
        mgr = get_active_stream_manager(req.camera_id, conn=request)
        if not mgr:
            raise HTTPException(status_code=404, detail=f"Camera '{req.camera_id}' not found")
        crop_img = await asyncio.to_thread(_extract_crop_from_frame, mgr, req.bbox)
    else:
        raise HTTPException(status_code=400, detail="Either crop_base64 or camera_id+bbox must be provided")

    return await asyncio.to_thread(
        enrollment_mgr.check_collision,
        crop=crop_img,
        threshold=req.threshold,
        top_k=req.top_k,
    )
