"""Identity Hysteresis State Machine for Multi-Object Re-ID Tracking.

Requires ``confirm_k`` strong matches before locking an entity identity onto a track,
and ``contradict_m`` consecutive strong differing matches (or operator override) to unbind.
"""

from dataclasses import dataclass
import time
from typing import Any, Optional, Set


@dataclass
class LockedIdentity:
    """Confirmed identity state bound to an active track ID."""

    entity_id: int
    entity_name: str
    entity_category: str
    avatar_url: Optional[str] = None
    similarity: float = 1.0
    locked_at: float = 0.0
    contradict_count: int = 0
    contradict_entity_id: Optional[int] = None


class IdentityHysteresisTracker:
    """Manages per-track candidate streaks, hysteresis locks, and contradiction unbinding."""

    def __init__(
        self, confirm_k: int = 3, confirm_threshold: float = 0.65,
        contradict_m: int = 5, coast_grace_seconds: float = 2.0,
    ) -> None:
        self.confirm_k = max(1, int(confirm_k))
        self.confirm_threshold = float(confirm_threshold)
        self.contradict_m = max(1, int(contradict_m))
        self.coast_grace_seconds = max(0.0, float(coast_grace_seconds))
        self._locked: dict[int, LockedIdentity] = {}
        self._candidates: dict[int, dict[str, Any]] = {}
        self._last_active_time: dict[int, float] = {}

    def get_locked(self, track_id: int) -> Optional[LockedIdentity]:
        """Return the active LockedIdentity for ``track_id``, or ``None`` if unbound."""
        return self._locked.get(int(track_id))

    def get_owner_track(self, entity_id: int, *, exclude_track_id: Optional[int] = None) -> Optional[int]:
        """Return the active ``track_id`` currently locked to ``entity_id``, if any."""
        target = int(entity_id)
        for tid, locked in self._locked.items():
            if exclude_track_id is not None and tid == int(exclude_track_id):
                continue
            if locked.entity_id == target:
                return tid
        return None

    def observe(
        self, track_id: int, candidate_entity_id: Optional[int], similarity: float = 0.0,
        *, entity_name: str = "", entity_category: str = "", avatar_url: Optional[str] = None,
        now: Optional[float] = None, threshold: Optional[float] = None,
    ) -> tuple[Optional[LockedIdentity], str]:
        """Advance hysteresis state for one observation; return ``(locked_or_none, status)``."""
        tid = int(track_id)
        ts = float(now) if now is not None else time.time()
        self._last_active_time[tid] = ts
        eff_thresh = float(threshold) if threshold is not None else self.confirm_threshold
        is_strong = candidate_entity_id is not None and float(similarity) >= eff_thresh
        locked = self._locked.get(tid)
        if locked is not None:
            return self._observe_while_locked(
                tid, locked, candidate_entity_id, float(similarity), is_strong=is_strong,
                entity_name=entity_name, entity_category=entity_category, avatar_url=avatar_url,
            )
        if not is_strong or candidate_entity_id is None:
            self._candidates.pop(tid, None)
            return None, "none"
        cand_eid = int(candidate_entity_id)
        prev = self._candidates.get(tid)
        streak = (int(prev["streak"]) + 1) if (prev and prev["entity_id"] == cand_eid) else 1
        if streak >= self.confirm_k:
            self._candidates.pop(tid, None)
            new_lock = LockedIdentity(
                entity_id=cand_eid, entity_name=entity_name, entity_category=entity_category,
                avatar_url=avatar_url, similarity=float(similarity), locked_at=ts,
            )
            self._locked[tid] = new_lock
            return new_lock, "locked"
        self._candidates[tid] = {"entity_id": cand_eid, "streak": streak, "similarity": float(similarity)}
        return None, "pending"

    def _observe_while_locked(
        self, tid: int, locked: LockedIdentity, candidate_entity_id: Optional[int], similarity: float,
        *, is_strong: bool, entity_name: str, entity_category: str, avatar_url: Optional[str],
    ) -> tuple[Optional[LockedIdentity], str]:
        """Update an already-locked track on reinforcement, dropout/class-flip, or contradiction."""
        if is_strong and candidate_entity_id is not None and int(candidate_entity_id) == locked.entity_id:
            locked.contradict_count, locked.contradict_entity_id, locked.similarity = 0, None, similarity
            locked.entity_name = entity_name or locked.entity_name
            locked.entity_category = entity_category or locked.entity_category
            locked.avatar_url = avatar_url or locked.avatar_url
            return locked, "reinforced"
        if is_strong and candidate_entity_id is not None and int(candidate_entity_id) != locked.entity_id:
            locked.contradict_count += 1
            locked.contradict_entity_id = int(candidate_entity_id)
            if locked.contradict_count >= self.contradict_m:
                self._locked.pop(tid, None)
                self._candidates.pop(tid, None)
                return None, "unbound"
            return locked, "held"
        locked.contradict_count, locked.contradict_entity_id = 0, None
        return locked, "held"

    def force_bind(
        self, track_id: int, entity_id: int, entity_name: str, entity_category: str = "person",
        *, avatar_url: Optional[str] = None, similarity: float = 1.0,
        now: Optional[float] = None, track: Optional[Any] = None,
    ) -> LockedIdentity:
        """Immediately lock ``track_id`` to an operator-assigned entity, clearing contradictions."""
        tid, ts = int(track_id), (float(now) if now is not None else time.time())
        self._last_active_time[tid] = ts
        self._candidates.pop(tid, None)
        locked = LockedIdentity(
            entity_id=int(entity_id), entity_name=str(entity_name),
            entity_category=str(entity_category or "person"), avatar_url=avatar_url,
            similarity=float(similarity), locked_at=ts,
        )
        self._locked[tid] = locked
        if track is not None:
            self.apply_to_track(track, locked)
        return locked

    def clear_track(self, track_id: int, track: Optional[Any] = None) -> None:
        """Clear hysteresis state for ``track_id`` and optionally strip identity fields off ``track``."""
        tid = int(track_id)
        for store in (self._locked, self._candidates, self._last_active_time):
            store.pop(tid, None)
        if track is not None:
            for attr in ("entity_id", "entity_category", "avatar_url", "reid_score"):
                if hasattr(track, attr):
                    delattr(track, attr)
            track.entity_name, track.identity_label = None, None

    def apply_to_track(self, track: Any, locked: LockedIdentity) -> None:
        """Decorate ``track`` with the locked entity metadata and avatar URL."""
        track.entity_id, track.entity_name = locked.entity_id, locked.entity_name
        track.entity_category, track.identity_label = locked.entity_category, locked.entity_name
        track.reid_score = locked.similarity
        if locked.avatar_url:
            track.avatar_url = locked.avatar_url
        elif hasattr(track, "avatar_url"):
            delattr(track, "avatar_url")

    def prune_stale(self, active_tids: Set[int], now: float) -> list[int]:
        """Prune locked and candidate entries absent longer than ``coast_grace_seconds``."""
        known = set(self._locked) | set(self._candidates) | set(self._last_active_time)
        pruned: list[int] = []
        for tid in known:
            if tid in active_tids:
                self._last_active_time[tid] = float(now)
            elif (float(now) - self._last_active_time.get(tid, -1e9)) > self.coast_grace_seconds:
                self.clear_track(tid)
                pruned.append(tid)
        return pruned


__all__ = ["IdentityHysteresisTracker", "LockedIdentity"]
