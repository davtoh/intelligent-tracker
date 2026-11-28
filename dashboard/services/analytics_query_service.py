"""Analytics query helpers for time-bucketed traffic flows, heatmap metadata, and sightings."""

import os
from typing import Any, Optional
from urllib.parse import quote

import numpy as np

from intelligent_tracker.source_ref import build_source_ref, source_ref_from_row

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


def query_traffic_flows_service(
    db: Any,
    *,
    camera_id: Optional[str] = None,
    zone_id: Optional[str] = None,
    event_type: Optional[str] = None,
    range_sec: int = 3600,
    end_time: Optional[float] = None,
    bucket_sec: Optional[int] = None,
    page: Optional[int] = None,
    page_size: Optional[int] = None,
    now_ts: float,
) -> dict[str, Any]:
    """Query time-bucketed traffic flows with optional zone, event_type, and bucket pagination."""
    is_live = end_time is None
    resolved_end = float(end_time) if end_time is not None else float(now_ts)
    resolved_bucket = resolve_bucket_sec(range_sec, bucket_sec)
    start_time = resolved_end - float(range_sec)
    if db is None:
        return {
            "camera_id": camera_id or None, "zone_id": zone_id or None, "event_type": event_type or None,
            "start_time": start_time, "end_time": resolved_end, "bucket_sec": resolved_bucket,
            "buckets": [], "totals": {"inflow": 0, "outflow": 0, "total": 0, "sightings": 0},
            "pagination": {"page": 1, "page_size": 0, "total_buckets": 0, "total_pages": 1, "has_prev": False, "has_next": False},
            "axes": {"x": {"label": "Time", "unit": "epoch_s", "bucket_sec": resolved_bucket}, "y": {"label": "Crossings / Events", "unit": "count"}},
            "is_live": is_live,
        }
    res = db.get_traffic_flows(
        start_time, resolved_end, resolved_bucket,
        camera_id=camera_id, zone_id=zone_id, event_type=event_type,
        page=page, page_size=page_size,
    )
    res["is_live"] = is_live
    return res


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


