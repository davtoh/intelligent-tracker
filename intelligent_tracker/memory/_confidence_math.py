"""Data models and pure mathematical calibration helpers for ConfidenceEngine."""

from dataclasses import asdict, dataclass, field
import math
from typing import Any


def clamp01(value: float) -> float:
    """Clamp numeric score cleanly into [0.0, 1.0]."""
    return max(0.0, min(1.0, float(value)))


def blend_ema(current: float, sample: float, alpha: float = 0.35) -> float:
    """Blend a positive observation into an existing EMA signal."""
    sample_clamped = clamp01(sample)
    if sample_clamped <= 0.0:
        return current
    if current <= 0.0:
        return sample_clamped
    return clamp01((1.0 - alpha) * current + alpha * sample_clamped)


def compute_base_visual(face_score: float, body_score: float, visual_sim: float) -> tuple[float, float]:
    """Combine face, body, and fallback visual similarity plus multimodal corroboration bonus."""
    if face_score > 0.0 and body_score > 0.0:
        # Weight facial biometrics slightly higher when both modalities corroborate.
        return 0.55 * face_score + 0.45 * body_score, 0.08 * min(face_score, body_score)
    if face_score > 0.0:
        return max(face_score, visual_sim), 0.0
    if body_score > 0.0:
        return max(body_score, visual_sim), 0.0
    return visual_sim, 0.0


def compute_calibrated_score(state: "ConfidenceState", visual_sim: float, topology_prior: float) -> float:
    """Compute calibrated confidence in [0.0, 1.0] from accumulated state evidence."""
    base_visual, multimodal_bonus = compute_base_visual(state.face_score, state.body_score, visual_sim)
    streak_bonus = 0.16 * (1.0 - math.exp(-0.35 * max(0, state.streak_count - 1)))
    prior_bonus = 0.25 * clamp01(topology_prior)
    confirm_bonus = 0.18 * (1.0 - math.exp(-0.70 * max(0, state.confirmation_count)))
    rejection_penalty = 0.16 * (1.0 - math.exp(-0.70 * max(0, state.rejection_count)))
    raw = (
        base_visual + multimodal_bonus + streak_bonus + prior_bonus
        + confirm_bonus - rejection_penalty - 0.45 * clamp01(state.ambiguity_penalty)
    )
    return clamp01(raw)


def apply_time_decay(
    base_confidence: float, last_seen_at: float, at_timestamp: float,
    grace_s: float, half_life_s: float, floor: float,
) -> float:
    """Apply half-life staleness decay once elapsed time exceeds grace_s."""
    if last_seen_at <= 0.0 or base_confidence <= floor:
        return clamp01(base_confidence)
    elapsed = max(0.0, at_timestamp - last_seen_at)
    if elapsed <= grace_s or half_life_s <= 0.0:
        return clamp01(base_confidence)
    factor = 0.5 ** ((elapsed - grace_s) / half_life_s)
    return clamp01(floor + (base_confidence - floor) * factor)


@dataclass
class ConfidenceEvidence:
    """Observation cues used to update an entity's long-term confidence state."""

    entity_id: int
    visual_similarity: float = 0.0
    face_score: float = 0.0
    body_score: float = 0.0
    topology_prior: float = 0.0
    ambiguity: float = 0.0
    camera_id: str = ""
    zone_id: str = ""
    timestamp: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConfidenceState:
    """Calibrated confidence state persisted per entity in TrackerDB."""

    entity_id: int
    confidence: float = 0.5
    face_score: float = 0.0
    body_score: float = 0.0
    streak_count: int = 0
    observation_count: int = 0
    confirmation_count: int = 0
    rejection_count: int = 0
    ambiguity_penalty: float = 0.0
    last_camera_id: str = ""
    last_zone_id: str = ""
    last_seen_at: float = 0.0
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize calibrated state into a JSON-compatible dictionary."""
        return asdict(self)


def state_from_row(row: dict[str, Any]) -> ConfidenceState:
    """Hydrate a ConfidenceState instance from a MemoryMixin DB row."""
    return ConfidenceState(
        entity_id=int(row["entity_id"]), confidence=float(row.get("confidence", 0.5)),
        face_score=float(row.get("face_score", 0.0)), body_score=float(row.get("body_score", 0.0)),
        streak_count=int(row.get("streak_count", 0)), observation_count=int(row.get("observation_count", 0)),
        confirmation_count=int(row.get("confirmation_count", 0)), rejection_count=int(row.get("rejection_count", 0)),
        ambiguity_penalty=float(row.get("ambiguity_penalty", 0.0)),
        last_camera_id=str(row.get("last_camera_id", "")), last_zone_id=str(row.get("last_zone_id", "")),
        last_seen_at=float(row.get("last_seen_at", 0.0)), evidence=dict(row.get("evidence") or {}),
    )


def update_state_with_evidence(
    state: ConfidenceState, ev: ConfidenceEvidence, now: float, streak_window_s: float,
) -> None:
    """Mutate a ConfidenceState copy with one new multi-modal sighting observation."""
    vis, face, body = clamp01(ev.visual_similarity), clamp01(ev.face_score), clamp01(ev.body_score)
    amb, prior = clamp01(ev.ambiguity), clamp01(ev.topology_prior)
    if face <= 0.0 and body <= 0.0 and vis > 0.0:
        body = vis
    state.face_score = blend_ema(state.face_score, face)
    state.body_score = blend_ema(state.body_score, body)

    within_window = state.observation_count > 0 and 0.0 <= (now - state.last_seen_at) <= streak_window_s
    state.streak_count = (state.streak_count + 1) if (within_window and amb < 0.35) else 1
    state.observation_count += 1
    if amb > 0.0:
        state.ambiguity_penalty = clamp01(0.5 * state.ambiguity_penalty + 0.55 * amb)
    elif max(vis, face, body) >= 0.70:
        state.ambiguity_penalty = clamp01(state.ambiguity_penalty * 0.80)

    if ev.camera_id:
        state.last_camera_id = ev.camera_id
    if ev.zone_id:
        state.last_zone_id = ev.zone_id
    state.last_seen_at = max(state.last_seen_at, now)

    prev_vis = float(state.evidence.get("visual_similarity", 0.0) or 0.0)
    eff_vis = blend_ema(prev_vis, vis) if vis > 0.0 else prev_vis
    state.confidence = compute_calibrated_score(state, eff_vis, prior)
    state.evidence = {
        **state.evidence, **ev.metadata,
        "visual_similarity": round(eff_vis, 4), "topology_prior": round(prior, 4), "last_ambiguity": round(amb, 4),
    }

