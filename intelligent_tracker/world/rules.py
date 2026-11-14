"""Reactive WorldRuleEngine subscribing to EventBus telemetry for WorldGraph updates."""

import threading
from typing import Any

from intelligent_tracker.events.types import (
    BaseEvent,
    EntityIdentifiedEvent,
    RestrictedEntityAlert,
    TripwireCrossEvent,
    ZoneEvent,
)
from intelligent_tracker.matching.types import (
    EntityIdentifiedEvent as MatchingEntityIdentifiedEvent,
)
from intelligent_tracker.world._lifecycle import (
    find_entity_by_track,
    resolve_tripwire_node,
    resolve_zone_node,
)
from intelligent_tracker.world.events import WorldPolicyUpdatedEvent
from intelligent_tracker.world.graph import WorldGraph
from intelligent_tracker.world.nodes import TripwireNode, WorldEntity, ZoneNode

_RESTRICTED_CATEGORIES = frozenset({"restricted", "banned", "blacklisted"})
_POLICY_KEYS = ("quiet_hours", "dwell_override", "alert_sensitivity", "extra")
_SUBSCRIBED_EVENT_TYPES = (
    ZoneEvent,
    TripwireCrossEvent,
    EntityIdentifiedEvent,
    MatchingEntityIdentifiedEvent,
    RestrictedEntityAlert,
    WorldPolicyUpdatedEvent,
)


def _find_target_entity(
    graph: WorldGraph,
    camera_id: str,
    track_id: int | None,
    entity_id: int | None,
) -> WorldEntity | None:
    """Resolve a live WorldEntity by persistent entity_id first, then (camera_id, track_id)."""
    if entity_id is not None:
        by_eid = graph.get_node(f"entity:{entity_id}", node_type="entity")
        if isinstance(by_eid, WorldEntity):
            return by_eid
    if camera_id and track_id is not None:
        return find_entity_by_track(graph, camera_id, int(track_id))
    return None


def _ensure_zone_for_event(graph: WorldGraph, camera_id: str, zone_id: str) -> ZoneNode | None:
    """Resolve existing ZoneNode or register one if its parent CameraNode is active."""
    zone = resolve_zone_node(graph, camera_id, zone_id)
    if zone is not None:
        return zone
    if graph.get_node(camera_id, node_type="camera") is None:
        return None
    return graph.register_zone(ZoneNode(zone_id=zone_id, camera_id=camera_id))


def _ensure_tripwire_for_event(
    graph: WorldGraph,
    camera_id: str,
    tripwire_id: str,
) -> TripwireNode | None:
    """Resolve existing TripwireNode or register one if its parent CameraNode is active."""
    tw = resolve_tripwire_node(graph, camera_id, tripwire_id)
    if tw is not None:
        return tw
    if graph.get_node(camera_id, node_type="camera") is None:
        return None
    return graph.register_tripwire(TripwireNode(tripwire_id=tripwire_id, camera_id=camera_id))


def _mutate_zone_membership(
    zone: ZoneNode,
    entity: WorldEntity | None,
    event: ZoneEvent,
) -> tuple[bool, bool]:
    """Mutate ZoneNode and optional WorldEntity membership for enter/dwell/exit events."""
    zone_changed = False
    entity_changed = False
    if event.action in ("enter", "dwell"):
        if event.track_id not in zone.active_track_ids:
            zone.active_track_ids.add(event.track_id)
            zone_changed = True
        if entity is not None:
            if entity.world_entity_id not in zone.active_entity_ids:
                zone.active_entity_ids.add(entity.world_entity_id)
                zone_changed = True
            cam_zones = entity.active_zones.setdefault(event.camera_id, set())
            if zone.node_id not in cam_zones:
                cam_zones.add(zone.node_id)
                entity_changed = True
    elif event.action == "exit":
        if event.track_id in zone.active_track_ids:
            zone.active_track_ids.discard(event.track_id)
            zone_changed = True
        if entity is not None:
            if entity.world_entity_id in zone.active_entity_ids:
                zone.active_entity_ids.discard(entity.world_entity_id)
                zone_changed = True
            cam_zones = entity.active_zones.get(event.camera_id)
            if cam_zones and any(z in cam_zones for z in (zone.node_id, event.zone_id)):
                cam_zones.discard(zone.node_id)
                cam_zones.discard(event.zone_id)
                if not cam_zones:
                    entity.active_zones.pop(event.camera_id, None)
                entity_changed = True
    return zone_changed, entity_changed


def _compute_policy_delta(
    current: dict[str, Any],
    incoming: dict[str, Any],
    changed_fields: list[str],
) -> dict[str, Any]:
    """Return only policy fields whose values differ from the active WorldPolicy."""
    keys = [k for k in changed_fields if k in _POLICY_KEYS] if changed_fields else list(_POLICY_KEYS)
    updates: dict[str, Any] = {}
    for key in keys:
        if key not in incoming:
            continue
        if key == "extra" and isinstance(incoming[key], dict):
            merged = {**current.get("extra", {}), **incoming[key]}
            if merged != current.get("extra", {}):
                updates["extra"] = incoming[key]
        elif incoming[key] != current.get(key):
            updates[key] = incoming[key]
    return updates


