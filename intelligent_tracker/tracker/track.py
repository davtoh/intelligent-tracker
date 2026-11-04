"""Rich object tracking representation.

Maintains trajectory history, velocity vectors, state lifecycle transitions,
persistent session identity, and spatial bounding boxes across frames.
"""

from collections import deque
import time
from typing import Any, Dict, Optional, Tuple


class Track:
    """Represents an individual tracked entity across multiple video frames."""

    def __init__(
        self,
        track_id: int,
        bbox: Tuple[int, int, int, int],
        class_id: int = 0,
        label: str = "object",
        confidence: float = 1.0,
        timestamp: Optional[float] = None,
        max_history: int = 60,
        centroid: Optional[Tuple[float, float]] = None,
        **kwargs: Any,
    ):
        self.track_id = int(track_id)
        self.bbox = tuple(int(v) for v in bbox)
        self.class_id = int(class_id)
        self.label = str(label)
        self.confidence = float(confidence)

        now = timestamp if timestamp is not None else time.time()
        self.start_time = now
        self.last_seen = now

        cx = float(centroid[0]) if centroid else (self.bbox[0] + self.bbox[2] / 2.0)
        cy = float(centroid[1]) if centroid else (self.bbox[1] + self.bbox[3] / 2.0)
        self.centroid = (cx, cy)

        self.max_history = max_history
        self.history: deque = deque([(cx, cy, now)], maxlen=max_history)
        self.bbox_history: deque = deque([self.bbox], maxlen=max_history)

        self._init_lifecycle_and_identity()

    def _init_lifecycle_and_identity(self) -> None:
        """Initialize state machine, velocity, and session identity fields."""
        self.hits = 1
        self.missed_frames = 0
        self.state = "tentative"
        self.velocity = (0.0, 0.0)
        self.identity_label: Optional[str] = None
        self.session_id: Optional[int] = None
        self.exit_point: Optional[Tuple[float, float]] = None
        self.exit_time: Optional[float] = None
        self.is_cluttered: bool = False
        self.clutter_partner_id: Optional[int] = None
        self.clutter_start_time: Optional[float] = None

    def update(
        self,
        bbox: Tuple[int, int, int, int],
        confidence: float = 1.0,
        label: Optional[str] = None,
        class_id: Optional[int] = None,
        timestamp: Optional[float] = None,
    ) -> None:
        """Update track with newly associated bounding box and detection metadata."""
        now = timestamp if timestamp is not None else time.time()
        dt = max(1e-4, now - self.last_seen)
        self.last_seen = now

        prev_cx, prev_cy = self.centroid
        new_bbox = tuple(int(v) for v in bbox)
        new_cx = new_bbox[0] + new_bbox[2] / 2.0
        new_cy = new_bbox[1] + new_bbox[3] / 2.0

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
        self.state = "confirmed" if self.hits >= 2 else "tentative"
        self.history.append((new_cx, new_cy, now))
        self.bbox_history.append(new_bbox)

    def predict(
        self,
        timestamp: Optional[float] = None,
        bounds: Optional[Tuple[int, int]] = None,
    ) -> Tuple[int, int, int, int]:
        """Extrapolate track position and bounding box using physical velocity (dead-reckoning)."""
        now = timestamp if timestamp is not None else time.time()
        dt = max(1e-4, min(1.0, now - self.last_seen))
        self.last_seen = now

        vx, vy = self.velocity
        new_cx = self.centroid[0] + vx * dt
        new_cy = self.centroid[1] + vy * dt

        w, h = self.bbox[2], self.bbox[3]
        new_x = int(round(new_cx - w / 2.0))
        new_y = int(round(new_cy - h / 2.0))

        if bounds is not None:
            max_w, max_h = bounds
            new_x = max(0, min(new_x, max_w - w))
            new_y = max(0, min(new_y, max_h - h))
            new_cx = new_x + w / 2.0
            new_cy = new_y + h / 2.0

        self.bbox = (int(new_x), int(new_y), int(w), int(h))
        self.centroid = (float(new_cx), float(new_cy))
        self.state = "predicting"
        self.history.append((new_cx, new_cy, now))
        self.bbox_history.append(self.bbox)
        return self.bbox

    def mark_missed(self) -> None:
        """Increment count of missed frames."""
        self.missed_frames += 1

    @property
    def dwell_time(self) -> float:
        """Elapsed time in seconds since the track was first detected."""
        return max(0.0, self.last_seen - self.start_time)

    def to_dict(self) -> Dict[str, Any]:
        """Convert track representation to serializable telemetry dictionary."""
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
            "is_predicting": self.state == "predicting",
            "identity_label": self.identity_label,
            "session_id": self.session_id,
            "velocity": (round(self.velocity[0], 1), round(self.velocity[1], 1)),
        }


__all__ = ["Track"]
