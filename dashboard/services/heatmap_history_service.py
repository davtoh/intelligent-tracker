"""Historical DB-backed filtered spatial density heatmap service (OBS-023)."""

import json
import math
import time
from typing import Any, Optional
from urllib.parse import quote, urlencode

import cv2
import numpy as np

from dashboard.services.analytics_query_service import (
    DEFAULT_HEATMAP_STOPS,
    HEATMAP_GRID_COLS,
    HEATMAP_GRID_ROWS,
    build_axis_ticks,
    build_heatmap_hotspots,
    downsample_heatmap_grid,
    resolve_colormap_name,
)
from intelligent_tracker.analytics.heatmap import OccupancyHeatmap
from intelligent_tracker.repositories._event_filter_sql import normalize_zone_name
from intelligent_tracker.source_ref import build_source_ref

_DEFAULT_WIDTH, _DEFAULT_HEIGHT, _MAX_HISTORICAL_POINTS = 640, 480, 25000


def _parse_footpoint_from_bbox(raw_bbox: Any) -> Optional[tuple[float, float]]:
    """Extract bottom-center footpoint (x + w/2, y + h) from JSON/list [x, y, w, h]."""
    bbox = raw_bbox
    if isinstance(raw_bbox, str):
        text = raw_bbox.strip()
        if not text:
            return None
        try:
            bbox = json.loads(text)
        except (ValueError, TypeError):
            return None
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return None
    try:
        x, y, w, h = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (x, y, w, h)) or w <= 0.0 or h <= 0.0:
        return None
    return (x + w * 0.5, y + h)


def _parse_footpoint_from_meta(metadata_json: str) -> tuple[Optional[tuple[float, float]], str]:
    """Extract footpoint and optional zone_id from world_timeline_events.metadata_json."""
    if not metadata_json:
        return None, ""
    try:
        meta = json.loads(metadata_json)
    except (ValueError, TypeError):
        return None, ""
    if not isinstance(meta, dict):
        return None, ""
    meta_zone = str(meta.get("zone_id") or "").strip()
    fp = _parse_footpoint_from_bbox(meta.get("bbox"))
    if fp is not None:
        return fp, meta_zone
    centroid = meta.get("centroid")
    if isinstance(centroid, (list, tuple)) and len(centroid) >= 2:
        try:
            cx, cy = float(centroid[0]), float(centroid[1])
            if math.isfinite(cx) and math.isfinite(cy):
                return (cx, cy), meta_zone
        except (TypeError, ValueError):
            pass
    return None, meta_zone


def _zone_matches(raw_zone: Any, target_norm_lower: str) -> bool:
    """Return True when target filter is empty or normalized zone names match."""
    return (not target_norm_lower) or (normalize_zone_name(str(raw_zone or "")).lower() == target_norm_lower)


def _query_sighting_footpoints(
    cursor: Any, start_time: float, end_time: float, lookup: Optional[str],
    norm_zone_lower: str, entity_id: Optional[int], limit: int,
) -> list[tuple[float, float]]:
    """Query sightings table and return matching bottom-center footpoints."""
    clauses = ["ts_epoch >= ?", "ts_epoch <= ?"]
    params: list[Any] = [start_time, end_time]
    if lookup:
        clauses.append("(camera_id = ? OR source = ? OR video_filename = ?)")
        params.extend([lookup, lookup, lookup])
    if entity_id is not None:
        clauses.append("entity_id = ?")
        params.append(int(entity_id))
    cursor.execute(
        "SELECT bbox, zone_id, CASE WHEN typeof(timestamp) IN ('integer', 'real') "
        "THEN CAST(timestamp AS REAL) ELSE CAST(strftime('%s', timestamp) AS REAL) END AS ts_epoch "
        f"FROM sightings WHERE {' AND '.join(clauses)} LIMIT ?",
        [*params, limit],
    )
    points: list[tuple[float, float]] = []
    for row in cursor.fetchall():
        if _zone_matches(row["zone_id"], norm_zone_lower):
            fp = _parse_footpoint_from_bbox(row["bbox"])
            if fp is not None:
                points.append(fp)
    return points


