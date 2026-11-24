"""Pure time-bucketed traffic flow aggregation helpers for AnalyticsMixin."""

import json
import math
import time
from typing import Any, Optional

_INFLOW_DIRECTIONS = frozenset({"in", "enter", "entry", "inflow", "a_to_b", "forward"})
_OUTFLOW_DIRECTIONS = frozenset({"out", "exit", "egress", "outflow", "b_to_a", "reverse", "backward"})


def _classify_flow_direction(event_type: str, metadata_json: str) -> tuple[int, int, int]:
    """Return (inflow_inc, outflow_inc, total_inc) for a flow event row."""
    if event_type == "zone_enter":
        return 1, 0, 1
    if event_type == "zone_exit":
        return 0, 1, 1
    if event_type == "tripwire_cross":
        direction = ""
        if metadata_json:
            try:
                direction = str(json.loads(metadata_json).get("direction") or "").strip().lower()
            except (ValueError, TypeError):
                direction = ""
        if direction in _INFLOW_DIRECTIONS:
            return 1, 0, 1
        if direction in _OUTFLOW_DIRECTIONS:
            return 0, 1, 1
        return 0, 0, 1
    return 0, 0, 0


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


def _accumulate_timeline_events(
    cursor: Any,
    buckets: list[dict[str, Any]],
    safe_start: float,
    safe_end: float,
    safe_bucket: int,
    cam: Optional[str],
) -> None:
    """Query world_timeline_events and accumulate inflow/outflow/total per bucket."""
    cam_clause = " AND camera_id = ?" if cam else ""
    ev_params: list[Any] = [safe_start, safe_end] + ([cam] if cam else [])
    cursor.execute(
        "SELECT event_type, timestamp, metadata_json FROM world_timeline_events "
        "WHERE event_type IN ('tripwire_cross', 'zone_enter', 'zone_exit') "
        f"AND timestamp >= ? AND timestamp <= ?{cam_clause}",
        ev_params,
    )
    for row in cursor.fetchall():
        idx = _bucket_index(float(row["timestamp"]), safe_start, safe_bucket, len(buckets))
        if idx is None:
            continue
        inf, outf, tot = _classify_flow_direction(row["event_type"], row["metadata_json"] or "")
        buckets[idx]["inflow"] += inf
        buckets[idx]["outflow"] += outf
        buckets[idx]["total"] += tot


def _accumulate_sightings(
    cursor: Any,
    buckets: list[dict[str, Any]],
    safe_start: float,
    safe_end: float,
    safe_bucket: int,
    cam: Optional[str],
) -> None:
    """Query sightings and accumulate sighting counts per bucket."""
    src_clause = " AND source = ?" if cam else ""
    sig_params: list[Any] = [safe_start, safe_end] + ([cam] if cam else [])
    cursor.execute(
        "SELECT CASE WHEN typeof(timestamp) IN ('integer', 'real') THEN CAST(timestamp AS REAL) "
        "ELSE CAST(strftime('%s', timestamp) AS REAL) END AS ts_epoch "
        f"FROM sightings WHERE ts_epoch >= ? AND ts_epoch <= ?{src_clause}",
        sig_params,
    )
    for row in cursor.fetchall():
        ts_val = row["ts_epoch"]
        if ts_val is None:
            continue
        idx = _bucket_index(float(ts_val), safe_start, safe_bucket, len(buckets))
        if idx is not None:
            buckets[idx]["sightings"] += 1


def query_traffic_flows_sync(
    cursor: Any,
    start_time: float,
    end_time: float,
    bucket_sec: int,
    camera_id: Optional[str] = None,
) -> dict[str, Any]:
    """Aggregate world_timeline_events and sightings into time buckets."""
    safe_bucket = max(1, int(bucket_sec))
    safe_start = float(start_time)
    safe_end = max(safe_start + float(safe_bucket), float(end_time))
    cam = camera_id.strip() if camera_id and camera_id.strip() else None

    buckets = _init_flow_buckets(safe_start, safe_end, safe_bucket)
    _accumulate_timeline_events(cursor, buckets, safe_start, safe_end, safe_bucket, cam)
    _accumulate_sightings(cursor, buckets, safe_start, safe_end, safe_bucket, cam)

    totals = {
        "inflow": sum(b["inflow"] for b in buckets),
        "outflow": sum(b["outflow"] for b in buckets),
        "total": sum(b["total"] for b in buckets),
        "sightings": sum(b["sightings"] for b in buckets),
    }
    return {
        "camera_id": cam,
        "start_time": safe_start,
        "end_time": safe_end,
        "bucket_sec": safe_bucket,
        "buckets": buckets,
        "totals": totals,
        "axes": {
            "x": {"label": "Time", "unit": "epoch_s", "bucket_sec": safe_bucket},
            "y": {"label": "Crossings / Events", "unit": "count"},
        },
    }
