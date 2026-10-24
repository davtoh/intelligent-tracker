#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Multi-Object Tracking (MOT) Module.

Provides:
- `Track`: Rich object tracking representation with trajectory history, velocity,
  state lifecycle, and spatial bounding boxes.
- `CentroidTracker`: IoU and Euclidean distance-based frame-to-frame association
  with zero heavy dependencies.
- `SortTracker`: Simple Online and Realtime Tracking using pure NumPy Kalman filters.
- `TrackerFactory`: Registry for dynamic instantiation.
"""

from __future__ import division, print_function, absolute_import

import time
import math
from collections import deque
from typing import List, Dict, Tuple, Optional, Any, Union

import numpy as np

# Optional SciPy Hungarian algorithm with pure NumPy greedy fallback
try:
    from scipy.optimize import linear_sum_assignment
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False


def compute_iou(boxA: Tuple[int, int, int, int], boxB: Tuple[int, int, int, int]) -> float:
    """
    Compute Intersection over Union (IoU) between two bounding boxes.
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


def compute_iou_matrix(boxesA: List[Tuple[int, int, int, int]], boxesB: List[Tuple[int, int, int, int]]) -> np.ndarray:
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


class Track(object):
    """
    Represents an individual tracked entity across multiple video frames.
    """

    def __init__(
        self,
        track_id: int,
        bbox: Tuple[int, int, int, int],
        class_id: int = 0,
        label: str = "object",
        confidence: float = 1.0,
        timestamp: Optional[float] = None,
        max_history: int = 60,
    ):
        self.track_id = int(track_id)
        self.bbox = tuple(int(v) for v in bbox)
        self.class_id = int(class_id)
        self.label = str(label)
        self.confidence = float(confidence)

        now = timestamp if timestamp is not None else time.time()
        self.start_time = now
        self.last_seen = now

        # Centroid (cx, cy)
        cx = self.bbox[0] + self.bbox[2] / 2.0
        cy = self.bbox[1] + self.bbox[3] / 2.0
        self.centroid = (cx, cy)

        # History queues
        self.max_history = max_history
        self.history = deque(maxlen=max_history)
        self.history.append((cx, cy, now))
        self.bbox_history = deque(maxlen=max_history)
        self.bbox_history.append(self.bbox)

        # State tracking
        self.hits = 1
        self.missed_frames = 0
        self.state = "tentative"  # 'tentative', 'confirmed', 'lost'
        self.velocity = (0.0, 0.0)

    def update(
        self,
        bbox: Tuple[int, int, int, int],
        confidence: float = 1.0,
        label: Optional[str] = None,
        class_id: Optional[int] = None,
        timestamp: Optional[float] = None,
    ):
        now = timestamp if timestamp is not None else time.time()
        dt = max(1e-4, now - self.last_seen)
        self.last_seen = now

        prev_cx, prev_cy = self.centroid
        new_bbox = tuple(int(v) for v in bbox)
        new_cx = new_bbox[0] + new_bbox[2] / 2.0
        new_cy = new_bbox[1] + new_bbox[3] / 2.0

        # Update velocity with exponential smoothing
        vx = (new_cx - prev_cx) / dt
        vy = (new_cy - prev_cy) / dt
        self.velocity = (0.7 * self.velocity[0] + 0.3 * vx, 0.7 * self.velocity[1] + 0.3 * vy)

        self.bbox = new_bbox
        self.centroid = (new_cx, new_cy)
        self.confidence = float(confidence)
        if label is not None:
            self.label = str(label)
        if class_id is not None:
            self.class_id = int(class_id)

        self.hits += 1
        self.missed_frames = 0
        self.history.append((new_cx, new_cy, now))
        self.bbox_history.append(new_bbox)

    def mark_missed(self):
        self.missed_frames += 1

    @property
    def dwell_time(self) -> float:
        return max(0.0, self.last_seen - self.start_time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "track_id": self.track_id,
            "bbox": self.bbox,
            "centroid": self.centroid,
            "class_id": self.class_id,
            "label": self.label,
            "confidence": round(self.confidence, 3),
            "dwell_time": round(self.dwell_time, 2),
            "hits": self.hits,
            "missed_frames": self.missed_frames,
            "state": self.state,
            "velocity": (round(self.velocity[0], 1), round(self.velocity[1], 1)),
        }


