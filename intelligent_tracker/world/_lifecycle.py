"""Internal lifecycle, detachment, and event-building helpers for WorldGraph."""

from copy import deepcopy
from typing import Any

from intelligent_tracker.events.types import BaseEvent
from intelligent_tracker.world.events import (
    EntityStateChangedEvent,
    NodeAddedEvent,
    NodeRemovedEvent,
)
from intelligent_tracker.world.nodes import (
    CameraNode,
    TripwireNode,
    WorldEntity,
    ZoneNode,
)


def dispatch_events(event_bus: Any, events: list[BaseEvent]) -> None:
    """Publish queued events strictly outside WorldGraph._lock."""
    if event_bus is None or not events:
        return
    for event in events:
        event_bus.publish(event)


def build_entity_state_event(
    entity: WorldEntity,
    camera_id: str,
    change_type: str,
) -> EntityStateChangedEvent:
    """Build an EntityStateChangedEvent snapshot from a WorldEntity."""
    return EntityStateChangedEvent(
        camera_id=camera_id,
        world_entity_id=entity.world_entity_id,
        entity_id=entity.entity_id,
        session_id=entity.session_id,
        change_type=change_type,
        camera_tracks=dict(entity.camera_tracks),
        active_zones={k: sorted(v) for k, v in entity.active_zones.items()},
        global_xy=entity.global_xy,
        restricted=entity.restricted,
    )


def ensure_parent_camera(
    cameras: dict[str, CameraNode],
    camera_id: str,
    now: float,
    events: list[BaseEvent],
) -> CameraNode:
    """Return existing CameraNode or register a minimal parent stub for child edges."""
    parent = cameras.get(camera_id)
    if parent is not None:
        return parent
    parent = CameraNode(camera_id=camera_id, created_at=now, updated_at=now)
    cameras[camera_id] = parent
    events.append(
        NodeAddedEvent(
            camera_id=camera_id,
            node_id=parent.node_id,
            node_type="camera",
            parent_id=None,
            node_snapshot=parent.to_dict(),
        )
    )
    return parent


def register_camera_child(
    cameras: dict[str, CameraNode],
    registry: dict[str, Any],
    child_node: ZoneNode | TripwireNode,
    parent_edge_attr: str,
    now: float,
    events: list[BaseEvent],
) -> Any:
    """Register or update a ZoneNode or TripwireNode under its parent CameraNode."""
    parent = ensure_parent_camera(cameras, child_node.camera_id, now, events)
    existing = registry.get(child_node.node_id)
    stored = deepcopy(child_node)
    stored.updated_at = now
    if existing is not None:
        stored.created_at = existing.created_at
    else:
        events.append(
            NodeAddedEvent(
                camera_id=stored.camera_id,
                node_id=stored.node_id,
                node_type=stored.node_type,
                parent_id=stored.camera_id,
                node_snapshot=stored.to_dict(),
            )
        )
    registry[stored.node_id] = stored
    getattr(parent, parent_edge_attr).add(stored.node_id)
    parent.updated_at = now
    return deepcopy(stored)


def detach_camera_from_entities(
    entities: dict[str, WorldEntity],
    camera_id: str,
    now: float,
) -> list[EntityStateChangedEvent]:
    """Strip camera-specific track and zone bindings from all live WorldEntities."""
    events: list[EntityStateChangedEvent] = []
    for entity in entities.values():
        removed_track = entity.camera_tracks.pop(camera_id, None)
        removed_zones = entity.active_zones.pop(camera_id, None)
        if removed_track is None and removed_zones is None:
            continue
        entity.updated_at = now
        events.append(build_entity_state_event(entity, camera_id, "camera_detached"))
    return events


def detach_zone_from_entities(
    entities: dict[str, WorldEntity],
    zone: ZoneNode,
    now: float,
) -> list[EntityStateChangedEvent]:
    """Remove a deleted zone from active_zones across live entities."""
    events: list[EntityStateChangedEvent] = []
    for entity in entities.values():
        cam_zones = entity.active_zones.get(zone.camera_id)
        if not cam_zones:
            continue
        if not any(c in cam_zones for c in (zone.node_id, zone.zone_id)):
            continue
        cam_zones.discard(zone.node_id)
        cam_zones.discard(zone.zone_id)
        if not cam_zones:
            entity.active_zones.pop(zone.camera_id, None)
        entity.updated_at = now
        events.append(build_entity_state_event(entity, zone.camera_id, "zone_detached"))
    return events


