"""Centroid and IoU Multi-Object Tracker.

Matches detections to existing tracks using a two-stage association strategy:
1. High-overlap IoU matching for stable targets.
2. Centroid Euclidean distance matching for fast-moving or displaced objects.
"""

import time
from typing import Any, Dict, List, Optional, Set, Tuple
import numpy as np

from intelligent_tracker.tracker.track import Track
from intelligent_tracker.tracker.utils import (
    _HAS_SCIPY,
    compute_iou_matrix,
    greedy_assignment,
)

if _HAS_SCIPY:
    from scipy.optimize import linear_sum_assignment


def _solve_cost_assignment(cost_mat: np.ndarray, max_cost: float) -> List[Tuple[int, int]]:
    """Solve minimum cost bipartite assignment via Hungarian or greedy fallback."""
    if _HAS_SCIPY:
        row_ind, col_ind = linear_sum_assignment(cost_mat)
        return list(zip(row_ind, col_ind))
    return greedy_assignment(cost_mat, max_cost=max_cost)


class CentroidTracker:
    """Centroid and IoU Multi-Object Tracker."""

    def __init__(
        self,
        max_disappeared: int = 30,
        min_hits: int = 3,
        max_distance: float = 120.0,
        iou_threshold: float = 0.2,
        coast_frames: int = 0,
    ):
        self.max_disappeared = int(max_disappeared)
        self.min_hits = int(min_hits)
        self.max_distance = float(max_distance)
        self.iou_threshold = float(iou_threshold)
        self.coast_frames = max(0, int(coast_frames))

        self.next_track_id = 1
        self.tracks: Dict[int, Track] = {}
        self.dormant_tracks: Dict[int, Track] = {}

    def reset(self) -> None:
        """Clear all active and dormant tracks and reset track ID sequence."""
        self.next_track_id = 1
        self.tracks.clear()
        self.dormant_tracks.clear()

    def _parse_detections(self, detections: List[Any]) -> Tuple[list, list, list, list]:
        """Extract bounding boxes, classes, confidence scores, and labels."""
        det_bboxes, det_classes, det_scores, det_labels = [], [], [], []
        for d in detections:
            bbox = getattr(d, "bbox", None)
            if bbox is None and isinstance(d, (tuple, list)) and len(d) >= 4:
                bbox = d[:4]
            if bbox is not None:
                det_bboxes.append(tuple(int(v) for v in bbox))
                det_classes.append(getattr(d, "class_id", 0))
                det_scores.append(getattr(d, "confidence", 1.0))
                det_labels.append(getattr(d, "label", "object"))
        return det_bboxes, det_classes, det_scores, det_labels

    def _coast_empty_frame(self, now: float) -> None:
        """Coast or retire active tracks when no detections are observed in the frame."""
        to_remove = []
        for tid, trk in self.tracks.items():
            trk.mark_missed()
            if trk.missed_frames > self.max_disappeared:
                trk.state = "dormant"
                trk.exit_point = trk.centroid
                trk.exit_time = now
                self.dormant_tracks[tid] = trk
                to_remove.append(tid)
            elif self.coast_frames > 0 and trk.missed_frames <= self.coast_frames:
                trk.predict(timestamp=now)
        for tid in to_remove:
            del self.tracks[tid]

    def _match_iou(
        self,
        track_ids: List[int],
        det_bboxes: List[Tuple[int, int, int, int]],
        det_scores: List[float],
        det_labels: List[str],
        det_classes: List[int],
        now: float,
    ) -> Tuple[Set[int], Set[int]]:
        """Stage 1: IoU bipartite matching."""
        track_boxes = [self.tracks[tid].bbox for tid in track_ids]
        iou_mat = compute_iou_matrix(track_boxes, det_bboxes)
        matched_tracks, matched_dets = set(), set()
        if iou_mat.size == 0:
            return matched_tracks, matched_dets

        assignments = _solve_cost_assignment(1.0 - iou_mat, max_cost=1.0 - self.iou_threshold)
        for r, c in assignments:
            if iou_mat[r, c] >= self.iou_threshold:
                self.tracks[track_ids[r]].update(
                    det_bboxes[c],
                    confidence=det_scores[c],
                    label=det_labels[c],
                    class_id=det_classes[c],
                    timestamp=now,
                )
                matched_tracks.add(r)
                matched_dets.add(c)
        return matched_tracks, matched_dets

    def _match_distance(
        self,
        track_ids: List[int],
        det_bboxes: List[Tuple[int, int, int, int]],
        det_scores: List[float],
        det_labels: List[str],
        det_classes: List[int],
        matched_tracks: Set[int],
        matched_dets: Set[int],
        now: float,
    ) -> None:
        """Stage 2: Centroid Euclidean distance matching for unmatched candidates."""
        unmatched_t = [r for r in range(len(track_ids)) if r not in matched_tracks]
        unmatched_d = [c for c in range(len(det_bboxes)) if c not in matched_dets]
        if not unmatched_t or not unmatched_d:
            return

        t_cents = np.array([self.tracks[track_ids[r]].centroid for r in unmatched_t])
        d_cents = np.array([
            (det_bboxes[c][0] + det_bboxes[c][2] / 2.0, det_bboxes[c][1] + det_bboxes[c][3] / 2.0)
            for c in unmatched_d
        ])
        dist_mat = np.linalg.norm(t_cents[:, None, :] - d_cents[None, :, :], axis=2)
        assignments = _solve_cost_assignment(dist_mat, max_cost=self.max_distance)

        for r, c in assignments:
            if dist_mat[r, c] <= self.max_distance:
                ar, ac = unmatched_t[r], unmatched_d[c]
                self.tracks[track_ids[ar]].update(
                    det_bboxes[ac],
                    confidence=det_scores[ac],
                    label=det_labels[ac],
                    class_id=det_classes[ac],
                    timestamp=now,
                )
                matched_tracks.add(ar)
                matched_dets.add(ac)

    def _update_stale_tracks(self, track_ids: List[int], matched_tracks: Set[int], now: float) -> None:
        """Update track states, predictively coast misses, and deregister stale tracks."""
        to_remove = []
        for r, tid in enumerate(track_ids):
            trk = self.tracks[tid]
            if r not in matched_tracks:
                trk.mark_missed()
                if trk.missed_frames > self.max_disappeared:
                    trk.state = "dormant"
                    trk.exit_point = trk.centroid
                    trk.exit_time = now
                    self.dormant_tracks[tid] = trk
                    to_remove.append(tid)
                elif self.coast_frames > 0 and trk.missed_frames <= self.coast_frames:
                    trk.predict(timestamp=now)
            elif trk.hits >= self.min_hits:
                trk.state = "confirmed"

        for tid in to_remove:
            del self.tracks[tid]

    def _register_new_detections(
        self,
        det_bboxes: list,
        det_classes: list,
        det_scores: list,
        det_labels: list,
        matched_dets: Set[int],
        now: float,
    ) -> None:
        """Instantiate new tracks for unassociated detections."""
        for c in range(len(det_bboxes)):
            if c not in matched_dets:
                self._register_track(
                    det_bboxes[c],
                    det_classes[c],
                    det_scores[c],
                    det_labels[c],
                    now,
                )

    def _register_track(
        self,
        bbox: Tuple[int, int, int, int],
        class_id: int,
        confidence: float,
        label: str,
        timestamp: float,
    ) -> Track:
        """Create and register a single Track instance."""
        tid = self.next_track_id
        self.next_track_id += 1
        track = Track(
            track_id=tid,
            bbox=bbox,
            class_id=class_id,
            label=label,
            confidence=confidence,
            timestamp=timestamp,
        )
        if self.min_hits <= 1:
            track.state = "confirmed"
        self.tracks[tid] = track
        return track

    def _get_active_tracks(self, confirmed_only: bool, include_predicting: bool = True) -> Dict[int, Track]:
        """Filter tracks by active or confirmed status."""
        can_coast = include_predicting and self.coast_frames > 0
        if not confirmed_only:
            return {
                tid: trk for tid, trk in self.tracks.items()
                if trk.missed_frames == 0 or (can_coast and trk.missed_frames <= self.coast_frames)
            }
        return {
            tid: trk for tid, trk in self.tracks.items()
            if (trk.state in ("confirmed", "predicting") if can_coast else trk.state == "confirmed")
            and (trk.missed_frames == 0 or (can_coast and trk.missed_frames <= self.coast_frames))
        }

    def update(
        self,
        detections: List[Any],
        timestamp: Optional[float] = None,
        confirmed_only: bool = False,
    ) -> Dict[int, Track]:
        """Update tracker with detections from current frame."""
        now = timestamp if timestamp is not None else time.time()
        bboxes, classes, scores, labels = self._parse_detections(detections)

        if len(self.tracks) == 0:
            for i in range(len(bboxes)):
                self._register_track(bboxes[i], classes[i], scores[i], labels[i], now)
            return self._get_active_tracks(confirmed_only)

        if len(bboxes) == 0:
            self._coast_empty_frame(now)
            return self._get_active_tracks(confirmed_only)

        track_ids = list(self.tracks.keys())
        matched_trks, matched_dets = self._match_iou(track_ids, bboxes, scores, labels, classes, now)
        self._match_distance(track_ids, bboxes, scores, labels, classes, matched_trks, matched_dets, now)
        self._update_stale_tracks(track_ids, matched_trks, now)
        self._register_new_detections(bboxes, classes, scores, labels, matched_dets, now)

        return self._get_active_tracks(confirmed_only)


__all__ = ["CentroidTracker"]
