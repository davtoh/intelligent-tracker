"""Confidence signal extraction and periodic sighting FTS indexing helpers for GalleryMatcher."""

import logging
from typing import Any, Optional

import numpy as np

from intelligent_tracker.tracker import Track

logger = logging.getLogger(__name__)


def _clamp01(value: float) -> float:
    """Clamp floating-point score cleanly into [0.0, 1.0]."""
    return max(0.0, min(1.0, float(value)))


def _safe_cosine(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """Compute non-negative cosine similarity for two 1D embedding slices."""
    norm_a = float(np.linalg.norm(vec_a))
    norm_b = float(np.linalg.norm(vec_b))
    if norm_a <= 1e-7 or norm_b <= 1e-7:
        return 0.0
    return _clamp01(float(np.dot(vec_a, vec_b)) / (norm_a * norm_b))


def compute_reid_ambiguity(
    similarities: np.ndarray,
    best_idx: int,
    entity_ids: Optional[list[int]] = None,
    margin_scale: float = 0.20,
) -> float:
    """Compute top-1 vs rival entity ambiguity in [0.0, 1.0] from gallery similarities."""
    if similarities.size <= 1 or margin_scale <= 0.0:
        return 0.0

    best_score = float(similarities[best_idx])
    best_eid = entity_ids[best_idx] if entity_ids and best_idx < len(entity_ids) else None

    rival_scores = [
        float(similarities[idx])
        for idx in range(int(similarities.size))
        if idx != best_idx and (best_eid is None or not entity_ids or entity_ids[idx] != best_eid)
    ]
    if not rival_scores:
        return 0.0

    second_best = max(0.0, max(rival_scores))
    margin = max(0.0, best_score - second_best)
    return _clamp01(1.0 - (margin / float(margin_scale)))


def compute_modality_scores(
    extractor: Any,
    query_vec: np.ndarray,
    gallery_vec: np.ndarray,
    visual_similarity: float,
) -> tuple[float, float]:
    """Compute (face_score, body_score) from dual extractors or fall back to body-only similarity."""
    primary = getattr(extractor, "primary_extractor", None)
    face = getattr(extractor, "face_extractor", None)
    if primary is not None and face is not None:
        p_dim = int(getattr(primary, "embedding_dim", 0) or 0)
        f_dim = int(getattr(face, "embedding_dim", 0) or 0)
        if p_dim > 0 and f_dim > 0 and query_vec.shape[0] >= p_dim + f_dim and gallery_vec.shape[0] >= p_dim + f_dim:
            body_score = _safe_cosine(query_vec[:p_dim], gallery_vec[:p_dim])
            face_score = _safe_cosine(query_vec[p_dim : p_dim + f_dim], gallery_vec[p_dim : p_dim + f_dim])
            return face_score, body_score
    return 0.0, _clamp01(visual_similarity)


def compute_topology_prior_signal(
    matched_prior: Any | None,
    raw_similarity: float,
    boosted_similarity: float,
) -> float:
    """Return normalized [0.0, 1.0] spatial topology prior strength for confidence calibration."""
    if matched_prior is None:
        return 0.0
    delta = max(0.0, float(boosted_similarity) - float(raw_similarity))
    boost = float(getattr(matched_prior, "prior_boost", 0.0) or 0.0)
    prob = float(getattr(matched_prior, "probability", 0.0) or 0.0)
    return _clamp01(max(delta, boost) if max(delta, boost) > 0.0 else prob)


def apply_track_confidence_signals(
    track: Track,
    *,
    extractor: Any,
    query_vec: np.ndarray,
    gallery_matrix: np.ndarray,
    gallery_entity_ids: list[int],
    similarities: np.ndarray,
    raw_similarities: Optional[np.ndarray],
    matched_priors: dict[int, Any],
    best_idx: int,
) -> None:
    """Attach face_score, body_score, topology_prior, and reid_ambiguity onto Track."""
    boosted = float(similarities[best_idx])
    raw_sim = float(raw_similarities[best_idx]) if raw_similarities is not None else boosted
    face_score, body_score = compute_modality_scores(extractor, query_vec, gallery_matrix[best_idx], raw_sim)
    track.face_score = face_score
    track.body_score = body_score
    track.topology_prior = compute_topology_prior_signal(matched_priors.get(best_idx), raw_sim, boosted)
    track.reid_ambiguity = compute_reid_ambiguity(similarities, best_idx, gallery_entity_ids)


def emit_periodic_sighting(
    matcher: Any,
    *,
    entity_id: int,
    name: str,
    category: str,
    track: Track,
    confidence: float,
    source: str,
    zone_id: str,
    timestamp: float,
) -> bool:
    """Log debounced sightings to TrackerDB and index them into EventFTSIndex when wired."""
    if matcher.db is None:
        return False
    tid = track.track_id
    last_log = matcher._last_sighting_time.get(tid)
    if last_log is not None and (timestamp - last_log < matcher.sighting_interval) and (timestamp >= last_log):
        return False

    matcher.db.add_sighting(
        entity_id=entity_id, track_id=tid, source=source,
        timestamp=timestamp, zone_id=zone_id, bbox=track.bbox, confidence=confidence,
    )
    matcher._last_sighting_time[tid] = timestamp
    fts_index = getattr(matcher, "fts_index", None)
    if fts_index is not None:
        try:
            fts_index.index_sighting(
                entity_id=entity_id, entity_name=name, category=category,
                camera_id=source, zone_id=zone_id, confidence=confidence,
                timestamp=timestamp, metadata={"track_id": tid},
            )
        except Exception as exc:
            logger.debug("Periodic sighting FTS indexing skipped: %s", exc)
    return True
