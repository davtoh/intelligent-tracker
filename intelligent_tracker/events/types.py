"""Typed event data classes and snapshot encoding/decoding utilities."""

import base64
from dataclasses import asdict, dataclass, field
import json
import logging
import time
from typing import Any, Dict, Optional, Tuple
import uuid

import cv2
import numpy as np

logger = logging.getLogger(__name__)


# ==============================================================================
# 1. Snapshot Encoding Helpers
# ==============================================================================

def frame_to_base64(
    frame: np.ndarray,
    quality: int = 80,
    max_dimension: Optional[int] = 640,
) -> Optional[str]:
    """
    Encode an OpenCV BGR frame into a base64-encoded JPEG string.

    :param frame: Video frame as NumPy array (H, W, 3).
    :param quality: JPEG quality (1-100).
    :param max_dimension: Optional maximum width/height constraint for downsampling.
    :return: Base64 ASCII string or None if frame is invalid.
    """
    if frame is None or frame.size == 0:
        return None

    h, w = frame.shape[:2]
    if max_dimension and (w > max_dimension or h > max_dimension):
        scale = float(max_dimension) / float(max(w, h))
        target_w = max(1, int(round(w * scale)))
        target_h = max(1, int(round(h * scale)))
        frame = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)

    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), max(10, min(100, int(quality)))]
    success, buffer = cv2.imencode(".jpg", frame, encode_params)
    if not success:
        return None

    return base64.b64encode(buffer).decode("ascii")


def crop_to_base64(
    frame: np.ndarray,
    bbox: Tuple[int, int, int, int],
    quality: int = 85,
    padding: int = 12,
) -> Optional[str]:
    """
    Crop bounding box region from frame with margin padding and encode to base64.

    :param frame: Video frame as NumPy array (H, W, 3).
    :param bbox: (x, y, w, h) in pixels.
    :param quality: JPEG quality (1-100).
    :param padding: Margin in pixels around bbox.
    :return: Base64 JPEG string or None.
    """
    if frame is None or bbox is None:
        return None

    h, w = frame.shape[:2]
    bx, by, bw, bh = bbox
    x0 = max(0, int(bx - padding))
    y0 = max(0, int(by - padding))
    x1 = min(w, int(bx + bw + padding))
    y1 = min(h, int(by + bh + padding))

    if x1 <= x0 or y1 <= y0:
        return None

    crop = frame[y0:y1, x0:x1]
    return frame_to_base64(crop, quality=quality, max_dimension=None)


def decode_snapshot_base64(b64_str: str) -> Optional[np.ndarray]:
    """Decode a base64 JPEG string back into an OpenCV BGR frame."""
    if not b64_str:
        return None
    try:
        raw_bytes = base64.b64decode(b64_str)
        arr = np.frombuffer(raw_bytes, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception as e:
        logger.warning("Failed to decode base64 snapshot: %s", e)
        return None


# ==============================================================================
# 2. Typed Event Data Classes
# ==============================================================================

@dataclass
class BaseEvent:
    """Base event contract for all intelligent tracker telemetry and alerts."""
    event_type: str = "generic_event"
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    camera_id: str = "cam_01"
    snapshot_base64: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self, include_snapshot: bool = True) -> Dict[str, Any]:
        """Convert event to serializable dictionary."""
        d = asdict(self)
        if not include_snapshot:
            d.pop("snapshot_base64", None)
        return d

    def to_json(self, include_snapshot: bool = True, indent: Optional[int] = None) -> str:
        """Convert event to JSON string."""
        return json.dumps(self.to_dict(include_snapshot=include_snapshot), default=str, indent=indent)


@dataclass
class ZoneEvent(BaseEvent):
    """Event emitted when a tracked entity enters, dwells, or exits a ZoneROI."""
    event_type: str = "zone_event"
    zone_id: str = ""
    track_id: int = 0
    action: str = "enter"  # 'enter', 'exit', 'dwell'
    dwell_time: float = 0.0
    centroid: Optional[Tuple[float, float]] = None
    bbox: Optional[Tuple[int, int, int, int]] = None
    entity_id: Optional[int] = None
    entity_name: Optional[str] = None
    entity_category: Optional[str] = None

    def __post_init__(self):
        if self.event_type in ("zone_event", "generic_event", "") or not self.event_type:
            self.event_type = f"zone_{self.action}"