def _build_heatmap_hotspots(
    grid: list[list[float]],
    width: int,
    height: int,
    resolved_cam: Optional[str],
    vfile: str,
    rid: str,
    image_url: str,
    freeze_frame_url: str,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Extract top normalized 32x24 heatmap hotspot cells with SourceRef drill-down metadata."""
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    if not rows or not cols:
        return []
    candidates = sorted(
        ((float(val), r, c) for r, rv in enumerate(grid) for c, val in enumerate(rv) if float(val) > 0.0),
        key=lambda item: (-item[0], item[1], item[2]),
    )
    hotspots: list[dict[str, Any]] = []
    for val, r, c in candidates[:limit]:
        px = round(((c + 0.5) / cols) * width) if width > 0 else c
        py = round(((r + 0.5) / rows) * height) if height > 0 else r
        cell_bbox = (
            [round((c / cols) * width), round((r / rows) * height), round(((c + 1) / cols) * width), round(((r + 1) / rows) * height)]
            if width > 0 and height > 0 else None
        )
        cell_ref = build_source_ref(camera_id=str(resolved_cam or ""), video_filename=vfile, run_id=rid, bbox=cell_bbox)
        hotspots.append({
            "col": c, "row": r, "px": px, "py": py, "bbox": cell_bbox, "density": val,
            "camera_id": resolved_cam, "image_url": image_url,
            "freeze_frame_url": freeze_frame_url, "source_ref": cell_ref,
        })
    return hotspots


HEATMAP_GRID_COLS = _HEATMAP_GRID_COLS
HEATMAP_GRID_ROWS = _HEATMAP_GRID_ROWS
DEFAULT_HEATMAP_STOPS = _DEFAULT_HEATMAP_STOPS
downsample_heatmap_grid = _downsample_heatmap_grid
build_heatmap_hotspots = _build_heatmap_hotspots
build_axis_ticks = _build_axis_ticks
resolve_colormap_name = _resolve_colormap_name


def build_heatmap_json(mgr: Any, camera_id: Optional[str]) -> dict[str, Any]:
    """Build enriched JSON metadata payload for the spatial density heatmap."""
    resolved_cam = camera_id or getattr(mgr, "camera_id", None)
    raw_vfile = getattr(mgr, "video_filename", "")
    raw_rid = getattr(mgr, "run_id", "")
    vfile = raw_vfile.strip() if isinstance(raw_vfile, str) else ""
    rid = raw_rid.strip() if isinstance(raw_rid, str) else ""
    q_cam = quote(str(resolved_cam), safe="") if resolved_cam else ""
    image_url = f"/analytics/heatmap?camera_id={q_cam}" if q_cam else "/analytics/heatmap"
    freeze_frame_url = f"/api/cameras/{q_cam}/freeze_frame" if q_cam else ""
    base_ref = build_source_ref(camera_id=str(resolved_cam or ""), video_filename=vfile, run_id=rid)
    if not mgr.analytics or not mgr.analytics.heatmap:
        return {
            "density": [], "initialized": False, "camera_id": resolved_cam,
            "grid_size": [_HEATMAP_GRID_COLS, _HEATMAP_GRID_ROWS], "grid": [], "x_ticks": [], "y_ticks": [],
            "source_ref": base_ref, "image_url": image_url, "freeze_frame_url": freeze_frame_url,
            "peak_media_ref": None, "hotspots": [],
        }
    hm = mgr.analytics.heatmap
    raw_density = getattr(hm, "density", None)
    arr = np.asarray(raw_density, dtype=np.float32) if raw_density is not None else np.empty((0, 0), dtype=np.float32)
    has_data = arr.ndim == 2 and arr.size > 0
    width = int(getattr(hm, "width", 0) or (arr.shape[1] if arr.ndim == 2 else 0))
    height = int(getattr(hm, "height", 0) or (arr.shape[0] if arr.ndim == 2 else 0))
    grid = _downsample_heatmap_grid(arr, _HEATMAP_GRID_COLS, _HEATMAP_GRID_ROWS)
    hotspots = _build_heatmap_hotspots(grid, width, height, resolved_cam, vfile, rid, image_url, freeze_frame_url)
    return {
        "initialized": True, "camera_id": resolved_cam, "resolution": [width, height],
        "max_value": float(np.max(arr)) if has_data else 0.0,
        "mean_value": float(np.mean(arr)) if has_data else 0.0,
        "colormap": _resolve_colormap_name(hm), "decay_rate": getattr(hm, "decay_rate", None),
        "radius": getattr(hm, "radius", None), "stops": _DEFAULT_HEATMAP_STOPS,
        "grid_size": [_HEATMAP_GRID_COLS, _HEATMAP_GRID_ROWS], "grid": grid,
        "x_ticks": _build_axis_ticks(width), "y_ticks": _build_axis_ticks(height),
        "source_ref": base_ref, "image_url": image_url, "freeze_frame_url": freeze_frame_url,
        "peak_media_ref": hotspots[0] if hotspots else None, "hotspots": hotspots,
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
    s_dict["source_ref"] = source_ref_from_row(s_dict)
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


def list_all_sighting_sources(
    db: Any, *, pool: Any = None, videos_dir: str | None = None,
) -> list[dict[str, Any]]:
    """Return DB sighting sources merged with all known cameras and video files."""
    by_source: dict[str, dict[str, Any]] = {}
    if db is not None and hasattr(db, "list_sighting_sources"):
        for row in db.list_sighting_sources():
            src = str(row.get("source") or "").strip()
            if src:
                by_source[src] = dict(row)
    if pool is not None:
        cam_ids = set(getattr(pool, "camera_configs", {}) or {})
        from dashboard.services.camera_pool_queries import snapshot_pool_streams

        cam_ids.update(snapshot_pool_streams(pool).keys())
        for cid in sorted(cam_ids):
            by_source.setdefault(str(cid), {"source": str(cid), "count": 0, "has_video": False})
    if db is not None and hasattr(db, "list_video_runs"):
        for run in db.list_video_runs():
            vname = str(run.get("video_filename") or "").strip()
            if vname:
                by_source.setdefault(vname, {"source": vname, "count": 0, "has_video": True})
    if videos_dir and os.path.isdir(videos_dir):
        for name in sorted(os.listdir(videos_dir)):
            if name.lower().endswith((".mp4", ".avi", ".mkv", ".mov", ".webm", ".m4v")):
                by_source.setdefault(name, {"source": name, "count": 0, "has_video": True})
    return sorted(by_source.values(), key=lambda r: (-int(r.get("count") or 0), str(r.get("source") or "")))
