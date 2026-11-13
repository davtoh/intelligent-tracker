#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Cross-Camera Topological Space Awareness Module.

Provides multi-camera spatial transition links, predictive spatial priors
within transit windows [T_min, T_max], optional WorldGraph TransitionEdgeNode
synchronization, and kinematic-aware Bayesian Re-ID score boosting.
"""

from dataclasses import asdict, dataclass, field
import logging
import time
from typing import Any
import uuid

import numpy as np

from intelligent_tracker.world.nodes import TransitionEdgeNode
from intelligent_tracker.world.transitions import (
    WorldTransitionRegistry,
    _resolve_entity_global_xy,
    is_transit_kinematically_plausible,
)

logger = logging.getLogger("intelligent_tracker.topology")


@dataclass
class SpatialTransitionLink:
    """Defines a directed or bidirectional transition path between two camera zones."""

    link_id: str
    source_camera: str
    source_zone: str
    target_camera: str
    target_zone: str
    t_min: float = 2.0
    t_max: float = 15.0
    prior_boost: float = 0.35
    bidirectional: bool = False
    active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SpatialTransitionLink":
        return cls(
            link_id=data.get("link_id") or f"link_{uuid.uuid4().hex[:8]}",
            source_camera=str(data["source_camera"]),
            source_zone=str(data["source_zone"]),
            target_camera=str(data["target_camera"]),
            target_zone=str(data["target_zone"]),
            t_min=float(data.get("t_min", 2.0)),
            t_max=float(data.get("t_max", 15.0)),
            prior_boost=float(data.get("prior_boost", 0.35)),
            bidirectional=bool(data.get("bidirectional", False)),
            active=bool(data.get("active", True)),
        )


@dataclass
class ActiveSpatialPrior:
    """A live predictive prior placed in a target camera zone following an entity's exit."""

    prior_id: str
    link_id: str
    entity_id: int | None
    entity_name: str
    source_camera: str
    source_zone: str
    target_camera: str
    target_zone: str
    exit_time: float
    window_start: float
    window_end: float
    prior_boost: float
    embedding: np.ndarray | None = None
    consumed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    exit_global_xy: tuple[float, float] | None = None

    def is_valid_at(self, current_time: float) -> bool:
        """Return True if current_time falls inside [window_start, window_end] and is unconsumed."""
        return not self.consumed and (self.window_start <= current_time <= self.window_end)

    def is_expired_at(self, current_time: float) -> bool:
        """Return True if current_time exceeds window_end or prior is consumed."""
        return current_time > self.window_end or self.consumed

    def to_dict(self) -> dict[str, Any]:
        return {
            "prior_id": self.prior_id, "link_id": self.link_id,
            "entity_id": self.entity_id, "entity_name": self.entity_name,
            "source_camera": self.source_camera, "source_zone": self.source_zone,
            "target_camera": self.target_camera, "target_zone": self.target_zone,
            "exit_time": self.exit_time, "window_start": self.window_start,
            "window_end": self.window_end, "prior_boost": self.prior_boost,
            "consumed": self.consumed, "metadata": self.metadata,
            "exit_global_xy": list(self.exit_global_xy) if self.exit_global_xy is not None else None,
        }


def _link_to_edge_node(link: SpatialTransitionLink) -> TransitionEdgeNode:
    """Convert a SpatialTransitionLink into a WorldGraph TransitionEdgeNode."""
    return TransitionEdgeNode(
        link_id=link.link_id, source_camera=link.source_camera, source_zone=link.source_zone,
        target_camera=link.target_camera, target_zone=link.target_zone, t_min=link.t_min,
        t_max=link.t_max, prior_boost=link.prior_boost, bidirectional=link.bidirectional, active=link.active,
    )


def _prior_matches_candidate(
    prior: ActiveSpatialPrior, candidate_entity_id: int | None, candidate_name: str | None,
) -> bool:
    """Check whether an active prior refers to the candidate entity by ID or name."""
    if candidate_entity_id is not None and prior.entity_id is not None:
        return candidate_entity_id == prior.entity_id
    if candidate_name and prior.entity_name:
        return candidate_name.lower() == prior.entity_name.lower()
    return False


