"""Analytics query helpers for time-bucketed traffic flows, heatmap metadata, and sightings."""

import os
from typing import Any, Optional

import numpy as np

_COLORMAP_NAMES = {
    2: "JET",
    11: "HOT",
    14: "INFERNO",
    20: "TURBO",
}

_DEFAULT_HEATMAP_STOPS = [
    {"ratio": 0.0, "color": "#1d4ed8", "label": "Low"},
    {"ratio": 0.35, "color": "#06b6d4", "label": "Moderate"},
    {"ratio": 0.7, "color": "#f59e0b", "label": "Elevated"},
    {"ratio": 1.0, "color": "#ef4444", "label": "Peak"},
]


def resolve_bucket_sec(range_sec: int, bucket_sec: Optional[int]) -> int:
    """Resolve an explicit or range-proportional time bucket width in seconds."""
    if bucket_sec is not None:
        return max(1, int(bucket_sec))
    if range_sec <= 900:
        return 60
    if range_sec <= 3600:
        return 300
    if range_sec <= 21600:
        return 900
    if range_sec <= 86400:
        return 3600
    return 21600


def build_heatmap_json(mgr: Any, camera_id: Optional[str]) -> dict[str, Any]:
    """Build enriched JSON metadata payload for the spatial density heatmap."""
    resolved_cam = camera_id or getattr(mgr, "camera_id", None)
    if not mgr.analytics or not mgr.analytics.heatmap:
        return {"density": [], "initialized": False, "camera_id": resolved_cam}
    hm = mgr.analytics.heatmap
    cmap_val = getattr(hm, "colormap", 2)
    cmap_name = (
        _COLORMAP_NAMES.get(int(cmap_val), str(cmap_val))
        if isinstance(cmap_val, int)
        else str(cmap_val)
    )
    return {
        "initialized": True,
        "camera_id": resolved_cam,
        "resolution": [hm.width, hm.height],
        "max_value": float(np.max(hm.density)),
        "mean_value": float(np.mean(hm.density)),
        "colormap": cmap_name,
        "decay_rate": getattr(hm, "decay_rate", None),
        "radius": getattr(hm, "radius", None),
        "stops": _DEFAULT_HEATMAP_STOPS,
    }


def enrich_sighting(s: dict[str, Any], db: Any) -> dict[str, Any]:
    """Enrich sighting with entity details and thumbnail URL (with entity avatar fallback)."""
    s_dict = dict(s)
    ent_id = s_dict.get("entity_id")
    if ent_id:
        ent = db.get_entity(ent_id)
        s_dict["entity_name"] = ent["name"] if ent else "Unknown"
        s_dict["entity_category"] = ent["category"] if ent else "unknown"
    else:
        s_dict["entity_name"] = f"Track #{s_dict.get('track_id', 0)}"
        s_dict["entity_category"] = "unidentified"

    if s_dict.get("snapshot_path"):
        s_dict["snapshot_url"] = f"/crops/{os.path.basename(s_dict['snapshot_path'])}"
    elif ent_id and hasattr(db, "get_signatures"):
        sigs = db.get_signatures(entity_id=ent_id)
        for sig in sigs:
            cp = str(sig.get("crop_path") or "").strip()
            if cp:
                s_dict["snapshot_url"] = f"/crops/{os.path.basename(cp)}"
                break
    return s_dict


def _empty_sightings_result(use_envelope: bool, offset: int, limit: int) -> list[dict[str, Any]] | dict[str, Any]:
    """Return an empty flat list or empty pagination envelope."""
    if use_envelope:
        return {"items": [], "total": 0, "offset": offset, "limit": limit, "has_more": False}
    return []


def query_sightings_page(
    db: Any,
    entity_id: Optional[int] = None,
    entity_name: Optional[str] = None,
    source: Optional[str] = None,
    zone_id: Optional[str] = None,
    video_filename: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    paginated: bool = False,
) -> list[dict[str, Any]] | dict[str, Any]:
    """Query sightings with optional pagination envelope while preserving flat-list default."""
    safe_offset = max(0, int(offset or 0))
    safe_limit = max(1, int(limit or 50))
    use_envelope = bool(paginated or safe_offset > 0)
    if entity_name and entity_id is None:
        ent = db.get_entity_by_name(entity_name)
        if not ent:
            return _empty_sightings_result(use_envelope, safe_offset, safe_limit)
        entity_id = ent["id"]

    filters: dict[str, Any] = {
        "entity_id": entity_id,
        "source": source,
        "zone_id": zone_id,
        "start_time": start_time,
        "end_time": end_time,
        "video_filename": video_filename,
    }
    sightings = db.query_sightings(**filters, limit=safe_limit, offset=safe_offset)
    items = [enrich_sighting(s, db) for s in sightings]
    if not use_envelope:
        return items

    total = db.count_sightings(**filters)
    return {"items": items, "total": total, "offset": safe_offset, "limit": safe_limit, "has_more": (safe_offset + len(items)) < total}
