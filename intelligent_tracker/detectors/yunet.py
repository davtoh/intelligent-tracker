"""ONNX-based YuNet face detector utilizing OpenCV's cv2.FaceDetectorYN."""

import os
from typing import Optional
import cv2
import numpy as np

from intelligent_tracker.detectors.base import BaseDetector, Detection, DetectorFactory
from intelligent_tracker.detectors.haar import FaceDetector


class YuNetFaceDetector(BaseDetector):
    """ONNX-based YuNet face detector utilizing OpenCV's cv2.FaceDetectorYN.

    Provides sub-millisecond, highly robust face localization with facial landmark awareness.
    Automatically cascades to HaarCascadeDetector if the ONNX model file or FaceDetectorYN
    is unavailable in the runtime environment.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        conf_threshold: float = 0.6,
        nms_threshold: float = 0.3,
        top_k: int = 5000,
        **kwargs,
    ):
        super().__init__()
        self.conf_threshold = float(conf_threshold)
        self.nms_threshold = float(nms_threshold)
        self.top_k = int(top_k)
        self._detector = None
        self._fallback = None

        resolved = self._resolve_model_path(model_path)
        if resolved and hasattr(cv2, "FaceDetectorYN"):
            try:
                self._detector = cv2.FaceDetectorYN.create(
                    model=resolved,
                    config="",
                    input_size=(320, 320),
                    score_threshold=self.conf_threshold,
                    nms_threshold=self.nms_threshold,
                    top_k=self.top_k,
                )
                self.model_path = resolved
            except Exception:
                self._detector = None

        if self._detector is None:
            self._fallback = FaceDetector(**kwargs)
            self.model_path = getattr(self._fallback, "cascade_path", "haar_fallback")

    @staticmethod
    def _resolve_model_path(path: Optional[str]) -> Optional[str]:
        """Search filesystem candidates for YuNet ONNX model weights."""
        if path and os.path.isfile(path):
            return os.path.abspath(path)
        script_dir = os.path.dirname(os.path.realpath(__file__))
        candidates = [
            "models/face_detection_yunet_2023mar.onnx",
            "models/yunet.onnx",
            os.path.join(script_dir, "..", "..", "models", "face_detection_yunet_2023mar.onnx"),
            os.path.join(script_dir, "..", "..", "models", "yunet.onnx"),
        ]
        for c in candidates:
            if c and os.path.isfile(c):
                return os.path.abspath(c)
        return None

    def _parse_face_detections(self, faces: np.ndarray, w: int, h: int) -> list[Detection]:
        """Convert cv2.FaceDetectorYN output rows to clamped Detection instances."""
        results = []
        for face in faces:
            bx, by, bw, bh = int(face[0]), int(face[1]), int(face[2]), int(face[3])
            score = float(face[-1])
            bx = max(0, min(bx, w - 1))
            by = max(0, min(by, h - 1))
            bw = max(1, min(bw, w - bx))
            bh = max(1, min(bh, h - by))
            results.append(
                Detection(
                    bbox=(bx, by, bw, bh),
                    class_id=0,
                    confidence=score,
                    label="face",
                )
            )
        return results

    def detect(self, frame: np.ndarray) -> list[Detection]:
        """Detect human faces in frame using YuNet or Haar fallback."""
        if frame is None or getattr(frame, "size", 0) == 0:
            return []

        if self._detector is not None:
            h, w = frame.shape[:2]
            if w < 2 or h < 2:
                return []
            self._detector.setInputSize((w, h))
            _ret, faces = self._detector.detect(frame)
            if faces is None or len(faces) == 0:
                return []
            return self._parse_face_detections(faces, w, h)

        if self._fallback is not None:
            return self._fallback.detect(frame)

        return []


DetectorFactory.register("yunet", YuNetFaceDetector)
DetectorFactory.register("face_yunet", YuNetFaceDetector)
DetectorFactory.register("yunetdetector", YuNetFaceDetector)

