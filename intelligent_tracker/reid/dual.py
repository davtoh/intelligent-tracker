"""Dual-Model feature extractor combining body/artifact appearance with localized facial biometrics."""

from typing import Optional, Any
import numpy as np

from intelligent_tracker.reid.base import BaseFeatureExtractor
from intelligent_tracker.reid.color import ColorHistogramExtractor
from intelligent_tracker.reid.onnx_extractor import OnnxReIDExtractor


class DualModelFeatureExtractor(BaseFeatureExtractor):
    """Dual-Model visual feature extractor combining deep artifact/body feature extraction

    (OSNet / ColorHistogram) with localized facial biometric extraction (YuNet/FaceDetector).

    When extracting an embedding from an entity crop:

    1. Extracts primary visual embedding (body/artifact appearance).
    2. Runs face detection across the crop using YuNetFaceDetector.
    3. If a face is detected, extracts a localized face embedding from the face subcrop
       and fuses it with the primary embedding.
    4. If no face is present (e.g., vehicles, tools, pets, packages, obscured faces),
       pads the face feature space cleanly, preserving dimensional consistency.
    5. Returns unified L2-normalized feature embedding vector.
    """

    def __init__(
        self,
        primary_extractor: Optional[BaseFeatureExtractor] = None,
        face_extractor: Optional[BaseFeatureExtractor] = None,
        face_detector: Optional[Any] = None,
        primary_model_path: Optional[str] = None,
        face_model_path: Optional[str] = None,
        fallback_to_color: bool = True,
    ):
        if primary_extractor is not None:
            self.primary_extractor = primary_extractor
        else:
            try:
                self.primary_extractor = OnnxReIDExtractor(
                    model_path=primary_model_path,
                    fallback_to_color=fallback_to_color,
                )
            except Exception:
                self.primary_extractor = ColorHistogramExtractor()

        if face_extractor is not None:
            self.face_extractor = face_extractor
        else:
            # High-resolution spatial color descriptor for facial structure and tone
            self.face_extractor = ColorHistogramExtractor(spatial_grid=(4, 4), h_bins=8, s_bins=4, v_bins=4)

        if face_detector is not None:
            self.face_detector = face_detector
        else:
            try:
                from intelligent_tracker.detectors import YuNetFaceDetector
                self.face_detector = YuNetFaceDetector(model_path=face_model_path)
            except Exception:
                self.face_detector = None

        self._dim = self.primary_extractor.embedding_dim + self.face_extractor.embedding_dim

    @property
    def embedding_dim(self) -> int:
        return self._dim

    def extract_crop(self, crop: np.ndarray) -> np.ndarray:
        if crop is None or getattr(crop, "size", 0) == 0:
            return np.zeros(self._dim, dtype=np.float32)

        # 1. Primary artifact / body visual embedding
        primary_vec = self.primary_extractor.extract_crop(crop)

        # 2. Localized face detection
        face_vec = np.zeros(self.face_extractor.embedding_dim, dtype=np.float32)
        if self.face_detector is not None:
            try:
                faces = self.face_detector.detect(crop)
                if faces:
                    # Select face with largest area
                    best_face = max(faces, key=lambda f: f.bbox[2] * f.bbox[3])
                    face_vec = self.face_extractor.extract(crop, best_face.bbox)
            except Exception:
                pass

        # 3. Concatenate and L2 normalize
        fused = np.concatenate([primary_vec, face_vec]).astype(np.float32)
        norm = np.linalg.norm(fused)
        if norm > 1e-7:
            fused = fused / norm
        return fused

