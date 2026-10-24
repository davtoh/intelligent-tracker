#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Visual Feature Descriptors & Re-Identification (Re-ID) Embeddings Module.

Provides:
- `BaseFeatureExtractor`: Abstract interface for visual feature extraction.
- `ColorHistogramExtractor`: Ultra-lightweight spatial-grid HSV color descriptor
  (zero neural network dependency, pure NumPy, sub-millisecond execution).
- `OnnxReIDExtractor`: Deep visual embedding extractor via ONNX Runtime
  with multi-provider execution cascade (CUDA -> DirectML -> OpenVINO -> CoreML -> CPU).
- `MockFeatureExtractor`: Deterministic synthetic feature extractor for tests and headless CI.
- `ReIDExtractorFactory`: Decoupled registry and factory for feature extractors.
- Cosine similarity matching primitives for gallery association.
"""

from __future__ import division, print_function, absolute_import

import os
from abc import ABC, abstractmethod
from typing import Tuple, Optional, Any, Union, List, Dict

import cv2
import numpy as np

try:
    import onnxruntime as ort
    _HAS_ONNX = True
except ImportError:
    ort = None
    _HAS_ONNX = False


# -----------------------------------------------------------------------------
# Similarity & Distance Utilities
# -----------------------------------------------------------------------------

def cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    """
    Compute cosine similarity between two 1D feature vectors.
    Returns float in range [-1.0, 1.0] (typically [0.0, 1.0] for L2-normalized non-negative embeddings).
    """
    v1 = np.asarray(vec1, dtype=np.float32).ravel()
    v2 = np.asarray(vec2, dtype=np.float32).ravel()

    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 < 1e-7 or norm2 < 1e-7:
        return 0.0

    dot = float(np.dot(v1, v2))
    return max(-1.0, min(1.0, dot / (norm1 * norm2)))


def batch_cosine_similarity(gallery_matrix: np.ndarray, query_vec: np.ndarray) -> np.ndarray:
    """
    Compute cosine similarity between a 2D gallery matrix of shape (N, D)
    and a 1D query vector of shape (D,).

    Assumes vectors are L2-normalized; performs fast matrix-vector dot product.
    :return: 1D array of shape (N,) with similarity scores.
    """
    if gallery_matrix.size == 0 or query_vec.size == 0:
        return np.empty((0,), dtype=np.float32)

    q = np.asarray(query_vec, dtype=np.float32).ravel()
    q_norm = np.linalg.norm(q)
    if q_norm > 1e-7:
        q = q / q_norm

    # Check gallery norms in case they were not normalized
    gallery = np.asarray(gallery_matrix, dtype=np.float32)
    if gallery.ndim == 1:
        gallery = gallery.reshape(1, -1)

    norms = np.linalg.norm(gallery, axis=1, keepdims=True)
    norms[norms < 1e-7] = 1.0
    normalized_gallery = gallery / norms

    scores = np.dot(normalized_gallery, q)
    return np.clip(scores, -1.0, 1.0).astype(np.float32)


# -----------------------------------------------------------------------------
# Base Feature Extractor Interface
# -----------------------------------------------------------------------------

class BaseFeatureExtractor(ABC):
    """
    Abstract base class for visual feature extraction and Re-ID embeddings.
    """

    @abstractmethod
    def extract_crop(self, crop: np.ndarray) -> np.ndarray:
        """
        Extract a 1D L2-normalized feature embedding vector from an image crop.

        :param crop: BGR image crop as np.ndarray (H, W, 3).
        :return: 1D float32 numpy array.
        """
        pass

    def extract(
        self,
        frame: np.ndarray,
        bbox: Tuple[int, int, int, int],
    ) -> np.ndarray:
        """
        Safely extract embedding from a bounding box within a frame.

        :param frame: Full BGR frame as np.ndarray (H, W, 3).
        :param bbox: (x, y, w, h) bounding box.
        :return: 1D float32 numpy array.
        """
        ih, iw = frame.shape[:2]
        x, y, w, h = [int(v) for v in bbox]

        # Clamp bounding box strictly inside image boundaries
        x1 = max(0, min(x, iw - 1))
        y1 = max(0, min(y, ih - 1))
        x2 = max(x1 + 1, min(x + w, iw))
        y2 = max(y1 + 1, min(y + h, ih))

        crop = frame[y1:y2, x1:x2]
        return self.extract_crop(crop)

    @property
    @abstractmethod
    def embedding_dim(self) -> int:
        """Return dimensionality of extracted feature vectors."""
        pass


# -----------------------------------------------------------------------------
# Spatial HSV Color Histogram Extractor (CPU Fallback)
# -----------------------------------------------------------------------------

class ColorHistogramExtractor(BaseFeatureExtractor):
    """
    Spatial-grid HSV color histogram feature extractor.
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
    ):
        """
        :param spatial_grid: (rows, cols) subdivision of the crop. Default: (3, 1) (3 vertical slices).
        :param h_bins: Number of bins for Hue channel [0, 180).
        :param s_bins: Number of bins for Saturation channel [0, 256).
        :param v_bins: Number of bins for Value channel [0, 256).
        """
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


