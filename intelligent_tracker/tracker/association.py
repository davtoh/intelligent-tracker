"""Class-consistency and appearance-assisted association helpers for trackers."""

from typing import Any, List, Optional, Sequence
import numpy as np

INVALID_ASSOCIATION_COST = 1e6


def classes_compatible(
    track_label: Optional[str],
    track_class_id: int,
    det_label: Optional[str],
    det_class_id: int,
) -> bool:
    """Return True if track and detection classes are compatible (allowing generic 'object')."""
    t_lbl = str(track_label or "").strip().lower()
    d_lbl = str(det_label or "").strip().lower()
    if not t_lbl or not d_lbl or t_lbl == "object" or d_lbl == "object":
        return True
    if t_lbl != d_lbl:
        return False
    return True


def compute_appearance_similarity(
    track_embedding: Optional[np.ndarray],
    det_embedding: Optional[np.ndarray],
) -> Optional[float]:
    """Compute non-negative cosine similarity in [0.0, 1.0] if both embeddings are valid."""
    if track_embedding is None or det_embedding is None:
        return None
    vec_a = np.asarray(track_embedding, dtype=np.float32).ravel()
    vec_b = np.asarray(det_embedding, dtype=np.float32).ravel()
    if vec_a.size == 0 or vec_a.shape != vec_b.shape:
        return None
    norm_a = float(np.linalg.norm(vec_a))
    norm_b = float(np.linalg.norm(vec_b))
    if norm_a <= 1e-7 or norm_b <= 1e-7:
        return None
    sim = float(np.dot(vec_a, vec_b)) / (norm_a * norm_b)
    return max(0.0, min(1.0, sim))


def extract_detection_embeddings(detections: Sequence[Any]) -> Optional[List[Optional[np.ndarray]]]:
    """Extract optional appearance embeddings attached to Detection objects."""
    embeddings: List[Optional[np.ndarray]] = []
    has_any = False
    for det in detections:
        emb = getattr(det, "embedding", None)
        if emb is None:
            emb = getattr(det, "feature", None)
        if emb is not None:
            has_any = True
        embeddings.append(emb)
    return embeddings if has_any else None


def _cell_cost(
    base_val: float,
    sim: Optional[float],
    mode: str,
    weight: float,
    scale: float,
) -> float:
    """Fuse geometric score/distance with optional appearance similarity."""
    if sim is None:
        return (1.0 - base_val) if mode == "iou" else base_val
    if mode == "iou":
        return 1.0 - ((1.0 - weight) * base_val + weight * sim)
    return ((1.0 - weight) * (base_val / scale) + weight * (1.0 - sim)) * scale


def build_fused_cost_matrix(
    track_labels: Sequence[Optional[str]],
    track_class_ids: Sequence[int],
    track_embeddings: Sequence[Optional[np.ndarray]],
    det_labels: Sequence[Optional[str]],
    det_class_ids: Sequence[int],
    det_embeddings: Optional[Sequence[Optional[np.ndarray]]] = None,
    *,
    iou_mat: Optional[np.ndarray] = None,
    dist_mat: Optional[np.ndarray] = None,
    max_distance: float = 120.0,
    appearance_weight: float = 0.35,
    invalid_cost: float = INVALID_ASSOCIATION_COST,
) -> np.ndarray:
    """Build bipartite cost matrix enforcing class consistency and optional appearance fusion."""
    if dist_mat is not None:
        base_mat, mode = np.asarray(dist_mat, dtype=np.float32), "dist"
        cost_mat = np.array(base_mat, dtype=np.float32, copy=True)
    elif iou_mat is not None:
        base_mat, mode = np.asarray(iou_mat, dtype=np.float32), "iou"
        cost_mat = (1.0 - base_mat).copy()
    else:
        raise ValueError("Either iou_mat or dist_mat must be provided.")

    rows, cols = cost_mat.shape
    w, scale = max(0.0, min(1.0, float(appearance_weight))), max(1.0, float(max_distance))
    for r in range(rows):
        for c in range(cols):
            if not classes_compatible(track_labels[r], track_class_ids[r], det_labels[c], det_class_ids[c]):
                cost_mat[r, c] = invalid_cost
            elif det_embeddings is not None:
                sim = compute_appearance_similarity(track_embeddings[r], det_embeddings[c])
                cost_mat[r, c] = _cell_cost(float(base_mat[r, c]), sim, mode, w, scale)
    return cost_mat


__all__ = [
    "INVALID_ASSOCIATION_COST",
    "build_fused_cost_matrix",
    "classes_compatible",
    "compute_appearance_similarity",
    "extract_detection_embeddings",
]
