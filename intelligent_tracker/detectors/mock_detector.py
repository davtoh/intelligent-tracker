"""Mock detector for headless testing, CI simulation, and deterministic verification."""

from typing import Optional

from intelligent_tracker.core import TailItem
from intelligent_tracker.detectors.base import Detection, DetectorFactory
from intelligent_tracker.detectors.core_detector import Detector


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

