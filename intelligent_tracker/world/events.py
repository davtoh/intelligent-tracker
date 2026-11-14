"""Typed EventBus events emitted by scoped WorldGraph state changes."""

from dataclasses import dataclass, field
from typing import Any

from intelligent_tracker.events.types import BaseEvent


@dataclass
class NodeAddedEvent(BaseEvent):
    """Emitted when a camera, zone, tripwire, or entity node is registered."""

    event_type: str = "world_node_added"
    node_id: str = ""
    node_type: str = ""
    parent_id: str | None = None
    node_snapshot: dict[str, Any] = field(default_factory=dict)


@dataclass
class NodeRemovedEvent(BaseEvent):
    """Emitted when a node (and any cascading children) is removed from WorldGraph."""

    event_type: str = "world_node_removed"
    node_id: str = ""
    node_type: str = ""
    parent_id: str | None = None
    cascade_removed_ids: list[str] = field(default_factory=list)


@dataclass
class EntityStateChangedEvent(BaseEvent):
    """Emitted when a live WorldEntity changes tracks, zones, position, or flags."""

    event_type: str = "world_entity_state_changed"
    world_entity_id: str = ""
    entity_id: int | None = None
    session_id: str | None = None
    change_type: str = "updated"
    camera_tracks: dict[str, int] = field(default_factory=dict)
    active_zones: dict[str, list[str]] = field(default_factory=dict)
    global_xy: tuple[float, float] | None = None
    restricted: bool = False


@dataclass
class WorldPolicyUpdatedEvent(BaseEvent):
    """Emitted when WorldGraph policy parameters change at runtime."""

    event_type: str = "world_policy_updated"
    policy: dict[str, Any] = field(default_factory=dict)
    changed_fields: list[str] = field(default_factory=list)

