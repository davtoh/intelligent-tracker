"""High-fidelity synthetic video frame generator for automated testing and CI.

Generates video frames with moving targets that cross virtual tripwires
and dwell in predefined ROI zones without requiring physical camera hardware.
"""

from typing import Optional, Tuple
import cv2
import numpy as np


class SyntheticFrameGenerator:
    """High-fidelity synthetic frame generator for automated testing and CI."""

    def __init__(self, width: int = 640, height: int = 480, fps: int = 30):
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.frame_idx = 0
        self._opened = True

    def isOpened(self) -> bool:
        """Return True if synthetic capture source is active."""
        return self._opened

    def open(self, *args, **kwargs) -> bool:
        """Reopen synthetic frame generator."""
        self._opened = True
        return True

    def _render_background(self) -> np.ndarray:
        """Render gradient retail floor simulation background with grid lines."""
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        frame[:, :, 0] = (np.linspace(30, 70, self.height)[:, None]).astype(np.uint8)
        frame[:, :, 1] = (np.linspace(35, 75, self.height)[:, None]).astype(np.uint8)
        frame[:, :, 2] = (np.linspace(40, 80, self.height)[:, None]).astype(np.uint8)

        for y in range(0, self.height, 40):
            cv2.line(frame, (0, y), (self.width, y), (55, 60, 65), 1)
        for x in range(0, self.width, 40):
            cv2.line(frame, (x, 0), (x, self.height), (55, 60, 65), 1)
        return frame

    def _render_targets(self, frame: np.ndarray, t: float) -> None:
        """Render simulated moving targets P1 (tripwire crosser) and P2 (zone dweller)."""
        # Target 1: Moves back and forth horizontally across the center (crosses tripwires)
        cycle_x = (np.sin(t * (2.0 * np.pi / 8.0)) + 1.0) / 2.0
        x1 = int(60 + cycle_x * (self.width - 160))
        y1 = int(self.height * 0.45 + np.sin(t * 1.5) * 30)
        cv2.rectangle(frame, (x1, y1), (x1 + 40, y1 + 90), (0, 200, 255), -1)
        cv2.putText(frame, "P1", (x1 + 10, y1 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1)

        # Target 2: Enters, dwells in upper-right zone, and leaves
        cycle_y = (np.cos(t * (2.0 * np.pi / 12.0)) + 1.0) / 2.0
        x2 = int(self.width * 0.65 + np.sin(t * 0.8) * 40)
        y2 = int(60 + cycle_y * (self.height - 180))
        cv2.rectangle(frame, (x2, y2), (x2 + 36, y2 + 80), (255, 100, 100), -1)
        cv2.putText(frame, "P2", (x2 + 8, y2 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 100, 100), 1)

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Advance time step and return synthetic simulated video frame."""
        if not self._opened:
            return False, None

        self.frame_idx += 1
        t = self.frame_idx / float(self.fps)

        frame = self._render_background()
        self._render_targets(frame, t)

        timestamp_str = f"FRAME: {self.frame_idx:06d} | T: {t:.2f}s"
        cv2.putText(frame, timestamp_str, (15, self.height - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 160, 160), 1)

        return True, frame

    def release(self) -> None:
        """Mark generator closed."""
        self._opened = False


__all__ = ["SyntheticFrameGenerator"]

