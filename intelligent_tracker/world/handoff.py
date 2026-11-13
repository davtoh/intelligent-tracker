"""Multi-camera entity handoff coordinator and overlapping FOV deduplication."""

import math
import threading
import time
from typing import Any

import numpy as np

from intelligent_tracker.world._bridge_helpers import (
    append_bounded_trajectory,
    compute_global_track_xy,
    decorate_track_identity,
    scoped_zone_id,
)
from intelligent_tracker.world._handoff_helpers import (
    build_track_entity,
    can_merge_entities,
    canonical_rank,
    categories_compatible,
    cosine_similarity,
    extract_embedding,
    merge_world_entities,
    predict_entity_xy,
    prior_attr,
    query_priors,
    resolve_entity_for_prior,
)
from intelligent_tracker.world._lifecycle import find_entity_by_track, list_entities_snapshot
from intelligent_tracker.world.coordinates import GlobalCoordinateMapper
from intelligent_tracker.world.graph import WorldGraph
from intelligent_tracker.world.nodes import WorldEntity
from intelligent_tracker.world.transitions import WorldTransitionRegistry, is_transit_kinematically_plausible


class MultiCameraHandoffCoordinator:
    """Coordinates overlapping FOV deduplication and cross-camera transit handoffs."""

    def __init__(
        self, world_graph: WorldGraph, *, coordinate_mapper: GlobalCoordinateMapper | None = None,
        topology: Any = None, transition_registry: WorldTransitionRegistry | None = None,
        overlap_radius_m: float = 1.2, reid_similarity_threshold: float = 0.55,
        overlap_concurrency_s: float = 2.0, max_trajectory_points: int = 120,
        max_transit_speed_mps: float = 12.0,
    ) -> None:
        self.world_graph = world_graph
        self.coordinate_mapper = coordinate_mapper
        self.topology = topology
        self.transition_registry = transition_registry or getattr(topology, "world_transitions", None)
        self.overlap_radius_m = max(0.05, float(overlap_radius_m))
        self.reid_similarity_threshold = float(reid_similarity_threshold)
        self.overlap_concurrency_s = max(0.05, float(overlap_concurrency_s))
        self.max_trajectory_points = max(1, int(max_trajectory_points))
        self.max_transit_speed_mps = max(0.1, float(max_transit_speed_mps))
        self._lock = threading.RLock()
        self._embeddings: dict[str, np.ndarray] = {}
        self._departed: dict[str, WorldEntity] = {}

    def register_embedding(self, entity_key: str, embedding: Any) -> None:
        """Cache a Re-ID feature embedding keyed by world_entity_id."""
        if entity_key and embedding is not None:
            with self._lock:
                self._embeddings[entity_key] = np.asarray(embedding, dtype=np.float32).ravel()

    def record_zone_exit(
        self, camera_id: str, zone_name: str, *, entity_id: int | None = None,
        world_entity_id: str | None = None, entity_name: str = "Unidentified",
        exit_global_xy: tuple[float, float] | None = None, embedding: Any = None,
        timestamp: float | None = None, metadata: dict[str, Any] | None = None,
    ) -> list[Any]:
        """Record a zone exit, snapshot departing WorldEntity state, and spawn transit priors."""
        now = float(timestamp) if timestamp is not None else time.time()
        we_id = world_entity_id or (f"entity:{int(entity_id)}" if entity_id is not None else None)
        node = self.world_graph.get_node(we_id, node_type="entity") if we_id else None
        if isinstance(node, WorldEntity):
            with self._lock:
                self._departed[node.world_entity_id] = node
            exit_global_xy = exit_global_xy or node.global_xy
            entity_name = entity_name if entity_name != "Unidentified" else node.name
        meta = dict(metadata or {})
        if we_id:
            meta.setdefault("world_entity_id", we_id)
            self.register_embedding(we_id, embedding)
        if self.topology is not None:
            return self.topology.record_zone_exit(
                camera_id, zone_name, entity_name=entity_name, entity_id=entity_id,
                embedding=embedding, timestamp=now, metadata=meta, exit_global_xy=exit_global_xy,
            )
        if self.transition_registry is not None:
            return self.transition_registry.record_zone_exit(
                camera_id, zone_name, entity_id=entity_id, entity_name=entity_name,
                exit_global_xy=exit_global_xy, timestamp=now, metadata=meta,
            )
        return []

    def deduplicate_overlapping_entities(
        self, *, timestamp: float | None = None, concurrency_window: float | None = None,
    ) -> list[tuple[str, str]]:
        """Merge concurrent WorldEntities across overlapping cameras within overlap_radius_m."""
        now = float(timestamp) if timestamp is not None else time.time()
        win = self.overlap_concurrency_s if concurrency_window is None else max(0.0, float(concurrency_window))
        entities = sorted(list_entities_snapshot(self.world_graph), key=canonical_rank)
        merged_away, merges = set(), []
        for idx, primary in enumerate(entities):
            if primary.world_entity_id in merged_away or primary.global_xy is None:
                continue
            for cand in entities[idx + 1 :]:
                if cand.world_entity_id in merged_away:
                    continue
                with self._lock:
                    ok = can_merge_entities(
                        primary, cand, win, self.overlap_radius_m, self.reid_similarity_threshold,
                        self._embeddings.get(primary.world_entity_id), self._embeddings.get(cand.world_entity_id),
                    )
                    if ok and primary.world_entity_id not in self._embeddings and cand.world_entity_id in self._embeddings:
                        self._embeddings[primary.world_entity_id] = self._embeddings.pop(cand.world_entity_id)
                if ok:
                    primary = merge_world_entities(self.world_graph, primary, cand, now, self.max_trajectory_points)
                    merged_away.add(cand.world_entity_id)
                    merges.append((primary.world_entity_id, cand.world_entity_id))
        return merges

    def handoff_track(
        self, camera_id: str, track: Any, *, zone_id: str = "", embedding: Any = None,
        visual_similarity: float | None = None, timestamp: float | None = None,
    ) -> WorldEntity:
        """Bind a camera track via existing binding, overlapping FOV, transit prior, or new session."""
        now = float(timestamp) if timestamp is not None else time.time()
        tid = int(track.track_id)
        mapper = self.coordinate_mapper or getattr(self.world_graph, "coordinate_mapper", None)
        cand_xy = compute_global_track_xy(track, camera_id=camera_id, coordinate_mapper=mapper, world_graph=self.world_graph)
        emb = extract_embedding(track, embedding)
        entity = (
            find_entity_by_track(self.world_graph, camera_id, tid)
            or self._match_overlapping_entity(camera_id, track, cand_xy, emb, now)
            or self._match_transit_prior(camera_id, track, zone_id, cand_xy, emb, visual_similarity, now)
            or build_track_entity(self.world_graph, camera_id, track, tid, now)
        )
        entity.camera_tracks[camera_id] = tid
        if cand_xy is not None:
            entity.global_xy = cand_xy
            append_bounded_trajectory(entity, cand_xy, now, max_points=self.max_trajectory_points)
        entity.last_seen = max(entity.last_seen, now)
        scoped_zone = scoped_zone_id(self.world_graph, camera_id, zone_id)
        if scoped_zone:
            entity.active_zones.setdefault(camera_id, set()).add(scoped_zone)
        if entity.entity_id is not None:
            decorate_track_identity(track, entity.entity_id, entity.name, entity.category, entity.confidence)
        self.register_embedding(entity.world_entity_id, emb)
        return self.world_graph.upsert_entity(entity)

    def _match_overlapping_entity(
        self, camera_id: str, track: Any, cand_xy: tuple[float, float] | None, emb: np.ndarray | None, now: float,
    ) -> WorldEntity | None:
        """Find the closest concurrent WorldEntity from another camera within overlap_radius_m."""
        if cand_xy is None:
            return None
        cat = getattr(track, "entity_category", None) or getattr(track, "label", "") or ""
        eid = getattr(track, "entity_id", None)
        best: tuple[float, WorldEntity] | None = None
        for entity in list_entities_snapshot(self.world_graph):
            if camera_id in entity.camera_tracks or entity.global_xy is None or abs(now - entity.last_seen) > self.overlap_concurrency_s:
                continue
            if eid is not None and entity.entity_id is not None and int(eid) != entity.entity_id:
                continue
            dist = math.hypot(cand_xy[0] - entity.global_xy[0], cand_xy[1] - entity.global_xy[1])
            if dist > self.overlap_radius_m or not categories_compatible(cat, entity.category):
                continue
            with self._lock:
                sim = cosine_similarity(emb, self._embeddings.get(entity.world_entity_id))
            if (sim is None or sim >= self.reid_similarity_threshold) and (best is None or dist < best[0]):
                best = (dist, entity)
        return best[1] if best is not None else None

    def _match_transit_prior(
        self, camera_id: str, track: Any, zone_id: str, cand_xy: tuple[float, float] | None,
        emb: np.ndarray | None, visual_similarity: float | None, now: float,
    ) -> WorldEntity | None:
        """Match a newly arriving track against active topology priors and velocity projections."""
        best: tuple[float, Any, WorldEntity] | None = None
        cat = getattr(track, "entity_category", None) or getattr(track, "label", "") or ""
        for prior in query_priors(self.topology, self.transition_registry, camera_id, zone_id, cand_xy, now):
            with self._lock:
                entity = resolve_entity_for_prior(self.world_graph, self._departed, prior, now)
                cached_emb = self._embeddings.get(entity.world_entity_id) if entity is not None else None
            if entity is None or not categories_compatible(cat, entity.category):
                continue
            exit_xy = prior_attr(prior, "exit_global_xy") or entity.global_xy
            if not is_transit_kinematically_plausible(exit_xy, cand_xy, float(prior_attr(prior, "exit_time", now)), now, self.max_transit_speed_mps):
                continue
            sim = visual_similarity if visual_similarity is not None else cosine_similarity(emb, prior_attr(prior, "embedding") or cached_emb)
            boosted = min(1.0, (0.5 if sim is None else sim) + float(prior_attr(prior, "prior_boost", 0.0)))
            if sim is not None and boosted < self.reid_similarity_threshold:
                continue
            pred_xy = predict_entity_xy(entity, now)
            vel_err = math.hypot(cand_xy[0] - pred_xy[0], cand_xy[1] - pred_xy[1]) if (cand_xy and pred_xy) else 0.0
            score = boosted - (0.02 * vel_err)
            if best is None or score > best[0]:
                best = (score, prior, entity)
        if best is None:
            return None
        pid = prior_attr(best[1], "prior_id")
        if pid and (self.topology or self.transition_registry):
            (self.topology or self.transition_registry).consume_prior(pid)
        with self._lock:
            self._departed.pop(best[2].world_entity_id, None)
        return best[2]

    def sync_camera_tracks(
        self, camera_id: str, tracks: dict[int, Any], *, zone_lookup: dict[int, str] | None = None,
        timestamp: float | None = None, deduplicate: bool = True,
    ) -> list[WorldEntity]:
        """Synchronize all active tracks for one camera through handoff and overlap deduplication."""
        now = float(timestamp) if timestamp is not None else time.time()
        updated = [
            self.handoff_track(
                camera_id, trk,
                zone_id=(zone_lookup.get(tid, "") if zone_lookup else "") or getattr(trk, "current_zone", "") or "",
                timestamp=now,
            )
            for tid, trk in tracks.items()
        ]
        if deduplicate:
            self.deduplicate_overlapping_entities(timestamp=now)
        return updated
