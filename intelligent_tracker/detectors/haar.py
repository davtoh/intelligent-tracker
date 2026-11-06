"""Haar Cascade detection, multi-angle invariant cascades, and affine perspective warps."""

import os
from typing import Optional
import cv2
import numpy as np

from intelligent_tracker.core import Agent, TailItem
from intelligent_tracker.detectors.base import Detection, DetectorFactory
from intelligent_tracker.detectors.core_detector import Detector

SCRIPT_PATH = os.path.dirname(os.path.realpath(__file__))
LOCAL_HAARCASCADES = os.path.abspath(os.path.join(SCRIPT_PATH, "..", "haarcascades"))

if (
    hasattr(cv2, "data")
    and hasattr(cv2.data, "haarcascades")
    and os.path.isfile(
        os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
    )
):
    DETECTOR_PATH = cv2.data.haarcascades
else:
    DETECTOR_PATH = LOCAL_HAARCASCADES

face_cascade = cv2.CascadeClassifier(
    os.path.abspath(
        os.path.join(DETECTOR_PATH, "haarcascade_frontalface_default.xml")
    )
)
eye_cascade = cv2.CascadeClassifier(
    os.path.abspath(os.path.join(DETECTOR_PATH, "haarcascade_eye.xml"))
)


def affine(phi: float, img: np.ndarray):
    """Increase robustness to descriptors by calculating other invariant perspectives to image.

    :param phi: rotation of image (in degrees)
    :param img: image to find Affine transforms
    :return: skew_img, Ai (invert Affine Transform)
    """
    h, w = img.shape[:2]
    A = np.float32([[1, 0, 0], [0, 1, 0]])
    if phi != 0.0:
        phi_rad = np.deg2rad(phi)
        s, c = np.sin(phi_rad), np.cos(phi_rad)
        A = np.float32([[c, -s], [s, c]])
        corners = [[0, 0], [w, 0], [w, h], [0, h]]
        tcorners = np.int32(np.dot(corners, A.T))
        x, y, w, h = cv2.boundingRect(tcorners.reshape(1, -1, 2))
        A = np.hstack([A, [[-x], [-y]]])
        img = cv2.warpAffine(
            img, A, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
        )
        h, w = img.shape[:2]
    Ai = cv2.invertAffineTransform(A)
    return img, Ai


class InvariantCascade:
    """Multi-perspective affine cascade generator and bounding box reconstruction."""

    def __init__(self, angles: Optional[list[float]] = None):
        self.angles = angles or []

    def transformations(self, frame: np.ndarray):
        """Yield inverted affine transform matrix, angle, and warped frame."""
        for angle in self.angles:
            img, Ai = affine(angle, frame)
            yield Ai, angle, img

    def reconstruct(self, Ai: np.ndarray, angle: float, bbox: tuple[int, int, int, int]):
        """Reconstruct canonical bounding box from inverted affine transform."""
        x, y, sz_x, sz_y = bbox
        xn, yn = np.dot(Ai, (x, y, 1))
        return (
            Agent.get_rotated_box_from_bounding_box((xn, yn, sz_x, sz_y))[:-1]
            + (-angle,)
        )