class CentroidTracker(object):
    """
    Centroid and IoU Multi-Object Tracker.

    Matches detections to existing tracks using a two-stage association strategy:
    1. High-overlap IoU matching for stable targets.
    2. Centroid Euclidean distance matching for fast-moving or displaced objects.

    Parameters:
    -----------
    max_disappeared : int
        Maximum consecutive frames a track can be missed before deregistration.
    min_hits : int
        Consecutive detections required to confirm a track.
    max_distance : float
        Maximum pixel distance for centroid matching fallback.
    iou_threshold : float
        Minimum IoU overlap to consider an association valid.
    """

    def __init__(
        self,
        max_disappeared: int = 30,
        min_hits: int = 3,
        max_distance: float = 120.0,
        iou_threshold: float = 0.2,
    ):
        self.max_disappeared = int(max_disappeared)
        self.min_hits = int(min_hits)
        self.max_distance = float(max_distance)
        self.iou_threshold = float(iou_threshold)

        self.next_track_id = 1
        self.tracks: Dict[int, Track] = {}

    def reset(self):
        self.next_track_id = 1
        self.tracks.clear()

    def update(
        self,
        detections: List[Any],
        timestamp: Optional[float] = None,
        confirmed_only: bool = False,
    ) -> Dict[int, Track]:
        """
        Update tracker with detections from current frame.

        :param detections: List of Detection namedtuples or objects with .bbox, .class_id, .confidence, .label
        :param timestamp: Frame timestamp
        :param confirmed_only: If True, only returns confirmed tracks
        :return: Dict[track_id, Track]
        """
        now = timestamp if timestamp is not None else time.time()

        # Parse detections into standardized format
        det_bboxes = []
        det_classes = []
        det_scores = []
        det_labels = []

        for d in detections:
            bbox = getattr(d, "bbox", None)
            if bbox is None and isinstance(d, (tuple, list)) and len(d) >= 4:
                bbox = d[:4]
            if bbox is not None:
                det_bboxes.append(tuple(int(v) for v in bbox))
                det_classes.append(getattr(d, "class_id", 0))
                det_scores.append(getattr(d, "confidence", 1.0))
                det_labels.append(getattr(d, "label", "object"))

        # If no active tracks, register all detections as new
        if len(self.tracks) == 0:
            for i in range(len(det_bboxes)):
                self._register_track(
                    det_bboxes[i],
                    det_classes[i],
                    det_scores[i],
                    det_labels[i],
                    now,
                )
            return self._get_active_tracks(confirmed_only)

        # If no detections in current frame, mark all active tracks as missed
        if len(det_bboxes) == 0:
            to_remove = []
            for tid, trk in self.tracks.items():
                trk.mark_missed()
                if trk.missed_frames > self.max_disappeared:
                    to_remove.append(tid)
            for tid in to_remove:
                del self.tracks[tid]
            return self._get_active_tracks(confirmed_only)

        # Stage 1: IoU Association
        track_ids = list(self.tracks.keys())
        track_boxes = [self.tracks[tid].bbox for tid in track_ids]

        iou_mat = compute_iou_matrix(track_boxes, det_bboxes)
        matched_tracks = set()
        matched_dets = set()

        if iou_mat.size > 0:
            cost_mat = 1.0 - iou_mat
            if _HAS_SCIPY:
                row_ind, col_ind = linear_sum_assignment(cost_mat)
                assignments = list(zip(row_ind, col_ind))
            else:
                assignments = greedy_assignment(cost_mat, max_cost=1.0 - self.iou_threshold)

            for r, c in assignments:
                if iou_mat[r, c] >= self.iou_threshold:
                    tid = track_ids[r]
                    self.tracks[tid].update(
                        det_bboxes[c],
                        confidence=det_scores[c],
                        label=det_labels[c],
                        class_id=det_classes[c],
                        timestamp=now,
                    )
                    matched_tracks.add(r)
                    matched_dets.add(c)

        # Stage 2: Centroid Euclidean Distance for Unmatched
        unmatched_track_indices = [r for r in range(len(track_ids)) if r not in matched_tracks]
        unmatched_det_indices = [c for c in range(len(det_bboxes)) if c not in matched_dets]

        if unmatched_track_indices and unmatched_det_indices:
            track_centroids = np.array([self.tracks[track_ids[r]].centroid for r in unmatched_track_indices])
            det_centroids = np.array([
                (det_bboxes[c][0] + det_bboxes[c][2] / 2.0, det_bboxes[c][1] + det_bboxes[c][3] / 2.0)
                for c in unmatched_det_indices
            ])

            dist_mat = np.linalg.norm(track_centroids[:, None, :] - det_centroids[None, :, :], axis=2)

            if _HAS_SCIPY:
                row_ind, col_ind = linear_sum_assignment(dist_mat)
                cent_assignments = list(zip(row_ind, col_ind))
            else:
                cent_assignments = greedy_assignment(dist_mat, max_cost=self.max_distance)

            for r, c in cent_assignments:
                if dist_mat[r, c] <= self.max_distance:
                    actual_r = unmatched_track_indices[r]
                    actual_c = unmatched_det_indices[c]
                    tid = track_ids[actual_r]
                    self.tracks[tid].update(
                        det_bboxes[actual_c],
                        confidence=det_scores[actual_c],
                        label=det_labels[actual_c],
                        class_id=det_classes[actual_c],
                        timestamp=now,
                    )
                    matched_tracks.add(actual_r)
                    matched_dets.add(actual_c)

        # Update states & deregister stale tracks
        to_remove = []
        for r, tid in enumerate(track_ids):
            if r not in matched_tracks:
                trk = self.tracks[tid]
                trk.mark_missed()
                if trk.missed_frames > self.max_disappeared:
                    to_remove.append(tid)
            else:
                trk = self.tracks[tid]
                if trk.hits >= self.min_hits:
                    trk.state = "confirmed"

        for tid in to_remove:
            del self.tracks[tid]

        # Register new detections
        for c in range(len(det_bboxes)):
            if c not in matched_dets:
                self._register_track(
                    det_bboxes[c],
                    det_classes[c],
                    det_scores[c],
                    det_labels[c],
                    now,
                )

        return self._get_active_tracks(confirmed_only)

    def _register_track(self, bbox, class_id, confidence, label, timestamp):
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

    def _get_active_tracks(self, confirmed_only: bool) -> Dict[int, Track]:
        if not confirmed_only:
            return {tid: trk for tid, trk in self.tracks.items() if trk.missed_frames == 0}
        return {tid: trk for tid, trk in self.tracks.items() if trk.state == "confirmed" and trk.missed_frames == 0}


