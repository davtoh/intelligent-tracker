"""Dashboard service for Category SSOT validation, preset export/import, and guarded deletes."""

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from dashboard.dependencies import (
    get_active_stream_manager,
    get_camera_pool,
    get_rsac_mgr,
)
from intelligent_tracker.category_registry import (
    is_valid_category_slug,
    normalize_category_slug,
    resolve_category_alias,
)
from intelligent_tracker.rsac import RSACManager

MAX_IMPORT_CATEGORIES = 200


def _read_field(item: Any, name: str, default: Any = "") -> Any:
    """Read an attribute or dictionary key uniformly."""
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def resolve_rsac_for_request(
    request: Any = None,
    *,
    db: Any = None,
    pool: Any = None,
    camera_id: str | None = None,
) -> Any:
    """Resolve RSACManager safely across live pools, test stubs, and dependency overrides."""
    app = getattr(request, "app", None)
    overrides = getattr(app, "dependency_overrides", None) or {}
    if get_rsac_mgr in overrides:
        return overrides[get_rsac_mgr]()

    resolved_pool = pool if pool is not None else (get_camera_pool(request) if request is not None else None)
    pool_rsac = getattr(resolved_pool, "rsac_manager", None)
    if callable(getattr(pool_rsac, "get_category", None)):
        return pool_rsac

    mgr = get_active_stream_manager(camera_id, conn=request) if request is not None else None
    mgr_rsac = getattr(mgr, "rsac_manager", None)
    if callable(getattr(mgr_rsac, "get_category", None)):
        return mgr_rsac

    state_db = getattr(getattr(app, "state", None), "db", None)
    resolved_db = db or getattr(mgr, "db", None) or getattr(resolved_pool, "_db", None) or state_db
    return RSACManager(db=resolved_db)


def ensure_known_category(rsac: RSACManager, raw: str | None, default: str = "person") -> str:
    """Validate and normalize a category slug against ``custom_categories``, raising HTTP 422 if unknown."""
    slug = default if (raw is None or not str(raw).strip()) else resolve_category_alias(normalize_category_slug(raw))
    if not is_valid_category_slug(slug) or rsac.get_category(slug) is None:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown category '{slug}'; create it via POST /api/rsac/categories",
        )
    return slug


def ensure_known_categories(rsac: RSACManager, raws: list[str] | None) -> list[str]:
    """Validate and normalize a list of category slugs against ``custom_categories``."""
    validated: list[str] = []
    for raw in raws or []:
        slug = resolve_category_alias(normalize_category_slug(raw))
        if not is_valid_category_slug(slug) or rsac.get_category(slug) is None:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown category '{slug}'; create it via POST /api/rsac/categories",
            )
        validated.append(slug)
    return validated


def export_categories(rsac: RSACManager) -> dict[str, Any]:
    """Export all registered categories in versioned preset JSON format."""
    return {
        "format": "intelligent-tracker.categories",
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "categories": rsac.list_categories(),
    }


def _is_protected_category(db: Any, cat_id: str) -> bool:
    """Return True when ``cat_id`` is 'person' or referenced by entities/RSAC rules."""
    if cat_id == "person":
        return True
    if db is not None and hasattr(db, "count_category_references"):
        refs = db.count_category_references(cat_id)
        return refs["entities"] > 0 or refs["rules"] > 0
    return False


def _prune_on_replace(rsac: RSACManager, resolved_db: Any, keep_set: set[str]) -> tuple[list[str], list[str]]:
    """Delete unreferenced non-person categories omitted from a replace import."""
    deleted_ids: list[str] = []
    preserved_ids: list[str] = []
    for cat in list(rsac.list_categories()):
        cid = cat["id"]
        if cid in keep_set:
            continue
        if _is_protected_category(resolved_db, cid):
            preserved_ids.append(cid)
        elif rsac.delete_category(cid):
            deleted_ids.append(cid)
    return deleted_ids, preserved_ids


def _register_imported_item(rsac: RSACManager, item: Any) -> tuple[str | None, dict[str, str] | None]:
    """Validate and upsert a single imported category item."""
    raw_id = str(_read_field(item, "id", "") or "")
    slug = normalize_category_slug(raw_id)
    name = str(_read_field(item, "name", "") or "").strip()
    if not is_valid_category_slug(slug):
        return None, {"id": raw_id, "reason": "invalid_slug"}
    if not name:
        return None, {"id": slug, "reason": "missing_name"}
    rsac.register_category(
        cat_id=slug,
        name=name,
        color=str(_read_field(item, "color", "#3B82F6") or "#3B82F6"),
        badge_icon=str(_read_field(item, "badge_icon", "") or ""),
        description=str(_read_field(item, "description", "") or ""),
    )
    return slug, None


def import_categories(
    rsac: RSACManager,
    db: Any,
    items: list[Any],
    mode: str = "merge",
) -> dict[str, Any]:
    """Import category presets with merge or replace semantics."""
    if len(items) > MAX_IMPORT_CATEGORIES:
        raise HTTPException(
            status_code=422,
            detail=f"At most {MAX_IMPORT_CATEGORIES} categories may be imported at once",
        )
    imported_ids: list[str] = []
    skipped: list[dict[str, str]] = []
    for item in items:
        slug, err = _register_imported_item(rsac, item)
        if err is not None:
            skipped.append(err)
        elif slug is not None:
            imported_ids.append(slug)

    deleted_ids: list[str] = []
    preserved_ids: list[str] = []
    if mode == "replace":
        resolved_db = db if db is not None else getattr(rsac, "db", None)
        deleted_ids, preserved_ids = _prune_on_replace(rsac, resolved_db, set(imported_ids))

    return {
        "status": "success",
        "mode": mode,
        "imported": len(imported_ids),
        "deleted": len(deleted_ids),
        "preserved": preserved_ids,
        "skipped": skipped,
        "categories": rsac.list_categories(),
    }


def delete_category_guarded(rsac: RSACManager, db: Any, cat_id: str) -> dict[str, Any]:
    """Delete a category unless it is protected ('person') or still referenced."""
    slug = normalize_category_slug(cat_id)
    if slug == "person":
        raise HTTPException(status_code=409, detail="Default category 'person' cannot be deleted")
    resolved_db = db if db is not None else getattr(rsac, "db", None)
    if resolved_db is not None and hasattr(resolved_db, "count_category_references"):
        refs = resolved_db.count_category_references(slug)
        if refs["entities"] > 0 or refs["rules"] > 0:
            raise HTTPException(
                status_code=409,
                detail=f"Category '{slug}' is referenced by {refs['entities']} entities and {refs['rules']} RSAC rules",
            )
    deleted = rsac.delete_category(slug)
    return {"status": "success" if deleted else "not_found", "deleted": slug}
