"""Pure math, trajectory, and prior-scoring helpers for MultiCameraHandoffCoordinator."""

from copy import deepcopy
import math
from typing import Any

import numpy as np

from intelligent_tracker.world._bridge_helpers import replace_zone_entity_ref
from intelligent_tracker.world._lifecycle import list_entities_snapshot
from intelligent_tracker.world.graph import WorldGraph
from intelligent_tracker.world.nodes import WorldEntity


def cosine_similarity(vec_a: Any, vec_b: Any) -> float | None:
    """Compute cosine similarity in [-1, 1] between two feature vectors if both exist."""
    if vec_a is None or vec_b is None:
        return None
    a = np.asarray(vec_a, dtype=np.float32).ravel()
    b = np.asarray(vec_b, dtype=np.float32).ravel()
    if a.size == 0 or a.size != b.size:
        return None
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom > 1e-8 else 0.0


def extract_embedding(track: Any, explicit: Any = None) -> np.ndarray | None:
    """Extract an optional 1D Re-ID embedding from explicit arg or track attributes."""
    raw = explicit if explicit is not None else getattr(track, "embedding", None)
    if raw is None:
        raw = getattr(track, "reid_embedding", None)
    return np.asarray(raw, dtype=np.float32).ravel() if raw is not None else None


_PERSON_ROLES = frozenset(
    {"", "unknown", "object", "person", "vip", "employee", "visitor", "staff", "guest", "restricted", "banned", "blacklisted"}
)


def categories_compatible(cat_a: str, cat_b: str) -> bool:
    """Return True when two entity/track categories are equal, generic, or person-role compatible."""
    a, b = (cat_a or "").strip().lower(), (cat_b or "").strip().lower()
    if a == b or a in {"", "unknown", "object"} or b in {"", "unknown", "object"}:
        return True
    return a in _PERSON_ROLES and b in _PERSON_ROLES


def query_priors(
    topology: Any, transition_registry: Any, camera_id: str, zone_id: str,
    cand_xy: tuple[float, float] | None, now: float,
) -> list[Any]:
    """Query active transit priors from CrossCameraTopology or WorldTransitionRegistry."""
    if topology is not None:
        return topology.get_active_priors(camera_id, zone_id or None, timestamp=now, candidate_global_xy=cand_xy)
    if transition_registry is not None:
        return transition_registry.query_active_priors(camera_id, zone_id or None, candidate_global_xy=cand_xy, timestamp=now)
    return []


def predict_entity_xy(entity: WorldEntity, now: float) -> tuple[float, float] | None:
    """Extrapolate linear 2D ground velocity from the last two global trajectory samples."""
    if len(entity.global_trajectory) >= 2:
        x0, y0, t0 = entity.global_trajectory[-2]
        x1, y1, t1 = entity.global_trajectory[-1]
        dt_hist = t1 - t0
        if dt_hist > 1e-3:
            dt_pred = max(0.0, now - t1)
            return (x1 + ((x1 - x0) / dt_hist) * dt_pred, y1 + ((y1 - y0) / dt_hist) * dt_pred)
    return entity.global_xy


def merge_trajectories(
    pts_a: list[tuple[float, float, float]],
    pts_b: list[tuple[float, float, float]],
    max_points: int,
) -> list[tuple[float, float, float]]:
    """Merge two timed global trajectories chronologically with duplicate suppression."""
    merged: list[tuple[float, float, float]] = []
    for pt in sorted([*pts_a, *pts_b], key=lambda p: (p[2], p[0], p[1])):
        if not merged or merged[-1] != pt:
            merged.append(pt)
    return merged[-max(1, max_points) :]


def prior_attr(prior: Any, key: str, default: Any = None) -> Any:
    """Read field uniformly from either ActiveSpatialPrior dataclass or dict record."""
    return prior.get(key, default) if isinstance(prior, dict) else getattr(prior, key, default)


def canonical_rank(entity: WorldEntity) -> tuple[int, float, str]:
    """Prefer persistent entity IDs over ephemeral sessions, then earlier creation time."""
    return (0 if entity.entity_id is not None else 1, entity.created_at, entity.world_entity_id)


