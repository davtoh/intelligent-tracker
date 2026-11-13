"""Pure Event-to-Timeline Document Normalizers for EventFTSIndex."""

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
    ZoneEvent,
)
from intelligent_tracker.world.events import EntityStateChangedEvent


def format_zone_event(event: ZoneEvent) -> dict[str, Any]:
    """Normalize a ZoneEvent into a timeline document payload."""
    who = event.entity_name or (f"Entity {event.entity_id}" if event.entity_id is not None else f"Track {event.track_id}")
    action = str(event.action or "enter").lower()
    dwell = f" after {event.dwell_time:.1f}s" if action in ("exit", "dwell") and event.dwell_time > 0 else ""
    return {
        "event_type": event.event_type or f"zone_{action}",
        "entity_id": event.entity_id,
        "entity_name": event.entity_name or "",
        "category": event.entity_category or "",
        "camera_id": event.camera_id,
        "zone_id": event.zone_id,
        "timestamp": event.timestamp,
        "confidence": 1.0,
        "title": f"Zone {action}: {event.zone_id}",
        "summary": f"{who} {action}ed zone {event.zone_id} on {event.camera_id}{dwell}.",
        "tags": f"zone,{action},{event.zone_id}",
        "metadata": {"track_id": event.track_id, "action": action, "dwell_time": event.dwell_time},
    }


def format_tripwire_event(event: TripwireCrossEvent) -> dict[str, Any]:
    """Normalize a TripwireCrossEvent into a timeline document payload."""
    who = event.entity_name or (f"Entity {event.entity_id}" if event.entity_id is not None else f"Track {event.track_id}")
    return {
        "event_type": event.event_type or "tripwire_cross",
        "entity_id": event.entity_id,
        "entity_name": event.entity_name or "",
        "category": event.entity_category or "",
        "camera_id": event.camera_id,
        "zone_id": str((event.metadata or {}).get("zone_id", "")),
        "timestamp": event.timestamp,
        "confidence": 1.0,
        "title": f"Tripwire cross: {event.tripwire_id}",
        "summary": f"{who} crossed tripwire {event.tripwire_id} ({event.direction}) on {event.camera_id}.",
        "tags": f"tripwire,{event.tripwire_id},{event.direction}",
        "metadata": {"track_id": event.track_id, "tripwire_id": event.tripwire_id, "direction": event.direction},
    }


def format_entity_state_event(event: EntityStateChangedEvent) -> dict[str, Any]:
    """Normalize a WorldGraph EntityStateChangedEvent into a timeline document payload."""
    zones = sorted({z for zlist in event.active_zones.values() for z in zlist})
    cams = sorted(event.camera_tracks.keys())
    cam_str = event.camera_id or (cams[0] if cams else "world")
    who = str((event.metadata or {}).get("entity_name") or (f"Entity {event.entity_id}" if event.entity_id is not None else event.world_entity_id))
    xy_text = f" at ({event.global_xy[0]:.2f}, {event.global_xy[1]:.2f})" if event.global_xy else ""
    zone_desc = f" in {', '.join(zones)}" if zones else ""
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
        "tags": f"world,state,{event.change_type}" + (",restricted" if event.restricted else ""),
        "metadata": {"world_entity_id": event.world_entity_id, "zones": zones, "cameras": cams, "restricted": event.restricted},
    }


def format_identified_event(event: EntityIdentifiedEvent) -> dict[str, Any]:
    """Normalize an EntityIdentifiedEvent into a timeline sighting payload."""
    who = event.name or f"Entity {event.entity_id}"
    zone_txt = f" in {event.zone_id}" if event.zone_id else ""
    return {
        "event_type": "sighting",
        "entity_id": event.entity_id,
        "entity_name": event.name,
        "category": event.category,
        "camera_id": event.camera_id,
        "zone_id": event.zone_id or "",
        "timestamp": event.timestamp,
        "confidence": float(event.similarity),
        "title": f"Sighting: {who}",
        "summary": event.message or f"Identified {who} ({event.category}) on {event.camera_id}{zone_txt} (sim {event.similarity:.2f}).",
        "tags": f"sighting,identified,{event.category}",
        "metadata": {"track_id": event.track_id, "similarity": event.similarity, "raw_event_type": event.event_type},
    }


def format_security_event(event: Any) -> dict[str, Any]:
    """Normalize RSACViolationEvent, IntrusionAlert, or RestrictedEntityAlert."""
    name = getattr(event, "entity_name", None) or getattr(event, "name", "") or "Unknown"
    reason = getattr(event, "reason", "") or getattr(event, "message", "") or event.event_type
    zone_id = getattr(event, "zone_id", "") or ""
    severity = getattr(event, "severity", "warning")
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
        "tags": f"security,alert,{event.event_type},{severity}",
        "metadata": {"severity": severity, "track_id": getattr(event, "track_id", 0)},
    }


def format_generic_event(event: BaseEvent) -> dict[str, Any]:
    """Normalize PetActivityEvent, OccupancyThresholdEvent, or generic BaseEvent."""
    meta = dict(getattr(event, "metadata", {}) or {})
    if isinstance(event, PetActivityEvent):
        who = event.entity_name or "Pet"
        return {
            "event_type": event.event_type or "pet_activity",
            "entity_id": event.entity_id,
            "entity_name": who,
            "category": event.entity_category or "pet",
            "camera_id": event.camera_id,
            "zone_id": event.zone_id,
            "timestamp": event.timestamp,
            "confidence": 1.0,
            "title": f"Pet activity: {who}",
            "summary": f"{who} detected in {event.zone_id or event.camera_id} on {event.camera_id}: {event.message}",
            "tags": "pet,activity,suppressed_alarm",
            "metadata": {"track_id": event.track_id},
        }
    summary = getattr(event, "message", "") or str(meta.get("summary", "")) or f"{event.event_type} on {event.camera_id}"
    return {
        "event_type": getattr(event, "event_type", "event"),
        "entity_id": getattr(event, "entity_id", None) or getattr(event, "suggested_entity_id", None),
        "entity_name": getattr(event, "entity_name", None) or getattr(event, "suggested_name", "") or "",
        "category": getattr(event, "entity_category", None) or getattr(event, "suggested_category", "") or "",
        "camera_id": getattr(event, "camera_id", ""),
        "zone_id": getattr(event, "zone_id", "") or "",
        "timestamp": getattr(event, "timestamp", time.time()),
        "confidence": float(getattr(event, "similarity", 1.0) or 1.0),
        "title": str(meta.get("title", event.event_type)),
        "summary": summary,
        "tags": str(meta.get("tags", event.event_type)),
        "metadata": meta,
    }


def normalize_event_doc(event: Any) -> dict[str, Any] | None:
    """Convert any supported pipeline/world event into a timeline document dict."""
    if isinstance(event, ZoneEvent):
        return format_zone_event(event)
    if isinstance(event, TripwireCrossEvent):
        return format_tripwire_event(event)
    if isinstance(event, EntityStateChangedEvent):
        return format_entity_state_event(event)
    if isinstance(event, EntityIdentifiedEvent):
        return format_identified_event(event)
    if isinstance(event, (RSACViolationEvent, IntrusionAlert, RestrictedEntityAlert)):
        return format_security_event(event)
    if isinstance(event, (PetActivityEvent, OccupancyThresholdEvent, ReviewItemQueuedEvent, BaseEvent)):
        return format_generic_event(event)
    return None

