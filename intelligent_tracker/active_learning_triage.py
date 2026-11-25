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
        unknown_min_dwell_sec: float = 3.0,
    ) -> None:
        self.db = db
        self.min_confidence = float(min_confidence)
        self.max_confidence = float(max_confidence)
        self.debounce_interval = float(debounce_interval)
        self.unknown_min_dwell_sec = max(0.0, float(unknown_min_dwell_sec))
        self.crops_dir = crops_dir
        self.event_bus = event_bus
        self.video_filename: str = ""
        self._last_queued: dict[tuple[str, int], float] = {}
        os.makedirs(self.crops_dir, exist_ok=True)

    def _classify_candidate_reason(
        self, camera_id: str, track_id: int, similarity: float, now: float, track_dwell_sec: float = 0.0,
    ) -> str | None:
        """Return queue reason ('borderline' or 'recurring_unknown') if eligible and not debounced."""
        last = self._last_queued.get((camera_id, track_id))
        if last is not None and 0.0 <= (now - last) < self.debounce_interval:
            return None
        score = float(similarity)
        if self.min_confidence <= score < self.max_confidence:
            return "borderline"
        if score < self.min_confidence and float(track_dwell_sec or 0.0) >= self.unknown_min_dwell_sec:
            return "recurring_unknown"
        return None

    def _is_candidate_eligible(
        self, camera_id: str, track_id: int, similarity: float, now: float, track_dwell_sec: float = 0.0,
    ) -> bool:
        """Check borderline or recurring-unknown eligibility and per-track debounce."""
        return self._classify_candidate_reason(camera_id, track_id, similarity, now, track_dwell_sec) is not None

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
        self, camera_id: str, track_id: int, crop: np.ndarray | None, similarity: float,
        suggested_entity_id: int | None, suggested_name: str, suggested_category: str, now: float,
        video_filename: str = "", media_offset_sec: float = 0.0, bbox: Any = None,
        frame_width: int = 0, frame_height: int = 0, run_id: str = "", reason: str = "borderline",
    ) -> int | None:
        """Persist crop, insert review queue record, update debounce, and emit event."""
        if crop is None or not _is_valid_crop(crop):
            return None
        crop_path = self._save_crop(camera_id, track_id, crop, now)
        if crop_path is None:
            return None
        score = float(similarity)
        eff_eid = None if reason == "recurring_unknown" else suggested_entity_id
        eff_name = "" if reason == "recurring_unknown" else suggested_name
        review_id = self.db.add_review_item(
            camera_id=camera_id, track_id=track_id, crop_path=crop_path,
            suggested_entity_id=eff_eid, suggested_name=eff_name,
            suggested_category=suggested_category, similarity=score, status="pending",
            video_filename=video_filename, media_offset_sec=media_offset_sec,
            bbox=bbox, frame_width=frame_width, frame_height=frame_height, run_id=run_id, reason=reason,
        )
        self._last_queued[(camera_id, track_id)] = now
        self._publish_queued_event(
            camera_id=camera_id, review_id=review_id, track_id=track_id, crop_path=crop_path,
            suggested_entity_id=eff_eid, suggested_name=eff_name,
            suggested_category=suggested_category, similarity=score, timestamp=now,
        )
        return review_id

    def _resolve_media_offset(self, resolved_video: str, media_offset_sec: float | None, now: float, timestamp: float | None) -> float:
        """Resolve media offset from explicit arg, stored offset, or video timestamp."""
        if media_offset_sec is not None:
            return float(media_offset_sec)
        stored_offset = getattr(self, "current_media_offset_sec", None)
        if resolved_video and stored_offset is not None:
            return float(stored_offset)
        return float(now) if resolved_video and timestamp is not None else 0.0

    def consider_candidate(
        self, track: Any, frame: np.ndarray, similarity: float,
        suggested_entity_id: int | None = None, suggested_name: str = "",
        suggested_category: str = "", camera_id: str = "cam_01",
        timestamp: float | None = None, video_filename: str = "",
        media_offset_sec: float | None = None, run_id: str = "",
        track_dwell_sec: float | None = None,
    ) -> int | None:
        """Evaluate track detection; crop from frame and queue if borderline or recurring unknown."""
        now = timestamp if timestamp is not None else time.time()
        tid = getattr(track, "track_id", 0)
        dwell = float(track_dwell_sec) if track_dwell_sec is not None else float(getattr(track, "dwell_time", 0.0) or 0.0)
        reason = self._classify_candidate_reason(camera_id, tid, similarity, now, track_dwell_sec=dwell)
        if reason is None:
            return None
        bbox = getattr(track, "bbox", None)
        crop = _extract_crop_from_frame(frame, bbox)
        frame_h, frame_w = (int(frame.shape[0]), int(frame.shape[1])) if frame is not None and frame.ndim >= 2 else (0, 0)
        resolved_video = str(video_filename or self.video_filename or "").strip()
        resolved_offset = self._resolve_media_offset(resolved_video, media_offset_sec, now, timestamp)
        return self._queue_crop(
            camera_id=camera_id, track_id=tid, crop=crop, similarity=similarity,
            suggested_entity_id=suggested_entity_id, suggested_name=suggested_name,
            suggested_category=suggested_category, now=now, video_filename=resolved_video,
            media_offset_sec=resolved_offset, bbox=bbox, frame_width=frame_w, frame_height=frame_h,
            run_id=run_id, reason=reason,
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
        frame_width: int = 0,
        frame_height: int = 0,
        video_filename: str = "",
        media_offset_sec: float = 0.0,
        run_id: str = "",
        track_dwell_sec: float = 0.0,
    ) -> dict[str, Any] | None:
        """Evaluate pre-cropped candidate and return queued review item dict or None."""
        now = timestamp if timestamp is not None else time.time()
        reason = self._classify_candidate_reason(camera_id, track_id, similarity, now, track_dwell_sec=track_dwell_sec)
        if reason is None:
            return None
        item_id = self._queue_crop(
            camera_id=camera_id, track_id=track_id, crop=crop, similarity=similarity,
            suggested_entity_id=matched_entity_id, suggested_name=matched_entity_name,
            suggested_category=matched_category, now=now,
            video_filename=video_filename, media_offset_sec=media_offset_sec,
            bbox=bbox, frame_width=frame_width, frame_height=frame_height, run_id=run_id,
            reason=reason,
        )
        return self.db.get_review_item(item_id) if item_id is not None else None
