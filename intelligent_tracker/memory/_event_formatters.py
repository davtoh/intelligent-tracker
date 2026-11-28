"""Pure Event-to-Timeline Document Normalizers for EventFTSIndex."""

from datetime import datetime, timezone
import time
from typing import Any

from intelligent_tracker.events.types import (
    BaseEvent,
    EntityIdentifiedEvent,
    IntrusionAlert,
    OccupancyThresholdEvent,
    PetActivityEvent,
    RSACViolationEvent,
    RestrictedEntityAlert,
    ReviewItemQueuedEvent,
    TripwireCrossEvent,
    UnattendedItemAlert,
    ZoneEvent,
)
from intelligent_tracker.source_ref import build_source_ref
from intelligent_tracker.world.events import EntityStateChangedEvent

CANONICAL_SEVERITIES = ("info", "warning", "critical")


def normalize_zone_id(zone_id: Any) -> str:
    """Strip '<camera>:zone:' WorldGraph prefixes to a canonical unscoped zone name."""
    raw = str(zone_id or "").strip()
    if not raw:
        return ""
    if ":zone:" in raw:
        return raw.rsplit(":zone:", 1)[-1].strip()
    return raw


def resolve_event_severity(event: Any, default: str = "info") -> str:
    """Resolve canonical event severity ('info' | 'warning' | 'critical')."""
    meta = getattr(event, "metadata", None)
    raw = getattr(event, "severity", None)
    if not raw and isinstance(meta, dict):
        raw = meta.get("severity")
    text = str(raw or "").strip().lower()
    if text == "critical":
        return "critical"
    if text in ("warning", "warn"):
        return "warning"
    if text in ("info", "cleared"):
        return "info"
    fb = str(default or "info").strip().lower()
    return fb if fb in CANONICAL_SEVERITIES else "info"


def _append_severity_tag(tags: str, severity: str) -> str:
    """Ensure canonical severity appears in comma-separated tags without duplicates."""
    parts = [p.strip() for p in str(tags or "").split(",") if p.strip()]
    if severity and severity not in parts:
        parts.append(severity)
    return ",".join(parts)


def _format_dwell_window(entry_time: float | None, exit_time: float | None) -> str:
    """Format optional entry/exit epoch timestamps as a compact UTC window string."""
    if entry_time is None and exit_time is None:
        return ""

    def _fmt(ts: float) -> str:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%H:%M:%S")

    if entry_time is not None and exit_time is not None:
        return f" ({_fmt(entry_time)}-{_fmt(exit_time)} UTC)"
    if entry_time is not None:
        return f" (since {_fmt(entry_time)} UTC)"
    if exit_time is not None:
        return f" (until {_fmt(exit_time)} UTC)"
    return ""


def format_zone_event(event: ZoneEvent) -> dict[str, Any]:
    """Normalize a ZoneEvent into a timeline document payload."""
    who = event.entity_name or (f"Entity {event.entity_id}" if event.entity_id is not None else f"Track {event.track_id}")
    action = str(event.action or "enter").lower()
    zone_id = normalize_zone_id(event.zone_id)
    severity = resolve_event_severity(event, default="info")
    dwell_val = float(event.dwell_time or 0.0)
    window = _format_dwell_window(event.entry_time, event.exit_time)
    dwell = f" after {dwell_val:.1f}s{window}" if action in ("exit", "dwell") and dwell_val > 0 else window
    meta: dict[str, Any] = {
        "track_id": event.track_id,
        "action": action,
        "dwell_time": dwell_val,
        "severity": severity,
    }
    if event.entry_time is not None:
        meta["entry_time"] = float(event.entry_time)
    if event.exit_time is not None:
        meta["exit_time"] = float(event.exit_time)
    if event.bbox is not None:
        meta["bbox"] = list(event.bbox)
    return {
        "event_type": event.event_type or f"zone_{action}",
        "entity_id": event.entity_id,
        "entity_name": event.entity_name or "",
        "category": event.entity_category or "",
        "camera_id": event.camera_id,
        "zone_id": zone_id,
        "timestamp": event.timestamp,
        "confidence": 1.0,
        "title": f"Zone {action}: {zone_id}",
        "summary": f"{who} {action}ed zone {zone_id} on {event.camera_id}{dwell}.",
        "tags": _append_severity_tag(f"zone,{action},{zone_id}", severity),
        "metadata": meta,
    }