@dataclass
class TripwireCrossEvent(BaseEvent):
    """Event emitted when an entity traverses a virtual directional tripwire."""
    event_type: str = "tripwire_cross"
    tripwire_id: str = ""
    track_id: int = 0
    direction: str = "in"  # 'in', 'out', 'A_to_B', 'B_to_A'
    pt1: Optional[Tuple[float, float]] = None
    pt2: Optional[Tuple[float, float]] = None
    centroid: Optional[Tuple[float, float]] = None
    entity_id: Optional[int] = None
    entity_name: Optional[str] = None
    entity_category: Optional[str] = None


@dataclass
class IntrusionAlert(BaseEvent):
    """Security alert emitted on unauthorized zone access or tripwire breach."""
    event_type: str = "intrusion_alert"
    zone_id: str = ""
    track_id: int = 0
    label: str = "person"
    entity_id: Optional[int] = None
    entity_name: Optional[str] = None
    entity_category: Optional[str] = None
    severity: str = "critical"  # "info", "warning", "critical"
    message: str = ""
    dwell_time: float = 0.0


@dataclass
class OccupancyThresholdEvent(BaseEvent):
    """Alert emitted when a zone exceeds or clears its capacity threshold."""
    event_type: str = "occupancy_threshold"
    zone_id: str = ""
    current_occupancy: int = 0
    threshold: int = 0
    breach_type: str = "exceeded"  # "exceeded", "cleared"
    severity: str = "warning"
    message: str = ""


@dataclass
class EntityIdentifiedEvent(BaseEvent):
    """Emitted when visual Re-ID matches a track against the canonical gallery."""
    event_type: str = "entity_identified"
    track_id: int = 0
    entity_id: int = 0
    name: str = ""
    category: str = "general"
    similarity: float = 0.0
    zone_id: Optional[str] = None
    severity: str = "info"
    message: str = ""


@dataclass
class RestrictedEntityAlert(BaseEvent):
    """Alert emitted when a restricted/blacklisted entity is recognized."""
    event_type: str = "restricted_entity_alert"
    zone_id: Optional[str] = None
    track_id: int = 0
    entity_id: Optional[int] = None
    name: str = ""
    category: str = "restricted"
    severity: str = "critical"
    message: str = ""


@dataclass
class RSACViolationEvent(BaseEvent):
    """Alert emitted when an entity breaches Role-Based Spatial Access Control permissions."""
    event_type: str = "rsac_violation"
    zone_id: str = ""
    track_id: int = 0
    entity_id: Optional[int] = None
    entity_name: Optional[str] = None
    entity_category: Optional[str] = None
    reason: str = "Unauthorized category or schedule violation"
    severity: str = "warning"  # "warning", "critical"
    message: str = ""


@dataclass
class PetActivityEvent(BaseEvent):
    """Informational event emitted on whitelisted domestic pet presence (suppressing alarms)."""
    event_type: str = "pet_activity"
    zone_id: str = ""
    track_id: int = 0
    entity_id: Optional[int] = None
    entity_name: Optional[str] = "Pet"
    entity_category: str = "pet"
    severity: str = "info"
    message: str = "Harmless domestic pet activity recorded; perimeter alarm suppressed"


@dataclass
class ReviewItemQueuedEvent(BaseEvent):
    """Notification emitted when an ambiguous detection is queued into Review & Learn."""
    event_type: str = "review_item_queued"
    review_id: int = 0
    track_id: int = 0
    crop_path: str = ""
    suggested_entity_id: Optional[int] = None
    suggested_name: str = ""
    suggested_category: str = ""
    similarity: float = 0.0
    severity: str = "info"