# -----------------------------------------------------------------------------
# ONNX Runtime Re-ID Extractor
# -----------------------------------------------------------------------------

class OnnxReIDExtractor(BaseFeatureExtractor):
    """
    Deep visual Re-ID embedding extractor running ONNX models (e.g. OSNet, MobileNetV3).
    Supports automatic multi-platform execution provider cascade:
    CUDA -> DirectML (Windows) -> OpenVINO -> CoreML (macOS) -> CPU.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        input_size: Tuple[int, int] = (128, 256),
        embedding_dim: int = 512,
        fallback_to_color: bool = True,
    ):
        """
        :param model_path: Path to ONNX model file. If None or not found, tries default search paths.
        :param input_size: (width, height) expected by model. Default: (128, 256) (standard person Re-ID).
        :param embedding_dim: Feature vector dimension.
        :param fallback_to_color: If True, falls back to ColorHistogramExtractor if model fails to load.
        """
        self.input_width, self.input_height = input_size
        self._dim = embedding_dim
        self.fallback_to_color = fallback_to_color
        self._fallback_extractor = ColorHistogramExtractor() if fallback_to_color else None

        self.session = None
        self.input_name = None
        self.output_name = None
        self.execution_provider = "None"

        # Search candidate model paths
        resolved_path = self._resolve_model_path(model_path)
        if resolved_path and os.path.isfile(resolved_path) and _HAS_ONNX:
            self._init_session(resolved_path)
        else:
            if not fallback_to_color:
                raise RuntimeError(
                    "ONNX model not found at '{}' and fallback_to_color is disabled.".format(model_path)
                )
            print("[WARN] ONNX Re-ID model not found. Using lightweight ColorHistogramExtractor fallback.")

    @property
    def embedding_dim(self) -> int:
        if self.session is not None:
            return self._dim
        return self._fallback_extractor.embedding_dim if self._fallback_extractor else self._dim

    def _resolve_model_path(self, model_path: Optional[str]) -> Optional[str]:
        if model_path and os.path.isfile(model_path):
            return model_path

        candidates = [
            model_path,
            "models/osnet_x0_25.onnx",
            "models/mobilenetv3_reid.onnx",
            "models/reid.onnx",
            os.path.join(os.path.dirname(__file__), "..", "models", "osnet_x0_25.onnx"),
            os.path.join(os.path.dirname(__file__), "..", "models", "reid.onnx"),
        ]
        for c in candidates:
            if c and os.path.isfile(c):
                return os.path.abspath(c)
        return None

    def _init_session(self, model_path: str):
        available_providers = ort.get_available_providers()
        priority_providers = [
            "CUDAExecutionProvider",
            "DmlExecutionProvider",
            "OpenVINOExecutionProvider",
            "CoreMLExecutionProvider",
            "CPUExecutionProvider",
        ]
        providers_to_use = [p for p in priority_providers if p in available_providers]
        if not providers_to_use:
            providers_to_use = ["CPUExecutionProvider"]

        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        try:
            self.session = ort.InferenceSession(model_path, sess_options=opts, providers=providers_to_use)
            self.execution_provider = self.session.get_providers()[0]
            self.input_name = self.session.get_inputs()[0].name
            self.output_name = self.session.get_outputs()[0].name

            # Inspect input shape if available
            inp_shape = self.session.get_inputs()[0].shape
            self.expected_batch_size = 1
            if len(inp_shape) == 4:
                if isinstance(inp_shape[0], int) and inp_shape[0] > 0:
                    self.expected_batch_size = inp_shape[0]
                if isinstance(inp_shape[2], int) and isinstance(inp_shape[3], int):
                    self.input_height = inp_shape[2]
                    self.input_width = inp_shape[3]

            # Inspect output shape
            out_shape = self.session.get_outputs()[0].shape
            if len(out_shape) >= 2 and isinstance(out_shape[-1], int):
                self._dim = out_shape[-1]

            print("[INFO] OnnxReIDExtractor loaded '{}' (batch={}, input={}x{}, dim={}) on {}".format(
                model_path, self.expected_batch_size, self.input_width, self.input_height, self._dim, self.execution_provider
            ))
        except Exception as e:
            print("[WARN] Failed to initialize ONNX Re-ID session: {}".format(e))
            self.session = None

    def extract_crop(self, crop: np.ndarray) -> np.ndarray:
        if self.session is None:
            if self._fallback_extractor is not None:
                return self._fallback_extractor.extract_crop(crop)
            return np.zeros(self._dim, dtype=np.float32)

        if crop is None or crop.size == 0 or crop.shape[0] < 2 or crop.shape[1] < 2:
            return np.zeros(self._dim, dtype=np.float32)

        # Preprocess: resize -> RGB -> normalize ImageNet -> NCHW
        resized = cv2.resize(crop, (self.input_width, self.input_height), interpolation=cv2.INTER_LINEAR)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0

        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        normalized = (rgb - mean) / std

        # Transpose HWC to CHW
        chw = np.transpose(normalized, (2, 0, 1))

        # Accommodate expected batch size (pad if model requires fixed batch size > 1)
        bs = getattr(self, "expected_batch_size", 1)
        if bs > 1:
            batch = np.zeros((bs, 3, self.input_height, self.input_width), dtype=np.float32)
            batch[0] = chw
        else:
            batch = np.expand_dims(chw, axis=0).astype(np.float32)

        # Run inference
        outputs = self.session.run([self.output_name], {self.input_name: batch})
        out_tensor = np.asarray(outputs[0], dtype=np.float32)
        if out_tensor.ndim >= 2:
            embedding = out_tensor[0].ravel()
        else:
            embedding = out_tensor.ravel()

        # L2 Normalize
        norm = np.linalg.norm(embedding)
        if norm > 1e-7:
            embedding = embedding / norm
        return embedding


# -----------------------------------------------------------------------------
# Mock Feature Extractor for Testing
# -----------------------------------------------------------------------------

class MockFeatureExtractor(BaseFeatureExtractor):
    """
    Deterministic synthetic feature extractor for unit tests and headless environments.
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


# -----------------------------------------------------------------------------
# Factory Registry
# -----------------------------------------------------------------------------

class ReIDExtractorFactory(object):
    """Registry and factory for visual feature extractors."""

    _registry = {
        "color": ColorHistogramExtractor,
        "hsv": ColorHistogramExtractor,
        "onnx": OnnxReIDExtractor,
        "mock": MockFeatureExtractor,
    }

    @classmethod
    def register(cls, name: str, extractor_cls):
        """Register a custom feature extractor class."""
        cls._registry[name.lower().strip()] = extractor_cls

    @classmethod
    def create(cls, name: str = "color", **kwargs) -> BaseFeatureExtractor:
        """
        Instantiate feature extractor by name.

        :param name: 'color', 'hsv', 'onnx', or 'mock'.
        """
        key = name.lower().strip()
        if key not in cls._registry:
            raise ValueError(
                "Unknown Re-ID extractor '{}'. Available: {}".format(name, list(cls._registry.keys()))
            )
        return cls._registry[key](**kwargs)
