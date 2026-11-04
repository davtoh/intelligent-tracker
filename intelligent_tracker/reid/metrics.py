"""Vector similarity and distance metrics for visual Re-ID feature embeddings."""

import logging
import numpy as np

logger = logging.getLogger(__name__)


def cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    """Compute cosine similarity between two 1D feature vectors.

    Returns float in range [-1.0, 1.0] (typically [0.0, 1.0] for L2-normalized
    non-negative embeddings).
    """
    v1 = np.asarray(vec1, dtype=np.float32).ravel()
    v2 = np.asarray(vec2, dtype=np.float32).ravel()

    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 < 1e-7 or norm2 < 1e-7:
        return 0.0

    dot = float(np.dot(v1, v2))
    return max(-1.0, min(1.0, dot / (norm1 * norm2)))


def batch_cosine_similarity(gallery_matrix: np.ndarray, query_vec: np.ndarray) -> np.ndarray:
    """Compute cosine similarity between a 2D gallery matrix of shape (N, D)

    and a 1D query vector of shape (D,).

    Assumes vectors are L2-normalized; performs fast matrix-vector dot product.
    :return: 1D array of shape (N,) with similarity scores.
    """
    if gallery_matrix.size == 0 or query_vec.size == 0:
        return np.empty((0,), dtype=np.float32)

    q = np.asarray(query_vec, dtype=np.float32).ravel()
    q_norm = np.linalg.norm(q)
    if q_norm > 1e-7:
        q = q / q_norm

    gallery = np.asarray(gallery_matrix, dtype=np.float32)
    if gallery.ndim == 1:
        gallery = gallery.reshape(1, -1)

    if gallery.shape[1] != q.shape[0]:
        logger.warning(
            "Dimension mismatch in batch_cosine_similarity: gallery dim %d != query dim %d. Returning empty scores.",
            gallery.shape[1],
            q.shape[0],
        )
        return np.empty((0,), dtype=np.float32)

    norms = np.linalg.norm(gallery, axis=1, keepdims=True)
    norms[norms < 1e-7] = 1.0
    normalized_gallery = gallery / norms

    scores = np.dot(normalized_gallery, q)
    return np.clip(scores, -1.0, 1.0).astype(np.float32)