def detach_camera_children(
    zones: dict[str, ZoneNode],
    tripwires: dict[str, TripwireNode],
    camera: CameraNode,
) -> tuple[list[str], list[BaseEvent]]:
    """Remove all child zones and tripwires belonging to camera under lock."""
    detached_ids: list[str] = []
    events: list[BaseEvent] = []
    targets: tuple[tuple[str, dict[str, Any], set[str]], ...] = (
        ("zone", zones, camera.zone_ids),
        ("tripwire", tripwires, camera.tripwire_ids),
    )
    for node_type, registry, edge_set in targets:
        matching = [
            nid for nid, node in registry.items()
            if node.camera_id == camera.camera_id or nid in edge_set
        ]
        for nid in matching:
            registry.pop(nid, None)
            detached_ids.append(nid)
            events.append(
                NodeRemovedEvent(
                    camera_id=camera.camera_id,
                    node_id=nid,
                    node_type=node_type,
                    parent_id=camera.camera_id,
                )
            )
    return detached_ids, events


def _remove_camera_child_node(
    cameras: dict[str, CameraNode],
    registry: dict[str, Any],
    edge_attr: str,
    node_id: str,
    now: float,
) -> tuple[Any, NodeRemovedEvent]:
    """Pop a zone or tripwire, detach its parent edge, and build NodeRemovedEvent."""
    node = registry.pop(node_id)
    parent = cameras.get(node.camera_id)
    if parent is not None:
        getattr(parent, edge_attr).discard(node_id)
        parent.updated_at = now
    event = NodeRemovedEvent(
        camera_id=node.camera_id,
        node_id=node_id,
        node_type=node.node_type,
        parent_id=node.camera_id,
    )
    return node, event


def remove_non_camera_node(
    cameras: dict[str, CameraNode],
    zones: dict[str, ZoneNode],
    tripwires: dict[str, TripwireNode],
    entities: dict[str, WorldEntity],
    node_id: str,
    now: float,
) -> tuple[bool, list[BaseEvent]]:
    """Remove a single zone, tripwire, or entity under lock and return removal events."""
    events: list[BaseEvent] = []
    if node_id in zones:
        zone, ev = _remove_camera_child_node(cameras, zones, "zone_ids", node_id, now)
        events.extend(detach_zone_from_entities(entities, zone, now))
        events.append(ev)
        return True, events

    if node_id in tripwires:
        _, ev = _remove_camera_child_node(cameras, tripwires, "tripwire_ids", node_id, now)
        events.append(ev)
        return True, events

    if node_id in entities:
        entities.pop(node_id)
        for zone in zones.values():
            zone.active_entity_ids.discard(node_id)
        events.append(NodeRemovedEvent(camera_id="world", node_id=node_id, node_type="entity"))
        return True, events

    return False, events


def find_entity_by_track(graph: Any, camera_id: str, track_id: int) -> WorldEntity | None:
    """Return a deep copy of the WorldEntity currently bound to (camera_id, track_id)."""
    with graph._lock:
        for entity in graph._entities.values():
            if entity.camera_tracks.get(camera_id) == track_id:
                return deepcopy(entity)
    return None


def list_entities_snapshot(graph: Any, camera_id: str | None = None) -> list[WorldEntity]:
    """Return isolated copies of live WorldEntities, optionally filtered by camera_id."""
    with graph._lock:
        return [
            deepcopy(entity)
            for entity in graph._entities.values()
            if camera_id is None or camera_id in entity.camera_tracks
        ]


def resolve_zone_node(graph: Any, camera_id: str, zone_id: str) -> ZoneNode | None:
    """Resolve a ZoneNode by scoped node_id or (camera_id, zone_id)."""
    if not zone_id:
        return None
    scoped_id = zone_id if ":zone:" in zone_id else f"{camera_id}:zone:{zone_id}"
    with graph._lock:
        zone = graph._zones.get(scoped_id) or graph._zones.get(zone_id)
        if zone is None:
            for candidate in graph._zones.values():
                if candidate.camera_id == camera_id and candidate.zone_id == zone_id:
                    zone = candidate
                    break
        return deepcopy(zone) if zone is not None else None


def resolve_tripwire_node(graph: Any, camera_id: str, tripwire_id: str) -> TripwireNode | None:
    """Resolve a TripwireNode by scoped node_id or (camera_id, tripwire_id)."""
    if not tripwire_id:
        return None
    scoped_id = tripwire_id if ":tripwire:" in tripwire_id else f"{camera_id}:tripwire:{tripwire_id}"
    with graph._lock:
        tw = graph._tripwires.get(scoped_id) or graph._tripwires.get(tripwire_id)
        if tw is None:
            for candidate in graph._tripwires.values():
                if candidate.camera_id == camera_id and candidate.tripwire_id == tripwire_id:
                    tw = candidate
                    break
        return deepcopy(tw) if tw is not None else None
