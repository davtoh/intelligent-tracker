"""Dashboard router for Custom Category Registry CRUD, preset export/import, and guarded deletes."""

import asyncio
import sys

from fastapi import APIRouter, Depends, HTTPException, Request

from dashboard.dependencies import get_db, get_rsac_mgr, reload_all_galleries as _deps_reload_all_galleries
from dashboard.schemas import CategoryImportRequest, CustomCategoryCreateRequest
from dashboard.services.category_service import (
    delete_category_guarded,
    export_categories,
    import_categories,
)
from intelligent_tracker.category_registry import is_valid_category_slug, normalize_category_slug
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.rsac import RSACManager

router = APIRouter(tags=["Category Registry"])
reload_all_galleries = _deps_reload_all_galleries


def _reload_galleries(conn: Request) -> None:
    """Invoke reload_all_galleries while honoring legacy patches on dashboard.routers.rsac."""
    if reload_all_galleries is not _deps_reload_all_galleries:
        reload_all_galleries(conn=conn)
        return
    rsac_mod = sys.modules.get("dashboard.routers.rsac")
    rsac_reload = getattr(rsac_mod, "reload_all_galleries", _deps_reload_all_galleries) if rsac_mod else _deps_reload_all_galleries
    rsac_reload(conn=conn)


@router.get("/api/rsac/categories")
async def list_custom_categories(rsac: RSACManager = Depends(get_rsac_mgr)):
    """List custom semantic categories and display badges."""
    return await asyncio.to_thread(rsac.list_categories)


@router.post("/api/rsac/categories")
async def create_custom_category(
    req: CustomCategoryCreateRequest,
    request: Request,
    rsac: RSACManager = Depends(get_rsac_mgr),
):
    """Register or update custom category badge with strict slug validation."""
    slug = normalize_category_slug(req.id)
    if not is_valid_category_slug(slug):
        raise HTTPException(status_code=422, detail=f"Invalid category slug '{req.id}'")
    cat = await asyncio.to_thread(
        rsac.register_category,
        cat_id=slug,
        name=req.name,
        color=req.color or "#3B82F6",
        badge_icon=req.badge_icon or "",
        description=req.description or "",
    )
    await asyncio.to_thread(_reload_galleries, request)
    return {"status": "success", "category": cat.to_dict()}


@router.get("/api/rsac/categories/export")
async def export_custom_categories(rsac: RSACManager = Depends(get_rsac_mgr)):
    """Export registered categories as a versioned JSON preset."""
    return await asyncio.to_thread(export_categories, rsac)


@router.post("/api/rsac/categories/import")
async def import_custom_categories(
    req: CategoryImportRequest,
    request: Request,
    rsac: RSACManager = Depends(get_rsac_mgr),
    db: TrackerDB = Depends(get_db),
):
    """Import category presets with merge or replace semantics."""
    res = await asyncio.to_thread(import_categories, rsac, db, req.categories, req.mode)
    await asyncio.to_thread(_reload_galleries, request)
    return res


@router.delete("/api/rsac/categories/{category_id}")
async def delete_custom_category(
    category_id: str,
    request: Request,
    rsac: RSACManager = Depends(get_rsac_mgr),
    db: TrackerDB = Depends(get_db),
):
    """Delete a custom category unless it is 'person' or referenced by entities/rules."""
    res = await asyncio.to_thread(delete_category_guarded, rsac, db, category_id)
    await asyncio.to_thread(_reload_galleries, request)
    return res
