#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Cross-Camera Topological Space Awareness Module.

Provides:
- Multi-camera spatial topology modeling realizing the vision of Scene, Area, and Line.
- Spatial Transition Links between cameras (e.g., Camera 1 'Door Exit' -> Camera 2 'Door Entrance').
- Predictive spatial priors generated on zone exit within transit time windows [T_min, T_max].
- Weighted Re-ID scoring combining visual similarity with topological spatial priors to eliminate
  identity swapping across cameras.
- Real-time serialization and persistence.
"""

import time
import uuid
import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple, Any, Union

import numpy as np

from intelligent_tracker.high_objects import Scene, Area, Line

logger = logging.getLogger("intelligent_tracker.topology")


@dataclass
class SpatialTransitionLink:
    """
    Defines a physical or topological transition path between two camera zones.
    
    Attributes:
        link_id: Unique identifier for the transition link.
        source_camera: Source camera ID (e.g. 'cam_01').
        source_zone: Name of the zone in the source camera (e.g. 'Door Exit').
        target_camera: Target camera ID (e.g. 'cam_02').
        target_zone: Name of the zone in the target camera (e.g. 'Door Entrance').
        t_min: Minimum expected travel time in seconds between source and target zones.
        t_max: Maximum expected travel time in seconds before the spatial prior expires.
        prior_boost: Score bonus (0.0 to 1.0) added to Re-ID visual similarity when the
                     entity appears in the target zone within [t_min, t_max].
        bidirectional: If True, also automatically creates/enforces the reverse link.
        active: Whether this transition link is currently active.
    """
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

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpatialTransitionLink":
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
    """
    A live predictive prior placed in a target camera zone following an entity's exit.
    """
    prior_id: str
    link_id: str
    entity_id: Optional[int]
    entity_name: str
    source_camera: str
    source_zone: str
    target_camera: str
    target_zone: str
    exit_time: float
    window_start: float
    window_end: float
    prior_boost: float
    embedding: Optional[np.ndarray] = None
    consumed: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_valid_at(self, current_time: float) -> bool:
        """Returns True if the current time falls inside the transit window [window_start, window_end]."""
        return not self.consumed and (self.window_start <= current_time <= self.window_end)

    def is_expired_at(self, current_time: float) -> bool:
        """Returns True if the current time exceeds the maximum transit window."""
        return current_time > self.window_end or self.consumed

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "prior_id": self.prior_id,
            "link_id": self.link_id,
            "entity_id": self.entity_id,
            "entity_name": self.entity_name,
            "source_camera": self.source_camera,
            "source_zone": self.source_zone,
            "target_camera": self.target_camera,
            "target_zone": self.target_zone,
            "exit_time": self.exit_time,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "prior_boost": self.prior_boost,
            "consumed": self.consumed,
            "metadata": self.metadata,
        }
        return d


class CrossCameraTopology:
    """
    Coordinates topological relationships and spatial priors across multiple cameras.
    """

    def __init__(self):
        self.links: Dict[str, SpatialTransitionLink] = {}
        self.active_priors: List[ActiveSpatialPrior] = []

    def add_link(self, link: SpatialTransitionLink):
        """Register a new spatial transition link."""
        self.links[link.link_id] = link
        logger.info(
            "Registered spatial transition link '%s': %s[%s] -> %s[%s] (transit: %.1fs-%.1fs, boost: +%.2f)",
            link.link_id,
            link.source_camera,
            link.source_zone,
            link.target_camera,
            link.target_zone,
            link.t_min,
            link.t_max,
            link.prior_boost,
        )

        # If bidirectional, register reverse link if not already existing
        if link.bidirectional:
            rev_id = f"{link.link_id}_rev"
            if rev_id not in self.links:
                rev_link = SpatialTransitionLink(
                    link_id=rev_id,
                    source_camera=link.target_camera,
                    source_zone=link.target_zone,
                    target_camera=link.source_camera,
                    target_zone=link.source_zone,
                    t_min=link.t_min,
                    t_max=link.t_max,
                    prior_boost=link.prior_boost,
                    bidirectional=False,
                    active=link.active,
                )
                self.links[rev_id] = rev_link

    def remove_link(self, link_id: str) -> bool:
        """Remove a transition link by ID."""
        if link_id in self.links:
            del self.links[link_id]
            rev_id = f"{link_id}_rev"
            if rev_id in self.links:
                del self.links[rev_id]
            return True
        return False

    def list_links(self) -> List[SpatialTransitionLink]:
        """Return list of all registered transition links."""
        return list(self.links.values())

    def record_zone_exit(
        self,
        camera_id: str,
        zone_name: str,
        entity_name: str = "Unidentified",
        entity_id: Optional[int] = None,
        embedding: Optional[np.ndarray] = None,
        timestamp: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[ActiveSpatialPrior]:
        """
        Triggered when an entity exits a zone. Matches registered transition links
        and instantiates ActiveSpatialPriors for linked target cameras.
        """
        now = time.time() if timestamp is None else float(timestamp)
        new_priors = []

        for link in self.links.values():
            if not link.active:
                continue
            if link.source_camera == camera_id and link.source_zone == zone_name:
                prior = ActiveSpatialPrior(
                    prior_id=f"prior_{uuid.uuid4().hex[:8]}",
                    link_id=link.link_id,
                    entity_id=entity_id,
                    entity_name=entity_name,
                    source_camera=camera_id,
                    source_zone=zone_name,
                    target_camera=link.target_camera,
                    target_zone=link.target_zone,
                    exit_time=now,
                    window_start=now + link.t_min,
                    window_end=now + link.t_max,
                    prior_boost=link.prior_boost,
                    embedding=embedding,
                    consumed=False,
                    metadata=metadata or {},
                )
                self.active_priors.append(prior)
                new_priors.append(prior)
                logger.info(
                    "Spawned spatial prior '%s' for '%s' -> %s[%s] (transit window: +%.1fs to +%.1fs)",
                    prior.prior_id,
                    entity_name,
                    link.target_camera,
                    link.target_zone,
                    link.t_min,
                    link.t_max,
                )

        return new_priors

    def get_active_priors(
        self,
        target_camera: str,
        target_zone: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> List[ActiveSpatialPrior]:
        """
        Retrieves valid active spatial priors for a specific target camera and zone.
        Automatically cleans up expired priors.
        """
        now = time.time() if timestamp is None else float(timestamp)
        valid = []

        # Retain unexpired priors
        retained = []
        for p in self.active_priors:
            if p.is_expired_at(now):
                continue
            retained.append(p)
            if p.target_camera == target_camera:
                if target_zone is None or p.target_zone == target_zone:
                    if p.is_valid_at(now):
                        valid.append(p)

        self.active_priors = retained
        return valid

    def compute_weighted_similarity(
        self,
        visual_similarity: float,
        candidate_entity_id: Optional[int],
        candidate_name: Optional[str],
        target_camera: str,
        target_zone: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> Tuple[float, Optional[ActiveSpatialPrior]]:
        """
        Adjusts visual Re-ID similarity by applying active spatial prior boost.
        
        Mathematical Formulation:
        -------------------------
        Let S_vis in [0.0, 1.0] be the visual cosine similarity.
        If an active prior exists matching candidate_entity_id or candidate_name:
            S_final = min(1.0, S_vis + prior_boost)
        otherwise:
            S_final = S_vis
            
        This provides heavy Bayesian prior weighting when an entity appears in
        the physically expected doorway/zone within the predicted transit window,
        preventing ID swapping with visually similar entities.
        """
        now = time.time() if timestamp is None else float(timestamp)
        active_priors = self.get_active_priors(target_camera, target_zone, timestamp=now)

        for prior in active_priors:
            match = False
            if candidate_entity_id is not None and prior.entity_id is not None:
                if candidate_entity_id == prior.entity_id:
                    match = True
            elif candidate_name and prior.entity_name:
                if candidate_name.lower() == prior.entity_name.lower():
                    match = True

            if match:
                weighted_score = min(1.0, visual_similarity + prior.prior_boost)
                return weighted_score, prior

        return visual_similarity, None

    def consume_prior(self, prior_id: str) -> bool:
        """Mark a spatial prior as consumed once an entity has been re-identified."""
        for p in self.active_priors:
            if p.prior_id == prior_id:
                p.consumed = True
                return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        """Serializes topology links to dictionary."""
        return {
            "links": [link.to_dict() for link in self.links.values() if not link.link_id.endswith("_rev")],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CrossCameraTopology":
        """Instantiates CrossCameraTopology from dictionary."""
        topology = cls()
        links_data = data.get("links", [])
        for ld in links_data:
            link = SpatialTransitionLink.from_dict(ld)
            topology.add_link(link)
        return topology
