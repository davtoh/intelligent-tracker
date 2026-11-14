"""Long-Term Multi-Modal Entity Confidence Engine.

Calibrates persistent entity presence and identity confidence in ``[0.0, 1.0]``
from multi-modal Re-ID evidence (face, body, visual similarity), temporal streak
consistency, ``CrossCameraTopology`` transition priors, and human-in-the-loop
confirmations, balanced against ambiguity conflicts and staleness time-decay.
"""

import logging
import sqlite3
import threading
import time
from typing import Any

from intelligent_tracker.memory._confidence_math import (
    ConfidenceEvidence,
    ConfidenceState,
    apply_time_decay,
    clamp01,
    compute_calibrated_score,
    state_from_row,
    update_state_with_evidence,
)

logger = logging.getLogger(__name__)

_VALID_FEEDBACK_ACTIONS = frozenset({"confirm", "reassign", "enroll_new", "dismiss"})


class ConfidenceEngine:
    """Calibrates and persists long-term multi-modal entity confidence."""

    def __init__(
        self,
        db: Any = None,
        *,
        event_bus: Any = None,
        streak_window_s: float = 60.0,
        decay_grace_s: float = 30.0,
        decay_half_life_s: float = 3600.0,
        decay_floor: float = 0.10,
        persist_interval: float = 0.0,
    ) -> None:
        self.db = db
        self.event_bus = event_bus
        self.streak_window_s = max(0.0, float(streak_window_s))
        self.decay_grace_s = max(0.0, float(decay_grace_s))
        self.decay_half_life_s = max(1.0, float(decay_half_life_s))
        self.decay_floor = clamp01(decay_floor)
        self.persist_interval = max(0.0, float(persist_interval))
        self._lock = threading.RLock()
        self._states: dict[int, ConfidenceState] = {}
        self._last_persisted: dict[int, float] = {}

    def _load_or_init_state(self, entity_id: int, default_confidence: float = 0.5) -> ConfidenceState:
        """Fetch cached state, hydrate from TrackerDB if present, or initialize cold start."""
        eid = int(entity_id)
        with self._lock:
            cached = self._states.get(eid)
            if cached is not None:
                return ConfidenceState(**cached.to_dict())

        row = self.db.get_entity_confidence(eid) if self.db is not None else None
        state = state_from_row(row) if row else ConfidenceState(entity_id=eid, confidence=default_confidence)
        with self._lock:
            self._states.setdefault(eid, state)
            return ConfidenceState(**self._states[eid].to_dict())

    def _persist_state(self, state: ConfidenceState, *, force: bool = False) -> None:
        """Persist calibrated state to TrackerDB outside internal locks."""
        if self.db is None:
            return
        now = time.monotonic()
        with self._lock:
            last_ts = self._last_persisted.get(state.entity_id)
            if not force and self.persist_interval > 0.0 and last_ts is not None:
                if (now - last_ts) < self.persist_interval:
                    return
            self._last_persisted[state.entity_id] = now

        try:
            self.db.upsert_entity_confidence(
                entity_id=state.entity_id, confidence=state.confidence,
                face_score=state.face_score, body_score=state.body_score,
                streak_count=state.streak_count, observation_count=state.observation_count,
                confirmation_count=state.confirmation_count, rejection_count=state.rejection_count,
                ambiguity_penalty=state.ambiguity_penalty, last_camera_id=state.last_camera_id,
                last_zone_id=state.last_zone_id, last_seen_at=state.last_seen_at, evidence=state.evidence,
            )
        except sqlite3.IntegrityError:
            logger.debug("Skipping confidence persist for non-existent entity_id=%s", state.entity_id)
        except Exception as exc:
            logger.warning("Failed persisting confidence for entity_id=%s: %s", state.entity_id, exc)

    def record_observation(
        self,
        evidence: ConfidenceEvidence | None = None,
        *,
        entity_id: int | None = None,
        visual_similarity: float = 0.0,
        face_score: float = 0.0,
        body_score: float = 0.0,
        topology_prior: float = 0.0,
        ambiguity: float = 0.0,
        camera_id: str = "",
        zone_id: str = "",
        timestamp: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConfidenceState:
        """Ingest a new sighting observation, recalibrate confidence, and persist."""
        ev = evidence or ConfidenceEvidence(
            entity_id=int(entity_id) if entity_id is not None else 0,
            visual_similarity=visual_similarity, face_score=face_score, body_score=body_score,
            topology_prior=topology_prior, ambiguity=ambiguity, camera_id=camera_id,
            zone_id=zone_id, timestamp=timestamp, metadata=dict(metadata or {}),
        )
        now = float(ev.timestamp) if ev.timestamp is not None else time.time()
        state = self._load_or_init_state(ev.entity_id, default_confidence=0.0)
        update_state_with_evidence(state, ev, now, self.streak_window_s)
        with self._lock:
            self._states[state.entity_id] = ConfidenceState(**state.to_dict())
        self._persist_state(state, force=(state.observation_count == 1))
        return state

    def record_human_feedback(
        self,
        entity_id: int | None,
        action: str,
        *,
        previous_entity_id: int | None = None,
        similarity: float | None = None,
        reviewer: str = "operator",
        timestamp: float | None = None,
    ) -> ConfidenceState | None:
        """Apply operator confirm/reassign/enroll_new/dismiss decision to entity confidence."""
        act = action.strip().lower()
        if act not in _VALID_FEEDBACK_ACTIONS:
            raise ValueError(f"Unsupported active learning feedback action: {action!r}")

        now = float(timestamp) if timestamp is not None else time.time()
        if previous_entity_id is not None and previous_entity_id != entity_id and act in ("reassign", "enroll_new"):
            self._apply_rejection(int(previous_entity_id), act, reviewer, now)

        if entity_id is None:
            return None
        if act == "dismiss":
            return self._apply_rejection(int(entity_id), act, reviewer, now)

        state = self._load_or_init_state(int(entity_id), default_confidence=0.65)
        state.confirmation_count += 1
        state.ambiguity_penalty = clamp01(state.ambiguity_penalty * 0.45)
        state.last_seen_at = max(state.last_seen_at, now)
        vis = clamp01(similarity) if similarity is not None else float(state.evidence.get("visual_similarity", 0.72) or 0.72)
        if state.face_score <= 0.0 and state.body_score <= 0.0:
            state.body_score = max(0.72, vis)
        state.confidence = max(state.confidence, compute_calibrated_score(state, max(vis, 0.72), 0.0))
        state.evidence = {**state.evidence, "last_feedback_action": act, "last_reviewer": reviewer}
        with self._lock:
            self._states[state.entity_id] = ConfidenceState(**state.to_dict())
        self._persist_state(state, force=True)
        return state

    def _apply_rejection(self, entity_id: int, action: str, reviewer: str, now: float) -> ConfidenceState:
        """Penalize an entity's confidence after dismissal or reassignment away from it."""
        state = self._load_or_init_state(entity_id, default_confidence=0.5)
        state.rejection_count += 1
        state.ambiguity_penalty = clamp01(state.ambiguity_penalty + 0.25)
        state.last_seen_at = max(state.last_seen_at, now)
        vis = float(state.evidence.get("visual_similarity", state.confidence) or state.confidence)
        state.confidence = compute_calibrated_score(state, vis, 0.0)
        state.evidence = {**state.evidence, "last_feedback_action": action, "last_reviewer": reviewer}
        with self._lock:
            self._states[state.entity_id] = ConfidenceState(**state.to_dict())
        self._persist_state(state, force=True)
        return state

    def handle_active_learning_feedback(self, payload: dict[str, Any]) -> ConfidenceState | None:
        """Callback adapter compatible with ActiveLearningManager(on_feedback=...)."""
        item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
        return self.record_human_feedback(
            entity_id=payload.get("entity_id"),
            action=str(payload.get("action", "")),
            previous_entity_id=payload.get("previous_entity_id"),
            similarity=item.get("similarity"),
            reviewer=str(payload.get("reviewer", "operator")),
        )

    def get_state(self, entity_id: int, *, timestamp: float | None = None) -> ConfidenceState | None:
        """Return time-decayed ConfidenceState for entity_id or None if never recorded."""
        eid = int(entity_id)
        with self._lock:
            cached = self._states.get(eid)
        if cached is None:
            row = self.db.get_entity_confidence(eid) if self.db is not None else None
            if row is None:
                return None
            cached = state_from_row(row)
            with self._lock:
                self._states.setdefault(eid, cached)
        now = float(timestamp) if timestamp is not None else time.time()
        snapshot = ConfidenceState(**cached.to_dict())
        snapshot.confidence = apply_time_decay(
            snapshot.confidence, snapshot.last_seen_at, now,
            self.decay_grace_s, self.decay_half_life_s, self.decay_floor,
        )
        return snapshot

    def get_confidence(self, entity_id: int, *, timestamp: float | None = None) -> float:
        """Return calibrated, time-decayed confidence in [0.0, 1.0] (0.0 if unknown)."""
        state = self.get_state(entity_id, timestamp=timestamp)
        return state.confidence if state is not None else 0.0

    def list_states(
        self, *, min_confidence: float | None = None, limit: int = 100, timestamp: float | None = None,
    ) -> list[ConfidenceState]:
        """List calibrated, time-decayed entity confidence states sorted descending."""
        now = float(timestamp) if timestamp is not None else time.time()
        merged: dict[int, ConfidenceState] = {}
        if self.db is not None:
            for row in self.db.list_entity_confidences(min_confidence=None, limit=max(limit, 250)):
                st = state_from_row(row)
                merged[st.entity_id] = st
        with self._lock:
            for eid, st in self._states.items():
                merged[eid] = ConfidenceState(**st.to_dict())

        results: list[ConfidenceState] = []
        for st in merged.values():
            st.confidence = apply_time_decay(
                st.confidence, st.last_seen_at, now,
                self.decay_grace_s, self.decay_half_life_s, self.decay_floor,
            )
            if min_confidence is None or st.confidence >= min_confidence:
                results.append(st)
        results.sort(key=lambda s: (s.confidence, s.last_seen_at), reverse=True)
        return results[: max(1, int(limit))]
