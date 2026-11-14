"""Gallery Matcher & Re-Appearance Engine.

Coordinates short-term frame-to-frame multi-object tracking with long-term visual Re-ID
gallery matching against TrackerDB and in-memory session tracking.
"""

import time
import logging
from collections import deque
from typing import Dict, List, Optional, Any
import numpy as np

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.reid import BaseFeatureExtractor, batch_cosine_similarity
from intelligent_tracker.tracker import Track, check_track_occlusions
from intelligent_tracker.matching.types import EntityIdentifiedEvent
from intelligent_tracker.matching.session_gallery import SessionGalleryManager
from intelligent_tracker.matching.adaptive_memory import apply_bounded_ema_update
from intelligent_tracker.matching._gallery_signals import apply_track_confidence_signals, emit_periodic_sighting

logger = logging.getLogger(__name__)


def _apply_topology_priors(
    topology: Any,
    gallery_entity_ids: List[int],
    gallery_names: List[str],
    similarities: np.ndarray,
    source: str,
    zone_id: str,
    now: float,
) -> Dict[int, Any]:
    """Compute and apply cross-camera transition predictive spatial priors to similarity vector."""
    matched_priors = {}
    for g_idx, g_eid in enumerate(gallery_entity_ids):
        g_name = gallery_names[g_idx]
        orig_sim = float(similarities[g_idx])
        boosted_sim, prior = topology.compute_weighted_similarity(
            visual_similarity=orig_sim,
            candidate_entity_id=g_eid,
            candidate_name=g_name,
            target_camera=source,
            target_zone=zone_id,
            timestamp=now,
        )
        similarities[g_idx] = boosted_sim
        if prior is not None:
            matched_priors[g_idx] = prior
    return matched_priors


def _process_confirmed_identification(
    matcher: "GalleryMatcher",
    track: Track,
    best_idx: int,
    best_score: float,
    query_vec: np.ndarray,
    source: str,
    now: float,
    zone_id: str,
) -> Optional[EntityIdentifiedEvent]:
    """Update track metadata, debounce sightings in DB, and execute continuous EMA adaptation."""
    tid = track.track_id
    entity_id = matcher.gallery_entity_ids[best_idx]
    name = matcher.gallery_names[best_idx]
    category = matcher.gallery_categories[best_idx]

    if matcher.world_bridge is not None:
        matcher.world_bridge.sync_track_identification(
            source, track, entity_id,
            name=name, category=category, confidence=best_score,
            zone_id=zone_id, timestamp=now,
        )
    else:
        track.entity_id = entity_id
        track.entity_name = name
        track.entity_category = category
        track.reid_score = best_score
        track.identity_label = name

    event = None
    was_identified = tid in matcher._identified_tracks
    prev_eid = matcher._identified_tracks[tid]["entity_id"] if was_identified else None

    if not was_identified or prev_eid != entity_id:
        matcher._identified_tracks[tid] = {
            "entity_id": entity_id,
            "name": name,
            "category": category,
            "similarity": best_score,
        }
        event = EntityIdentifiedEvent(
            entity_id=entity_id,
            name=name,
            category=category,
            track_id=tid,
            similarity=best_score,
            source=source,
            timestamp=now,
            zone_id=zone_id,
            bbox=track.bbox,
        )

    if matcher.auto_adaptive_memory and best_score >= matcher.ema_confidence_threshold:
        matcher._apply_bounded_ema_update(
            entity_id=entity_id,
            query_vec=query_vec,
            gallery_idx=best_idx,
            timestamp=now,
        )

    emit_periodic_sighting(
        matcher, entity_id=entity_id, name=name, category=category,
        track=track, confidence=best_score, source=source, zone_id=zone_id, timestamp=now,
    )
    return event


