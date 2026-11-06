"""Geometric matching and assignment utilities for multi-object tracking.

Provides IoU computation, IoU distance matrix generation, and greedy
assignment fallback when SciPy's Hungarian algorithm is unavailable.
"""

from typing import List, Tuple
import numpy as np

# Optional SciPy Hungarian algorithm with pure NumPy greedy fallback
try:
    from scipy.optimize import linear_sum_assignment
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False


def compute_iou(boxA: Tuple[int, int, int, int], boxB: Tuple[int, int, int, int]) -> float:
    """Compute Intersection over Union (IoU) between two bounding boxes.

    Boxes are in (x, y, w, h) format.
    """
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[0] + boxA[2], boxB[0] + boxB[2])
    yB = min(boxA[1] + boxA[3], boxB[1] + boxB[3])

    inter_w = max(0, xB - xA)
    inter_h = max(0, yB - yA)
    inter_area = inter_w * inter_h

    boxA_area = boxA[2] * boxA[3]
    boxB_area = boxB[2] * boxB[3]
    union_area = float(boxA_area + boxB_area - inter_area)

    if union_area <= 0:
        return 0.0
    return inter_area / union_area


def compute_iou_matrix(
    boxesA: List[Tuple[int, int, int, int]],
    boxesB: List[Tuple[int, int, int, int]],
) -> np.ndarray:
    """Compute IoU matrix between N boxesA and M boxesB."""
    if not boxesA or not boxesB:
        return np.empty((len(boxesA), len(boxesB)), dtype=np.float32)

    iou_mat = np.zeros((len(boxesA), len(boxesB)), dtype=np.float32)
    for i, a in enumerate(boxesA):
        for j, b in enumerate(boxesB):
            iou_mat[i, j] = compute_iou(a, b)
    return iou_mat


def greedy_assignment(cost_matrix: np.ndarray, max_cost: float = float("inf")) -> List[Tuple[int, int]]:
    """Greedy minimum-cost assignment fallback when SciPy is not available."""
    rows, cols = cost_matrix.shape
    assignments = []
    used_rows = set()
    used_cols = set()

    # Flatten and sort indices by ascending cost
    indices = np.dstack(np.unravel_index(np.argsort(cost_matrix.ravel()), (rows, cols)))[0]
    for r, c in indices:
        if r in used_rows or c in used_cols:
            continue
        if cost_matrix[r, c] > max_cost:
            break
        assignments.append((r, c))
        used_rows.add(r)
        used_cols.add(c)
    return assignments


__all__ = [
    "compute_iou",
    "compute_iou_matrix",
    "greedy_assignment",
    "_HAS_SCIPY",
]