def format_tripwire_event(event: TripwireCrossEvent) -> dict[str, Any]:
    """Normalize a TripwireCrossEvent into a timeline document payload."""
    who = event.entity_name or (f"Entity {event.entity_id}" if event.entity_id is not None else f"Track {event.track_id}")
    zone_id = normalize_zone_id((event.metadata or {}).get("zone_id", ""))
    severity = resolve_event_severity(event, default="info")
    return {
        "event_type": event.event_type or "tripwire_cross",
        "entity_id": event.entity_id,
        "entity_name": event.entity_name or "",
        "category": event.entity_category or "",
        "camera_id": event.camera_id,
        "zone_id": zone_id,
        "timestamp": event.timestamp,
        "confidence": 1.0,
        "title": f"Tripwire cross: {event.tripwire_id}",
        "summary": f"{who} crossed tripwire {event.tripwire_id} ({event.direction}) on {event.camera_id}.",
        "tags": _append_severity_tag(f"tripwire,{event.tripwire_id},{event.direction}", severity),
        "metadata": {
            "track_id": event.track_id,
            "tripwire_id": event.tripwire_id,
            "direction": event.direction,
            "severity": severity,
        },
    }


def format_entity_state_event(event: EntityStateChangedEvent) -> dict[str, Any]:
    """Normalize a WorldGraph EntityStateChangedEvent into a timeline document payload."""
    zones = sorted({normalize_zone_id(z) for zlist in event.active_zones.values() for z in zlist if normalize_zone_id(z)})
    cams = sorted(event.camera_tracks.keys())
    cam_str = event.camera_id or (cams[0] if cams else "world")
    who = str((event.metadata or {}).get("entity_name") or (f"Entity {event.entity_id}" if event.entity_id is not None else event.world_entity_id))
    xy_text = f" at ({event.global_xy[0]:.2f}, {event.global_xy[1]:.2f})" if event.global_xy else ""
    zone_desc = f" in {', '.join(zones)}" if zones else ""
    severity = resolve_event_severity(event, default="info")
    base_tags = f"world,state,{event.change_type}" + (",restricted" if event.restricted else "")
    return {
        "event_type": event.event_type or "world_entity_state_changed",
        "entity_id": event.entity_id,
        "entity_name": str((event.metadata or {}).get("entity_name", "")),
        "category": str((event.metadata or {}).get("category", "")),
        "camera_id": cam_str,
        "zone_id": zones[0] if zones else "",
        "timestamp": event.timestamp,
        "confidence": float((event.metadata or {}).get("confidence", 1.0)),
        "title": f"Entity state {event.change_type}: {who}",
        "summary": f"{who} state {event.change_type} on {cam_str}{zone_desc}{xy_text}.",
        "tags": _append_severity_tag(base_tags, severity),
        "metadata": {
            "world_entity_id": event.world_entity_id,
            "zones": zones,
            "cameras": cams,
            "restricted": event.restricted,
            "severity": severity,
        },
    }


def format_identified_event(event: EntityIdentifiedEvent) -> dict[str, Any]:
    """Normalize an EntityIdentifiedEvent into a timeline sighting payload."""
    who = event.name or f"Entity {event.entity_id}"
    zone_id = normalize_zone_id(event.zone_id)
    zone_txt = f" in {zone_id}" if zone_id else ""
    severity = resolve_event_severity(event, default="info")
    return {
        "event_type": "sighting",
        "entity_id": event.entity_id,
        "entity_name": event.name,
        "category": event.category,
        "camera_id": event.camera_id,
        "zone_id": zone_id,
        "timestamp": event.timestamp,
        "confidence": float(event.similarity),
        "title": f"Sighting: {who}",
        "summary": event.message or f"Identified {who} ({event.category}) on {event.camera_id}{zone_txt} (sim {event.similarity:.2f}).",
        "tags": _append_severity_tag(f"sighting,identified,{event.category}", severity),
        "metadata": {
            "track_id": event.track_id,
            "similarity": event.similarity,
            "raw_event_type": event.event_type,
            "severity": severity,
        },
    }


