"""SORT (Simple Online and Realtime Tracking) implementation.

Uses pure NumPy 2D Kinematic Kalman filters for continuous bounding box tracking
and IoU association.
"""

import math
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


class KalmanBoxTracker:
    """2D Kinematic Kalman Filter for bounding box tracking in pure NumPy.

    State: ``[x, y, s, r, vx, vy, vs]`` where:
    - ``(x, y)`` = center of bbox
    - ``s`` = area (w * h)
    - ``r`` = aspect ratio (w / h)
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
        self.history: list = []
        self.hits = 1
        self.hit_streak = 1
        self.age = 0

    def predict(self) -> Tuple[int, int, int, int]:
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

    def update(self, bbox: Tuple[int, int, int, int]) -> None:
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


class SortTracker:
    """SORT (Simple Online and Realtime Tracking) implementation using pure NumPy Kalman filtering."""

    def __init__(self, max_age: int = 30, min_hits: int = 3, iou_threshold: float = 0.3):
        self.max_age = int(max_age)
        self.min_hits = int(min_hits)
        self.iou_threshold = float(iou_threshold)
        self.trackers: List[KalmanBoxTracker] = []
        self.track_metadata: Dict[int, Dict[str, Any]] = {}

    def reset(self) -> None:
        """Clear active Kalman trackers and associated detection metadata."""
        self.trackers.clear()
        self.track_metadata.clear()

    def _parse_detections(self, detections: List[Any]) -> Tuple[list, list, list, list]:
        """Parse detections into standardized tuples."""
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

    def _predict_trackers(self) -> List[Tuple[int, int, int, int]]:
        """Advance all Kalman trackers and prune invalid NaN/degenerated predictions."""
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
        return predicted_boxes

    def _associate_and_update(
        self,
        predicted_boxes: List[Tuple[int, int, int, int]],
        det_bboxes: List[Tuple[int, int, int, int]],
        det_classes: List[int],
        det_scores: List[float],
        det_labels: List[str],
    ) -> Tuple[Set[int], Set[int]]:
        """Associate predictions to detections via IoU matching."""
        matched_trks, matched_dets = set(), set()
        if not predicted_boxes or not det_bboxes:
            return matched_trks, matched_dets

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
        return matched_trks, matched_dets

    def _register_new_detections(
        self,
        det_bboxes: list,
        det_classes: list,
        det_scores: list,
        det_labels: list,
        matched_dets: Set[int],
    ) -> None:
        """Create new Kalman trackers for unassociated detections."""
        for c in range(len(det_bboxes)):
            if c not in matched_dets:
                trk = KalmanBoxTracker(det_bboxes[c])
                self.trackers.append(trk)
                self.track_metadata[trk.id] = {
                    "class_id": det_classes[c],
                    "confidence": det_scores[c],
                    "label": det_labels[c],
                }

    def _format_active_tracks(self, now: float, confirmed_only: bool) -> Dict[int, Track]:
        """Construct active Track dictionary for current frame."""
        active: Dict[int, Track] = {}
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
                active[trk.id] = t
        return active

    def update(
        self,
        detections: List[Any],
        timestamp: Optional[float] = None,
        confirmed_only: bool = False,
    ) -> Dict[int, Track]:
        """Update SORT tracker state with current frame detections."""
        now = timestamp if timestamp is not None else time.time()
        bboxes, classes, scores, labels = self._parse_detections(detections)
        predicted_boxes = self._predict_trackers()

        _, matched_dets = self._associate_and_update(
            predicted_boxes, bboxes, classes, scores, labels
        )
        self._register_new_detections(bboxes, classes, scores, labels, matched_dets)

        active = self._format_active_tracks(now, confirmed_only)
        self.trackers = [t for t in self.trackers if t.time_since_update <= self.max_age]
        return active


__all__ = ["KalmanBoxTracker", "SortTracker"]

