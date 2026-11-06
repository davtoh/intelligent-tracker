"""Spatial-grid HSV color histogram feature extractor."""

from typing import Optional, Tuple
import cv2
import numpy as np

from intelligent_tracker.reid.base import BaseFeatureExtractor


class ColorHistogramExtractor(BaseFeatureExtractor):
    """Spatial-grid HSV color histogram feature extractor.

    Zero neural network dependencies, pure NumPy and OpenCV.
    Extremely fast (<0.5ms on Raspberry Pi CPU).

    Divides the crop into spatial vertical slices (e.g. 3 vertical blocks: head/upper,
    torso/middle, legs/lower) to capture spatial color distribution (clothing, vehicle color).
    """

    def __init__(
        self,
        spatial_grid: Tuple[int, int] = (3, 1),
        h_bins: int = 8,
        s_bins: int = 4,
        v_bins: int = 4,
        bins: Optional[Tuple[int, int, int]] = None,
    ):
        """
        :param spatial_grid: (rows, cols) subdivision of the crop. Default: (3, 1) (3 vertical slices).
        :param h_bins: Number of bins for Hue channel [0, 180).
        :param s_bins: Number of bins for Saturation channel [0, 256).
        :param v_bins: Number of bins for Value channel [0, 256).
        :param bins: Optional (h_bins, s_bins, v_bins) tuple shorthand.
        """
        if bins is not None and len(bins) == 3:
            h_bins, s_bins, v_bins = bins

        self.rows, self.cols = spatial_grid
        self.h_bins = int(h_bins)
        self.s_bins = int(s_bins)
        self.v_bins = int(v_bins)
        self._bins_per_cell = self.h_bins * self.s_bins * self.v_bins
        self._dim = self.rows * self.cols * self._bins_per_cell

    @property
    def embedding_dim(self) -> int:
        return self._dim

    def extract_crop(self, crop: np.ndarray) -> np.ndarray:
        if crop is None or crop.size == 0 or crop.shape[0] < 2 or crop.shape[1] < 2:
            return np.zeros(self._dim, dtype=np.float32)

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        h, w = hsv.shape[:2]

        block_h = h // self.rows
        block_w = w // self.cols

        features = []
        for r in range(self.rows):
            y_start = r * block_h
            y_end = (r + 1) * block_h if r < self.rows - 1 else h
            for c in range(self.cols):
                x_start = c * block_w
                x_end = (c + 1) * block_w if c < self.cols - 1 else w

                sub_hsv = hsv[y_start:y_end, x_start:x_end]
                if sub_hsv.size == 0:
                    features.append(np.zeros(self._bins_per_cell, dtype=np.float32))
                    continue

                # Compute joint 3D histogram for (H, S, V)
                hist = cv2.calcHist(
                    [sub_hsv],
                    [0, 1, 2],
                    None,
                    [self.h_bins, self.s_bins, self.v_bins],
                    [0, 180, 0, 256, 0, 256],
                )
                features.append(hist.flatten().astype(np.float32))

        vector = np.concatenate(features).astype(np.float32)

        # L2 normalization
        norm = np.linalg.norm(vector)
        if norm > 1e-7:
            vector = vector / norm
        return vector