def format_security_event(event: Any) -> dict[str, Any]:
    """Normalize RSACViolationEvent, IntrusionAlert, or RestrictedEntityAlert."""
    name = getattr(event, "entity_name", None) or getattr(event, "name", "") or "Unknown"
    reason = getattr(event, "reason", "") or getattr(event, "message", "") or event.event_type
    zone_id = normalize_zone_id(getattr(event, "zone_id", ""))
    severity = resolve_event_severity(event, default="warning")
    return {
        "event_type": event.event_type,
        "entity_id": getattr(event, "entity_id", None),
        "entity_name": name,
        "category": getattr(event, "entity_category", None) or getattr(event, "category", "") or "",
        "camera_id": event.camera_id,
        "zone_id": zone_id,
        "timestamp": event.timestamp,
        "confidence": 1.0,
        "title": f"Security {event.event_type}: {zone_id or event.camera_id}",
        "summary": f"{name} triggered {event.event_type} in {zone_id or event.camera_id} on {event.camera_id}: {reason}.",
        "tags": _append_severity_tag(f"security,alert,{event.event_type}", severity),
        "metadata": {"severity": severity, "track_id": getattr(event, "track_id", 0)},
    }


def format_generic_event(event: BaseEvent) -> dict[str, Any]:
    """Normalize PetActivityEvent, OccupancyThresholdEvent, or generic BaseEvent."""
    meta = dict(getattr(event, "metadata", {}) or {})
    severity = resolve_event_severity(event, default="info")
    meta["severity"] = severity
    zone_id = normalize_zone_id(getattr(event, "zone_id", ""))
    if isinstance(event, PetActivityEvent):
        who = event.entity_name or "Pet"
        return {
            "event_type": event.event_type or "pet_activity",
            "entity_id": event.entity_id,
            "entity_name": who,
            "category": event.entity_category or "pet",
            "camera_id": event.camera_id,
            "zone_id": zone_id,
            "timestamp": event.timestamp,
            "confidence": 1.0,
            "title": f"Pet activity: {who}",
            "summary": f"{who} detected in {zone_id or event.camera_id} on {event.camera_id}: {event.message}",
            "tags": _append_severity_tag("pet,activity,suppressed_alarm", severity),
            "metadata": {"track_id": event.track_id, "severity": severity},
        }
    summary = getattr(event, "message", "") or str(meta.get("summary", "")) or f"{event.event_type} on {event.camera_id}"
    return {
        "event_type": getattr(event, "event_type", "event"),
        "entity_id": getattr(event, "entity_id", None) or getattr(event, "suggested_entity_id", None),
        "entity_name": getattr(event, "entity_name", None) or getattr(event, "suggested_name", "") or "",
        "category": getattr(event, "entity_category", None) or getattr(event, "suggested_category", "") or "",
        "camera_id": getattr(event, "camera_id", ""),
        "zone_id": zone_id,
        "timestamp": getattr(event, "timestamp", time.time()),
        "confidence": float(getattr(event, "similarity", 1.0) or 1.0),
        "title": str(meta.get("title", event.event_type)),
        "summary": summary,
        "tags": _append_severity_tag(str(meta.get("tags", event.event_type)), severity),
        "metadata": meta,
    }


