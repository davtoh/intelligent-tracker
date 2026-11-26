"""Centroid and IoU Multi-Object Tracker.

Matches detections to existing tracks using a two-stage association strategy:
1. High-overlap IoU matching for stable targets.
2. Centroid Euclidean distance matching for fast-moving or displaced objects.
"""

import time
from typing import Any, Dict, List, Optional, Set, Tuple
import numpy as np

from intelligent_tracker.tracker.association import (
    INVALID_ASSOCIATION_COST,
    build_fused_cost_matrix,
    extract_detection_embeddings,
)
from intelligent_tracker.tracker.track import Track
from intelligent_tracker.tracker.utils import (
    _HAS_SCIPY,
    compute_iou_matrix,
    greedy_assignment,
    parse_detections,
)

if _HAS_SCIPY:
    from scipy.optimize import linear_sum_assignment


def _solve_cost_assignment(cost_mat: np.ndarray, max_cost: float) -> List[Tuple[int, int]]:
    """Solve minimum cost bipartite assignment via Hungarian or greedy fallback."""
    if _HAS_SCIPY:
        row_ind, col_ind = linear_sum_assignment(cost_mat)
        return list(zip(row_ind, col_ind))
    return greedy_assignment(cost_mat, max_cost=max_cost)


def _is_within_coast_budget(
    trk: Track,
    now: float,
    is_time_sliced: bool,
    coast_frames: int,
    coast_seconds: float,
) -> bool:
    """Return True if a missed track is eligible to coast via frame or second grace."""
    within_frames = coast_frames > 0 and trk.missed_frames <= coast_frames
    elapsed = now - getattr(trk, "last_detected_time", trk.last_seen)
    within_seconds = coast_seconds > 0.0 and elapsed <= coast_seconds
    if is_time_sliced and coast_seconds > 0.0:
        return within_seconds
    return within_frames or within_seconds


def _coast_track(trk: Track, now: float, coast_seconds: float) -> None:
    """Extrapolate track bbox and assign canonical coasting/occluded/predicting state."""
    trk.predict(timestamp=now)
    if getattr(trk, "is_cluttered", False):
        trk.state = "occluded"
    elif coast_seconds > 0.0:
        trk.state = "coasting"


