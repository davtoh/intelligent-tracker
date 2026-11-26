"""ByteTrack-style 2-stage association helpers for SORT tracking."""

from typing import List, Optional, Sequence, Tuple
import numpy as np

from intelligent_tracker.tracker.association import (
    INVALID_ASSOCIATION_COST,
    build_fused_cost_matrix,
)
from intelligent_tracker.tracker.utils import _HAS_SCIPY, compute_iou_matrix, greedy_assignment

if _HAS_SCIPY:
    from scipy.optimize import linear_sum_assignment


def split_detections_by_confidence(
    scores: Sequence[float],
    high_conf_threshold: float,
    low_conf_threshold: float,
) -> Tuple[List[int], List[int]]:
    """Split detection indices into high-confidence and low-confidence tiers."""
    if float(low_conf_threshold) <= 0.0:
        return list(range(len(scores))), []
    high_thr, low_thr = float(high_conf_threshold), float(low_conf_threshold)
    high_indices: List[int] = []
    low_indices: List[int] = []
    for idx, score in enumerate(scores):
        val = float(score)
        if val >= high_thr:
            high_indices.append(idx)
        elif val >= low_thr:
            low_indices.append(idx)
    return high_indices, low_indices


def _solve_stage(
    trk_indices: Sequence[int],
    det_indices: Sequence[int],
    predicted_boxes: Sequence[Tuple[int, int, int, int]],
    det_bboxes: Sequence[Tuple[int, int, int, int]],
    trk_meta: Tuple[Sequence[Optional[str]], Sequence[int], Sequence[Optional[np.ndarray]]],
    det_meta: Tuple[Sequence[Optional[str]], Sequence[int], Optional[Sequence[Optional[np.ndarray]]]],
    stage_iou_threshold: float,
    appearance_weight: float,
) -> List[Tuple[int, int]]:
    """Solve one bipartite association stage on track and detection index subsets."""
    if not trk_indices or not det_indices:
        return []
    trk_labels, trk_classes, trk_embs = trk_meta
    det_labels, det_classes, det_embeddings = det_meta
    iou_mat = compute_iou_matrix([predicted_boxes[r] for r in trk_indices], [det_bboxes[c] for c in det_indices])
    sub_embs = [det_embeddings[c] for c in det_indices] if det_embeddings is not None else None
    cost_mat = build_fused_cost_matrix(
        [trk_labels[r] for r in trk_indices], [trk_classes[r] for r in trk_indices],
        [trk_embs[r] for r in trk_indices], [det_labels[c] for c in det_indices],
        [det_classes[c] for c in det_indices], sub_embs, iou_mat=iou_mat, appearance_weight=appearance_weight,
    )
    assignments = (
        list(zip(*linear_sum_assignment(cost_mat)))
        if _HAS_SCIPY
        else greedy_assignment(cost_mat, max_cost=1.0 - float(stage_iou_threshold))
    )
    return [
        (trk_indices[r_sub], det_indices[c_sub])
        for r_sub, c_sub in assignments
        if float(cost_mat[r_sub, c_sub]) < INVALID_ASSOCIATION_COST
        and float(iou_mat[r_sub, c_sub]) > 0.0
        and (1.0 - float(cost_mat[r_sub, c_sub])) >= float(stage_iou_threshold)
    ]


def associate_two_stage(
    predicted_boxes: Sequence[Tuple[int, int, int, int]],
    det_bboxes: Sequence[Tuple[int, int, int, int]],
    det_scores: Sequence[float],
    trk_labels: Sequence[Optional[str]],
    trk_classes: Sequence[int],
    trk_embs: Sequence[Optional[np.ndarray]],
    det_labels: Sequence[Optional[str]],
    det_classes: Sequence[int],
    det_embeddings: Optional[Sequence[Optional[np.ndarray]]] = None,
    *,
    iou_threshold: float = 0.3,
    high_conf_threshold: float = 0.4,
    low_conf_threshold: float = 0.1,
    appearance_weight: float = 0.35,
    low_iou_threshold: Optional[float] = None,
) -> Tuple[List[Tuple[int, int]], List[int]]:
    """Run ByteTrack 2-stage association, returning matches and unmatched high-conf indices."""
    high_dets, low_dets = split_detections_by_confidence(det_scores, high_conf_threshold, low_conf_threshold)
    if not predicted_boxes or not det_bboxes:
        return [], list(high_dets)

    all_trks = list(range(len(predicted_boxes)))
    trk_meta = (trk_labels, trk_classes, trk_embs)
    stage1_matches = _solve_stage(
        all_trks, high_dets, predicted_boxes, det_bboxes, trk_meta,
        (det_labels, det_classes, det_embeddings), float(iou_threshold), float(appearance_weight),
    )
    matched_trks = {r for r, _ in stage1_matches}
    matched_high = {c for _, c in stage1_matches}
    unmatched_high_dets = [c for c in high_dets if c not in matched_high]

    all_matches = list(stage1_matches)
    remaining_trks = [r for r in all_trks if r not in matched_trks]
    if float(low_conf_threshold) > 0.0 and remaining_trks and low_dets:
        stage2_iou = float(low_iou_threshold) if low_iou_threshold is not None else min(float(iou_threshold), 0.2)
        all_matches.extend(_solve_stage(
            remaining_trks, low_dets, predicted_boxes, det_bboxes, trk_meta,
            (det_labels, det_classes, None), stage2_iou, 0.0,
        ))
    return all_matches, unmatched_high_dets


__all__ = ["associate_two_stage", "split_detections_by_confidence"]
