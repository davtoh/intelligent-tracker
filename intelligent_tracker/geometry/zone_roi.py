"""Polygonal Region of Interest (ROI) for occupancy counting and dwell monitoring."""

import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np


@dataclass
class ZoneEvent:
    """Event emitted when a tracked entity interacts with a ZoneROI.

    event_type: 'enter', 'exit', or 'dwell'
    """
    zone_id: str
    track_id: int
    event_type: str  # 'enter', 'exit', 'dwell'
    timestamp: float
    dwell_time: float = 0.0
    centroid: Optional[Tuple[float, float]] = None
    bbox: Optional[Tuple[int, int, int, int]] = None

    @property
    def action(self) -> str:
        """Alias for event_type ('enter', 'exit', 'dwell') for cross-subsystem event compatibility."""
        return self.event_type

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["action"] = self.event_type
        return d


class ZoneROI:
    """Polygonal Region of Interest (ROI) for occupancy counting and dwell time monitoring.

    Parameters:
    -----------
    polygon : Union[List[Tuple[float, float]], np.ndarray]
        List of vertices [(x, y), ...] defining the polygonal zone boundary.
    name : str
        Unique identifier for the zone (e.g. 'checkout_queue', 'aisle_3')
    dwell_threshold : float
        Seconds of continuous presence before emitting a 'dwell' event.
    color : Tuple[int, int, int]
        BGR color for boundary and translucent fill.
    capacity_limit : Optional[int]
        Maximum allowed occupancy before threshold breach flag is set.
    """

    def __init__(
        self,
        polygon,
        name="zone_1",
        dwell_threshold=5.0,
        color=(0, 200, 100),
        capacity_limit=None,
    ):
        self.name = str(name)
        self.dwell_threshold = float(dwell_threshold)
        self.color = color
        self.capacity_limit = int(capacity_limit) if capacity_limit is not None else None
        self._threshold_breached = False

        # Normalize polygon points to NumPy array of shape (N, 1, 2) int32 for OpenCV
        pts = [[float(pt[0]), float(pt[1])] for pt in polygon]
        self.points = np.array(pts, dtype=np.float32)
        self.contour = np.array(pts, dtype=np.int32).reshape((-1, 1, 2))

        # Occupant tracking: track_id -> dict(entry_time=float, last_seen=float, dwell_emitted=bool)
        self.current_occupants: Dict[int, Dict[str, Any]] = {}
        self.total_entries = 0
        self.total_exits = 0
        self.max_occupancy = 0
        self.event_history: List[ZoneEvent] = []

    def contains_point(self, pt) -> bool:
        """Vectorized point-in-polygon containment test via cv2.pointPolygonTest."""
        p = (float(pt[0]), float(pt[1]))
        return cv2.pointPolygonTest(self.contour, p, False) >= 0

    @property
    def polygon(self) -> np.ndarray:
        """Array of vertices defining the zone polygon."""
        return self.points

    @property
    def occupancy(self) -> int:
        """Current number of active occupants inside the zone."""
        return len(self.current_occupants)

    def update(self, tracks, timestamp: Optional[float] = None) -> List[ZoneEvent]:
        """Update zone state with active tracked entities.

        :param tracks: Dict[track_id, Track] or Dict[track_id, centroid] or List[Track]
        :param timestamp: Current frame timestamp
        :return: List of ZoneEvent instances generated on this frame
        """
        now = timestamp if timestamp is not None else time.time()
        events: List[ZoneEvent] = []

        active_items = self._extract_active_track_items(tracks)
        present_tids = set()

        for tid, (centroid, bbox) in active_items.items():
            if centroid is None:
                continue

            if self.contains_point(centroid):
                present_tids.add(tid)
                self._handle_occupant_update(tid, centroid, bbox, now, events)

        self._handle_departed_occupants(present_tids, now, events)
        self.max_occupancy = max(self.max_occupancy, len(self.current_occupants))
        return events

    def _extract_active_track_items(self, tracks):
        active_items = {}
        if isinstance(tracks, dict):
            for tid, val in tracks.items():
                if hasattr(val, "centroid"):
                    active_items[int(tid)] = (val.centroid, getattr(val, "bbox", None))
                elif isinstance(val, (tuple, list)) and len(val) >= 2:
                    active_items[int(tid)] = (val[:2], None)
        elif isinstance(tracks, (list, tuple)):
            for trk in tracks:
                tid = getattr(trk, "track_id", id(trk))
                centroid = getattr(trk, "centroid", None)
                bbox = getattr(trk, "bbox", None)
                if centroid is not None:
                    active_items[int(tid)] = (centroid, bbox)
        return active_items

    def _handle_occupant_update(self, tid, centroid, bbox, now, events):
        if tid not in self.current_occupants:
            self.current_occupants[tid] = {
                "entry_time": now,
                "last_seen": now,
                "dwell_emitted": False,
                "centroid": centroid,
                "bbox": bbox,
            }
            self.total_entries += 1
            event = ZoneEvent(
                zone_id=self.name,
                track_id=tid,
                event_type="enter",
                timestamp=now,
                dwell_time=0.0,
                centroid=centroid,
                bbox=bbox,
            )
            events.append(event)
            self.event_history.append(event)
        else:
            occ = self.current_occupants[tid]
            occ["last_seen"] = now
            occ["centroid"] = centroid
            occ["bbox"] = bbox
            dwell_dur = now - occ["entry_time"]

            if dwell_dur >= self.dwell_threshold and not occ["dwell_emitted"]:
                occ["dwell_emitted"] = True
                event = ZoneEvent(
                    zone_id=self.name,
                    track_id=tid,
                    event_type="dwell",
                    timestamp=now,
                    dwell_time=dwell_dur,
                    centroid=centroid,
                    bbox=bbox,
                )
                events.append(event)
                self.event_history.append(event)

    def _handle_departed_occupants(self, present_tids, now, events):
        departed_tids = [tid for tid in self.current_occupants if tid not in present_tids]
        for tid in departed_tids:
            occ = self.current_occupants.pop(tid)
            dwell_dur = max(0.0, now - occ["entry_time"])
            self.total_exits += 1
            event = ZoneEvent(
                zone_id=self.name,
                track_id=tid,
                event_type="exit",
                timestamp=now,
                dwell_time=dwell_dur,
                centroid=occ.get("centroid"),
                bbox=occ.get("bbox"),
            )
            events.append(event)
            self.event_history.append(event)

    def draw(self, frame: np.ndarray, alpha=0.25, color=None, show_label=True) -> np.ndarray:
        """Draw translucent polygon overlay and occupancy badge onto frame."""
        col = color or self.color

        overlay = frame.copy()
        cv2.fillPoly(overlay, [self.contour], col)
        cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0, frame)

        cv2.polylines(frame, [self.contour], True, col, 2, cv2.LINE_AA)

        if show_label:
            min_y_idx = np.argmin(self.points[:, 1])
            lx = int(self.points[min_y_idx, 0])
            ly = max(20, int(self.points[min_y_idx, 1]) - 8)

            label = f"{self.name}: {len(self.current_occupants)} occ"
            (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(frame, (lx, ly - h - 4), (lx + w + 8, ly + 4), (30, 30, 30), -1)
            cv2.putText(frame, label, (lx + 4, ly), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1, cv2.LINE_AA)

        return frame