def _query_timeline_footpoints(
    cursor: Any, start_time: float, end_time: float, lookup: Optional[str],
    norm_zone_lower: str, event_type: Optional[str], entity_id: Optional[int], limit: int,
) -> list[tuple[float, float]]:
    """Query world_timeline_events table and return matching footpoints."""
    clauses = ["timestamp >= ?", "timestamp <= ?"]
    params: list[Any] = [start_time, end_time]
    if lookup:
        clauses.append("(camera_id = ? OR video_filename = ?)")
        params.extend([lookup, lookup])
    if event_type:
        clauses.append("event_type = ?")
        params.append(event_type)
    if entity_id is not None:
        clauses.append("entity_id = ?")
        params.append(int(entity_id))
    cursor.execute(
        f"SELECT zone_id, metadata_json FROM world_timeline_events WHERE {' AND '.join(clauses)} LIMIT ?",
        [*params, limit],
    )
    points: list[tuple[float, float]] = []
    for row in cursor.fetchall():
        fp, meta_zone = _parse_footpoint_from_meta(row["metadata_json"] or "")
        if fp is not None and _zone_matches(row["zone_id"] or meta_zone, norm_zone_lower):
            points.append(fp)
    return points


def _collect_filtered_footpoints(
    db: Any, start_time: float, end_time: float, camera_id: Optional[str],
    zone_id: Optional[str], event_type: Optional[str], entity_id: Optional[int],
) -> list[tuple[float, float]]:
    """Collect matching footpoints from sightings and world_timeline_events under db._lock."""
    if db is None or getattr(db, "_conn", None) is None:
        return []
    cam = camera_id.strip() if camera_id and camera_id.strip() else None
    lookup = cam[6:].strip() if (cam and cam.startswith("video:")) else cam
    norm_zone_lower = normalize_zone_name(zone_id).lower()
    ev_type = event_type.strip() if event_type and event_type.strip() else None
    points: list[tuple[float, float]] = []
    with db._lock:
        if db._conn is None:
            return []
        cursor = db._conn.cursor()
        try:
            if not ev_type or ev_type == "sighting":
                points.extend(_query_sighting_footpoints(cursor, start_time, end_time, lookup, norm_zone_lower, entity_id, _MAX_HISTORICAL_POINTS))
            rem = max(0, _MAX_HISTORICAL_POINTS - len(points))
            if rem > 0 and ev_type != "sighting":
                points.extend(_query_timeline_footpoints(cursor, start_time, end_time, lookup, norm_zone_lower, ev_type, entity_id, rem))
        finally:
            cursor.close()
    return points


def _resolve_dimensions(
    points: list[tuple[float, float]], width: Optional[int], height: Optional[int], mgr: Any,
) -> tuple[int, int]:
    """Resolve heatmap canvas dimensions from explicit args, live manager, or point bounds."""
    if width and height and int(width) > 0 and int(height) > 0:
        return int(width), int(height)
    hm = getattr(getattr(mgr, "analytics", None), "heatmap", None) if mgr is not None else None
    if hm is not None and int(getattr(hm, "width", 0) or 0) > 0 and int(getattr(hm, "height", 0) or 0) > 0:
        return int(hm.width), int(hm.height)
    w, h = _DEFAULT_WIDTH, _DEFAULT_HEIGHT
    if points:
        w = max(w, int(math.ceil(max(p[0] for p in points) + 32)))
        h = max(h, int(math.ceil(max(p[1] for p in points) + 32)))
    return w, h


def _build_filtered_heatmap_instance(
    db: Any, *, camera_id: Optional[str] = None, zone_id: Optional[str] = None,
    event_type: Optional[str] = None, range_sec: int = 3600, end_time: Optional[float] = None,
    entity_id: Optional[int] = None, width: Optional[int] = None, height: Optional[int] = None,
    mgr: Any = None, now_ts: Optional[float] = None,
) -> tuple[OccupancyHeatmap, list[tuple[float, float]], dict[str, Any]]:
    """Build a cumulative OccupancyHeatmap from filtered DB footpoints."""
    resolved_end = float(end_time) if end_time is not None else float(now_ts if now_ts is not None else time.time())
    safe_range = max(60, int(range_sec or 3600))
    start_time = resolved_end - float(safe_range)
    points = _collect_filtered_footpoints(db, start_time, resolved_end, camera_id, zone_id, event_type, entity_id)
    w, h = _resolve_dimensions(points, width, height, mgr)
    hm = OccupancyHeatmap(width=w, height=h, decay_rate=None)
    if points:
        hm.update(points)
    filters = {
        "camera_id": camera_id.strip() if camera_id and camera_id.strip() else None,
        "zone_id": normalize_zone_name(zone_id) or None,
        "event_type": event_type.strip() if event_type and event_type.strip() else None,
        "entity_id": int(entity_id) if entity_id is not None else None,
        "range_sec": safe_range, "start_time": start_time, "end_time": resolved_end,
    }
    return hm, points, filters


