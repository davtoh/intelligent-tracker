"""Scoped, thread-safe WorldGraph registry with cascading lifecycle and EventBus dispatch."""

from copy import deepcopy
import threading
import time
from typing import Any

from intelligent_tracker.events.types import BaseEvent
from intelligent_tracker.world._lifecycle import (
    build_entity_state_event,
    detach_camera_children,
    detach_camera_from_entities,
    detach_camera_transitions,
    dispatch_events,
    register_camera_child,
    remove_non_camera_node,
)
from intelligent_tracker.world.events import (
    NodeAddedEvent,
    NodeRemovedEvent,
    WorldPolicyUpdatedEvent,
)
from intelligent_tracker.world.nodes import (
    CameraNode,
    TransitionEdgeNode,
    TripwireNode,
    WorldEntity,
    WorldNode,
    WorldPolicy,
    ZoneNode,
)

_POLICY_FIELDS = frozenset({"quiet_hours", "dwell_override", "alert_sensitivity", "extra"})


class WorldGraph:
    """Instance-scoped, thread-safe graph of cameras, zones, tripwires, entities, and policy."""

    def __init__(
        self,
        event_bus: Any = None,
        policy: WorldPolicy | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._event_bus = event_bus
        self._cameras: dict[str, CameraNode] = {}
        self._zones: dict[str, ZoneNode] = {}
        self._tripwires: dict[str, TripwireNode] = {}
        self._entities: dict[str, WorldEntity] = {}
        self._transitions: dict[str, TransitionEdgeNode] = {}
        self._policy: WorldPolicy = policy.clone() if policy is not None else WorldPolicy()

    def register_camera(self, camera: CameraNode) -> CameraNode:
        """Register or update a CameraNode while preserving existing child edges."""
        if not camera.camera_id:
            raise ValueError("CameraNode.camera_id must be non-empty")

        now = time.time()
        events: list[BaseEvent] = []
        with self._lock:
            existing = self._cameras.get(camera.camera_id)
            stored = deepcopy(camera)
            stored.updated_at = now
            if existing is not None:
                stored.created_at = existing.created_at
                stored.zone_ids = set(existing.zone_ids) | set(stored.zone_ids)
                stored.tripwire_ids = set(existing.tripwire_ids) | set(stored.tripwire_ids)
            else:
                events.append(
                    NodeAddedEvent(
                        camera_id=stored.camera_id,
                        node_id=stored.node_id,
                        node_type="camera",
                        parent_id=None,
                        node_snapshot=stored.to_dict(),
                    )
                )
            self._cameras[stored.camera_id] = stored
            result = deepcopy(stored)

        dispatch_events(self._event_bus, events)
        return result

    def register_zone(self, zone: ZoneNode) -> ZoneNode:
        """Register or update a ZoneNode under its parent CameraNode."""
        if not zone.camera_id or not zone.zone_id:
            raise ValueError("ZoneNode requires non-empty camera_id and zone_id")

        now = time.time()
        events: list[BaseEvent] = []
        with self._lock:
            result = register_camera_child(
                self._cameras, self._zones, zone, "zone_ids", now, events
            )
        dispatch_events(self._event_bus, events)
        return result

    def register_tripwire(self, tripwire: TripwireNode) -> TripwireNode:
        """Register or update a TripwireNode under its parent CameraNode."""
        if not tripwire.camera_id or not tripwire.tripwire_id:
            raise ValueError("TripwireNode requires non-empty camera_id and tripwire_id")

        now = time.time()
        events: list[BaseEvent] = []
        with self._lock:
            result = register_camera_child(
                self._cameras, self._tripwires, tripwire, "tripwire_ids", now, events
            )
        dispatch_events(self._event_bus, events)
        return result

    def upsert_entity(self, entity: WorldEntity) -> WorldEntity:
        """Insert or update a live WorldEntity and emit state-change telemetry."""
        if not entity.world_entity_id:
            raise ValueError("WorldEntity.world_entity_id must be non-empty")

        now = time.time()
        events: list[BaseEvent] = []
        with self._lock:
            existing = self._entities.get(entity.world_entity_id)
            stored = deepcopy(entity)
            stored.updated_at = now
            cam_id = next(iter(stored.camera_tracks), "world")
            change_type = "added" if existing is None else "updated"
            if existing is not None:
                stored.created_at = existing.created_at
            else:
                events.append(
                    NodeAddedEvent(
                        camera_id=cam_id,
                        node_id=stored.world_entity_id,
                        node_type="entity",
                        node_snapshot=stored.to_dict(),
                    )
                )
            self._entities[stored.world_entity_id] = stored
            events.append(build_entity_state_event(stored, cam_id, change_type))
            result = deepcopy(stored)

        dispatch_events(self._event_bus, events)
        return result

    def remove_camera(self, camera_id: str) -> list[str]:
        """Cascade-remove a CameraNode, its child zones/tripwires, and entity bindings."""
        now = time.time()
        events: list[BaseEvent] = []
        with self._lock:
            camera = self._cameras.pop(camera_id, None)
            if camera is None:
                return []
            detached_ids, child_events = detach_camera_children(
                self._zones, self._tripwires, camera
            )
            trans_ids, trans_events = detach_camera_transitions(self._transitions, camera_id)
            detached_ids.extend(trans_ids)
            events.extend(child_events)
            events.extend(trans_events)
            events.extend(detach_camera_from_entities(self._entities, camera_id, now))
            events.append(
                NodeRemovedEvent(
                    camera_id=camera_id,
                    node_id=camera_id,
                    node_type="camera",
                    cascade_removed_ids=list(detached_ids),
                )
            )
            removed = [camera_id, *detached_ids]

        dispatch_events(self._event_bus, events)
        return removed

    def remove_node(self, node_id: str) -> bool:
        """Remove a single zone, tripwire, entity, or cascade-remove a camera."""
        with self._lock:
            is_camera = node_id in self._cameras
            if not is_camera:
                removed, events = remove_non_camera_node(
                    self._cameras, self._zones, self._tripwires, self._entities, node_id, time.time(),
                    transitions=self._transitions,
                )
            else:
                removed, events = False, []
        if is_camera:
            return bool(self.remove_camera(node_id))
        if removed:
            dispatch_events(self._event_bus, events)
        return removed

    def get_node(self, node_id: str, node_type: str | None = None) -> WorldNode | None:
        """Fetch an isolated copy of a node by ID and optional node_type."""
        with self._lock:
            registries: dict[str, dict[str, Any]] = {
                "camera": self._cameras,
                "zone": self._zones,
                "tripwire": self._tripwires,
                "entity": self._entities,
                "transition": self._transitions,
            }
            if node_type is not None:
                reg = registries.get(node_type)
                node = reg.get(node_id) if reg is not None else None
                return deepcopy(node) if node is not None else None

            for reg in registries.values():
                if node_id in reg:
                    return deepcopy(reg[node_id])

            zone_matches = [z for z in self._zones.values() if z.zone_id == node_id]
            if len(zone_matches) == 1:
                return deepcopy(zone_matches[0])
            tw_matches = [tw for tw in self._tripwires.values() if tw.tripwire_id == node_id]
            if len(tw_matches) == 1:
                return deepcopy(tw_matches[0])
            return None

    def get_children(self, camera_id: str) -> dict[str, list[WorldNode]]:
        """Return deep copies of all child ZoneNodes and TripwireNodes for a camera."""
        with self._lock:
            return {
                "zones": [deepcopy(z) for z in self._zones.values() if z.camera_id == camera_id],
                "tripwires": [deepcopy(tw) for tw in self._tripwires.values() if tw.camera_id == camera_id],
            }

    def set_policy(self, policy: WorldPolicy | None = None, **updates: Any) -> WorldPolicy:
        """Update graph-wide policy and broadcast WorldPolicyUpdatedEvent outside lock."""
        unknown = set(updates) - _POLICY_FIELDS
        if unknown:
            raise ValueError(f"Unknown WorldPolicy field(s): {sorted(unknown)}")

        changed_fields: list[str] = []
        with self._lock:
            if policy is not None:
                self._policy = policy.clone()
                changed_fields.extend(sorted(_POLICY_FIELDS))
            for key, value in updates.items():
                if key == "extra" and isinstance(value, dict):
                    self._policy.extra = {**self._policy.extra, **deepcopy(value)}
                else:
                    setattr(self._policy, key, deepcopy(value))
                if key not in changed_fields:
                    changed_fields.append(key)
            self._policy.updated_at = time.time()
            result = self._policy.clone()
            event = WorldPolicyUpdatedEvent(
                camera_id="world",
                policy=result.to_dict(),
                changed_fields=changed_fields,
            )

        dispatch_events(self._event_bus, [event])
        return result

    def get_policy(self) -> WorldPolicy:
        """Return an isolated copy of the active WorldPolicy."""
        with self._lock:
            return self._policy.clone()

    def snapshot(self) -> dict[str, Any]:
        """Return a thread-safe, JSON-serializable snapshot of the entire WorldGraph."""
        with self._lock:
            return {
                "cameras": {cid: cam.to_dict() for cid, cam in self._cameras.items()},
                "zones": {zid: zone.to_dict() for zid, zone in self._zones.items()},
                "tripwires": {tid: tw.to_dict() for tid, tw in self._tripwires.items()},
                "entities": {eid: ent.to_dict() for eid, ent in self._entities.items()},
                "transitions": {tid: tr.to_dict() for tid, tr in self._transitions.items()},
                "policy": self._policy.to_dict(),
                "counts": {
                    "cameras": len(self._cameras),
                    "zones": len(self._zones),
                    "tripwires": len(self._tripwires),
                    "entities": len(self._entities),
                },
            }
