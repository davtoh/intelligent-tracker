"""SORT (Simple Online and Realtime Tracking) implementation.

Uses pure NumPy 2D Kinematic Kalman filters for continuous bounding box tracking
and IoU association.
"""

import time
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
import numpy as np

from intelligent_tracker.tracker.association import extract_detection_embeddings
from intelligent_tracker.tracker.bytetrack_association import associate_two_stage
from intelligent_tracker.tracker.kalman import KalmanBoxTracker
from intelligent_tracker.tracker.track import Track
from intelligent_tracker.tracker.utils import parse_detections


class SortTracker:
    """SORT (Simple Online and Realtime Tracking) implementation using pure NumPy Kalman filtering."""

    def __init__(
        self,
        max_age: int = 30,
        min_hits: int = 3,
        iou_threshold: float = 0.3,
        max_disappeared: Optional[int] = None,
        max_age_seconds: float = 2.5,
        time_slice_dt_threshold: float = 0.4,
        coast_frames: int = 0,
        coast_seconds: float = 0.0,
        high_conf_threshold: float = 0.4,
        low_conf_threshold: float = 0.1,
        **kwargs: Any,
    ):
        if max_disappeared is not None:
            max_age = max_disappeared
        self.max_age = int(max_age)
        self.min_hits = int(min_hits)
        self.iou_threshold = float(iou_threshold)
        self.max_age_seconds = float(max_age_seconds)
        self.time_slice_dt_threshold = float(time_slice_dt_threshold)
        self.coast_frames = max(0, int(coast_frames))
        self.coast_seconds = max(0.0, float(coast_seconds))
        self.high_conf_threshold = float(high_conf_threshold)
        self.low_conf_threshold = float(low_conf_threshold)
        self._last_update_time: Optional[float] = None
        self.trackers: List[KalmanBoxTracker] = []
        self.track_metadata: Dict[int, Dict[str, Any]] = {}
        self._active_tracks: Dict[int, Track] = {}

    def reset(self) -> None:
        """Clear active Kalman trackers and associated detection metadata."""
        self.trackers.clear()
        self.track_metadata.clear()
        self._active_tracks.clear()
        self._last_update_time = None

    @property
    def tracks(self) -> Dict[int, Track]:
        """Return currently active tracks keyed by track ID."""
        return {
            tid: trk for tid, trk in self._active_tracks.items()
            if trk.missed_frames == 0 or trk.state in ("coasting", "occluded")
        }

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
        det_embeddings: Optional[List[Optional[np.ndarray]]] = None,
        now: Optional[float] = None,
    ) -> Tuple[Set[int], List[int]]:
        """Associate predictions to detections via 2-stage ByteTrack IoU+appearance matching."""
        trk_labels = [self.track_metadata.get(t.id, {}).get("label", getattr(self._active_tracks.get(t.id), "label", "object")) for t in self.trackers]
        trk_classes = [int(self.track_metadata.get(t.id, {}).get("class_id", getattr(self._active_tracks.get(t.id), "class_id", 0))) for t in self.trackers]
        trk_embs = [getattr(self._active_tracks.get(t.id), "last_embedding", None) for t in self.trackers]
        matches, unmatched_high_dets = associate_two_stage(
            predicted_boxes, det_bboxes, det_scores, trk_labels, trk_classes, trk_embs,
            det_labels, det_classes, det_embeddings, iou_threshold=self.iou_threshold,
            high_conf_threshold=self.high_conf_threshold, low_conf_threshold=self.low_conf_threshold,
            appearance_weight=getattr(self, "appearance_weight", 0.35),
        )
        matched_trks: Set[int] = set()
        for r, c in matches:
            self.trackers[r].update(det_bboxes[c], timestamp=now)
            self.track_metadata[self.trackers[r].id] = {
                "class_id": det_classes[c], "confidence": det_scores[c], "label": det_labels[c],
                "embedding": det_embeddings[c] if det_embeddings is not None else None,
            }
            matched_trks.add(r)
        return matched_trks, unmatched_high_dets

    def _register_new_detections(
        self,
        det_bboxes: list,
        det_classes: list,
        det_scores: list,
        det_labels: list,
        unmatched_high_dets: Sequence[int] | Set[int],
        det_embeddings: Optional[List[Optional[np.ndarray]]] = None,
        now: Optional[float] = None,
    ) -> None:
        """Create new Kalman trackers only for unmatched high-confidence detections."""
        for c in unmatched_high_dets:
            trk = KalmanBoxTracker(det_bboxes[c], timestamp=now)
            self.trackers.append(trk)
            self.track_metadata[trk.id] = {
                "class_id": det_classes[c],
                "confidence": det_scores[c],
                "label": det_labels[c],
                "embedding": det_embeddings[c] if det_embeddings is not None else None,
            }

    def _is_within_coast_budget(
        self, trk: KalmanBoxTracker, now: float, is_time_sliced: bool
    ) -> bool:
        """Return True if missed Kalman tracker is eligible to emit a coasted box."""
        if trk.time_since_update <= 0:
            return False
        within_frames = self.coast_frames > 0 and trk.time_since_update <= self.coast_frames
        within_seconds = self.coast_seconds > 0.0 and (now - trk.last_seen) <= self.coast_seconds
        if is_time_sliced and self.coast_seconds > 0.0:
            return within_seconds
        return within_frames or within_seconds

    def _sync_persistent_track(
        self, trk: KalmanBoxTracker, now: float, is_time_sliced: bool
    ) -> Optional[Track]:
        """Update or coast the persistent Track object for a KalmanBoxTracker."""
        meta = self.track_metadata.get(trk.id, {})
        box = trk.get_state()
        t = self._active_tracks.get(trk.id)
        if trk.time_since_update == 0:
            if t is None:
                t = Track(
                    track_id=trk.id, bbox=box, class_id=meta.get("class_id", 0),
                    label=meta.get("label", "object"), confidence=meta.get("confidence", 1.0),
                    timestamp=now,
                )
                t.hits = trk.hits
                t.state = "confirmed" if (self.min_hits <= 1 or is_time_sliced or trk.hit_streak >= self.min_hits) else "tentative"
                self._active_tracks[trk.id] = t
            elif trk.hits > t.hits:
                t.update(
                    box, confidence=meta.get("confidence", 1.0), label=meta.get("label", "object"),
                    class_id=meta.get("class_id", 0), timestamp=now, min_hits=self.min_hits,
                )
                if is_time_sliced:
                    t.state = "confirmed"
            if meta.get("embedding") is not None:
                t.last_embedding = meta["embedding"]
            return t

        if t is None or not self._is_within_coast_budget(trk, now, is_time_sliced):
            return None
        t.missed_frames = trk.time_since_update
        t.bbox = box
        t.centroid = (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0)
        t.last_seen = now
        t.history.append((t.centroid[0], t.centroid[1], now))
        t.bbox_history.append(box)
        t.state = "occluded" if getattr(t, "is_cluttered", False) else "coasting"
        return t

    def _format_active_tracks(
        self, now: float, confirmed_only: bool, is_time_sliced: bool = False
    ) -> Dict[int, Track]:
        """Construct active Track dictionary for current frame."""
        active: Dict[int, Track] = {}
        for trk in self.trackers:
            if not self._keep_tracker(trk, now, is_time_sliced):
                continue
            t = self._sync_persistent_track(trk, now, is_time_sliced)
            if t is None:
                continue
            was_confirmed = t.hits >= self.min_hits or is_time_sliced
            if not confirmed_only or was_confirmed:
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
        step_dt = (now - self._last_update_time) if self._last_update_time is not None else 0.0
        self._last_update_time = now
        is_time_sliced = step_dt >= self.time_slice_dt_threshold

        bboxes, classes, scores, labels = parse_detections(detections)
        det_embeddings = extract_detection_embeddings(detections)
        predicted_boxes = self._predict_trackers()

        _, matched_dets = self._associate_and_update(
            predicted_boxes, bboxes, classes, scores, labels,
            det_embeddings=det_embeddings, now=now,
        )
        self._register_new_detections(
            bboxes, classes, scores, labels, matched_dets,
            det_embeddings=det_embeddings, now=now,
        )

        active = self._format_active_tracks(now, confirmed_only, is_time_sliced=is_time_sliced)
        kept: List[KalmanBoxTracker] = []
        for t in self.trackers:
            if self._keep_tracker(t, now, is_time_sliced):
                kept.append(t)
            else:
                trk_obj = self._active_tracks.pop(t.id, None)
                if trk_obj is not None:
                    trk_obj.state = "deleted"
                self.track_metadata.pop(t.id, None)
        self.trackers = kept
        return active

    def _keep_tracker(self, trk: KalmanBoxTracker, now: float, is_time_sliced: bool) -> bool:
        """Return True if Kalman tracker is within frame or elapsed-time age budget."""
        dt = now - trk.last_seen
        if is_time_sliced and self.max_age_seconds > 0:
            return dt <= self.max_age_seconds
        if trk.time_since_update > self.max_age:
            return False
        return self.max_age_seconds <= 0 or dt <= self.max_age_seconds


__all__ = ["KalmanBoxTracker", "SortTracker"]