def _make_prior_from_link(
    link: SpatialTransitionLink, entity_name: str, entity_id: int | None,
    embedding: np.ndarray | None, now: float, metadata: dict[str, Any] | None,
    exit_xy: tuple[float, float] | None, prior_id: str | None = None,
) -> ActiveSpatialPrior:
    """Instantiate an ActiveSpatialPrior from a matching transition link."""
    return ActiveSpatialPrior(
        prior_id=prior_id or f"prior_{uuid.uuid4().hex[:8]}", link_id=link.link_id,
        entity_id=entity_id, entity_name=entity_name, source_camera=link.source_camera,
        source_zone=link.source_zone, target_camera=link.target_camera, target_zone=link.target_zone,
        exit_time=now, window_start=now + link.t_min, window_end=now + link.t_max,
        prior_boost=link.prior_boost, embedding=embedding, consumed=False,
        metadata=metadata or {}, exit_global_xy=exit_xy,
    )


class CrossCameraTopology:
    """Coordinates topological relationships, WorldGraph edges, and spatial priors."""

    def __init__(
        self,
        world_transitions: WorldTransitionRegistry | None = None,
        max_transit_speed_mps: float = 12.0,
    ) -> None:
        self.links: dict[str, SpatialTransitionLink] = {}
        self.active_priors: list[ActiveSpatialPrior] = []
        self.world_transitions = world_transitions
        self.max_transit_speed_mps = max(0.1, float(max_transit_speed_mps))

    def _sync_links_with_world(self) -> None:
        """Prune local links whose TransitionEdgeNode was removed from WorldGraph."""
        if self.world_transitions is None:
            return
        live_ids = {edge.link_id for edge in self.world_transitions.list_edges()}
        for stale_id in [lid for lid in self.links if lid not in live_ids]:
            del self.links[stale_id]

    def add_link(self, link: SpatialTransitionLink) -> None:
        """Register a spatial transition link and sync to WorldGraph if attached."""
        self.links[link.link_id] = link
        logger.info(
            "Registered spatial transition link '%s': %s[%s] -> %s[%s] (transit: %.1fs-%.1fs, boost: +%.2f)",
            link.link_id, link.source_camera, link.source_zone,
            link.target_camera, link.target_zone, link.t_min, link.t_max, link.prior_boost,
        )
        if link.bidirectional:
            rev_id = f"{link.link_id}_rev"
            if rev_id not in self.links:
                self.links[rev_id] = SpatialTransitionLink(
                    link_id=rev_id, source_camera=link.target_camera, source_zone=link.target_zone,
                    target_camera=link.source_camera, target_zone=link.source_zone,
                    t_min=link.t_min, t_max=link.t_max, prior_boost=link.prior_boost,
                    bidirectional=False, active=link.active,
                )
        if self.world_transitions is not None:
            self.world_transitions.register_edge(_link_to_edge_node(link))

    def remove_link(self, link_id: str) -> bool:
        """Remove a transition link by ID (and any reverse link) across topology and WorldGraph."""
        removed = False
        if link_id in self.links:
            del self.links[link_id]
            self.links.pop(f"{link_id}_rev", None)
            removed = True
        if self.world_transitions is not None:
            removed = self.world_transitions.remove_edge(link_id) or removed
        return removed

    def list_links(self) -> list[SpatialTransitionLink]:
        """Return list of all active registered transition links."""
        self._sync_links_with_world()
        return list(self.links.values())

    def record_zone_exit(
        self,
        camera_id: str,
        zone_name: str,
        entity_name: str = "Unidentified",
        entity_id: int | None = None,
        embedding: np.ndarray | None = None,
        timestamp: float | None = None,
        metadata: dict[str, Any] | None = None,
        exit_global_xy: tuple[float, float] | None = None,
    ) -> list[ActiveSpatialPrior]:
        """Instantiate ActiveSpatialPriors for outgoing links when an entity exits a zone."""
        self._sync_links_with_world()
        now = time.time() if timestamp is None else float(timestamp)
        resolved_xy = exit_global_xy or ((metadata or {}).get("global_xy") if metadata else None)
        world_priors_by_link: dict[str, dict[str, Any]] = {}
        if self.world_transitions is not None:
            if resolved_xy is None:
                resolved_xy = _resolve_entity_global_xy(self.world_transitions.world_graph, entity_id)
            for wp in self.world_transitions.record_zone_exit(
                camera_id, zone_name, entity_id=entity_id, entity_name=entity_name,
                exit_global_xy=resolved_xy, timestamp=now, metadata=metadata,
            ):
                world_priors_by_link[wp["link_id"]] = wp

        new_priors: list[ActiveSpatialPrior] = []
        for link in self.links.values():
            if not link.active or link.source_camera != camera_id or link.source_zone != zone_name:
                continue
            wp = world_priors_by_link.get(link.link_id)
            prior = _make_prior_from_link(
                link, entity_name, entity_id, embedding, now, metadata,
                resolved_xy, prior_id=wp["prior_id"] if wp else None,
            )
            self.active_priors.append(prior)
            new_priors.append(prior)
        return new_priors

    def get_active_priors(
        self,
        target_camera: str,
        target_zone: str | None = None,
        timestamp: float | None = None,
        candidate_global_xy: tuple[float, float] | None = None,
    ) -> list[ActiveSpatialPrior]:
        """Return valid, kinematically plausible priors for target_camera/zone and prune expired."""
        self._sync_links_with_world()
        now = time.time() if timestamp is None else float(timestamp)
        valid: list[ActiveSpatialPrior] = []
        retained: list[ActiveSpatialPrior] = []
        for p in self.active_priors:
            if p.is_expired_at(now) or p.link_id not in self.links:
                continue
            retained.append(p)
            if p.target_camera != target_camera or (target_zone is not None and p.target_zone != target_zone):
                continue
            if p.is_valid_at(now) and is_transit_kinematically_plausible(
                p.exit_global_xy, candidate_global_xy, p.exit_time, now, self.max_transit_speed_mps,
            ):
                valid.append(p)
        self.active_priors = retained
        return valid

    def compute_weighted_similarity(
        self,
        visual_similarity: float,
        candidate_entity_id: int | None,
        candidate_name: str | None,
        target_camera: str,
        target_zone: str | None = None,
        timestamp: float | None = None,
        candidate_global_xy: tuple[float, float] | None = None,
    ) -> tuple[float, ActiveSpatialPrior | None]:
        """
        Adjust visual Re-ID similarity by applying an active, kinematically plausible spatial prior.

        Mathematical Formulation:
        -------------------------
        Let S_vis in [0.0, 1.0] be the visual cosine similarity.
        If an active prior exists matching candidate_entity_id or candidate_name
        and passing kinematic ground-speed gating v <= v_max:
            S_final = min(1.0, S_vis + prior_boost)
        otherwise:
            S_final = S_vis
        """
        now = time.time() if timestamp is None else float(timestamp)
        active_priors = self.get_active_priors(
            target_camera, target_zone, timestamp=now, candidate_global_xy=candidate_global_xy,
        )
        for prior in active_priors:
            if _prior_matches_candidate(prior, candidate_entity_id, candidate_name):
                return min(1.0, visual_similarity + prior.prior_boost), prior
        return visual_similarity, None

    def consume_prior(self, prior_id: str) -> bool:
        """Mark a spatial prior as consumed once an entity has been re-identified."""
        consumed = False
        for p in self.active_priors:
            if p.prior_id == prior_id:
                p.consumed = True
                consumed = True
                break
        if self.world_transitions is not None:
            consumed = self.world_transitions.consume_prior(prior_id) or consumed
        return consumed

    def to_dict(self) -> dict[str, Any]:
        """Serialize non-reverse topology links to dictionary."""
        return {
            "links": [link.to_dict() for link in self.list_links() if not link.link_id.endswith("_rev")],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CrossCameraTopology":
        """Instantiate CrossCameraTopology from dictionary."""
        topology = cls()
        for ld in data.get("links", []):
            topology.add_link(SpatialTransitionLink.from_dict(ld))
        return topology
