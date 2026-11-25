"""Pure time-bucketed traffic flow aggregation helpers for AnalyticsMixin."""

import json
import math
import time
from typing import Any, Optional

from intelligent_tracker.source_ref import build_source_ref, snapshot_path_to_url

_INFLOW_DIRECTIONS = frozenset({"in", "enter", "entry", "inflow", "a_to_b", "forward"})
_OUTFLOW_DIRECTIONS = frozenset({"out", "exit", "egress", "outflow", "b_to_a", "reverse", "backward"})
_MAX_BUCKET_MEDIA_REFS = 5
_VIDEO_EXTS = (".mp4", ".avi", ".mkv", ".mov", ".webm", ".m4v")


def _parse_meta_json(metadata_json: str) -> dict[str, Any]:
    """Safely parse a JSON metadata blob into a dictionary."""
    if not metadata_json:
        return {}
    try:
        parsed = json.loads(metadata_json)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def _classify_flow_direction(event_type: str, metadata_json: str) -> tuple[int, int, int]:
    """Return (inflow_inc, outflow_inc, total_inc) for a flow event row."""
    if event_type == "zone_enter":
        return 1, 0, 1
    if event_type == "zone_exit":
        return 0, 1, 1
    if event_type == "tripwire_cross":
        direction = str(_parse_meta_json(metadata_json).get("direction") or "").strip().lower()
        if direction in _INFLOW_DIRECTIONS:
            return 1, 0, 1
        if direction in _OUTFLOW_DIRECTIONS:
            return 0, 1, 1
        return 0, 0, 1
    return 0, 0, 0


def _build_flow_media_ref(
    *,
    camera_id: str = "",
    video_filename: str = "",
    media_offset_sec: Any = 0.0,
    run_id: str = "",
    snapshot_path: str = "",
    zone_id: str = "",
    ts: float | None = None,
    track_id: Any = None,
    entity_id: Any = None,
    bbox: Any = None,
) -> dict[str, Any]:
    """Build a bounded flow-bucket media reference paired with canonical SourceRef."""
    vfile = str(video_filename or "").strip()
    cam_id = str(camera_id or "").strip()
    rid = str(run_id or "").strip()
    zid = str(zone_id or "").strip()
    snap_url = snapshot_path_to_url(snapshot_path)
    try:
        offset = round(max(0.0, float(media_offset_sec or 0.0)), 3)
    except (TypeError, ValueError):
        offset = 0.0
    tid = int(track_id) if track_id not in (None, "") else None
    eid = int(entity_id) if entity_id not in (None, "") else None
    ref = build_source_ref(
        camera_id=cam_id, video_filename=vfile, run_id=rid,
        media_offset_sec=offset if (vfile or offset) else None, ts=ts,
        track_id=tid, entity_id=eid, zone_id=zid, bbox=bbox, snapshot_url=snap_url,
    )
    return {
        "camera_id": cam_id, "video_filename": vfile, "media_offset_sec": offset,
        "run_id": rid, "snapshot_url": snap_url, "zone_id": zid, "source_ref": ref,
    }


def _init_flow_buckets(start_time: float, end_time: float, bucket_sec: int) -> list[dict[str, Any]]:
    """Build contiguous integer-aligned time buckets covering [start_time, end_time]."""
    span = max(float(bucket_sec), float(end_time) - float(start_time))
    count = max(1, min(500, int(math.ceil(span / float(bucket_sec)))))
    fmt = "%H:%M:%S" if bucket_sec < 60 else "%H:%M"
    buckets: list[dict[str, Any]] = []
    for idx in range(count):
        b_start = float(start_time) + idx * float(bucket_sec)
        buckets.append({
            "bucket_start": b_start,
            "bucket_end": b_start + float(bucket_sec),
            "label": time.strftime(fmt, time.gmtime(b_start)),
            "inflow": 0,
            "outflow": 0,
            "total": 0,
            "sightings": 0,
            "media_refs": [],
        })
    return buckets


