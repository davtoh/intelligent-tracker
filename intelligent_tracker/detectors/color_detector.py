"""Color-based object detector filtering HSV color intervals."""

import cv2
import numpy as np

from intelligent_tracker.array_utils import norm_range
from intelligent_tracker.core import Point
from intelligent_tracker.detectors.base import Detection, DetectorFactory
from intelligent_tracker.detectors.core_detector import Detector


class ColorDetector(Detector):
    """Detect objects by color range thresholding in HSV color space."""

    def __init__(self, color_lower, color_upper):
        super().__init__()
        self.color_lower = norm_range(color_lower)
        self.color_upper = norm_range(color_upper)

    def get_HSV_color_range(self):
        """Return lower and upper HSV ranges."""
        return self.color_lower, self.color_upper

    def set_HSV_color_range(self, color_lower=None, color_upper=None):
        """Set lower and upper HSV ranges."""
        if color_lower:
            self.color_lower = norm_range(color_lower)
        if color_upper:
            self.color_upper = norm_range(color_upper)

    def get_HSV_color(self):
        """Return median HSV color between lower and upper bounds."""
        lower, upper = self.get_HSV_color_range()
        lower, upper = np.array(lower), np.array(upper)
        return (lower + upper) / 2

    def get_BGR_color(self):
        """Return median BGR color corresponding to current HSV color range."""
        return cv2.cvtColor(
            np.array([[self.get_HSV_color()]], np.uint8), cv2.COLOR_BGR2HSV
        )[0, 0]

    def detect_raw_objects(self, frame, mask=None):
        """Extract contours matching the target HSV color range."""
        blurred = cv2.GaussianBlur(frame, (11, 11), 0)
        hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
        mk = cv2.inRange(hsv, self.color_lower, self.color_upper)
        mk = cv2.erode(mk, None, iterations=2)
        mk = cv2.dilate(mk, None, iterations=2)
        cnts = cv2.findContours(mk, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[-2]
        return cnts

    def filter_bad_raw_objects(self, tail_objects, frame, mask=None):
        """Filter candidate objects that fail minimum area thresholds."""
        ignore = False
        ignore_z = 0.001
        z_must_be = frame.shape[0] * frame.shape[1] * ignore_z
        bad_objects = []
        for ti in tail_objects:
            M = cv2.moments(ti.cnt)
            z = M["m00"]
            x, y = int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"])
            ti._pt = Point(*(x, y, z))
            if ignore and z < z_must_be:
                bad_objects.append(ti)
        return bad_objects

    def detect(self, frame):
        """BaseDetector contract: detect color contours in frame."""
        cnts = self.detect_raw_objects(frame)
        if not cnts:
            return []
        detections = []
        for c in cnts:
            x, y, w, h = cv2.boundingRect(c)
            detections.append(
                Detection(
                    bbox=(int(x), int(y), int(w), int(h)),
                    class_id=0,
                    confidence=1.0,
                    label="color_object",
                )
            )
        return detections

    @classmethod
    def __json_deco__(cls, data):
        return cls(data[0], data[1])

    def __json_enco__(self):
        return self.get_HSV_color_range()


Detector.register_detector(ColorDetector)
DetectorFactory.register("color", ColorDetector)
DetectorFactory.register("colordetector", ColorDetector)

