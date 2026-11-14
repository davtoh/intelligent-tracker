"""Internal graph synchronization and cleanup helpers for WorldEntityBridge."""

from typing import Any

from intelligent_tracker.world._lifecycle import find_entity_by_track, resolve_zone_node
from intelligent_tracker.world.coordinates import project_bbox_from_camera_node
from intelligent_tracker.world.graph import WorldGraph
from intelligent_tracker.world.nodes import CameraNode, WorldEntity


def scoped_session_id(camera_id: str, session_id: int | str) -> str:
    """Scope numeric or raw session IDs per camera to avoid cross-camera collisions."""
    raw = str(session_id)
    return raw if ":" in raw else f"{camera_id}:{raw}"


def scoped_zone_id(graph: WorldGraph, camera_id: str, zone_id: str) -> str:
    """Resolve canonical ZoneNode.node_id for a camera-local zone identifier."""
    if not zone_id:
        return ""
    zone = resolve_zone_node(graph, camera_id, zone_id)
    if zone is not None:
        return zone.node_id
    return zone_id if ":zone:" in zone_id else f"{camera_id}:zone:{zone_id}"


def extract_global_xy(track: Any) -> tuple[float, float] | None:
    """Extract float (x, y) coordinates from Track.global_xy or Track.centroid."""
    coords = getattr(track, "global_xy", None) or getattr(track, "centroid", None)
    if coords is None or len(coords) < 2:
        return None
    return (float(coords[0]), float(coords[1]))


def compute_global_track_xy(
    track: Any,
    *,
    camera_id: str = "",
    coordinate_mapper: Any = None,
    world_graph: WorldGraph | None = None,
) -> tuple[float, float] | None:
    """Resolve global (X, Y) meters via GlobalCoordinateMapper, CameraNode calibration, or Track fallback."""
    bbox = getattr(track, "bbox", None)
    if bbox is not None and len(bbox) >= 4 and camera_id:
        if coordinate_mapper is not None and coordinate_mapper.has_camera(camera_id):
            return coordinate_mapper.project_track_bbox(camera_id, bbox)
        if world_graph is not None:
            cam_node = world_graph.get_node(camera_id, node_type="camera")
            if isinstance(cam_node, CameraNode):
                projected = project_bbox_from_camera_node(cam_node, bbox)
                if projected is not None:
                    return projected
    return extract_global_xy(track)


def append_bounded_trajectory(
    entity: WorldEntity,
    xy: tuple[float, float] | None,
    timestamp: float,
    *,
    max_points: int = 120,
) -> None:
    """Append (X, Y, timestamp) to WorldEntity.global_trajectory while enforcing bounded length."""
    if xy is None:
        return
    limit = max(1, int(max_points))
    point = (float(xy[0]), float(xy[1]), float(timestamp))
    if entity.global_trajectory and entity.global_trajectory[-1] == point:
        return
    entity.global_trajectory.append(point)
    if len(entity.global_trajectory) > limit:
        del entity.global_trajectory[:-limit]


def decorate_track_identity(
    track: Any,
    entity_id: int,
    name: str,
    category: str,
    confidence: float,
) -> None:
    """Synchronize canonical identification attributes on a Track instance."""
    track.entity_id = int(entity_id)
    track.entity_name = name
    track.entity_category = category
    track.reid_score = float(confidence)
    track.identity_label = name


def calibrate_entity_confidence(
    confidence_engine: Any,
    entity: WorldEntity,
    track: Any,
    *,
    entity_id: int,
    visual_similarity: float,
    camera_id: str,
    zone_id: str,
    timestamp: float,
) -> None:
    """Update WorldEntity.confidence via ConfidenceEngine without blocking 30 FPS tracking."""
    if confidence_engine is None:
        entity.confidence = max(entity.confidence, float(visual_similarity))
        return
    state = confidence_engine.record_observation(
        entity_id=int(entity_id),
        visual_similarity=float(visual_similarity),
        face_score=float(getattr(track, "face_score", 0.0) or 0.0),
        body_score=float(getattr(track, "body_score", 0.0) or 0.0),
        topology_prior=float(getattr(track, "topology_prior", 0.0) or 0.0),
        ambiguity=float(getattr(track, "reid_ambiguity", 0.0) or 0.0),
        camera_id=camera_id,
        zone_id=zone_id,
        timestamp=timestamp,
    )
    entity.confidence = state.confidence
    entity.confidence_breakdown = {
        "confidence": state.confidence,
        "face_score": state.face_score,
        "body_score": state.body_score,
        "streak_count": state.streak_count,
        "observation_count": state.observation_count,
        "confirmation_count": state.confirmation_count,
        "rejection_count": state.rejection_count,
        "ambiguity_penalty": state.ambiguity_penalty,
    }


def replace_zone_entity_ref(
    graph: WorldGraph,
    camera_id: str,
    old_we_id: str,
    new_we_id: str,
) -> None:
    """Swap superseded ephemeral WorldEntity references inside camera ZoneNodes."""
    for zone in graph.get_children(camera_id).get("zones", []):
        if old_we_id in zone.active_entity_ids:
            zone.active_entity_ids.discard(old_we_id)
            zone.active_entity_ids.add(new_we_id)
            graph.register_zone(zone)


def promote_session_node(
    graph: WorldGraph,
    camera_id: str,
    track: Any,
    target_entity: WorldEntity,
    target_we_id: str,
) -> None:
    """Migrate zone occupancy from an explicit session node and remove the stale session."""
    sess_id = getattr(track, "session_id", None)
    if sess_id is None:
        return
    sess_we_id = f"session:{scoped_session_id(camera_id, sess_id)}"
    sess_node = graph.get_node(sess_we_id, node_type="entity")
    if not isinstance(sess_node, WorldEntity):
        return
    sess_zones = sess_node.active_zones.get(camera_id)
    if sess_zones:
        target_entity.active_zones.setdefault(camera_id, set()).update(sess_zones)
    replace_zone_entity_ref(graph, camera_id, sess_we_id, target_we_id)
    graph.remove_node(sess_we_id)


def detach_track_from_other_entities(
    graph: WorldGraph,
    camera_id: str,
    track_id: int,
    target_we_id: str,
    target_entity: WorldEntity,
    now: float,
) -> None:
    """Migrate active_zones and remove stale bindings when a track switches WorldEntity."""
    old = find_entity_by_track(graph, camera_id, track_id)
    if old is None or old.world_entity_id == target_we_id:
        return
    old_zones = old.active_zones.pop(camera_id, set())
    if old_zones:
        target_entity.active_zones.setdefault(camera_id, set()).update(old_zones)
    old.camera_tracks.pop(camera_id, None)
    old.updated_at = now
    if not old.camera_tracks:
        replace_zone_entity_ref(graph, camera_id, old.world_entity_id, target_we_id)
        graph.remove_node(old.world_entity_id)
    else:
        graph.upsert_entity(old)


def remove_track_from_zones(
    graph: WorldGraph,
    camera_id: str,
    track_id: int | None,
    we_id: str,
) -> None:
    """Remove track_id and optional WorldEntity ID from camera ZoneNodes."""
    for zone in graph.get_children(camera_id).get("zones", []):
        changed = False
        if track_id is not None and track_id in zone.active_track_ids:
            zone.active_track_ids.discard(track_id)
            changed = True
        if we_id and we_id in zone.active_entity_ids:
            zone.active_entity_ids.discard(we_id)
            changed = True
        if changed:
            graph.register_zone(zone)

