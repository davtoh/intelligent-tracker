"""Automatic in-memory session gallery tracking and dead-reckoning re-linking."""

from collections import deque
from typing import Dict, Tuple, Any, Optional
import numpy as np

from intelligent_tracker.matching.types import SessionEntity


class SessionGalleryManager:
    """Manages automatic session identities, dropout re-linking, and exit telemetry."""

    def __init__(
        self,
        session_reid_threshold: float = 0.55,
        spatial_bonus_radius: float = 200.0,
        spatial_bonus_max_dt: float = 60.0,
        feature_history_len: int = 10,
    ):
        self.session_reid_threshold = float(session_reid_threshold)
        self.spatial_bonus_radius = float(spatial_bonus_radius)
        self.spatial_bonus_max_dt = float(spatial_bonus_max_dt)
        self.feature_history_len = int(feature_history_len)

        self.session_entities: Dict[int, SessionEntity] = {}
        self.next_session_id: int = 1

    def update_existing_track_session(self, track: Any, feat: np.ndarray, now: float) -> bool:
        """Update feature history and telemetry if track is already bound to a session entity."""
        if track.session_id is not None and track.session_id in self.session_entities:
            ent = self.session_entities[track.session_id]
            ent.feature_history.append(feat)
            ent.last_seen = now
            ent.last_centroid = track.centroid
            ent.exit_point = None
            ent.exit_time = None
            track.identity_label = ent.label
            return True
        return False

    def compute_spatial_bonus(
        self,
        ent: SessionEntity,
        track_centroid: Tuple[float, float],
        now: float,
    ) -> float:
        """Compute proximity bonus for entity re-appearance near last seen exit point."""
        ref_point = ent.exit_point if ent.exit_point is not None else ent.last_centroid
        ref_time = ent.exit_time if ent.exit_time is not None else ent.last_seen
        dt = max(0.0, now - ref_time)
        if dt <= self.spatial_bonus_max_dt and ref_point is not None:
            dx = track_centroid[0] - ref_point[0]
            dy = track_centroid[1] - ref_point[1]
            dist = float(np.hypot(dx, dy))
            if dist <= self.spatial_bonus_radius:
                return 0.15 * (1.0 - dist / self.spatial_bonus_radius)
        return 0.0

    def _find_best_dormant_candidate(
        self,
        track: Any,
        query_vec: np.ndarray,
        now: float,
        active_tracks_cache: Dict[int, Any],
    ) -> Tuple[Optional[SessionEntity], float]:
        """Search all dormant session entities for the closest visual & spatial match."""
        tid = track.track_id
        best_ent: Optional[SessionEntity] = None
        best_fused_score = -1.0

        for ent in self.session_entities.values():
            if ent.category.lower() != (track.label or "object").lower():
                continue

            # Don't steal identity from another track currently active in this frame
            is_active_elsewhere = any(
                other_tid != tid and other_trk.session_id == ent.session_id and other_trk.missed_frames == 0
                for other_tid, other_trk in active_tracks_cache.items()
            )
            if is_active_elsewhere:
                continue

            ent_vec = ent.get_embedding()
            if ent_vec is None:
                continue

            visual_sim = float(np.dot(ent_vec, query_vec))
            spatial_bonus = self.compute_spatial_bonus(ent, track.centroid, now)
            fused_score = visual_sim + spatial_bonus

            if fused_score > best_fused_score:
                best_fused_score = fused_score
                best_ent = ent

        return best_ent, best_fused_score

    def match_returning_entity(
        self,
        track: Any,
        feat: np.ndarray,
        query_vec: np.ndarray,
        now: float,
        active_tracks_cache: Dict[int, Any],
    ) -> bool:
        """Attempt to re-link an unassigned track to a dormant session entity via fused affinity."""
        best_ent, best_score = self._find_best_dormant_candidate(
            track, query_vec, now, active_tracks_cache
        )
        if best_ent is not None and best_score >= self.session_reid_threshold:
            track.session_id = best_ent.session_id
            track.identity_label = best_ent.label
            best_ent.assigned_track_ids.append(track.track_id)
            best_ent.feature_history.append(feat)
            best_ent.last_seen = now
            best_ent.last_centroid = track.centroid
            best_ent.exit_point = None
            best_ent.exit_time = None
            return True

        return False

    def allocate_new_session_entity(self, track: Any, feat: np.ndarray, now: float) -> SessionEntity:
        """Create and register a new canonical session entity for an unlinked track."""
        sess_id = self.next_session_id
        self.next_session_id += 1
        cat_name = (track.label or "object").capitalize()
        label = f"{cat_name} #{sess_id}"

        new_ent = SessionEntity(
            session_id=sess_id,
            label=label,
            category=track.label or "object",
            feature_history=deque([feat], maxlen=self.feature_history_len),
            first_seen=now,
            last_seen=now,
            last_centroid=track.centroid,
            assigned_track_ids=[track.track_id],
        )
        self.session_entities[sess_id] = new_ent
        track.session_id = sess_id
        track.identity_label = label
        return new_ent

    def update_exit_telemetry(self, tracks: Dict[int, Any]):
        """Update exit point and exit timestamp for session entities whose tracks have disappeared."""
        for ent in self.session_entities.values():
            if ent.exit_point is None:
                active_for_ent = [t for t in ent.assigned_track_ids if t in tracks and tracks[t].missed_frames == 0]
                if not active_for_ent:
                    ent.exit_point = ent.last_centroid
                    ent.exit_time = ent.last_seen
