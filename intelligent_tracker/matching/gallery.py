"""Gallery Matcher & Re-Appearance Engine.

Coordinates short-term frame-to-frame multi-object tracking with long-term visual Re-ID
gallery matching against TrackerDB and in-memory session tracking.
"""

import time
import logging
from typing import Dict, List, Optional, Any
import numpy as np

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.reid import BaseFeatureExtractor
from intelligent_tracker.tracker import Track, check_track_occlusions
from intelligent_tracker.matching.types import EntityIdentifiedEvent
from intelligent_tracker.matching.feature_buffer import TrackFeatureBuffer
from intelligent_tracker.matching.identity_hysteresis import IdentityHysteresisTracker
from intelligent_tracker.matching.session_gallery import SessionGalleryManager
from intelligent_tracker.matching.adaptive_memory import apply_bounded_ema_update
from intelligent_tracker.matching._gallery_matching import (
    log_skipped_signature_dims,
    match_persistent_gallery,
    resolve_entity_avatars,
)

logger = logging.getLogger(__name__)
_COASTING_STATES = frozenset({"coasting", "occluded", "predicting"})


def _is_coasting_or_occluded(track: Track) -> bool:
    """Return True when a track is coasting/occluded and must not pollute Re-ID features."""
    return getattr(track, "missed_frames", 0) > 0 or getattr(track, "state", "") in _COASTING_STATES


def _should_skip_track_reid(matcher: "GalleryMatcher", track: Track, now: float) -> bool:
    """Return True when a track should bypass feature extraction while preserving locked identity."""
    if getattr(track, "is_cluttered", False):
        return True
    locked = matcher.hysteresis.get_locked(track.track_id)
    if _is_coasting_or_occluded(track):
        matcher._feature_buffer.mark_active(track.track_id, now)
        if locked is not None:
            matcher.hysteresis.apply_to_track(track, locked)
        else:
            matcher._feature_buffer.restore_track_identity(track)
        return True
    unready = (
        (track.hits < matcher.min_track_hits and getattr(track, "state", "") != "confirmed")
        or track.bbox[2] <= 4 or track.bbox[3] <= 4 or matcher.extractor is None
    )
    if unready and locked is not None:
        matcher.hysteresis.apply_to_track(track, locked)
    return unready


