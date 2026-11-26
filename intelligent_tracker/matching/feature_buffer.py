"""Track feature buffer, smoothed embedding cache, and coasting-grace pruning."""

from collections import deque
from typing import Any, Dict, Optional, Set
import numpy as np


class TrackFeatureBuffer:
    """Maintains per-track Re-ID feature history and identity metadata across short dropouts."""

    def __init__(
        self,
        feature_history_len: int = 10,
        coast_grace_seconds: float = 2.0,
    ) -> None:
        self.feature_history_len = max(1, int(feature_history_len))
        self.coast_grace_seconds = max(0.0, float(coast_grace_seconds))
        self.track_features: Dict[int, deque] = {}
        self.last_sighting_time: Dict[int, float] = {}
        self.identified_tracks: Dict[int, Dict[str, Any]] = {}
        self._last_active_time: Dict[int, float] = {}

    def append(self, track_id: int, feat: np.ndarray, timestamp: float) -> None:
        """Append a newly extracted feature vector and refresh the active timestamp."""
        if track_id not in self.track_features:
            self.track_features[track_id] = deque(maxlen=self.feature_history_len)
        self.track_features[track_id].append(feat)
        self._last_active_time[track_id] = float(timestamp)

    def mark_active(self, track_id: int, timestamp: float) -> None:
        """Refresh the last-active timestamp for a track (e.g. while coasting)."""
        self._last_active_time[track_id] = float(timestamp)

    def get_smoothed_embedding(self, track_id: int) -> Optional[np.ndarray]:
        """Compute L2-normalized mean feature vector from accumulated history."""
        buf = self.track_features.get(track_id)
        if not buf:
            return None
        arr = np.array(buf, dtype=np.float32)
        mean_vec = np.mean(arr, axis=0)
        norm = float(np.linalg.norm(mean_vec))
        if norm > 1e-7:
            mean_vec = mean_vec / norm
        return mean_vec

    def record_identification(
        self,
        track_id: int,
        entity_id: int,
        name: str,
        category: str,
        similarity: float,
    ) -> None:
        """Cache confirmed entity identity for a track ID."""
        self.identified_tracks[track_id] = {
            "entity_id": entity_id,
            "name": name,
            "category": category,
            "similarity": similarity,
        }

    def restore_track_identity(self, track: Any) -> None:
        """Re-apply cached identity metadata onto a coasting/re-acquired Track if missing."""
        cached = self.identified_tracks.get(track.track_id)
        if not cached:
            return
        if getattr(track, "entity_id", None) is None:
            track.entity_id = cached["entity_id"]
            track.entity_name = cached["name"]
            track.entity_category = cached["category"]
            track.reid_score = cached["similarity"]
            track.identity_label = cached["name"]

    def prune_stale(self, active_tids: Set[int], now: float) -> list[int]:
        """Prune tracks absent longer than coast_grace_seconds while retaining recent dropouts."""
        known_tids = set(self.track_features.keys()) | set(self.identified_tracks.keys())
        pruned: list[int] = []
        for tid in known_tids:
            if tid in active_tids:
                self._last_active_time.setdefault(tid, float(now))
                continue
            last_t = self._last_active_time.get(tid)
            if last_t is not None and (float(now) - last_t) < self.coast_grace_seconds:
                continue
            self.track_features.pop(tid, None)
            self.last_sighting_time.pop(tid, None)
            self.identified_tracks.pop(tid, None)
            self._last_active_time.pop(tid, None)
            pruned.append(tid)
        return pruned


__all__ = ["TrackFeatureBuffer"]
