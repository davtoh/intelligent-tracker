"""Alerts & Timeline Event Query Service for GET /events."""

from dataclasses import asdict
from typing import Any, Optional

from intelligent_tracker.repositories._event_filter_sql import matches_event_filters


def _event_to_dict(ev: Any) -> dict[str, Any]:
    """Normalize an EventBus event object into a plain dictionary."""
    if hasattr(ev, "to_dict"):
        return dict(ev.to_dict())
    if hasattr(ev, "__dataclass_fields__"):
        return asdict(ev)
    return {"event_type": getattr(ev, "event_type", "event")}


def _matches_filters(
    item: dict[str, Any], camera_id: Optional[str], severity: Optional[str],
    event_type: Optional[str], zone_id: Optional[str],
    start_time: Optional[float], end_time: Optional[float],
    min_severity: Optional[str] = None,
) -> bool:
    """Apply structured filters in-memory to an EventBus event dict."""
    return matches_event_filters(
        item,
        camera_id=camera_id,
        severity=severity,
        min_severity=min_severity,
        event_type=event_type,
        zone_id=zone_id,
        start_time=start_time,
        end_time=end_time,
    )


def _dedupe_key(item: dict[str, Any]) -> tuple[Any, Any, float]:
    """Build deterministic deduplication key across EventBus and TrackerDB."""
    return (item.get("event_type"), item.get("camera_id"), round(float(item.get("timestamp") or 0.0), 3))


def _collect_bus_events(
    mgr: Any, fetch_window: int, seen: set[tuple[Any, Any, float]],
    camera_id: Optional[str], severity: Optional[str], event_type: Optional[str],
    zone_id: Optional[str], start_time: Optional[float], end_time: Optional[float],
    min_severity: Optional[str] = None,
) -> tuple[list[dict[str, Any]], set[tuple[Any, Any, float]]]:
    """Collect filtered EventBus events and track their deduplication keys."""
    items: list[dict[str, Any]] = []
    bus_keys: set[tuple[Any, Any, float]] = set()
    if not (mgr and getattr(mgr, "event_bus", None)):
        return items, bus_keys
    for ev in mgr.event_bus.get_recent_events(limit=max(fetch_window, 200)):
        item = _event_to_dict(ev)
        if not _matches_filters(
            item, camera_id, severity, event_type, zone_id, start_time, end_time, min_severity=min_severity
        ):
            continue
        key = _dedupe_key(item)
        if key not in seen:
            seen.add(key)
            bus_keys.add(key)
            items.append(item)
    return items, bus_keys


def _collect_db_events(
    db: Any, fetch_window: int, seen: set[tuple[Any, Any, float]],
    bus_keys: set[tuple[Any, Any, float]], camera_id: Optional[str],
    severity: Optional[str], event_type: Optional[str], zone_id: Optional[str],
    start_time: Optional[float], end_time: Optional[float],
    min_severity: Optional[str] = None,
) -> tuple[list[dict[str, Any]], int]:
    """Collect filtered TrackerDB timeline events and total matching row count."""
    if db is None or not hasattr(db, "search_timeline_events"):
        return [], 0
    rows = db.search_timeline_events(
        camera_id=camera_id, zone_id=zone_id, event_type=event_type,
        start_time=start_time, end_time=end_time, severity=severity,
        min_severity=min_severity, limit=fetch_window, offset=0,
    )
    items: list[dict[str, Any]] = []
    for row in rows:
        key = _dedupe_key(row)
        bus_keys.discard(key)
        if key not in seen:
            seen.add(key)
            items.append(row)
    db_total = db.count_timeline_events(
        camera_id=camera_id, zone_id=zone_id, event_type=event_type,
        start_time=start_time, end_time=end_time, severity=severity,
        min_severity=min_severity,
    ) if hasattr(db, "count_timeline_events") else 0
    return items, db_total


def _safe_unread_count(db: Any) -> int:
    if db is None or getattr(db, "_closed", False) or not hasattr(db, "count_unread_timeline_events"):
        return 0
    try:
        return int(db.count_unread_timeline_events())
    except Exception:
        return 0


def query_merged_events(
    mgr: Any, db: Any, *, camera_id: Optional[str] = None, severity: Optional[str] = None,
    min_severity: Optional[str] = None, event_type: Optional[str] = None,
    zone_id: Optional[str] = None, start_time: Optional[float] = None, end_time: Optional[float] = None,
    limit: int = 50, offset: int = 0, paginated: bool = False,
) -> list[dict[str, Any]] | dict[str, Any]:
    """Merge live EventBus alerts with TrackerDB timeline events and optionally paginate."""
    safe_limit = max(1, min(500, int(limit)))
    safe_offset = max(0, int(offset))
    fetch_window = safe_limit + safe_offset
    seen: set[tuple[Any, Any, float]] = set()
    if db is not None and not getattr(db, "_closed", False) and hasattr(db, "search_timeline_events"):
        merged, db_total = _collect_db_events(
            db, fetch_window, seen, set(), camera_id, severity, event_type,
            zone_id, start_time, end_time, min_severity=min_severity,
        )
        bus_keys: set[tuple[Any, Any, float]] = set()
    else:
        merged, bus_keys = _collect_bus_events(
            mgr, fetch_window, seen, camera_id, severity, event_type,
            zone_id, start_time, end_time, min_severity=min_severity,
        )
        db_total = 0
    merged.sort(key=lambda e: float(e.get("timestamp") or 0.0), reverse=True)
    page_items = merged[safe_offset : safe_offset + safe_limit]
    if not paginated and safe_offset == 0:
        return page_items
    total = max(len(merged), db_total + len(bus_keys))
    return {
        "items": page_items, "total": total, "offset": safe_offset, "limit": safe_limit,
        "has_more": (safe_offset + len(page_items)) < total,
        "unread_alert_count": _safe_unread_count(db),
    }