class WorldRuleEngine:
    """Subscribes to EventBus events to keep WorldGraph occupancy, flags, and policy in sync."""

    def __init__(self, world_graph: WorldGraph, event_bus: Any = None) -> None:
        self.world_graph = world_graph
        self.event_bus = event_bus
        self._lock = threading.Lock()
        self._started = False

    @property
    def is_running(self) -> bool:
        """Return True when subscribed to the configured EventBus."""
        with self._lock:
            return self._started

    def start(self) -> bool:
        """Subscribe to world-relevant EventBus channels (idempotent)."""
        with self._lock:
            if self._started or self.event_bus is None:
                return False
            self.event_bus.subscribe(self._on_event, event_type=_SUBSCRIBED_EVENT_TYPES)
            self._started = True
            return True

    def stop(self) -> bool:
        """Unsubscribe from the EventBus cleanly (idempotent)."""
        with self._lock:
            if not self._started:
                return False
            if self.event_bus is not None:
                self.event_bus.unsubscribe(self._on_event)
            self._started = False
            return True

    def _on_event(self, event: BaseEvent) -> None:
        """Dispatch supported telemetry and policy events to WorldGraph."""
        if isinstance(event, ZoneEvent):
            self._apply_zone_event(event)
        elif isinstance(event, TripwireCrossEvent):
            self._apply_tripwire_event(event)
        elif isinstance(event, (EntityIdentifiedEvent, MatchingEntityIdentifiedEvent)):
            self._apply_identified_event(event)
        elif isinstance(event, RestrictedEntityAlert):
            self._apply_restricted_alert(event)
        elif isinstance(event, WorldPolicyUpdatedEvent):
            self._apply_policy_event(event)

    def _apply_zone_event(self, event: ZoneEvent) -> None:
        """Update ZoneNode occupancy and WorldEntity.active_zones on enter/dwell/exit."""
        zone = _ensure_zone_for_event(self.world_graph, event.camera_id, event.zone_id)
        if zone is None:
            return
        entity = _find_target_entity(
            self.world_graph, event.camera_id, event.track_id, event.entity_id
        )
        zone_changed, entity_changed = _mutate_zone_membership(zone, entity, event)
        if zone_changed:
            self.world_graph.register_zone(zone)
        if entity_changed and entity is not None:
            entity.last_seen = max(entity.last_seen, float(event.timestamp))
            self.world_graph.upsert_entity(entity)

    def _apply_tripwire_event(self, event: TripwireCrossEvent) -> None:
        """Increment crossing_count on the matching TripwireNode."""
        tw = _ensure_tripwire_for_event(self.world_graph, event.camera_id, event.tripwire_id)
        if tw is None:
            return
        tw.crossing_count += 1
        self.world_graph.register_tripwire(tw)

    def _apply_identified_event(self, event: Any) -> None:
        """Converge EntityIdentifiedEvent metadata onto the live WorldEntity."""
        camera_id = getattr(event, "camera_id", "") or getattr(event, "source", "") or "cam_01"
        entity_id = getattr(event, "entity_id", None)
        if entity_id is None:
            return

        existing = self.world_graph.get_node(f"entity:{entity_id}", node_type="entity")
        is_restricted = str(getattr(event, "category", "")).lower() in _RESTRICTED_CATEGORIES
        ev_ts = float(getattr(event, "timestamp", 0.0) or 0.0)
        if isinstance(existing, WorldEntity):
            changed = (
                existing.camera_tracks.get(camera_id) != event.track_id
                or existing.name != (event.name or existing.name)
                or existing.category != (event.category or existing.category)
                or (is_restricted and not existing.restricted)
            )
            entity = existing
            if ev_ts > 0.0:
                entity.last_seen = max(entity.last_seen, ev_ts)
        else:
            entity = WorldEntity(entity_id=int(entity_id), last_seen=ev_ts)
            changed = True

        entity.camera_tracks[camera_id] = int(event.track_id)
        if event.name:
            entity.name = event.name
        if event.category:
            entity.category = event.category
        entity.confidence = max(entity.confidence, float(getattr(event, "similarity", 0.0)))
        entity.restricted = entity.restricted or is_restricted

        zone_id = getattr(event, "zone_id", None)
        if zone_id:
            zone = resolve_zone_node(self.world_graph, camera_id, zone_id)
            scoped = zone.node_id if zone is not None else f"{camera_id}:zone:{zone_id}"
            cam_zones = entity.active_zones.setdefault(camera_id, set())
            if scoped not in cam_zones:
                cam_zones.add(scoped)
                changed = True

        if changed:
            self.world_graph.upsert_entity(entity)

    def _apply_restricted_alert(self, event: RestrictedEntityAlert) -> None:
        """Mark the target WorldEntity as restricted upon RestrictedEntityAlert."""
        entity = _find_target_entity(
            self.world_graph, event.camera_id, event.track_id, event.entity_id
        )
        if entity is None:
            if event.entity_id is None:
                return
            entity = WorldEntity(
                entity_id=int(event.entity_id),
                name=event.name or f"Entity {event.entity_id}",
                category=event.category or "restricted",
                restricted=True,
                camera_tracks={event.camera_id: int(event.track_id)} if event.camera_id else {},
                last_seen=float(event.timestamp),
            )
            self.world_graph.upsert_entity(entity)
            return

        if entity.restricted and entity.category == (event.category or entity.category):
            return
        entity.restricted = True
        if event.category:
            entity.category = event.category
        entity.last_seen = max(entity.last_seen, float(event.timestamp))
        self.world_graph.upsert_entity(entity)

    def _apply_policy_event(self, event: WorldPolicyUpdatedEvent) -> None:
        """Synchronize external WorldPolicyUpdatedEvent changes without feedback loops."""
        if not event.policy:
            return
        current = self.world_graph.get_policy().to_dict()
        delta = _compute_policy_delta(current, event.policy, list(event.changed_fields))
        if delta:
            self.world_graph.set_policy(**delta)
