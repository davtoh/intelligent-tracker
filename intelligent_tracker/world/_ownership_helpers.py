"""Pure geometry, entity-resolution, and alert-building helpers for OwnershipAssociationEngine."""

import math
from typing import Any

from intelligent_tracker.events.types import UnattendedItemAlert, crop_to_base64
from intelligent_tracker.world._lifecycle import find_entity_by_track
from intelligent_tracker.world.graph import WorldGraph


def track_center(track: Any) -> tuple[float, float]:
    """Resolve (cx, cy) center from Track.centroid or Track.bbox."""
    centroid = getattr(track, "centroid", None)
    if centroid is not None and len(centroid) >= 2:
        return float(centroid[0]), float(centroid[1])
    bbox = getattr(track, "bbox", None)
    if bbox is not None and len(bbox) >= 4:
        return float(bbox[0]) + float(bbox[2]) * 0.5, float(bbox[1]) + float(bbox[3]) * 0.5
    return 0.0, 0.0


def euclidean_distance(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """Compute 2D Euclidean pixel distance between two centers."""
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


def resolve_entity_ref(
    world_graph: WorldGraph, camera_id: str, track_id: int, track: Any,
) -> tuple[str, int | None, str]:
    """Resolve (world_entity_id, entity_id, display_name) for a Track."""
    ent = find_entity_by_track(world_graph, camera_id, track_id)
    if ent is not None:
        return ent.world_entity_id, ent.entity_id, ent.name or f"Track #{track_id}"
    ent_id = getattr(track, "entity_id", None)
    name = (
        getattr(track, "entity_name", None)
        or getattr(track, "identity_label", None)
        or (f"Entity {ent_id}" if ent_id is not None else f"Track #{track_id}")
    )
    we_id = f"entity:{ent_id}" if ent_id is not None else f"track:{camera_id}:{track_id}"
    return we_id, ent_id, str(name)


def build_unattended_alert(
    world_graph: WorldGraph,
    binding: Any,
    bag_trk: Any,
    now: float,
    unattended_dur: float,
    zone_lookup: dict[int, str],
    frame: Any,
) -> UnattendedItemAlert:
    """Construct an UnattendedItemAlert with location, global_xy, bbox, and snapshot."""
    loc = str(zone_lookup.get(binding.bag_track_id) or getattr(bag_trk, "current_zone", None) or binding.camera_id)
    bag_ent = find_entity_by_track(world_graph, binding.camera_id, binding.bag_track_id)
    raw = getattr(bag_trk, "bbox", None)
    bbox: tuple[int, int, int, int] | None = (
        (int(raw[0]), int(raw[1]), int(raw[2]), int(raw[3])) if raw is not None and len(raw) >= 4 else None
    )
    snap = crop_to_base64(frame, bbox) if frame is not None and bbox is not None else None
    return UnattendedItemAlert(
        camera_id=binding.camera_id, timestamp=now, location=loc,
        global_xy=getattr(bag_ent, "global_xy", None) if bag_ent is not None else None,
        bbox=bbox, owner_entity_id=binding.owner_entity_id,
        owner_world_entity_id=binding.owner_world_entity_id, owner_name=binding.owner_name,
        owner_track_id=binding.owner_track_id, bag_track_id=binding.bag_track_id,
        bag_world_entity_id=binding.bag_world_entity_id, item_label=binding.item_label,
        unattended_duration_s=round(unattended_dur, 2), snapshot_base64=snap,
        message=f"Unattended {binding.item_label} (track {binding.bag_track_id}) left at {loc} by {binding.owner_name} for {unattended_dur:.1f}s",
    )
