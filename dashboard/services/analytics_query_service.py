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


_HEATMAP_GRID_COLS = 32
_HEATMAP_GRID_ROWS = 24


def _downsample_heatmap_grid(
    density: Any,
    cols: int = _HEATMAP_GRID_COLS,
    rows: int = _HEATMAP_GRID_ROWS,
) -> list[list[float]]:
    """Downsample a 2D heatmap density array into a normalized rows x cols grid."""
    if density is None:
        return [[0.0] * cols for _ in range(rows)]
    arr = np.asarray(density, dtype=np.float32)
    if arr.ndim != 2 or arr.size == 0 or arr.shape[0] <= 0 or arr.shape[1] <= 0:
        return [[0.0] * cols for _ in range(rows)]
    max_val = float(np.max(arr))
    if not np.isfinite(max_val) or max_val <= 0.0:
        return [[0.0] * cols for _ in range(rows)]

    h, w = arr.shape
    grid: list[list[float]] = []
    for r in range(rows):
        r0 = (r * h) // rows
        r1 = max(r0 + 1, ((r + 1) * h) // rows)
        row_vals: list[float] = []
        for c in range(cols):
            c0 = (c * w) // cols
            c1 = max(c0 + 1, ((c + 1) * w) // cols)
            cell_max = float(np.max(arr[r0:r1, c0:c1]))
            row_vals.append(round(max(0.0, min(1.0, cell_max / max_val)), 4))
        grid.append(row_vals)
    return grid


def _build_axis_ticks(span: int, steps: int = 5) -> list[int]:
    """Return evenly spaced integer pixel ticks from 0 to span."""
    safe_span = max(0, int(span))
    if safe_span == 0 or steps <= 1:
        return [0]
    return [round(safe_span * i / (steps - 1)) for i in range(steps)]


def _resolve_colormap_name(hm: Any) -> str:
    """Resolve human-readable colormap name from a Heatmap object."""
    cmap_val = getattr(hm, "colormap", 2)
    return _COLORMAP_NAMES.get(int(cmap_val), str(cmap_val)) if isinstance(cmap_val, int) else str(cmap_val)


def build_heatmap_json(mgr: Any, camera_id: Optional[str]) -> dict[str, Any]:
    """Build enriched JSON metadata payload for the spatial density heatmap."""
    resolved_cam = camera_id or getattr(mgr, "camera_id", None)
    if not mgr.analytics or not mgr.analytics.heatmap:
        return {
            "density": [], "initialized": False, "camera_id": resolved_cam,
            "grid_size": [_HEATMAP_GRID_COLS, _HEATMAP_GRID_ROWS], "grid": [], "x_ticks": [], "y_ticks": [],
        }
    hm = mgr.analytics.heatmap
    raw_density = getattr(hm, "density", None)
    arr = np.asarray(raw_density, dtype=np.float32) if raw_density is not None else np.empty((0, 0), dtype=np.float32)
    has_data = arr.ndim == 2 and arr.size > 0
    width = int(getattr(hm, "width", 0) or (arr.shape[1] if arr.ndim == 2 else 0))
    height = int(getattr(hm, "height", 0) or (arr.shape[0] if arr.ndim == 2 else 0))
    return {
        "initialized": True,
        "camera_id": resolved_cam,
        "resolution": [width, height],
        "max_value": float(np.max(arr)) if has_data else 0.0,
        "mean_value": float(np.mean(arr)) if has_data else 0.0,
        "colormap": _resolve_colormap_name(hm),
        "decay_rate": getattr(hm, "decay_rate", None),
        "radius": getattr(hm, "radius", None),
        "stops": _DEFAULT_HEATMAP_STOPS,
        "grid_size": [_HEATMAP_GRID_COLS, _HEATMAP_GRID_ROWS],
        "grid": _downsample_heatmap_grid(arr, _HEATMAP_GRID_COLS, _HEATMAP_GRID_ROWS),
        "x_ticks": _build_axis_ticks(width),
        "y_ticks": _build_axis_ticks(height),
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