class HaarCascadeDetector(Detector):
    """Haar cascade classifier wrapped as a concrete BaseDetector subclass."""

    def __init__(
        self,
        cascade_path: Optional[str] = None,
        scale_factor: float = 1.3,
        min_neighbors: int = 5,
        min_size: tuple[int, int] = (30, 30),
        max_size: Optional[tuple[int, int]] = None,
        label: str = "haar_object",
    ):
        super().__init__()
        if cascade_path is None:
            cascade_path = os.path.abspath(
                os.path.join(DETECTOR_PATH, "haarcascade_frontalface_default.xml")
            )
        elif not os.path.isabs(cascade_path):
            p = os.path.abspath(os.path.join(DETECTOR_PATH, cascade_path))
            if os.path.isfile(p):
                cascade_path = p
        self.cascade_path = cascade_path
        self.cascade = cv2.CascadeClassifier(cascade_path)
        self.scale_factor = scale_factor
        self.min_neighbors = min_neighbors
        self.min_size = min_size
        self.max_size = max_size
        self.label = label

    def detect(self, frame):
        if frame is None or getattr(frame, "size", 0) == 0 or self.cascade.empty():
            return []
        if len(frame.shape) == 3 and frame.shape[2] == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        elif len(frame.shape) == 3 and frame.shape[2] == 4:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
        else:
            gray = frame

        kwargs = {"scaleFactor": self.scale_factor, "minNeighbors": self.min_neighbors}
        if self.min_size:
            kwargs["minSize"] = self.min_size
        if self.max_size:
            kwargs["maxSize"] = self.max_size

        rects = self.cascade.detectMultiScale(gray, **kwargs)
        if len(rects) == 0:
            return []

        return [
            Detection(
                bbox=tuple(map(int, r)),
                class_id=0,
                confidence=1.0,
                label=self.label,
            )
            for r in rects
        ]

    def detect_raw_objects(self, frame, mask=None):
        detections = self.detect(frame)
        return [TailItem(bbox=d.bbox) for d in detections]


class EyeDetector(HaarCascadeDetector):
    """Eye detector based on Haar cascade classifier."""

    def __init__(self, **kwargs):
        eye_xml = os.path.abspath(os.path.join(DETECTOR_PATH, "haarcascade_eye.xml"))
        kwargs.setdefault("cascade_path", eye_xml)
        kwargs.setdefault("label", "eye")
        super().__init__(**kwargs)

    def detect_raw_objects(self, frame, mask=None):
        min_size = 0.1
        max_size = 0.5
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        eyes = eye_cascade.detectMultiScale(
            gray,
            minSize=(int(w * min_size), int(h * min_size)),
            maxSize=(int(w * max_size), int(h * max_size)),
            flags=cv2.CASCADE_SCALE_IMAGE,
        )
        return [TailItem(bbox=bbox) for bbox in eyes]


class FaceDetector(HaarCascadeDetector):
    """Frontal face detector supporting multi-angle rotational invariant cascades."""

    def __init__(self, **kwargs):
        face_xml = os.path.abspath(
            os.path.join(DETECTOR_PATH, "haarcascade_frontalface_default.xml")
        )
        kwargs.setdefault("cascade_path", face_xml)
        kwargs.setdefault("label", "face")
        super().__init__(**kwargs)

    def detect_raw_objects(self, frame, mask=None):
        min_scale = 0.05
        h, w = frame.shape[:2]
        min_size = (int(w * min_scale), int(h * min_scale))
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        normal = []
        to_rotate = InvariantCascade([0, 20, 40, -20, -40])
        for M, i, f in to_rotate.transformations(gray):
            faces = face_cascade.detectMultiScale(
                f,
                minSize=min_size,
                scaleFactor=1.3,
                minNeighbors=5,
                flags=cv2.CASCADE_SCALE_IMAGE,
            )
            normal.extend(
                [TailItem(rbox=to_rotate.reconstruct(M, i, bbox)) for bbox in faces]
            )
        return normal


Detector.register_detector(HaarCascadeDetector)
Detector.register_detector(EyeDetector)
Detector.register_detector(FaceDetector)

DetectorFactory.register("haar", HaarCascadeDetector)
DetectorFactory.register("cascade", HaarCascadeDetector)
DetectorFactory.register("haarcascade", HaarCascadeDetector)
DetectorFactory.register("haarcascadedetector", HaarCascadeDetector)
DetectorFactory.register("face", FaceDetector)
DetectorFactory.register("facedetector", FaceDetector)
DetectorFactory.register("eye", EyeDetector)
DetectorFactory.register("eyedetector", EyeDetector)