def _bucket_index(ts: float, start_time: float, bucket_sec: int, count: int) -> Optional[int]:
    """Map a Unix epoch timestamp to a bucket index, or None if out of bounds."""
    if ts < start_time:
        return None
    idx = int((ts - start_time) // float(bucket_sec))
    if 0 <= idx < count:
        return idx
    if idx == count and ts <= start_time + count * float(bucket_sec):
        return count - 1
    return None


_FLOW_EVENT_TYPES = frozenset({"tripwire_cross", "zone_enter", "zone_exit"})


def _build_timeline_where(
    safe_start: float, safe_end: float, lookup: Optional[str],
    zone_id: Optional[str], event_type: Optional[str],
) -> tuple[str, list[Any]]:
    """Build parameterized WHERE clause for world_timeline_events flow queries."""
    clauses = ["timestamp >= ?", "timestamp <= ?"]
    params: list[Any] = [safe_start, safe_end]
    if event_type:
        clauses.append("event_type = ?")
        params.append(event_type)
    else:
        clauses.append("event_type IN ('tripwire_cross', 'zone_enter', 'zone_exit')")
    if lookup:
        clauses.append("(camera_id = ? OR video_filename = ?)")
        params.extend([lookup, lookup])
    if zone_id:
        clauses.append("zone_id = ?")
        params.append(zone_id)
    return " AND ".join(clauses), params


def _accumulate_timeline_events(
    cursor: Any, buckets: list[dict[str, Any]], safe_start: float, safe_end: float,
    safe_bucket: int, cam: Optional[str], zone_id: Optional[str] = None, event_type: Optional[str] = None,
) -> None:
    """Query world_timeline_events and accumulate inflow/outflow/total and media_refs per bucket."""
    if event_type and event_type not in _FLOW_EVENT_TYPES:
        return
    lookup = cam[6:].strip() if (cam and cam.startswith("video:")) else cam
    where_sql, ev_params = _build_timeline_where(safe_start, safe_end, lookup, zone_id, event_type)
    cursor.execute(
        "SELECT event_type, timestamp, camera_id, zone_id, entity_id, "
        "video_filename, media_offset_sec, run_id, metadata_json FROM world_timeline_events "
        f"WHERE {where_sql}",
        ev_params,
    )
    for row in cursor.fetchall():
        ts_val = float(row["timestamp"])
        idx = _bucket_index(ts_val, safe_start, safe_bucket, len(buckets))
        if idx is None:
            continue
        inf, outf, tot = _classify_flow_direction(row["event_type"], row["metadata_json"] or "")
        buckets[idx]["inflow"] += inf
        buckets[idx]["outflow"] += outf
        buckets[idx]["total"] += tot
        if len(buckets[idx]["media_refs"]) < _MAX_BUCKET_MEDIA_REFS:
            meta = _parse_meta_json(row["metadata_json"] or "")
            moff = row["media_offset_sec"] if row["media_offset_sec"] not in (None, 0.0, "") else meta.get("media_offset_sec", 0.0)
            buckets[idx]["media_refs"].append(_build_flow_media_ref(
                camera_id=row["camera_id"] or "", video_filename=row["video_filename"] or meta.get("video_filename") or "",
                media_offset_sec=moff, run_id=row["run_id"] or meta.get("run_id") or "",
                snapshot_path=meta.get("snapshot_path") or meta.get("crop_path") or "",
                zone_id=row["zone_id"] or meta.get("zone_id") or "", ts=ts_val,
                track_id=meta.get("track_id"), entity_id=row["entity_id"], bbox=meta.get("bbox"),
            ))


def _accumulate_sightings(
    cursor: Any, buckets: list[dict[str, Any]], safe_start: float, safe_end: float,
    safe_bucket: int, cam: Optional[str], zone_id: Optional[str] = None, event_type: Optional[str] = None,
) -> None:
    """Query sightings and accumulate sighting counts and media_refs per bucket."""
    if event_type and event_type != "sighting":
        return
    lookup = cam[6:].strip() if (cam and cam.startswith("video:")) else cam
    clauses = ["ts_epoch >= ?", "ts_epoch <= ?"]
    sig_params: list[Any] = [safe_start, safe_end]
    if lookup:
        clauses.append("(camera_id = ? OR source = ? OR video_filename = ?)")
        sig_params.extend([lookup, lookup, lookup])
    if zone_id:
        clauses.append("zone_id = ?")
        sig_params.append(zone_id)
    cursor.execute(
        "SELECT CASE WHEN typeof(timestamp) IN ('integer', 'real') THEN CAST(timestamp AS REAL) "
        "ELSE CAST(strftime('%s', timestamp) AS REAL) END AS ts_epoch, "
        "entity_id, track_id, source, camera_id, zone_id, bbox, snapshot_path, "
        f"video_filename, media_offset_sec, run_id FROM sightings WHERE {' AND '.join(clauses)}",
        sig_params,
    )
    for row in cursor.fetchall():
        ts_val = row["ts_epoch"]
        idx = _bucket_index(float(ts_val), safe_start, safe_bucket, len(buckets)) if ts_val is not None else None
        if idx is None:
            continue
        buckets[idx]["sightings"] += 1
        if len(buckets[idx]["media_refs"]) < _MAX_BUCKET_MEDIA_REFS:
            vfile = str(row["video_filename"] or "").strip()
            cam_id = str(row["camera_id"] or "").strip() or ("" if vfile else str(row["source"] or "").strip())
            buckets[idx]["media_refs"].append(_build_flow_media_ref(
                camera_id=cam_id, video_filename=vfile, media_offset_sec=row["media_offset_sec"],
                run_id=row["run_id"] or "", snapshot_path=row["snapshot_path"] or "",
                zone_id=row["zone_id"] or "", ts=float(ts_val), track_id=row["track_id"],
                entity_id=row["entity_id"], bbox=row["bbox"],
            ))


def _resolve_flow_source_ref(cam: Optional[str]) -> dict[str, Any]:
    """Build top-level SourceRef for a camera or video flow query."""
    if not cam:
        return {}
    lookup = cam[6:].strip() if cam.startswith("video:") else cam
    is_vid = cam.startswith("video:") or lookup.lower().endswith(_VIDEO_EXTS)
    return build_source_ref(video_filename=lookup) if is_vid else build_source_ref(camera_id=cam)


def _paginate_buckets(
    buckets: list[dict[str, Any]], page: Optional[int], page_size: Optional[int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Slice flow buckets when page_size is specified and return pagination metadata."""
    total_buckets = len(buckets)
    if page_size is None:
        return buckets, {
            "page": 1, "page_size": total_buckets, "total_buckets": total_buckets,
            "total_pages": 1, "has_prev": False, "has_next": False,
        }
    safe_ps = max(1, int(page_size))
    total_pages = max(1, int(math.ceil(total_buckets / float(safe_ps))))
    safe_page = max(1, min(int(page or 1), total_pages))
    start_idx = (safe_page - 1) * safe_ps
    return buckets[start_idx:start_idx + safe_ps], {
        "page": safe_page, "page_size": safe_ps, "total_buckets": total_buckets,
        "total_pages": total_pages, "has_prev": safe_page > 1, "has_next": safe_page < total_pages,
    }


def query_traffic_flows_sync(
    cursor: Any,
    start_time: float,
    end_time: float,
    bucket_sec: int,
    camera_id: Optional[str] = None,
    zone_id: Optional[str] = None,
    event_type: Optional[str] = None,
    page: Optional[int] = None,
    page_size: Optional[int] = None,
) -> dict[str, Any]:
    """Aggregate world_timeline_events and sightings into time buckets with optional filters/pagination."""
    safe_bucket = max(1, int(bucket_sec))
    safe_start = float(start_time)
    safe_end = max(safe_start + float(safe_bucket), float(end_time))
    cam = camera_id.strip() if camera_id and camera_id.strip() else None
    zone = zone_id.strip() if zone_id and zone_id.strip() else None
    ev_type = event_type.strip() if event_type and event_type.strip() else None

    all_buckets = _init_flow_buckets(safe_start, safe_end, safe_bucket)
    _accumulate_timeline_events(cursor, all_buckets, safe_start, safe_end, safe_bucket, cam, zone, ev_type)
    _accumulate_sightings(cursor, all_buckets, safe_start, safe_end, safe_bucket, cam, zone, ev_type)
    totals = {
        "inflow": sum(b["inflow"] for b in all_buckets),
        "outflow": sum(b["outflow"] for b in all_buckets),
        "total": sum(b["total"] for b in all_buckets),
        "sightings": sum(b["sightings"] for b in all_buckets),
    }
    page_buckets, pagination = _paginate_buckets(all_buckets, page, page_size)
    return {
        "camera_id": cam, "zone_id": zone, "event_type": ev_type,
        "source_ref": _resolve_flow_source_ref(cam),
        "start_time": safe_start, "end_time": safe_end, "bucket_sec": safe_bucket,
        "buckets": page_buckets, "totals": totals, "pagination": pagination,
        "axes": {
            "x": {"label": "Time", "unit": "epoch_s", "bucket_sec": safe_bucket},
            "y": {"label": "Crossings / Events", "unit": "count"},
        },
    }
