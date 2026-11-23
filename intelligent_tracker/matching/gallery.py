"""Gallery Matcher & Re-Appearance Engine.

Coordinates short-term frame-to-frame multi-object tracking with long-term visual Re-ID
gallery matching against TrackerDB and in-memory session tracking.
"""

import time
import logging
from typing import Dict, List, Optional, Any
import numpy as np

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.reid import BaseFeatureExtractor, batch_cosine_similarity
from intelligent_tracker.tracker import Track, check_track_occlusions
from intelligent_tracker.matching.types import EntityIdentifiedEvent
from intelligent_tracker.matching.feature_buffer import TrackFeatureBuffer
from intelligent_tracker.matching.session_gallery import SessionGalleryManager
from intelligent_tracker.matching.adaptive_memory import apply_bounded_ema_update
from intelligent_tracker.matching._gallery_signals import (
    apply_topology_priors,
    apply_track_confidence_signals,
    process_confirmed_identification,
)

logger = logging.getLogger(__name__)
_COASTING_STATES = frozenset({"coasting", "occluded", "predicting"})


def _is_coasting_or_occluded(track: Track) -> bool:
    """Return True when a track is coasting/occluded and must not pollute Re-ID features."""
    return getattr(track, "missed_frames", 0) > 0 or getattr(track, "state", "") in _COASTING_STATES


class GalleryMatcher:
    """Coordinates gallery Re-ID matching between active tracks and persistent TrackerDB."""

    def __init__(
        self,
        db: Optional[TrackerDB] = None, extractor: Optional[BaseFeatureExtractor] = None,
        reid_threshold: float = 0.65, feature_history_len: int = 10, sighting_interval: float = 4.0,
        min_track_hits: int = 2, auto_session_gallery: bool = True, session_reid_threshold: float = 0.55,
        spatial_bonus_radius: float = 200.0, spatial_bonus_max_dt: float = 60.0,
        topology: Optional[Any] = None, camera_id: str = "cam_01", active_learning: Optional[Any] = None,
        auto_adaptive_memory: bool = True, ema_alpha: float = 0.05, ema_confidence_threshold: float = 0.75,
        min_anchor_similarity: float = 0.65, max_drift_threshold: Optional[float] = None,
        world_bridge: Optional[Any] = None, **kwargs: Any,
    ):
        self.db, self.extractor, self.topology = db, extractor, topology
        self.camera_id, self.active_learning, self.world_bridge = camera_id, active_learning, world_bridge
        self.fts_index = kwargs.get("fts_index")
        self.auto_adaptive_memory = bool(auto_adaptive_memory)
        self.ema_alpha, self.ema_confidence_threshold = float(ema_alpha), float(ema_confidence_threshold)
        self.min_anchor_similarity = float(max_drift_threshold if max_drift_threshold is not None else min_anchor_similarity)
        self.reid_threshold, self.feature_history_len = float(reid_threshold), int(feature_history_len)
        self.sighting_interval, self.min_track_hits = float(sighting_interval), int(min_track_hits)
        self.auto_session_gallery = bool(auto_session_gallery)
        self.session_reid_threshold = float(session_reid_threshold)
        self.spatial_bonus_radius, self.spatial_bonus_max_dt = float(spatial_bonus_radius), float(spatial_bonus_max_dt)
        self._init_runtime_caches(kwargs.get("coast_grace_seconds", 2.0))
        self.reload_gallery()

    def _init_runtime_caches(self, coast_grace_seconds: float) -> None:
        """Initialize session gallery, feature buffer, and empty gallery matrix."""
        self._session_manager = SessionGalleryManager(
            session_reid_threshold=self.session_reid_threshold,
            spatial_bonus_radius=self.spatial_bonus_radius,
            spatial_bonus_max_dt=self.spatial_bonus_max_dt,
            feature_history_len=self.feature_history_len,
        )
        self.session_entities = self._session_manager.session_entities
        self._active_tracks_cache: Dict[int, Track] = {}
        self._feature_buffer = TrackFeatureBuffer(
            feature_history_len=self.feature_history_len,
            coast_grace_seconds=float(coast_grace_seconds),
        )
        self._track_features = self._feature_buffer.track_features
        self._last_sighting_time = self._feature_buffer.last_sighting_time
        self._identified_tracks = self._feature_buffer.identified_tracks
        self.gallery_matrix = np.empty((0, 0), dtype=np.float32)
        self.gallery_entity_ids: List[int] = []
        self.gallery_names: List[str] = []
        self.gallery_categories: List[str] = []

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
        return self._feature_buffer.get_smoothed_embedding(track_id)

    def _match_persistent_gallery(
        self, track: Track, query_vec: np.ndarray, frame: np.ndarray,
        source: str, now: float, zone_id: str,
    ) -> Optional[EntityIdentifiedEvent]:
        """Query persistent database gallery with cross-camera priors and active learning."""
        similarities = batch_cosine_similarity(self.gallery_matrix, query_vec)
        if similarities.size == 0:
            return None

        matched_priors = {}
        raw_similarities = None
        if self.topology is not None:
            raw_similarities = similarities.copy()
            matched_priors = apply_topology_priors(
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
            return process_confirmed_identification(
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
        if _is_coasting_or_occluded(track):
            self._feature_buffer.mark_active(track.track_id, now)
            self._feature_buffer.restore_track_identity(track)
            return None
        if track.hits < self.min_track_hits or track.bbox[2] <= 4 or track.bbox[3] <= 4 or self.extractor is None:
            return None

        source = source or self.camera_id
        zone_id = zone_id or getattr(track, "current_zone", "") or ""
        feat = self.extractor.extract(frame, track.bbox)
        self._feature_buffer.append(track.track_id, feat, now)
        query_vec = self._get_smoothed_embedding(track.track_id)
        if query_vec is None:
            return None

        if self.gallery_size > 0:
            ev = self._match_persistent_gallery(track, query_vec, frame, source, now, zone_id)
            if ev is not None or getattr(track, "entity_id", None) is not None:
                return ev
        if self.auto_session_gallery and getattr(track, "entity_name", None) is None:
            self._match_session_track(track, feat, query_vec, source, zone_id, now)
        return None

    def _match_session_track(
        self, track: Track, feat: np.ndarray, query_vec: np.ndarray,
        source: str, zone_id: str, now: float,
    ) -> None:
        """Assign or update ephemeral session entity for an unidentified track."""
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
        self._feature_buffer.prune_stale(active_tids, now)
        self._session_manager.update_exit_telemetry(tracks)
        check_track_occlusions(tracks, timestamp=now)

        for tid, trk in tracks.items():
            zid = zone_lookup.get(tid, "") if zone_lookup else ""
            ev = self.match_track(trk, frame, source=source, timestamp=now, zone_id=zid)
            if ev is not None:
                events.append(ev)

        if self.world_bridge is not None:
            coasting_tids = {tid for tid, trk in tracks.items() if _is_coasting_or_occluded(trk)}
            self.world_bridge.prune_stale_tracks(
                camera_id=source, active_track_ids=active_tids,
                coasting_track_ids=coasting_tids, timestamp=now,
            )
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
