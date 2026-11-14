"""WorldGraph-backed TransitionEdgeNode registry and kinematic-aware transit priors."""

from copy import deepcopy
import math
import threading
import time
from typing import Any
import uuid

from intelligent_tracker.events.types import BaseEvent
from intelligent_tracker.world._lifecycle import dispatch_events
from intelligent_tracker.world.coordinates import GlobalCoordinateMapper
from intelligent_tracker.world.events import NodeAddedEvent, NodeRemovedEvent
from intelligent_tracker.world.graph import WorldGraph
from intelligent_tracker.world.nodes import TransitionEdgeNode, WorldEntity


def compute_transit_speed_mps(
    exit_xy: tuple[float, float], candidate_xy: tuple[float, float], exit_time: float, arrival_time: float,
) -> float:
    """Compute implied metric ground speed v = ||p1 - p0||_2 / max(dt, 1e-3) in m/s."""
    dt = max(float(arrival_time) - float(exit_time), 1e-3)
    return math.hypot(float(candidate_xy[0]) - float(exit_xy[0]), float(candidate_xy[1]) - float(exit_xy[1])) / dt


def is_transit_kinematically_plausible(
    exit_xy: tuple[float, float] | None, candidate_xy: tuple[float, float] | None,
    exit_time: float, arrival_time: float, max_speed_mps: float = 12.0,
) -> bool:
    """Return True if global metric travel speed does not exceed max_speed_mps."""
    if exit_xy is None or candidate_xy is None:
        return True
    if float(arrival_time) < float(exit_time):
        return False
    return compute_transit_speed_mps(exit_xy, candidate_xy, exit_time, arrival_time) <= float(max_speed_mps)


def _build_reverse_edge(edge: TransitionEdgeNode) -> TransitionEdgeNode:
    """Create the directed reverse TransitionEdgeNode for a bidirectional link."""
    return TransitionEdgeNode(
        link_id=f"{edge.link_id}_rev", source_camera=edge.target_camera, source_zone=edge.target_zone,
        target_camera=edge.source_camera, target_zone=edge.source_zone, t_min=edge.t_min,
        t_max=edge.t_max, prior_boost=edge.prior_boost, bidirectional=False, active=edge.active,
    )


def _store_edge_locked(
    transitions: dict[str, TransitionEdgeNode], edge: TransitionEdgeNode, now: float, events: list[BaseEvent],
) -> TransitionEdgeNode:
    """Insert or update a TransitionEdgeNode in the graph map and queue NodeAddedEvent."""
    existing = transitions.get(edge.node_id)
    stored = deepcopy(edge)
    stored.updated_at = now
    if existing is not None:
        stored.created_at = existing.created_at
    else:
        events.append(
            NodeAddedEvent(
                camera_id=stored.source_camera or "world", node_id=stored.node_id,
                node_type="transition", parent_id=stored.source_camera or None, node_snapshot=stored.to_dict(),
            )
        )
    transitions[stored.node_id] = stored
    return deepcopy(stored)


def _resolve_entity_global_xy(world_graph: WorldGraph, entity_id: int | None) -> tuple[float, float] | None:
    """Look up current global_xy from WorldGraph for an identified entity."""
    if entity_id is None:
        return None
    node = world_graph.get_node(f"entity:{int(entity_id)}", node_type="entity")
    if isinstance(node, WorldEntity) and node.global_xy is not None:
        return (float(node.global_xy[0]), float(node.global_xy[1]))
    return None


def _build_prior_record(
    edge: TransitionEdgeNode, entity_id: int | None, entity_name: str,
    exit_xy: tuple[float, float] | None, now: float, metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "prior_id": f"prior_{uuid.uuid4().hex[:8]}", "link_id": edge.link_id,
        "entity_id": entity_id, "entity_name": entity_name,
        "source_camera": edge.source_camera, "source_zone": edge.source_zone,
        "target_camera": edge.target_camera, "target_zone": edge.target_zone,
        "exit_time": now, "window_start": now + edge.t_min, "window_end": now + edge.t_max,
        "prior_boost": edge.prior_boost, "exit_global_xy": exit_xy,
        "consumed": False, "metadata": dict(metadata or {}),
    }


