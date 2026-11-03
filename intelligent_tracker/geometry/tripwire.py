"""Bidirectional virtual tripwires and crossing detection events."""

import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from intelligent_tracker.geometry.primitives import segments_intersect


@dataclass
class TripwireEvent:
    """Event emitted when a tracked entity crosses a virtual Tripwire.

    direction: 'in' (A_to_B) or 'out' (B_to_A)
    """
    tripwire_id: str
    track_id: int
    direction: str  # 'in', 'out', 'A_to_B', 'B_to_A'
    timestamp: float
    pt1: Tuple[float, float]
    pt2: Tuple[float, float]
    centroid: Optional[Tuple[float, float]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class Tripwire:
    """Bidirectional virtual tripwire for person / vehicle crossing detection.

    Parameters:
    -----------
    line_segment : Tuple[Tuple[float, float], Tuple[float, float]] or List
        Line coordinates ((x1, y1), (x2, y2))
    name : str
        Unique identifier for the tripwire (e.g. 'store_entrance')
    bidirectional : bool
        If True, tracks crossings in both directions ('in' / 'out')
    color : Tuple[int, int, int]
        BGR color for visualization
    """

    def __init__(
        self,
        line_segment,
        name="tripwire_1",
        bidirectional=True,
        color=(0, 255, 255),
    ):
        pt1, pt2 = line_segment
        self.pt1 = (float(pt1[0]), float(pt1[1]))
        self.pt2 = (float(pt2[0]), float(pt2[1]))
        self.name = str(name)
        self.bidirectional = bool(bidirectional)
        self.color = color

        # Counters
        self.total_in = 0
        self.total_out = 0
        self.last_crossed_time = None
        self.event_history: List[TripwireEvent] = []

        # Vector representation for direction determination
        self.dx = self.pt2[0] - self.pt1[0]
        self.dy = self.pt2[1] - self.pt1[1]

    @property
    def line_segment(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        return (self.pt1, self.pt2)

    @property
    def in_count(self) -> int:
        return self.total_in

    @property
    def out_count(self) -> int:
        return self.total_out

    def check_crossing(
        self,
        track_id: int,
        prev_centroid: Optional[Tuple[float, float]],
        curr_centroid: Optional[Tuple[float, float]],
        timestamp: Optional[float] = None,
    ) -> Optional[TripwireEvent]:
        """Check if trajectory between prev_centroid and curr_centroid crossed the tripwire.

        :param track_id: Identifier of the tracked object
        :param prev_centroid: (x, y) coordinates on previous frame
        :param curr_centroid: (x, y) coordinates on current frame
        :param timestamp: Event timestamp (defaults to current time)
        :return: TripwireEvent if crossed, else None
        """
        if prev_centroid is None or curr_centroid is None:
            return None

        p1 = (float(prev_centroid[0]), float(prev_centroid[1]))
        p2 = (float(curr_centroid[0]), float(curr_centroid[1]))

        if not segments_intersect(self.pt1, self.pt2, p1, p2):
            return None

        # Determine crossing direction relative to tripwire vector (pt1 -> pt2)
        # Using 2D cross product: dx * my - dy * mx
        mx = p2[0] - p1[0]
        my = p2[1] - p1[1]
        cross_prod = self.dx * my - self.dy * mx

        if cross_prod > 0:
            direction = "in"
            self.total_in += 1
        else:
            direction = "out"
            self.total_out += 1

        ts = timestamp if timestamp is not None else time.time()
        self.last_crossed_time = ts

        event = TripwireEvent(
            tripwire_id=self.name,
            track_id=int(track_id),
            direction=direction,
            timestamp=ts,
            pt1=self.pt1,
            pt2=self.pt2,
            centroid=p2,
        )
        self.event_history.append(event)
        return event

    def draw(self, frame: np.ndarray, color=None, thickness=2, show_counts=True) -> np.ndarray:
        """Draw tripwire line and counter labels onto an image frame."""
        col = color or self.color
        p1 = (int(self.pt1[0]), int(self.pt1[1]))
        p2 = (int(self.pt2[0]), int(self.pt2[1]))

        # Line
        cv2.line(frame, p1, p2, col, thickness, cv2.LINE_AA)

        # Endpoints
        cv2.circle(frame, p1, 4, (0, 0, 255), -1)
        cv2.circle(frame, p2, 4, (255, 0, 0), -1)

        # Direction indicator arrow in the middle
        mid_x = int((p1[0] + p2[0]) / 2)
        mid_y = int((p1[1] + p2[1]) / 2)

        # Normal vector pointing 'in'
        length = np.hypot(self.dx, self.dy)
        if length > 0:
            nx = int(-self.dy / length * 15)
            ny = int(self.dx / length * 15)
            cv2.arrowedLine(frame, (mid_x, mid_y), (mid_x + nx, mid_y + ny), col, 1, tipLength=0.3)

        if show_counts:
            label = f"{self.name}: IN {self.total_in} | OUT {self.total_out}"
            cv2.putText(
                frame,
                label,
                (mid_x - 40, max(20, mid_y - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )
        return frame

