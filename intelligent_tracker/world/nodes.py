"""Typed node and policy models for the scoped WorldGraph."""

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import time
from typing import Any
import uuid


def _serialize_set_map(mapping: dict[str, set[str]]) -> dict[str, list[str]]:
    """Convert mapping of set values to deterministic sorted lists for JSON snapshots."""
    return {key: sorted(values) for key, values in mapping.items()}


@dataclass
class WorldNode:
    """Base contract for every node tracked in a scoped WorldGraph."""

    node_id: str = ""
    node_type: str = "node"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Serialize node fields into a JSON-compatible dictionary."""
        return asdict(self)


@dataclass
class CameraNode(WorldNode):
    """Represents a camera stream anchored in the world graph."""

    node_type: str = "camera"
    camera_id: str = ""
    name: str = ""
    source: str = ""
    enabled: bool = True
    zone_ids: set[str] = field(default_factory=set)
    tripwire_ids: set[str] = field(default_factory=set)
    homography: list[list[float]] | None = None
    world_pose: tuple[float, float, float] = (0.0, 0.0, 0.0)
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.camera_id and self.node_id:
            self.camera_id = self.node_id
        elif not self.node_id and self.camera_id:
            self.node_id = self.camera_id

    def to_dict(self) -> dict[str, Any]:
        """Serialize camera node with sorted child ID lists."""
        data = asdict(self)
        data["zone_ids"] = sorted(self.zone_ids)
        data["tripwire_ids"] = sorted(self.tripwire_ids)
        return data


@dataclass
class ZoneNode(WorldNode):
    """Represents a spatial region of interest owned by a parent CameraNode."""

    node_type: str = "zone"
    zone_id: str = ""
    camera_id: str = ""
    name: str = ""
    points: list[tuple[float, float]] = field(default_factory=list)
    restricted: bool = False
    max_occupancy: int | None = None
    active_track_ids: set[int] = field(default_factory=set)
    active_entity_ids: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not self.zone_id and self.node_id:
            self.zone_id = self.node_id
        elif not self.node_id and self.zone_id:
            self.node_id = (
                f"{self.camera_id}:zone:{self.zone_id}"
                if self.camera_id
                else f"zone:{self.zone_id}"
            )
        if not self.name:
            self.name = self.zone_id

    def to_dict(self) -> dict[str, Any]:
        """Serialize zone node with sorted occupancy collections."""
        data = asdict(self)
        data["active_track_ids"] = sorted(self.active_track_ids)
        data["active_entity_ids"] = sorted(self.active_entity_ids)
        return data


@dataclass
class TripwireNode(WorldNode):
    """Represents a directional virtual tripwire owned by a parent CameraNode."""

    node_type: str = "tripwire"
    tripwire_id: str = ""
    camera_id: str = ""
    name: str = ""
    pt1: tuple[float, float] = (0.0, 0.0)
    pt2: tuple[float, float] = (0.0, 0.0)
    direction: str = "both"
    crossing_count: int = 0

    def __post_init__(self) -> None:
        if not self.tripwire_id and self.node_id:
            self.tripwire_id = self.node_id
        elif not self.node_id and self.tripwire_id:
            self.node_id = (
                f"{self.camera_id}:tripwire:{self.tripwire_id}"
                if self.camera_id
                else f"tripwire:{self.tripwire_id}"
            )
        if not self.name:
            self.name = self.tripwire_id


@dataclass
class WorldEntity(WorldNode):
    """Live cross-camera entity converging ephemeral tracks and persistent identity."""

    node_type: str = "entity"
    world_entity_id: str = ""
    entity_id: int | None = None
    session_id: str | None = None
    name: str = ""
    category: str = "unknown"
    confidence: float = 0.0
    confidence_breakdown: dict[str, Any] = field(default_factory=dict)
    restricted: bool = False
    camera_tracks: dict[str, int] = field(default_factory=dict)
    active_zones: dict[str, set[str]] = field(default_factory=dict)
    global_xy: tuple[float, float] | None = None
    global_trajectory: list[tuple[float, float, float]] = field(default_factory=list)
    last_seen: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.world_entity_id and self.node_id:
            self.world_entity_id = self.node_id
        elif not self.world_entity_id:
            if self.entity_id is not None:
                self.world_entity_id = f"entity:{self.entity_id}"
            elif self.session_id:
                self.world_entity_id = f"session:{self.session_id}"
            else:
                self.world_entity_id = f"we:{uuid.uuid4().hex[:12]}"
        if not self.node_id:
            self.node_id = self.world_entity_id

    def to_dict(self) -> dict[str, Any]:
        """Serialize live entity state including sorted per-camera zone memberships."""
        data = asdict(self)
        data["active_zones"] = _serialize_set_map(self.active_zones)
        return data


@dataclass
class TransitionEdgeNode(WorldNode):
    """Directed cross-camera transition edge linking a source zone to a target zone."""

    node_type: str = "transition"
    link_id: str = ""
    source_camera: str = ""
    source_zone: str = ""
    target_camera: str = ""
    target_zone: str = ""
    t_min: float = 2.0
    t_max: float = 15.0
    prior_boost: float = 0.35
    bidirectional: bool = False
    active: bool = True

    def __post_init__(self) -> None:
        if not self.link_id and self.node_id:
            self.link_id = self.node_id
        elif not self.node_id and self.link_id:
            self.node_id = self.link_id


@dataclass
class WorldPolicy:
    """Graph-wide operational policy propagated reactively without stream restarts."""

    quiet_hours: dict[str, Any] | None = None
    dwell_override: float | None = None
    alert_sensitivity: float = 1.0
    extra: dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Serialize policy configuration into a JSON-compatible dictionary."""
        return deepcopy(asdict(self))

    def clone(self) -> "WorldPolicy":
        """Return an isolated deep copy of this policy instance."""
        return deepcopy(self)

