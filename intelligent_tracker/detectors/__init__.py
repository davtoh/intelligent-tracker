"""Edge AI object detection subsystem: neural ONNX models, Haar cascades, and tracking primitives.

Re-exports 100% of public detector classes, factory registry, and object tracking
representations to preserve complete backward compatibility across all modules and tests.
"""

from intelligent_tracker.detectors.base import (
    BaseDetector,
    Detection,
    DetectorFactory,
)
from intelligent_tracker.detectors.coco_classes import COCO_CLASSES
from intelligent_tracker.detectors.color_detector import ColorDetector
from intelligent_tracker.detectors.core_detector import Detector
from intelligent_tracker.detectors.edgetpu_detector import EdgeTpuDetector
from intelligent_tracker.detectors.haar import (
    DETECTOR_PATH,
    LOCAL_HAARCASCADES,
    SCRIPT_PATH,
    EyeDetector,
    FaceDetector,
    HaarCascadeDetector,
    InvariantCascade,
    affine,
    eye_cascade,
    face_cascade,
)
from intelligent_tracker.detectors.legacy_detectors import (
    MovementDetector,
    ObjectDetector,
    PeopleDetector,
)
from intelligent_tracker.detectors.mock_detector import MockDetector
from intelligent_tracker.detectors.objects import Object
from intelligent_tracker.detectors.onnx_detector import (
    OnnxDetector,
    letterbox,
    nms_numpy,
)
from intelligent_tracker.detectors.yunet import YuNetFaceDetector

__author__ = "David Toro"
__license__ = "GPL"
__maintainer__ = "David Toro"
__email__ = "davsamirtor@gmail.com"

__all__ = [
    "Detection",
    "BaseDetector",
    "Detector",
    "DetectorFactory",
    "HaarCascadeDetector",
    "FaceDetector",
    "YuNetFaceDetector",
    "EyeDetector",
    "ColorDetector",
    "MockDetector",
    "OnnxDetector",
    "EdgeTpuDetector",
    "COCO_CLASSES",
    "Object",
    "PeopleDetector",
    "ObjectDetector",
    "MovementDetector",
    "InvariantCascade",
    "affine",
    "letterbox",
    "nms_numpy",
    "DETECTOR_PATH",
    "LOCAL_HAARCASCADES",
    "SCRIPT_PATH",
    "face_cascade",
    "eye_cascade",
]

