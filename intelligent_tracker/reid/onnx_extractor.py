"""Deep visual Re-ID embedding extractor running ONNX models."""

import os
import logging
from typing import Optional, Tuple
import cv2
import numpy as np

from intelligent_tracker.reid.base import BaseFeatureExtractor
from intelligent_tracker.reid.color import ColorHistogramExtractor

logger = logging.getLogger(__name__)

try:
    import onnxruntime as ort
    _HAS_ONNX = True
except ImportError:
    ort = None
    _HAS_ONNX = False


class OnnxReIDExtractor(BaseFeatureExtractor):
    """Deep visual Re-ID embedding extractor running ONNX models (e.g. OSNet, MobileNetV3).

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
                    f"ONNX model not found at '{model_path}' and fallback_to_color is disabled."
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
            os.path.join(os.path.dirname(__file__), "..", "..", "models", "osnet_x0_25.onnx"),
            os.path.join(os.path.dirname(__file__), "..", "..", "models", "reid.onnx"),
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

            print(f"[INFO] OnnxReIDExtractor loaded '{model_path}' (batch={self.expected_batch_size}, "
                  f"input={self.input_width}x{self.input_height}, dim={self._dim}) on {self.execution_provider}")
        except Exception as e:
            print(f"[WARN] Failed to initialize ONNX Re-ID session: {e}")
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

