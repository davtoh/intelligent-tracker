"""Active Learning Candidate Triage Collaborator.

Handles ambiguous detection gating, per-track debouncing, BGR crop persistence,
and ``ReviewItemQueuedEvent`` publishing for ``ActiveLearningManager``.
"""

import os
import time
from typing import Any

import cv2
import numpy as np

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.events import ReviewItemQueuedEvent


def _extract_crop_from_frame(frame: np.ndarray | None, bbox: Any) -> np.ndarray | None:
    """Slice and validate a bounded crop from ``frame`` using ``bbox=(x, y, w, h)``."""
    if bbox is None or frame is None or frame.size == 0:
        return None
    x, y, w, h = [int(v) for v in bbox]
    ih, iw = frame.shape[:2]
    x1, y1 = max(0, min(x, iw - 1)), max(0, min(y, ih - 1))
    x2, y2 = max(x1 + 1, min(x + w, iw)), max(y1 + 1, min(y + h, ih))
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0 or crop.shape[0] < 4 or crop.shape[1] < 4:
        return None
    return crop


def _is_valid_crop(crop: np.ndarray | None) -> bool:
    """Return True if ``crop`` is a non-empty image at least 4x4 pixels."""
    return crop is not None and crop.size > 0 and crop.shape[0] >= 4 and crop.shape[1] >= 4


class ActiveLearningTriage:
    """Evaluates ambiguous detections and queues debounced review candidates."""

    def __init__(
        self,
        db: TrackerDB,
        min_confidence: float = 0.45,
        max_confidence: float = 0.70,
        debounce_interval: float = 30.0,
        crops_dir: str = "data/crops",
        event_bus: Any | None = None,
    ) -> None:
        self.db = db
        self.min_confidence = float(min_confidence)
        self.max_confidence = float(max_confidence)
        self.debounce_interval = float(debounce_interval)
        self.crops_dir = crops_dir
        self.event_bus = event_bus
        self._last_queued: dict[tuple[str, int], float] = {}
        os.makedirs(self.crops_dir, exist_ok=True)

    def _is_candidate_eligible(self, camera_id: str, track_id: int, similarity: float, now: float) -> bool:
        """Check similarity range [min_confidence, max_confidence) and track debounce."""
        score = float(similarity)
        if not (self.min_confidence <= score < self.max_confidence):
            return False
        return (now - self._last_queued.get((camera_id, track_id), 0.0)) >= self.debounce_interval

    def _save_crop(self, camera_id: str, track_id: int, crop: np.ndarray, now: float) -> str | None:
        """Persist candidate BGR crop thumbnail to ``crops_dir``."""
        filename = f"review_{camera_id}_{track_id}_{int(now)}_{np.random.randint(100, 999)}.jpg"
        crop_path = os.path.join(self.crops_dir, filename)
        try:
            return crop_path if cv2.imwrite(crop_path, crop) else None
        except Exception:
            return None

    def _publish_queued_event(self, **event_kwargs: Any) -> None:
        """Dispatch ``ReviewItemQueuedEvent`` to the attached event bus."""
        if self.event_bus is None:
            return
        try:
            self.event_bus.publish(ReviewItemQueuedEvent(**event_kwargs))
        except Exception:
            pass

    def _queue_crop(
        self,
        camera_id: str,
        track_id: int,
        crop: np.ndarray | None,
        similarity: float,
        suggested_entity_id: int | None,
        suggested_name: str,
        suggested_category: str,
        now: float,
    ) -> int | None:
        """Persist crop, insert review queue record, update debounce, and emit event."""
        if not _is_valid_crop(crop):
            return None
        crop_path = self._save_crop(camera_id, track_id, crop, now)
        if crop_path is None:
            return None
        score = float(similarity)
        review_id = self.db.add_review_item(
            camera_id=camera_id, track_id=track_id, crop_path=crop_path,
            suggested_entity_id=suggested_entity_id, suggested_name=suggested_name,
            suggested_category=suggested_category, similarity=score, status="pending",
        )
        self._last_queued[(camera_id, track_id)] = now
        self._publish_queued_event(
            camera_id=camera_id, review_id=review_id, track_id=track_id, crop_path=crop_path,
            suggested_entity_id=suggested_entity_id, suggested_name=suggested_name,
            suggested_category=suggested_category, similarity=score, timestamp=now,
        )
        return review_id

    def consider_candidate(
        self,
        track: Any,
        frame: np.ndarray,
        similarity: float,
        suggested_entity_id: int | None = None,
        suggested_name: str = "",
        suggested_category: str = "",
        camera_id: str = "cam_01",
        timestamp: float | None = None,
    ) -> int | None:
        """Evaluate track detection; crop from frame and queue if ambiguous."""
        now = timestamp if timestamp is not None else time.time()
        tid = getattr(track, "track_id", 0)
        if not self._is_candidate_eligible(camera_id, tid, similarity, now):
            return None
        crop = _extract_crop_from_frame(frame, getattr(track, "bbox", None))
        return self._queue_crop(
            camera_id=camera_id, track_id=tid, crop=crop, similarity=similarity,
            suggested_entity_id=suggested_entity_id, suggested_name=suggested_name,
            suggested_category=suggested_category, now=now,
        )

    def maybe_queue_candidate(
        self,
        camera_id: str,
        track_id: int,
        crop: np.ndarray,
        similarity: float,
        matched_entity_id: int | None = None,
        matched_entity_name: str = "",
        matched_category: str = "",
        bbox: tuple[int, int, int, int] | None = None,
        timestamp: float | None = None,
    ) -> dict[str, Any] | None:
        """Evaluate pre-cropped candidate and return queued review item dict or None."""
        del bbox  # Preserved in signature for caller parity
        now = timestamp if timestamp is not None else time.time()
        if not self._is_candidate_eligible(camera_id, track_id, similarity, now):
            return None
        item_id = self._queue_crop(
            camera_id=camera_id, track_id=track_id, crop=crop, similarity=similarity,
            suggested_entity_id=matched_entity_id, suggested_name=matched_entity_name,
            suggested_category=matched_category, now=now,
        )
        return self.db.get_review_item(item_id) if item_id is not None else None