class CentroidTracker:
    """Centroid and IoU Multi-Object Tracker."""

    def __init__(
        self,
        max_disappeared: int = 30,
        min_hits: int = 3,
        max_distance: float = 120.0,
        iou_threshold: float = 0.2,
        coast_frames: int = 0,
        coast_seconds: float = 0.0,
        max_age_seconds: float = 2.5,
        time_slice_dt_threshold: float = 0.4,
    ):
        self.max_disappeared = int(max_disappeared)
        self.min_hits = int(min_hits)
        self.max_distance = float(max_distance)
        self.iou_threshold = float(iou_threshold)
        self.coast_frames = max(0, int(coast_frames))
        self.coast_seconds = max(0.0, float(coast_seconds))
        self.max_age_seconds = float(max_age_seconds)
        self.time_slice_dt_threshold = float(time_slice_dt_threshold)
        self._last_update_time: Optional[float] = None

        self.next_track_id = 1
        self.tracks: Dict[int, Track] = {}
        self.dormant_tracks: Dict[int, Track] = {}

    def reset(self) -> None:
        """Clear all active and dormant tracks and reset track ID sequence."""
        self.next_track_id = 1
        self.tracks.clear()
        self.dormant_tracks.clear()
        self._last_update_time = None

    def _should_retire_track(self, trk: Track, now: float, is_time_sliced: bool) -> bool:
        """Return True if track exceeded frame-count or elapsed-time age budget."""
        dt = now - trk.last_seen
        if is_time_sliced and self.max_age_seconds > 0:
            return dt > self.max_age_seconds
        if trk.missed_frames > self.max_disappeared:
            return True
        return self.max_age_seconds > 0 and dt > self.max_age_seconds

    def _coast_empty_frame(self, now: float, is_time_sliced: bool = False) -> None:
        """Coast or retire active tracks when no detections are observed in the frame."""
        to_remove = []
        for tid, trk in self.tracks.items():
            trk.mark_missed()
            if self._should_retire_track(trk, now, is_time_sliced):
                trk.state = "dormant"
                trk.exit_point = trk.centroid
                trk.exit_time = now
                self.dormant_tracks[tid] = trk
                to_remove.append(tid)
            elif _is_within_coast_budget(trk, now, is_time_sliced, self.coast_frames, self.coast_seconds):
                _coast_track(trk, now, self.coast_seconds)
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
        det_embeddings: Optional[List[Optional[np.ndarray]]] = None,
    ) -> Tuple[Set[int], Set[int]]:
        """Stage 1: Class-consistent, appearance-assisted IoU bipartite matching."""
        track_boxes: List[Tuple[int, int, int, int]] = [self.tracks[tid].bbox for tid in track_ids]
        iou_mat = compute_iou_matrix(track_boxes, det_bboxes)
        matched_tracks: Set[int] = set()
        matched_dets: Set[int] = set()
        if iou_mat.size == 0:
            return matched_tracks, matched_dets

        cost_mat = build_fused_cost_matrix(
            [self.tracks[tid].label for tid in track_ids],
            [self.tracks[tid].class_id for tid in track_ids],
            [getattr(self.tracks[tid], "last_embedding", None) for tid in track_ids],
            det_labels, det_classes, det_embeddings,
            iou_mat=iou_mat,
            appearance_weight=getattr(self, "appearance_weight", 0.35),
        )
        assignments = _solve_cost_assignment(cost_mat, max_cost=1.0 - self.iou_threshold)
        for r, c in assignments:
            if cost_mat[r, c] >= INVALID_ASSOCIATION_COST or iou_mat[r, c] <= 0.0:
                continue
            if (1.0 - cost_mat[r, c]) >= self.iou_threshold:
                trk = self.tracks[track_ids[r]]
                trk.update(
                    det_bboxes[c], confidence=det_scores[c], label=det_labels[c],
                    class_id=det_classes[c], timestamp=now, min_hits=self.min_hits,
                )
                if det_embeddings is not None and det_embeddings[c] is not None:
                    trk.last_embedding = det_embeddings[c]
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
        det_embeddings: Optional[List[Optional[np.ndarray]]] = None,
    ) -> None:
        """Stage 2: Class-consistent centroid distance matching for unmatched candidates."""
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
        sub_embs = [det_embeddings[c] for c in unmatched_d] if det_embeddings is not None else None
        cost_mat = build_fused_cost_matrix(
            [self.tracks[track_ids[r]].label for r in unmatched_t],
            [self.tracks[track_ids[r]].class_id for r in unmatched_t],
            [getattr(self.tracks[track_ids[r]], "last_embedding", None) for r in unmatched_t],
            [det_labels[c] for c in unmatched_d], [det_classes[c] for c in unmatched_d], sub_embs,
            dist_mat=dist_mat, max_distance=self.max_distance, appearance_weight=getattr(self, "appearance_weight", 0.35),
        )
        for r, c in _solve_cost_assignment(cost_mat, max_cost=self.max_distance):
            if cost_mat[r, c] <= self.max_distance:
                ar, ac = unmatched_t[r], unmatched_d[c]
                trk = self.tracks[track_ids[ar]]
                trk.update(det_bboxes[ac], confidence=det_scores[ac], label=det_labels[ac], class_id=det_classes[ac], timestamp=now, min_hits=self.min_hits)
                if det_embeddings is not None and det_embeddings[ac] is not None:
                    trk.last_embedding = det_embeddings[ac]
                matched_tracks.add(ar)
                matched_dets.add(ac)

    def _update_stale_tracks(
        self, track_ids: List[int], matched_tracks: Set[int], now: float, is_time_sliced: bool = False
    ) -> None:
        """Update track states, predictively coast misses, and deregister stale tracks."""
        to_remove = []
        for r, tid in enumerate(track_ids):
            trk = self.tracks[tid]
            if r not in matched_tracks:
                trk.mark_missed()
                if self._should_retire_track(trk, now, is_time_sliced):
                    trk.state = "dormant"
                    trk.exit_point = trk.centroid
                    trk.exit_time = now
                    self.dormant_tracks[tid] = trk
                    to_remove.append(tid)
                elif _is_within_coast_budget(trk, now, is_time_sliced, self.coast_frames, self.coast_seconds):
                    _coast_track(trk, now, self.coast_seconds)
            elif trk.hits >= self.min_hits or is_time_sliced:
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
        is_time_sliced: bool = False,
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
                    is_time_sliced=is_time_sliced,
                )

    def _register_track(
        self,
        bbox: Tuple[int, int, int, int],
        class_id: int,
        confidence: float,
        label: str,
        timestamp: float,
        is_time_sliced: bool = False,
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
        if self.min_hits <= 1 or is_time_sliced:
            track.state = "confirmed"
        self.tracks[tid] = track
        return track

    def _get_active_tracks(self, confirmed_only: bool, include_predicting: bool = True) -> Dict[int, Track]:
        """Filter tracks by active or confirmed status."""
        can_coast = include_predicting and (self.coast_frames > 0 or self.coast_seconds > 0.0)
        coast_states = ("predicting", "coasting", "occluded")
        if not confirmed_only:
            return {
                tid: trk for tid, trk in self.tracks.items()
                if trk.missed_frames == 0 or (can_coast and trk.state in coast_states)
            }
        return {
            tid: trk for tid, trk in self.tracks.items()
            if (trk.state in ("confirmed", *coast_states) if can_coast else trk.state == "confirmed")
            and (trk.missed_frames == 0 or (can_coast and trk.state in coast_states))
        }

    def update(
        self,
        detections: List[Any],
        timestamp: Optional[float] = None,
        confirmed_only: bool = False,
    ) -> Dict[int, Track]:
        """Update tracker with detections from current frame."""
        now = timestamp if timestamp is not None else time.time()
        step_dt = (now - self._last_update_time) if self._last_update_time is not None else 0.0
        self._last_update_time = now
        is_time_sliced = step_dt >= self.time_slice_dt_threshold

        bboxes, classes, scores, labels = parse_detections(detections)
        det_embeddings = extract_detection_embeddings(detections)

        if len(self.tracks) == 0:
            for i in range(len(bboxes)):
                trk = self._register_track(bboxes[i], classes[i], scores[i], labels[i], now, is_time_sliced=is_time_sliced)
                if det_embeddings is not None and det_embeddings[i] is not None:
                    trk.last_embedding = det_embeddings[i]
            return self._get_active_tracks(confirmed_only)

        if len(bboxes) == 0:
            self._coast_empty_frame(now, is_time_sliced=is_time_sliced)
            return self._get_active_tracks(confirmed_only)

        track_ids = list(self.tracks.keys())
        matched_trks, matched_dets = self._match_iou(
            track_ids, bboxes, scores, labels, classes, now, det_embeddings=det_embeddings
        )
        self._match_distance(
            track_ids, bboxes, scores, labels, classes, matched_trks, matched_dets, now,
            det_embeddings=det_embeddings,
        )
        self._update_stale_tracks(track_ids, matched_trks, now, is_time_sliced=is_time_sliced)
        self._register_new_detections(bboxes, classes, scores, labels, matched_dets, now, is_time_sliced=is_time_sliced)
        if det_embeddings is not None:
            for trk in self.tracks.values():
                if trk.hits == 1 and trk.last_embedding is None:
                    for c in range(len(bboxes)):
                        if c not in matched_dets and trk.bbox == bboxes[c] and det_embeddings[c] is not None:
                            trk.last_embedding = det_embeddings[c]
                            break

        return self._get_active_tracks(confirmed_only)


__all__ = ["CentroidTracker"]