def _recompute_mismatched_signatures(db: Any, extractor: Any, expected_dim: int) -> None:
    """Auto-recompute DB signatures whose embedding dim mismatches extractor from stored crop_path."""
    if db is None or extractor is None or not hasattr(db, "get_signatures") or not hasattr(db, "update_entity_signature"):
        return
    try:
        sigs = db.get_signatures()
    except Exception:
        return
    import os
    import cv2
    for sig in sigs:
        emb = sig.get("embedding")
        dim = int(emb.shape[0]) if hasattr(emb, "shape") and emb.ndim == 1 else (int(emb.size) if hasattr(emb, "size") else 0)
        crop_path = str(sig.get("crop_path") or "").strip()
        if dim == expected_dim:
            logger.debug("Signature id=%s already matches expected_dim=%d", sig.get("id"), expected_dim)
            continue
        if not crop_path or not os.path.exists(crop_path):
            logger.debug("Signature id=%s dim=%d mismatch without readable crop_path", sig.get("id"), dim)
            continue
        try:
            crop = cv2.imread(crop_path)
            if crop is None or getattr(crop, "size", 0) == 0:
                logger.debug("Empty crop skipped during signature recompute: %s", crop_path)
                continue
            new_vec = extractor.extract_crop(crop)
            if hasattr(new_vec, "shape") and int(new_vec.shape[0]) == expected_dim and float(np.linalg.norm(new_vec)) > 1e-7:
                db.update_entity_signature(int(sig["id"]), embedding=new_vec)
        except Exception as exc:
            logger.debug("Signature recompute skipped for id=%s: %s", sig.get("id"), exc)


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
        self.negative_suppression_threshold = float(kwargs.get("negative_suppression_threshold", 0.78))
        self.global_negative_threshold = float(kwargs.get("global_negative_threshold", 0.82))
        raw_cats = kwargs.get("tracked_categories")
        self.tracked_categories: Optional[List[str]] = (
            [str(c).strip().lower() for c in raw_cats if str(c).strip()] or None
            if raw_cats is not None
            else None
        )
        self._init_runtime_caches(kwargs)
        self.reload_gallery()

    def _init_runtime_caches(self, kwargs: Dict[str, Any]) -> None:
        """Initialize session gallery, feature buffer, hysteresis tracker, and gallery arrays."""
        coast_grace = float(kwargs.get("coast_grace_seconds", 2.0))
        self._session_manager = SessionGalleryManager(
            session_reid_threshold=self.session_reid_threshold,
            spatial_bonus_radius=self.spatial_bonus_radius,
            spatial_bonus_max_dt=self.spatial_bonus_max_dt,
            feature_history_len=self.feature_history_len,
        )
        self.session_entities = self._session_manager.session_entities
        self._active_tracks_cache: Dict[int, Track] = {}
        self._feature_buffer = TrackFeatureBuffer(
            feature_history_len=self.feature_history_len, coast_grace_seconds=coast_grace,
        )
        self.hysteresis = IdentityHysteresisTracker(
            confirm_k=int(kwargs.get("hysteresis_k", kwargs.get("confirm_k", 1))),
            confirm_threshold=float(kwargs.get("hysteresis_threshold", kwargs.get("confirm_threshold", self.reid_threshold))),
            contradict_m=int(kwargs.get("hysteresis_contradict_m", kwargs.get("contradict_m", 5))),
            coast_grace_seconds=coast_grace,
        )
        self._track_features = self._feature_buffer.track_features
        self._last_sighting_time = self._feature_buffer.last_sighting_time
        self._identified_tracks = self._feature_buffer.identified_tracks
        self.gallery_matrix = np.empty((0, 0), dtype=np.float32)
        self.gallery_entity_ids: List[int] = []
        self.gallery_names: List[str] = []
        self.gallery_categories: List[str] = []
        self.entity_avatars: Dict[int, str] = {}
        self.negative_matrix = np.empty((0, 0), dtype=np.float32)
        self.negative_entity_ids: List[Optional[int]] = []
        self.negative_labels: List[str] = []

    @property
    def next_session_id(self) -> int:
        return self._session_manager.next_session_id

    def reload_gallery(self):
        """Reload and vectorize all enrolled active signatures from SQLite database."""
        if self.db is None:
            self.gallery_matrix = np.empty((0, 0), dtype=np.float32)
            self.gallery_entity_ids, self.gallery_names, self.gallery_categories = [], [], []
            self.entity_avatars = {}
            self.negative_matrix = np.empty((0, 0), dtype=np.float32)
            self.negative_entity_ids, self.negative_labels = [], []
            return
        expected_dim = getattr(self.extractor, "embedding_dim", None)
        if expected_dim is not None and self.extractor is not None:
            _recompute_mismatched_signatures(self.db, self.extractor, int(expected_dim))
        mat, ids, names, categories = self.db.get_gallery_embeddings(expected_dim=expected_dim)
        self.gallery_matrix, self.gallery_entity_ids = mat, ids
        self.gallery_names, self.gallery_categories = names, categories
        self.entity_avatars = resolve_entity_avatars(self.db)
        if hasattr(self.db, "get_negative_embeddings"):
            neg_mat, neg_ids, neg_labels = self.db.get_negative_embeddings(expected_dim=expected_dim)
            self.negative_matrix, self.negative_entity_ids, self.negative_labels = neg_mat, neg_ids, neg_labels
        log_skipped_signature_dims(self, expected_dim, ids)

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
        """Query persistent database gallery with class compatibility, priors, and active learning."""
        return match_persistent_gallery(self, track, query_vec, frame, source, now, zone_id)

    def match_track(
        self,
        track: Track,
        frame: np.ndarray,
        source: str = "",
        timestamp: Optional[float] = None,
        zone_id: str = "",
    ) -> Optional[EntityIdentifiedEvent]:
        """Process a single track: extract feature, smooth embedding, and query gallery."""
        now = timestamp if timestamp is not None else time.time()
        if _should_skip_track_reid(self, track, now):
            return None

        source = source or self.camera_id
        zone_id = zone_id or getattr(track, "current_zone", "") or ""
        feat = self.extractor.extract(frame, track.bbox)
        self._feature_buffer.append(track.track_id, feat, now)
        query_vec = self._get_smoothed_embedding(track.track_id)
        if query_vec is None:
            return None
        track.last_embedding = query_vec

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
        self.hysteresis.prune_stale(active_tids, now)
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

        if frame is not None and self.extractor is not None and self.db is not None:
            feat = self.extractor.extract(frame, track.bbox)
            self.db.add_signature(new_entity_id, feat)
            self.reload_gallery()

        avatar_url = self.entity_avatars.get(new_entity_id)
        self.hysteresis.force_bind(
            track.track_id, new_entity_id, entity["name"], entity["category"],
            avatar_url=avatar_url, track=track,
        )
        if self.world_bridge is not None:
            self.world_bridge.reassign_track(
                self.camera_id, track, new_entity_id,
                name=entity["name"], category=entity["category"],
            )
        self._identified_tracks[track.track_id] = {
            "entity_id": new_entity_id, "name": entity["name"],
            "category": entity["category"], "similarity": 1.0, "avatar_url": avatar_url,
        }
        return True