class KalmanBoxTracker(object):
    """
    2D Kinematic Kalman Filter for bounding box tracking in pure NumPy.
    State: [x, y, s, r, vx, vy, vs]
      (x, y) = center of bbox
      s = area (w * h)
      r = aspect ratio (w / h)
    """

    count = 0

    def __init__(self, bbox: Tuple[int, int, int, int]):
        KalmanBoxTracker.count += 1
        self.id = KalmanBoxTracker.count

        # Initial state x: [7, 1]
        self.x = np.zeros((7, 1), dtype=np.float32)
        cx = bbox[0] + bbox[2] / 2.0
        cy = bbox[1] + bbox[3] / 2.0
        s = float(bbox[2] * bbox[3])
        r = float(bbox[2]) / float(bbox[3]) if bbox[3] > 0 else 1.0
        self.x[:4, 0] = [cx, cy, s, r]

        # State transition matrix F (constant velocity)
        self.F = np.eye(7, dtype=np.float32)
        for i in range(3):
            self.F[i, i + 4] = 1.0

        # Measurement matrix H
        self.H = np.zeros((4, 7), dtype=np.float32)
        self.H[:4, :4] = np.eye(4, dtype=np.float32)

        # Covariance matrices
        self.P = np.eye(7, dtype=np.float32) * 10.0
        self.P[4:, 4:] *= 100.0

        self.Q = np.eye(7, dtype=np.float32)
        self.Q[4:, 4:] *= 0.01

        self.R = np.eye(4, dtype=np.float32) * 1.0
        self.R[2:, 2:] *= 10.0

        self.time_since_update = 0
        self.history = []
        self.hits = 1
        self.hit_streak = 1
        self.age = 0

    def predict(self) -> np.ndarray:
        """Advance the state vector and return the predicted bounding box."""
        if (self.x[6, 0] + self.x[2, 0]) <= 0:
            self.x[6, 0] = 0.0

        self.x = np.dot(self.F, self.x)
        self.P = np.dot(np.dot(self.F, self.P), self.F.T) + self.Q

        self.age += 1
        if self.time_since_update > 0:
            self.hit_streak = 0
        self.time_since_update += 1

        return self.get_state()

    def update(self, bbox: Tuple[int, int, int, int]):
        """Update the state vector with observed bounding box."""
        self.time_since_update = 0
        self.history = []
        self.hits += 1
        self.hit_streak += 1

        cx = bbox[0] + bbox[2] / 2.0
        cy = bbox[1] + bbox[3] / 2.0
        s = float(bbox[2] * bbox[3])
        r = float(bbox[2]) / float(bbox[3]) if bbox[3] > 0 else 1.0
        z = np.array([[cx], [cy], [s], [r]], dtype=np.float32)

        # Innovation
        y = z - np.dot(self.H, self.x)
        S = np.dot(np.dot(self.H, self.P), self.H.T) + self.R
        K = np.dot(np.dot(self.P, self.H.T), np.linalg.inv(S))

        self.x = self.x + np.dot(K, y)
        I = np.eye(7, dtype=np.float32)
        self.P = np.dot(I - np.dot(K, self.H), self.P)

    def get_state(self) -> Tuple[int, int, int, int]:
        """Convert current state back to (x, y, w, h) bounding box."""
        cx = self.x[0, 0]
        cy = self.x[1, 0]
        s = max(1.0, self.x[2, 0])
        r = max(0.01, self.x[3, 0])

        w = math.sqrt(s * r)
        h = s / w if w > 0 else 0
        x = int(cx - w / 2.0)
        y = int(cy - h / 2.0)
        return (x, y, int(w), int(h))