def _build_filtered_image_url(filters: dict[str, Any], end_time_explicit: Optional[float]) -> str:
    """Build a canonical /analytics/heatmap?mode=filtered... URL."""
    params: list[tuple[str, str]] = [("mode", "filtered")]
    for key in ("camera_id", "zone_id", "event_type", "entity_id"):
        if filters.get(key) is not None:
            params.append((key, str(filters[key])))
    params.append(("range_sec", str(filters["range_sec"])))
    if end_time_explicit is not None:
        params.append(("end_time", str(filters["end_time"])))
    return f"/analytics/heatmap?{urlencode(params)}"


def build_filtered_heatmap_jpeg(
    db: Any, *, camera_id: Optional[str] = None, zone_id: Optional[str] = None,
    event_type: Optional[str] = None, range_sec: int = 3600, end_time: Optional[float] = None,
    entity_id: Optional[int] = None, width: Optional[int] = None, height: Optional[int] = None,
    mgr: Any = None, now_ts: Optional[float] = None,
) -> bytes:
    """Render filtered historical DB footpoints as a colorized JPEG heatmap."""
    hm, _points, _filters = _build_filtered_heatmap_instance(
        db, camera_id=camera_id, zone_id=zone_id, event_type=event_type,
        range_sec=range_sec, end_time=end_time, entity_id=entity_id,
        width=width, height=height, mgr=mgr, now_ts=now_ts,
    )
    ret, buf = cv2.imencode(".jpg", hm.get_colored_map(), [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    return buf.tobytes() if ret else b""


def build_filtered_heatmap_json(
    db: Any, *, camera_id: Optional[str] = None, zone_id: Optional[str] = None,
    event_type: Optional[str] = None, range_sec: int = 3600, end_time: Optional[float] = None,
    entity_id: Optional[int] = None, width: Optional[int] = None, height: Optional[int] = None,
    mgr: Any = None, now_ts: Optional[float] = None,
) -> dict[str, Any]:
    """Build enriched JSON metadata payload for a filtered historical DB heatmap."""
    hm, points, filters = _build_filtered_heatmap_instance(
        db, camera_id=camera_id, zone_id=zone_id, event_type=event_type,
        range_sec=range_sec, end_time=end_time, entity_id=entity_id,
        width=width, height=height, mgr=mgr, now_ts=now_ts,
    )
    arr = np.asarray(hm.density, dtype=np.float32)
    has_data = arr.ndim == 2 and arr.size > 0
    resolved_cam = filters["camera_id"]
    image_url = _build_filtered_image_url(filters, end_time)
    q_cam = quote(str(resolved_cam), safe="") if resolved_cam else ""
    freeze_frame_url = f"/api/cameras/{q_cam}/freeze_frame" if q_cam else ""
    grid = downsample_heatmap_grid(arr, HEATMAP_GRID_COLS, HEATMAP_GRID_ROWS)
    hotspots = build_heatmap_hotspots(grid, hm.width, hm.height, resolved_cam, "", "", image_url, freeze_frame_url)
    return {
        "initialized": True, "mode": "filtered", "point_count": len(points), "filters": filters,
        "camera_id": resolved_cam, "resolution": [hm.width, hm.height],
        "max_value": float(np.max(arr)) if has_data else 0.0,
        "mean_value": float(np.mean(arr)) if has_data else 0.0,
        "colormap": resolve_colormap_name(hm), "decay_rate": None, "radius": hm.radius,
        "stops": DEFAULT_HEATMAP_STOPS, "grid_size": [HEATMAP_GRID_COLS, HEATMAP_GRID_ROWS],
        "grid": grid, "x_ticks": build_axis_ticks(hm.width), "y_ticks": build_axis_ticks(hm.height),
        "source_ref": build_source_ref(camera_id=str(resolved_cam or ""), zone_id=str(filters["zone_id"] or "")),
        "image_url": image_url, "freeze_frame_url": freeze_frame_url,
        "peak_media_ref": hotspots[0] if hotspots else None, "hotspots": hotspots,
    }
