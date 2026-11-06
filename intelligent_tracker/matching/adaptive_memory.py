"""Bounded Exponential Moving Average (EMA) adaptive memory for Re-ID gallery embeddings."""

import time
from typing import Optional, List, Any
import numpy as np


def _check_anchor_bounds(
    db: Any,
    entity_id: int,
    target_vec: np.ndarray,
    candidate_vec: np.ndarray,
    min_anchor_similarity: float,
) -> bool:
    """Validate that candidate vectors do not exceed drift thresholds against locked anchors."""
    anchors = db.get_signatures(entity_id=entity_id, anchors_only=True)
    for anc in anchors:
        anc_vec = anc["embedding"]
        # 1. Candidate observation itself must not deviate beyond the drift threshold
        if float(np.dot(target_vec, anc_vec)) < min_anchor_similarity:
            return False
        # 2. Candidate smoothed vector must not deviate beyond the drift threshold
        if float(np.dot(candidate_vec, anc_vec)) < min_anchor_similarity:
            return False
    return True


def _persist_signature_update(
    db: Any,
    entity_id: int,
    candidate_vec: np.ndarray,
    timestamp: Optional[float],
) -> None:
    """Write smoothed non-anchor signature embedding back to SQLite database."""
    blob = db.serialize_embedding(candidate_vec)
    now_ts = timestamp if timestamp is not None else time.time()
    now_str = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now_ts))
    try:
        with db._lock:
            cur = db._conn.cursor()
            cur.execute(
                "UPDATE entity_signatures SET embedding = ?, created_at = ? "
                "WHERE entity_id = ? AND is_anchor = 0",
                (blob, now_str, entity_id),
            )
            db._conn.commit()
            cur.close()
    except Exception:
        pass


def apply_bounded_ema_update(
    db: Optional[Any],
    gallery_matrix: np.ndarray,
    gallery_entity_ids: List[int],
    ema_alpha: float,
    min_anchor_similarity: float,
    entity_id: int,
    query_vec: Optional[np.ndarray] = None,
    gallery_idx: Optional[int] = None,
    timestamp: Optional[float] = None,
    candidate_features: Optional[np.ndarray] = None,
    track_confidence: float = 0.9,
) -> bool:
    """Continuously adapt running descriptor centroid using Bounded Exponential Moving Average.

    Rejects update if cosine similarity against ground-truth Locked Anchors drops below bound.
    """
    target_vec = candidate_features if candidate_features is not None else query_vec
    if target_vec is None:
        return False

    q_norm = np.linalg.norm(target_vec)
    if q_norm > 1e-7:
        target_vec = target_vec / q_norm

    curr_vec = None
    if gallery_idx is not None and 0 <= gallery_idx < len(gallery_matrix):
        curr_vec = gallery_matrix[gallery_idx]
    elif gallery_entity_ids and entity_id in gallery_entity_ids:
        gallery_idx = gallery_entity_ids.index(entity_id)
        curr_vec = gallery_matrix[gallery_idx]
    elif db is not None:
        sigs = db.get_signatures(entity_id=entity_id)
        curr_vec = sigs[0]["embedding"] if sigs else target_vec
    else:
        curr_vec = target_vec

    candidate_vec = (1.0 - ema_alpha) * curr_vec + ema_alpha * target_vec
    cand_norm = np.linalg.norm(candidate_vec)
    if cand_norm > 1e-7:
        candidate_vec = candidate_vec / cand_norm

    if db is not None:
        if not _check_anchor_bounds(db, entity_id, target_vec, candidate_vec, min_anchor_similarity):
            return False
        _persist_signature_update(db, entity_id, candidate_vec, timestamp)

    if gallery_idx is not None and 0 <= gallery_idx < len(gallery_matrix):
        gallery_matrix[gallery_idx] = candidate_vec

    return True