def resolve_entity_for_prior(
    world_graph: WorldGraph, departed: dict[str, WorldEntity], prior: Any, now: float,
) -> WorldEntity | None:
    """Resolve an active or recently departed WorldEntity referenced by an active prior."""
    meta = prior_attr(prior, "metadata", {}) or {}
    eid = prior_attr(prior, "entity_id")
    for we_id in (meta.get("world_entity_id"), f"entity:{int(eid)}" if eid is not None else None):
        if not we_id:
            continue
        node = world_graph.get_node(we_id, node_type="entity")
        if isinstance(node, WorldEntity):
            return node
        if we_id in departed:
            return deepcopy(departed[we_id])
    name = prior_attr(prior, "entity_name", "")
    if name and name != "Unidentified":
        for node in list_entities_snapshot(world_graph):
            if node.name == name:
                return node
    return WorldEntity(entity_id=int(eid), name=name or f"Entity {eid}", last_seen=now) if eid is not None else None


def build_track_entity(world_graph: WorldGraph, camera_id: str, track: Any, tid: int, now: float) -> WorldEntity:
    """Build or load a WorldEntity for an unmatched camera track."""
    eid = getattr(track, "entity_id", None)
    sess = getattr(track, "session_id", None) or tid
    scoped_sess = f"{camera_id}:{sess}" if ":" not in str(sess) else str(sess)
    we_id = f"entity:{int(eid)}" if eid is not None else f"session:{scoped_sess}"
    existing = world_graph.get_node(we_id, node_type="entity")
    if isinstance(existing, WorldEntity):
        return existing
    return WorldEntity(
        world_entity_id=we_id,
        entity_id=int(eid) if eid is not None else None,
        session_id=None if eid is not None else scoped_sess,
        name=getattr(track, "entity_name", None) or getattr(track, "identity_label", None) or f"Track #{tid}",
        category=getattr(track, "entity_category", None) or getattr(track, "label", "person"),
        last_seen=now,
    )


def can_merge_entities(
    ent_a: WorldEntity, ent_b: WorldEntity, win: float, radius_m: float, sim_thresh: float,
    emb_a: np.ndarray | None, emb_b: np.ndarray | None,
) -> bool:
    """Check disjoint cameras, temporal concurrency, Euclidean radius, category, and Re-ID."""
    if ent_a.global_xy is None or ent_b.global_xy is None or not ent_a.camera_tracks or not ent_b.camera_tracks:
        return False
    if set(ent_a.camera_tracks) & set(ent_b.camera_tracks):
        return False
    if ent_a.entity_id is not None and ent_b.entity_id is not None and ent_a.entity_id != ent_b.entity_id:
        return False
    if abs(ent_a.last_seen - ent_b.last_seen) > win:
        return False
    if math.hypot(ent_a.global_xy[0] - ent_b.global_xy[0], ent_a.global_xy[1] - ent_b.global_xy[1]) > radius_m:
        return False
    if not categories_compatible(ent_a.category, ent_b.category):
        return False
    sim = cosine_similarity(emb_a, emb_b)
    return sim is None or sim >= sim_thresh


def merge_world_entities(
    world_graph: WorldGraph, primary: WorldEntity, secondary: WorldEntity, now: float, max_points: int,
) -> WorldEntity:
    """Absorb secondary WorldEntity's cameras, zones, and trajectory into primary."""
    primary.camera_tracks.update(secondary.camera_tracks)
    for cam, zones in secondary.active_zones.items():
        primary.active_zones.setdefault(cam, set()).update(zones)
        replace_zone_entity_ref(world_graph, cam, secondary.world_entity_id, primary.world_entity_id)
    if secondary.global_xy is not None and secondary.last_seen >= primary.last_seen:
        primary.global_xy = secondary.global_xy
    primary.last_seen = max(primary.last_seen, secondary.last_seen)
    primary.global_trajectory = merge_trajectories(primary.global_trajectory, secondary.global_trajectory, max_points)
    primary.restricted = primary.restricted or secondary.restricted
    primary.updated_at = now
    world_graph.remove_node(secondary.world_entity_id)
    return world_graph.upsert_entity(primary)
