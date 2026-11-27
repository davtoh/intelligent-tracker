"""Mock detector for headless testing, CI simulation, and deterministic verification."""

from typing import Any, Optional

import numpy as np

from intelligent_tracker.core import TailItem
from intelligent_tracker.detectors.base import Detection, DetectorFactory
from intelligent_tracker.detectors.core_detector import Detector


def _extract_color_box(
    mask: np.ndarray,
    min_pixels: int = 200,
    min_span: int = 15,
) -> tuple[int, int, int, int] | None:
    """Extract tight bounding box from a boolean pixel mask, ignoring thin text strokes."""
    if int(mask.sum()) < min_pixels:
        return None
    row_hits = mask.sum(axis=1) >= min_span
    col_hits = mask.sum(axis=0) >= min_span
    if not row_hits.any() or not col_hits.any():
        return None
    ys = np.flatnonzero(row_hits)
    xs = np.flatnonzero(col_hits)
    return (int(xs[0]), int(ys[0]), int(xs[-1] - xs[0] + 1), int(ys[-1] - ys[0] + 1))


def _detect_synthetic_targets(frame: Any) -> list[tuple[int, int, int, int]]:
    """Detect SyntheticFrameGenerator P1 (amber) and P2 (blue) target boxes if present."""
    if frame is None or not hasattr(frame, "ndim") or frame.ndim != 3 or frame.shape[2] < 3:
        return []
    b, g, r = frame[:, :, 0], frame[:, :, 1], frame[:, :, 2]
    p1_mask = (r >= 180) & (g >= 140) & (b <= 80)
    p2_mask = (b >= 180) & (g <= 150) & (r <= 150)
    boxes: list[tuple[int, int, int, int]] = []
    for mask in (p1_mask, p2_mask):
        box = _extract_color_box(mask)
        if box is not None:
            boxes.append(box)
    return boxes


class MockDetector(Detector):
    """Mock detector for CI, unit testing, and headless execution.

    Generates synthetic or deterministic bounding boxes without requiring hardware or models.
    """

    def __init__(
        self,
        boxes: Optional[list[tuple[int, int, int, int]]] = None,
        class_id: int = 0,
        confidence: float = 0.95,
        label: str = "mock_person",
        step: int = 5,
        width: int = 640,
        height: int = 480,
    ):
        super().__init__()
        self.preset_boxes = boxes
        self.class_id = class_id
        self.confidence = float(confidence)
        self.label = str(label)
        self.step = int(step)
        self.width = int(width)
        self.height = int(height)
        self._frame_count = 0

    def detect(self, frame=None):
        if frame is not None and hasattr(frame, "shape"):
            h, w = frame.shape[:2]
        else:
            w, h = self.width, self.height

        if self.preset_boxes is not None:
            boxes = self.preset_boxes
        else:
            synth_boxes = _detect_synthetic_targets(frame)
            if synth_boxes:
                boxes = synth_boxes
            else:
                bw, bh = 60, 120
                max_x = max(10, w - bw - 10)
                max_y = max(10, h - bh - 10)
                x = int(50 + (self._frame_count * self.step)) % max_x
                y = int(50 + (self._frame_count * (self.step // 2 + 1))) % max_y
                boxes = [(x, y, bw, bh)]

        self._frame_count += 1
        return [
            Detection(
                bbox=tuple(map(int, b)),
                class_id=self.class_id,
                confidence=self.confidence,
                label=self.label,
            )
            for b in boxes
        ]

    def detect_raw_objects(self, frame, mask=None):
        detections = self.detect(frame)
        return [TailItem(bbox=d.bbox) for d in detections]


Detector.register_detector(MockDetector)
DetectorFactory.register("mock", MockDetector)