def format_unattended_item_event(event: UnattendedItemAlert) -> dict[str, Any]:
    """Normalize an UnattendedItemAlert into a timeline document payload."""
    loc = normalize_zone_id(event.location) or event.camera_id
    who = event.owner_name or (f"Entity {event.owner_entity_id}" if event.owner_entity_id is not None else "Unknown owner")
    severity = resolve_event_severity(event, default="warning")
    summary = (
        event.message
        or f"Unattended {event.item_label} (track {event.bag_track_id}) left at {loc} by {who} for {event.unattended_duration_s:.1f}s."
    )
    return {
        "event_type": event.event_type or "unattended_item",
        "entity_id": event.owner_entity_id,
        "entity_name": event.owner_name,
        "category": "unattended_item",
        "camera_id": event.camera_id,
        "zone_id": loc,
        "timestamp": event.timestamp,
        "confidence": 1.0,
        "title": f"Unattended {event.item_label}: {loc}",
        "summary": summary,
        "tags": _append_severity_tag(f"unattended,alert,{event.item_label},{loc}", severity),
        "metadata": {
            "location": loc,
            "global_xy": event.global_xy,
            "bbox": event.bbox,
            "owner_entity_id": event.owner_entity_id,
            "owner_world_entity_id": event.owner_world_entity_id,
            "owner_name": event.owner_name,
            "bag_track_id": event.bag_track_id,
            "item_label": event.item_label,
            "unattended_duration_s": event.unattended_duration_s,
            "severity": severity,
        },
    }


def _attach_media_provenance(event: Any, doc: dict[str, Any]) -> None:
    """Attach video/media offset, run_id, and canonical SourceRef to a timeline doc."""
    raw_meta = getattr(event, "metadata", None)
    meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
    raw_doc_meta = doc.get("metadata")
    doc_meta: dict[str, Any] = raw_doc_meta if isinstance(raw_doc_meta, dict) else {}
    vfile = str(getattr(event, "video_filename", None) or meta.get("video_filename") or "").strip()
    m_off = float(getattr(event, "media_offset_sec", None) or meta.get("media_offset_sec") or 0.0)
    run_id = str(getattr(event, "run_id", None) or meta.get("run_id") or "").strip()
    if run_id and isinstance(doc.get("metadata"), dict):
        doc["metadata"]["run_id"] = run_id
    doc["video_filename"] = vfile
    doc["media_offset_sec"] = m_off
    doc["run_id"] = run_id
    doc["source_ref"] = build_source_ref(
        camera_id=str(doc.get("camera_id") or ""),
        video_filename=vfile,
        run_id=run_id,
        media_offset_sec=m_off,
        ts=doc.get("timestamp"),
        track_id=doc_meta.get("track_id"),
        entity_id=doc.get("entity_id"),
        zone_id=str(doc.get("zone_id") or ""),
        bbox=doc_meta.get("bbox"),
        snapshot_path=str(
            getattr(event, "snapshot_path", None)
            or getattr(event, "crop_path", None)
            or meta.get("snapshot_path")
            or meta.get("crop_path")
            or ""
        ),
    )


def normalize_event_doc(event: Any) -> dict[str, Any] | None:
    """Convert any supported pipeline/world event into a timeline document dict."""
    doc: dict[str, Any] | None = None
    if isinstance(event, ZoneEvent):
        doc = format_zone_event(event)
    elif isinstance(event, TripwireCrossEvent):
        doc = format_tripwire_event(event)
    elif isinstance(event, EntityStateChangedEvent):
        doc = format_entity_state_event(event)
    elif isinstance(event, EntityIdentifiedEvent):
        doc = format_identified_event(event)
    elif isinstance(event, UnattendedItemAlert):
        doc = format_unattended_item_event(event)
    elif isinstance(event, (RSACViolationEvent, IntrusionAlert, RestrictedEntityAlert)):
        doc = format_security_event(event)
    elif isinstance(event, (PetActivityEvent, OccupancyThresholdEvent, ReviewItemQueuedEvent, BaseEvent)):
        doc = format_generic_event(event)
    if doc is not None:
        _attach_media_provenance(event, doc)
    return doc