class WorldTransitionRegistry:
    """Manages TransitionEdgeNode lifecycle and kinematic-aware transit priors in WorldGraph."""

    def __init__(
        self, world_graph: WorldGraph, coordinate_mapper: GlobalCoordinateMapper | None = None,
        *, max_transit_speed_mps: float = 12.0,
    ) -> None:
        self.world_graph = world_graph
        self.coordinate_mapper = coordinate_mapper if coordinate_mapper is not None else getattr(world_graph, "coordinate_mapper", None)
        self.max_transit_speed_mps = max(0.1, float(max_transit_speed_mps))
        self._priors_lock = threading.Lock()
        self._active_priors: list[dict[str, Any]] = []

    def register_edge(self, edge: TransitionEdgeNode) -> list[TransitionEdgeNode]:
        """Register or update a directed TransitionEdgeNode (and reverse edge if bidirectional)."""
        if not edge.link_id or not edge.source_camera or not edge.target_camera:
            raise ValueError("TransitionEdgeNode requires non-empty link_id, source_camera, and target_camera")
        now, events, created = time.time(), [], []
        with self.world_graph._lock:
            created.append(_store_edge_locked(self.world_graph._transitions, edge, now, events))
            if edge.bidirectional:
                created.append(_store_edge_locked(self.world_graph._transitions, _build_reverse_edge(edge), now, events))
        dispatch_events(self.world_graph._event_bus, events)
        return created

    def remove_edge(self, link_id: str) -> bool:
        """Remove a transition edge (and any generated _rev edge) from WorldGraph."""
        events: list[BaseEvent] = []
        removed = False
        with self.world_graph._lock:
            for tid in (link_id, f"{link_id}_rev"):
                edge = self.world_graph._transitions.pop(tid, None)
                if edge is None:
                    continue
                removed = True
                events.append(NodeRemovedEvent(
                    camera_id=edge.source_camera or "world", node_id=tid,
                    node_type="transition", parent_id=edge.source_camera or None,
                ))
        dispatch_events(self.world_graph._event_bus, events)
        return removed

    def list_edges(self, *, active_only: bool = False, include_reverse: bool = True) -> list[TransitionEdgeNode]:
        """Return isolated copies of registered TransitionEdgeNodes."""
        with self.world_graph._lock:
            return [
                deepcopy(edge) for edge in self.world_graph._transitions.values()
                if (not active_only or edge.active) and (include_reverse or not edge.link_id.endswith("_rev"))
            ]

    def get_edges_from(
        self, source_camera: str, source_zone: str | None = None, *, active_only: bool = True,
    ) -> list[TransitionEdgeNode]:
        """Return TransitionEdgeNodes departing from source_camera (and optional source_zone)."""
        with self.world_graph._lock:
            return [
                deepcopy(edge) for edge in self.world_graph._transitions.values()
                if edge.source_camera == source_camera
                and (source_zone is None or edge.source_zone == source_zone)
                and (not active_only or edge.active)
            ]

    def record_zone_exit(
        self, camera_id: str, zone_name: str, *, entity_id: int | None = None,
        entity_name: str = "Unidentified", exit_global_xy: tuple[float, float] | None = None,
        timestamp: float | None = None, metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Spawn active Bayesian transit priors for outgoing TransitionEdgeNodes."""
        now = time.time() if timestamp is None else float(timestamp)
        edges = self.get_edges_from(camera_id, zone_name, active_only=True)
        resolved_xy = exit_global_xy if exit_global_xy is not None else _resolve_entity_global_xy(self.world_graph, entity_id)
        spawned: list[dict[str, Any]] = []
        with self._priors_lock:
            for edge in edges:
                prior = _build_prior_record(edge, entity_id, entity_name, resolved_xy, now, metadata)
                self._active_priors.append(prior)
                spawned.append(deepcopy(prior))
        return spawned

    def query_active_priors(
        self, target_camera: str, target_zone: str | None = None, *,
        candidate_global_xy: tuple[float, float] | None = None, timestamp: float | None = None,
    ) -> list[dict[str, Any]]:
        """Return valid, kinematically plausible priors for target_camera/zone and prune expired."""
        now = time.time() if timestamp is None else float(timestamp)
        with self.world_graph._lock:
            live_link_ids = set(self.world_graph._transitions)
        valid, retained = [], []
        with self._priors_lock:
            for prior in self._active_priors:
                if prior["consumed"] or now > prior["window_end"] or prior["link_id"] not in live_link_ids:
                    continue
                retained.append(prior)
                if prior["target_camera"] != target_camera or (target_zone is not None and prior["target_zone"] != target_zone):
                    continue
                if prior["window_start"] <= now <= prior["window_end"] and is_transit_kinematically_plausible(
                    prior.get("exit_global_xy"), candidate_global_xy, prior["exit_time"], now, self.max_transit_speed_mps,
                ):
                    valid.append(deepcopy(prior))
            self._active_priors = retained
        return valid

    def consume_prior(self, prior_id: str) -> bool:
        """Mark a transit prior as consumed once identity continuity is resolved."""
        with self._priors_lock:
            for prior in self._active_priors:
                if prior["prior_id"] == prior_id:
                    prior["consumed"] = True
                    return True
        return False

    def prune_orphaned_edges(self) -> list[str]:
        """Remove TransitionEdgeNodes whose source or target CameraNode is missing from WorldGraph."""
        events: list[BaseEvent] = []
        pruned: list[str] = []
        with self.world_graph._lock:
            active_cams = set(self.world_graph._cameras)
            for tid in [k for k, e in self.world_graph._transitions.items() if e.source_camera not in active_cams or e.target_camera not in active_cams]:
                edge = self.world_graph._transitions.pop(tid)
                pruned.append(tid)
                events.append(NodeRemovedEvent(
                    camera_id=edge.source_camera or "world", node_id=tid,
                    node_type="transition", parent_id=edge.source_camera or None,
                ))
        dispatch_events(self.world_graph._event_bus, events)
        return pruned