class GalleryMatcher:
    """Coordinates gallery Re-ID matching between active tracks and persistent TrackerDB."""

    def __init__(
        self,
        db: Optional[TrackerDB] = None,
        extractor: Optional[BaseFeatureExtractor] = None,
        reid_threshold: float = 0.65,
        feature_history_len: int = 10,
        sighting_interval: float = 4.0,
        min_track_hits: int = 2,
        auto_session_gallery: bool = True,
        session_reid_threshold: float = 0.55,
        spatial_bonus_radius: float = 200.0,
        spatial_bonus_max_dt: float = 60.0,
        topology: Optional[Any] = None,
        camera_id: str = "cam_01",
        active_learning: Optional[Any] = None,
        auto_adaptive_memory: bool = True,
        ema_alpha: float = 0.05,
        ema_confidence_threshold: float = 0.75,
        min_anchor_similarity: float = 0.65,
        max_drift_threshold: Optional[float] = None,
        world_bridge: Optional[Any] = None,
        **kwargs,
    ):
        self.db = db
        self.extractor = extractor
        self.topology = topology
        self.camera_id = camera_id
        self.active_learning = active_learning
        self.world_bridge = world_bridge
        self.fts_index = kwargs.get("fts_index")
        self.auto_adaptive_memory = bool(auto_adaptive_memory)
        self.ema_alpha = float(ema_alpha)
        self.ema_confidence_threshold = float(ema_confidence_threshold)
        self.min_anchor_similarity = (
            float(max_drift_threshold) if max_drift_threshold is not None else float(min_anchor_similarity)
        )

        self.reid_threshold = float(reid_threshold)
        self.feature_history_len = int(feature_history_len)
        self.sighting_interval = float(sighting_interval)
        self.min_track_hits = int(min_track_hits)

        self.auto_session_gallery = bool(auto_session_gallery)
        self.session_reid_threshold = float(session_reid_threshold)
        self.spatial_bonus_radius = float(spatial_bonus_radius)
        self.spatial_bonus_max_dt = float(spatial_bonus_max_dt)

        self._session_manager = SessionGalleryManager(
            session_reid_threshold=self.session_reid_threshold,
            spatial_bonus_radius=self.spatial_bonus_radius,
            spatial_bonus_max_dt=self.spatial_bonus_max_dt,
            feature_history_len=self.feature_history_len,
        )
        self.session_entities = self._session_manager.session_entities
        self._active_tracks_cache: Dict[int, Track] = {}

        self._track_features: Dict[int, deque] = {}
        self._last_sighting_time: Dict[int, float] = {}
        self._identified_tracks: Dict[int, Dict[str, Any]] = {}

        self.gallery_matrix = np.empty((0, 0), dtype=np.float32)
        self.gallery_entity_ids: List[int] = []
        self.gallery_names: List[str] = []
        self.gallery_categories: List[str] = []

        self.reload_gallery()

    @property
    def next_session_id(self) -> int:
        return self._session_manager.next_session_id

    def reload_gallery(self):
        """Reload and vectorize all enrolled active signatures from SQLite database."""
        if self.db is None:
            self.gallery_matrix = np.empty((0, 0), dtype=np.float32)
            self.gallery_entity_ids = []
            self.gallery_names = []
            self.gallery_categories = []
            return
        expected_dim = getattr(self.extractor, "embedding_dim", None)
        mat, ids, names, categories = self.db.get_gallery_embeddings(expected_dim=expected_dim)
        self.gallery_matrix = mat
        self.gallery_entity_ids = ids
        self.gallery_names = names
        self.gallery_categories = categories

        if expected_dim is not None and len(ids) == 0:
            try:
                all_sigs = self.db.get_signatures()
                if all_sigs:
                    other_dims = {
                        (s["embedding"].shape[0] if hasattr(s.get("embedding"), "shape") else 0)
                        for s in all_sigs
                    }
                    logger.info(
                        "GalleryMatcher: %d active signatures skipped (dim mismatch: %s vs %s dim=%d).",
                        len(all_sigs), ", ".join(str(d) for d in sorted(other_dims) if d > 0),
                        self.extractor.__class__.__name__, expected_dim,
                    )
            except Exception:
                pass

    refresh_gallery = reload_gallery

    @property
    def gallery_size(self) -> int:
        return len(self.gallery_entity_ids)

    def _get_smoothed_embedding(self, track_id: int) -> Optional[np.ndarray]:
        """Compute mean feature vector from accumulated history."""
        buf = self._track_features.get(track_id)
        if not buf:
            return None
        arr = np.array(buf, dtype=np.float32)
        mean_vec = np.mean(arr, axis=0)
        norm = np.linalg.norm(mean_vec)
        if norm > 1e-7:
            mean_vec = mean_vec / norm
        return mean_vec

    def _match_persistent_gallery(
        self,
        track: Track,
        query_vec: np.ndarray,
        frame: np.ndarray,
        source: str,
        now: float,
        zone_id: str,
    ) -> Optional[EntityIdentifiedEvent]:
        """Query persistent database gallery with cross-camera priors and active learning."""
        similarities = batch_cosine_similarity(self.gallery_matrix, query_vec)
        if similarities.size == 0:
            return None

        matched_priors = {}
        raw_similarities = None
        if self.topology is not None:
            raw_similarities = similarities.copy()
            matched_priors = _apply_topology_priors(
                self.topology, self.gallery_entity_ids, self.gallery_names,
                similarities, source, zone_id, now,
            )

        best_idx = int(np.argmax(similarities))
        best_score = float(similarities[best_idx])

        if best_score >= self.reid_threshold:
            apply_track_confidence_signals(
                track, extractor=self.extractor, query_vec=query_vec, gallery_matrix=self.gallery_matrix,
                gallery_entity_ids=self.gallery_entity_ids, similarities=similarities,
                raw_similarities=raw_similarities, matched_priors=matched_priors, best_idx=best_idx,
            )
            if self.topology is not None and best_idx in matched_priors:
                self.topology.consume_prior(matched_priors[best_idx].prior_id)
            return _process_confirmed_identification(
                self, track, best_idx, best_score, query_vec, source, now, zone_id
            )

        if self.active_learning is not None:
            cand_eid = self.gallery_entity_ids[best_idx] if best_idx < len(self.gallery_entity_ids) else None
            cand_name = self.gallery_names[best_idx] if best_idx < len(self.gallery_names) else ""
            cand_cat = self.gallery_categories[best_idx] if best_idx < len(self.gallery_categories) else ""
            self.active_learning.consider_candidate(
                track=track, frame=frame, similarity=best_score,
                suggested_entity_id=cand_eid, suggested_name=cand_name,
                suggested_category=cand_cat, camera_id=source, timestamp=now,
            )
        return None

    def match_track(
        self,
        track: Track,
        frame: np.ndarray,
        source: str = "",
        timestamp: Optional[float] = None,
        zone_id: str = "",
    ) -> Optional[EntityIdentifiedEvent]:
        """Process a single track: extract feature, smooth embedding, and query gallery."""
        if getattr(track, "is_cluttered", False):
            return None

        now = timestamp if timestamp is not None else time.time()
        source = source or self.camera_id
        zone_id = zone_id or getattr(track, "current_zone", "") or ""
        tid = track.track_id

        if track.hits < self.min_track_hits or track.bbox[2] <= 4 or track.bbox[3] <= 4 or self.extractor is None:
            return None

        if tid not in self._track_features:
            self._track_features[tid] = deque(maxlen=self.feature_history_len)

        feat = self.extractor.extract(frame, track.bbox)
        self._track_features[tid].append(feat)

        query_vec = self._get_smoothed_embedding(tid)
        if query_vec is None:
            return None

        if self.gallery_size > 0:
            ev = self._match_persistent_gallery(track, query_vec, frame, source, now, zone_id)
            if ev is not None or getattr(track, "entity_id", None) is not None:
                return ev

        if self.auto_session_gallery and getattr(track, "entity_name", None) is None:
            if not self._session_manager.update_existing_track_session(track, feat, now):
                matched = self._session_manager.match_returning_entity(
                    track, feat, query_vec, now, self._active_tracks_cache
                )
                if not matched:
                    self._session_manager.allocate_new_session_entity(track, feat, now)
            if self.world_bridge is not None and getattr(track, "session_id", None) is not None:
                self.world_bridge.sync_session_track(
                    source, track, track.session_id,
                    label=track.identity_label or "", category=track.label,
                    zone_id=zone_id, timestamp=now,
                )

        return None

    def match_tracks(
        self,
        tracks: Dict[int, Track],
        frame: np.ndarray,
        source: str = "",
        timestamp: Optional[float] = None,
        zone_lookup: Optional[Dict[int, str]] = None,
    ) -> List[EntityIdentifiedEvent]:
        """Process all active tracks, update gallery Re-ID status, and return identification events."""
        now = timestamp if timestamp is not None else time.time()
        source = source or self.camera_id
        events = []
        self._active_tracks_cache = tracks

        active_tids = set(tracks.keys())
        stale_tids = [tid for tid in self._track_features if tid not in active_tids]
        for tid in stale_tids:
            self._track_features.pop(tid, None)
            self._last_sighting_time.pop(tid, None)
            self._identified_tracks.pop(tid, None)

        self._session_manager.update_exit_telemetry(tracks)
        check_track_occlusions(tracks, timestamp=now)

        for tid, trk in tracks.items():
            zid = zone_lookup.get(tid, "") if zone_lookup else ""
            ev = self.match_track(trk, frame, source=source, timestamp=now, zone_id=zid)
            if ev is not None:
                events.append(ev)

        if self.world_bridge is not None:
            self.world_bridge.prune_stale_tracks(camera_id=source, active_track_ids=active_tids, timestamp=now)
            self.world_bridge.sync_camera_tracks(source, tracks, zone_lookup=zone_lookup, timestamp=now)

        return events

    def _apply_bounded_ema_update(
        self, entity_id: int, query_vec: Optional[np.ndarray] = None,
        gallery_idx: Optional[int] = None, timestamp: Optional[float] = None,
        candidate_features: Optional[np.ndarray] = None, track_confidence: float = 0.9,
    ) -> bool:
        """Continuously adapt running descriptor centroid using Bounded Exponential Moving Average."""
        return apply_bounded_ema_update(
            db=self.db, gallery_matrix=self.gallery_matrix, gallery_entity_ids=self.gallery_entity_ids,
            ema_alpha=self.ema_alpha, min_anchor_similarity=self.min_anchor_similarity,
            entity_id=entity_id, query_vec=query_vec, gallery_idx=gallery_idx,
            timestamp=timestamp, candidate_features=candidate_features, track_confidence=track_confidence,
        )

    def reassign_track(
        self,
        track: Track,
        new_entity_id: int,
        frame: Optional[np.ndarray] = None,
    ) -> bool:
        """Manually reassign a track to a different entity and optionally enroll a crop."""
        entity = self.db.get_entity(new_entity_id) if self.db is not None else None
        if not entity:
            return False

        if self.world_bridge is not None:
            self.world_bridge.reassign_track(
                self.camera_id, track, new_entity_id,
                name=entity["name"], category=entity["category"],
            )
        else:
            track.entity_id = new_entity_id
            track.entity_name = entity["name"]
            track.entity_category = entity["category"]
            track.reid_score = 1.0

        self._identified_tracks[track.track_id] = {
            "entity_id": new_entity_id,
            "name": entity["name"],
            "category": entity["category"],
            "similarity": 1.0,
        }

        if frame is not None and self.extractor is not None and self.db is not None:
            feat = self.extractor.extract(frame, track.bbox)
            self.db.add_signature(new_entity_id, feat)
            self.reload_gallery()

        return True
