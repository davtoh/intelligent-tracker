"""Abstract base interface for visual feature extraction and Re-ID embeddings."""

from abc import ABC, abstractmethod
from typing import Optional, Tuple
import numpy as np


class BaseFeatureExtractor(ABC):
    """Abstract base class for visual feature extraction and Re-ID embeddings."""

    @property
    @abstractmethod
    def embedding_dim(self) -> int:
        """Return dimensionality of extracted feature vectors."""
        pass

    @abstractmethod
    def extract_crop(self, crop: np.ndarray) -> np.ndarray:
        """Extract a 1D L2-normalized feature embedding vector from an image crop.

        :param crop: BGR image crop as np.ndarray (H, W, 3).
        :return: 1D float32 numpy array.
        """
        pass

    def extract(
        self,
        frame: np.ndarray,
        bbox: Optional[Tuple[int, int, int, int]] = None,
    ) -> np.ndarray:
        """Safely extract embedding from a bounding box within a frame, or direct crop if bbox is None.

        :param frame: Full BGR frame as np.ndarray (H, W, 3) or direct crop.
        :param bbox: (x, y, w, h) bounding box, or None if frame is already a crop.
        :return: 1D float32 numpy array.
        """
        if bbox is None:
            return self.extract_crop(frame)

        ih, iw = frame.shape[:2]
        x, y, w, h = [int(v) for v in bbox]

        # Clamp bounding box strictly inside image boundaries
        x1 = max(0, min(x, iw - 1))
        y1 = max(0, min(y, ih - 1))
        x2 = max(x1 + 1, min(x + w, iw))
        y2 = max(y1 + 1, min(y + h, ih))

        crop = frame[y1:y2, x1:x2]
        return self.extract_crop(crop)

