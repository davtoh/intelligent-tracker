"""Registry and factory for visual feature extractors."""

from typing import Type, Dict
from intelligent_tracker.reid.base import BaseFeatureExtractor
from intelligent_tracker.reid.color import ColorHistogramExtractor
from intelligent_tracker.reid.onnx_extractor import OnnxReIDExtractor
from intelligent_tracker.reid.mock import MockFeatureExtractor
from intelligent_tracker.reid.dual import DualModelFeatureExtractor


class ReIDExtractorFactory:
    """Registry and factory for visual feature extractors."""

    _registry: Dict[str, Type[BaseFeatureExtractor]] = {
        "color": ColorHistogramExtractor,
        "hsv": ColorHistogramExtractor,
        "onnx": OnnxReIDExtractor,
        "mock": MockFeatureExtractor,
        "dual": DualModelFeatureExtractor,
        "dual_model": DualModelFeatureExtractor,
    }

    @classmethod
    def register(cls, name: str, extractor_cls: Type[BaseFeatureExtractor]):
        """Register a custom feature extractor class."""
        cls._registry[name.lower().strip()] = extractor_cls

    @classmethod
    def create(cls, name: str = "color", **kwargs) -> BaseFeatureExtractor:
        """Instantiate feature extractor by name.

        :param name: 'color', 'hsv', 'onnx', 'mock', 'dual', or 'dual_model'.
        """
        key = name.lower().strip()
        if key not in cls._registry:
            raise ValueError(
                f"Unknown Re-ID extractor '{name}'. Available: {list(cls._registry.keys())}"
            )
        return cls._registry[key](**kwargs)

