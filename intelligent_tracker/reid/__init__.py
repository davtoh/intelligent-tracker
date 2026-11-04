"""Visual Feature Descriptors & Re-Identification (Re-ID) Embeddings Package.

Re-exports 100% of public visual feature extractors, cosine similarity metrics,
and extractor factories to preserve backward compatibility across all modules and tests.
"""

from intelligent_tracker.reid.base import BaseFeatureExtractor
from intelligent_tracker.reid.color import ColorHistogramExtractor
from intelligent_tracker.reid.dual import DualModelFeatureExtractor
from intelligent_tracker.reid.factory import ReIDExtractorFactory
from intelligent_tracker.reid.metrics import batch_cosine_similarity, cosine_similarity
from intelligent_tracker.reid.mock import MockFeatureExtractor
from intelligent_tracker.reid.onnx_extractor import OnnxReIDExtractor, _HAS_ONNX

__all__ = [
    "BaseFeatureExtractor",
    "ColorHistogramExtractor",
    "OnnxReIDExtractor",
    "MockFeatureExtractor",
    "DualModelFeatureExtractor",
    "ReIDExtractorFactory",
    "cosine_similarity",
    "batch_cosine_similarity",
    "_HAS_ONNX",
]