class SortTracker(object):
    """
    SORT (Simple Online and Realtime Tracking) implementation using pure NumPy Kalman filtering.
    """

    def __init__(self, max_age: int = 30, min_hits: int = 3, iou_threshold: float = 0.3):
        self.max_age = int(max_age)
        self.min_hits = int(min_hits)
        self.iou_threshold = float(iou_threshold)
        self.trackers: List[KalmanBoxTracker] = []
        self.track_metadata: Dict[int, Dict[str, Any]] = {}

    def reset(self):
        self.trackers.clear()
        self.track_metadata.clear()

    def update(
        self,
        detections: List[Any],
        timestamp: Optional[float] = None,
        confirmed_only: bool = False,
    ) -> Dict[int, Track]:
        now = timestamp if timestamp is not None else time.time()

        det_bboxes = []
        det_classes = []
        det_scores = []
        det_labels = []

        for d in detections:
            bbox = getattr(d, "bbox", None)
            if bbox is None and isinstance(d, (tuple, list)) and len(d) >= 4:
                bbox = d[:4]
            if bbox is not None:
                det_bboxes.append(tuple(int(v) for v in bbox))
                det_classes.append(getattr(d, "class_id", 0))
                det_scores.append(getattr(d, "confidence", 1.0))
                det_labels.append(getattr(d, "label", "object"))

        # Predict new locations of existing targets
        predicted_boxes = []
        to_del = []
        for i, trk in enumerate(self.trackers):
            pos = trk.predict()
            if any(np.isnan(pos)) or pos[2] <= 0 or pos[3] <= 0:
                to_del.append(i)
            else:
                predicted_boxes.append(pos)

        for i in reversed(to_del):
            del self.trackers[i]

        # Associate detections to predicted boxes via IoU
        matched_trks = set()
        matched_dets = set()

        if predicted_boxes and det_bboxes:
            iou_mat = compute_iou_matrix(predicted_boxes, det_bboxes)
            cost_mat = 1.0 - iou_mat
            if _HAS_SCIPY:
                row_ind, col_ind = linear_sum_assignment(cost_mat)
                assignments = list(zip(row_ind, col_ind))
            else:
                assignments = greedy_assignment(cost_mat, max_cost=1.0 - self.iou_threshold)

            for r, c in assignments:
                if iou_mat[r, c] >= self.iou_threshold:
                    self.trackers[r].update(det_bboxes[c])
                    trk_id = self.trackers[r].id
                    self.track_metadata[trk_id] = {
                        "class_id": det_classes[c],
                        "confidence": det_scores[c],
                        "label": det_labels[c],
                    }
                    matched_trks.add(r)
                    matched_dets.add(c)

        # Create and initialize new trackers for unmatched detections
        for c in range(len(det_bboxes)):
            if c not in matched_dets:
                trk = KalmanBoxTracker(det_bboxes[c])
                self.trackers.append(trk)
                self.track_metadata[trk.id] = {
                    "class_id": det_classes[c],
                    "confidence": det_scores[c],
                    "label": det_labels[c],
                }

        # Format output into Dict[track_id, Track]
        active_tracks: Dict[int, Track] = {}
        for trk in self.trackers:
            if trk.time_since_update < 1 and (trk.hit_streak >= self.min_hits or not confirmed_only):
                meta = self.track_metadata.get(trk.id, {})
                box = trk.get_state()
                t = Track(
                    track_id=trk.id,
                    bbox=box,
                    class_id=meta.get("class_id", 0),
                    label=meta.get("label", "object"),
                    confidence=meta.get("confidence", 1.0),
                    timestamp=now,
                )
                t.hits = trk.hits
                t.state = "confirmed" if trk.hit_streak >= self.min_hits else "tentative"
                active_tracks[trk.id] = t

        # Remove dead trackers
        self.trackers = [t for t in self.trackers if t.time_since_update <= self.max_age]
        return active_tracks


class TrackerFactory(object):
    """Factory registry for multi-object tracking engines."""

    _registry = {
        "centroid": CentroidTracker,
        "sort": SortTracker,
    }

    @classmethod
    def register(cls, name: str, tracker_cls: type):
        cls._registry[name.lower()] = tracker_cls

    @classmethod
    def create(cls, name: str = "centroid", **kwargs) -> Any:
        key = name.lower()
        if key not in cls._registry:
            raise ValueError(
                "Unknown tracker '{}'. Available trackers: {}".format(name, list(cls._registry.keys()))
            )
        return cls._registry[key](**kwargs)

    @classmethod
    def available_trackers(cls) -> List[str]:
        return list(cls._registry.keys())
