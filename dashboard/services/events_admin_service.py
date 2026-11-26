"""Service helpers for alert facets, acknowledgement, clearing, and CSV/JSON export."""

import csv
import io
from typing import Any

from dashboard.services.stream_telemetry import invalidate_unread_alert_cache

_CSV_COLUMNS = [
    "id", "timestamp", "event_type", "severity", "camera_id", "zone_id",
    "entity_id", "entity_name", "category", "title", "summary", "is_read", "acknowledged_at",
]


def get_event_facets(db: Any, pool: Any = None) -> dict[str, list[str]]:
    """Return distinct event facets unioned with live CameraPool camera IDs."""
    facets = (
        db.get_timeline_event_facets()
        if db is not None and hasattr(db, "get_timeline_event_facets")
        else {"cameras": [], "zones": [], "event_types": [], "severities": []}
    )
    cameras = set(facets.get("cameras", []))
    if pool is not None and hasattr(pool, "list_cameras"):
        try:
            for item in pool.list_cameras() or []:
                cid = str(item.get("camera_id") or item.get("id") or "").strip() if isinstance(item, dict) else str(item or "").strip()
                if cid:
                    cameras.add(cid)
        except Exception:
            pass
    severities = set(facets.get("severities", [])) | {"critical", "warning", "info"}
    return {
        "cameras": sorted(cameras),
        "zones": sorted(set(facets.get("zones", []))),
        "event_types": sorted(set(facets.get("event_types", []))),
        "severities": sorted(severities),
    }


def acknowledge_events(
    db: Any, *, event_ids: list[int] | None = None, mark_all: bool = False, is_read: bool = True,
) -> dict[str, Any]:
    """Acknowledge or un-acknowledge timeline events and return updated unread count."""
    updated = db.acknowledge_timeline_events(event_ids=event_ids, mark_all=mark_all, is_read=is_read)
    invalidate_unread_alert_cache()
    unread = db.count_unread_timeline_events()
    return {"updated": updated, "is_read": bool(is_read), "unread_alert_count": unread}


def delete_event(db: Any, event_id: int) -> dict[str, Any] | None:
    """Delete a single timeline event by ID, returning None if not found."""
    if not db.delete_timeline_event(event_id):
        return None
    invalidate_unread_alert_cache()
    return {"deleted": True, "event_id": event_id, "unread_alert_count": db.count_unread_timeline_events()}


def clear_events(
    db: Any, *, camera_id: str | None = None, severity: str | None = None,
    event_type: str | None = None, zone_id: str | None = None, read_only: bool = False,
) -> dict[str, Any]:
    """Clear timeline events matching filters and return remaining unread count."""
    deleted = db.clear_timeline_events(
        camera_id=camera_id, severity=severity, event_type=event_type,
        zone_id=zone_id, read_only=read_only,
    )
    invalidate_unread_alert_cache()
    return {"deleted": deleted, "unread_alert_count": db.count_unread_timeline_events()}


def format_events_csv(rows: list[dict[str, Any]]) -> str:
    """Serialize timeline event rows into a UTF-8 CSV string."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_COLUMNS)
    writer.writeheader()
    for row in rows:
        raw_meta = row.get("metadata")
        meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
        sev = str(row.get("severity") or meta.get("severity") or "")
        writer.writerow({
            "id": row.get("id", ""),
            "timestamp": row.get("timestamp", ""),
            "event_type": row.get("event_type", ""),
            "severity": sev,
            "camera_id": row.get("camera_id", ""),
            "zone_id": row.get("zone_id", ""),
            "entity_id": row.get("entity_id", ""),
            "entity_name": row.get("entity_name", ""),
            "category": row.get("category", ""),
            "title": row.get("title", ""),
            "summary": row.get("summary", ""),
            "is_read": bool(row.get("is_read", False)),
            "acknowledged_at": row.get("acknowledged_at", ""),
        })
    return buf.getvalue()
