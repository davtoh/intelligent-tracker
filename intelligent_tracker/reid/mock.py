"""Deterministic synthetic feature extractor for tests and headless CI."""

import numpy as np

from intelligent_tracker.reid.base import BaseFeatureExtractor


class MockFeatureExtractor(BaseFeatureExtractor):
    """Deterministic synthetic feature extractor for unit tests and headless environments.

    Generates repeatable L2-normalized feature vectors based on dominant crop color and size.
    """

    def __init__(self, embedding_dim: int = 16):
        self._dim = int(embedding_dim)

    @property
    def embedding_dim(self) -> int:
        return self._dim

    def extract_crop(self, crop: np.ndarray) -> np.ndarray:
        if crop is None or crop.size == 0:
            return np.zeros(self._dim, dtype=np.float32)

        # Use mean BGR color and dimensions to seed a deterministic pseudo-embedding
        mean_bgr = np.mean(crop, axis=(0, 1))
        h, w = crop.shape[:2]

        vec = np.zeros(self._dim, dtype=np.float32)
        vec[0] = mean_bgr[0] / 255.0
        vec[1] = mean_bgr[1] / 255.0
        vec[2] = mean_bgr[2] / 255.0
        vec[3] = (h / 1000.0) % 1.0
        vec[4] = (w / 1000.0) % 1.0

        for i in range(5, self._dim):
            vec[i] = (vec[i % 5] * (i + 1)) % 1.0

        norm = np.linalg.norm(vec)
        if norm > 1e-7:
            vec = vec / norm
        return vec

