"""Detector instantiation with status tracking and safe live-source fallback."""

import logging
from typing import Any

from intelligent_tracker.detectors import DetectorFactory
from intelligent_tracker.detectors.base import BaseDetector
from intelligent_tracker.pipeline.config import PipelineConfig, is_synthetic_source

logger = logging.getLogger("intelligent_tracker.pipeline.detector_setup")

_YOLO_NAMES = ("yolov8", "yolov8n", "yolo11", "yolo11n", "onnx")
_MOCK_NAMES = ("mock", "mockdetector")


class EmptyDetector(BaseDetector):
    """No-op detector used when real weights are unavailable on live sources."""

    def detect(self, frame: Any) -> list[Any]:
        """Return an empty detection list without fabricating mock entities."""
        return []


def _build_detector_kwargs(config: PipelineConfig, det_name: str) -> dict[str, Any]:
    """Assemble backend-specific keyword arguments for DetectorFactory."""
    kwargs: dict[str, Any] = {}
    if det_name in _YOLO_NAMES:
        kwargs["conf_threshold"] = config.detector_confidence
        if config.detector_classes:
            kwargs["classes"] = config.detector_classes
        if det_name == "onnx":
            kwargs["agnostic_nms"] = getattr(config, "detector_agnostic_nms", True)
    elif det_name in _MOCK_NAMES:
        kwargs["confidence"] = config.detector_confidence
    return kwargs


def _should_raise_on_error(config: PipelineConfig, raise_on_error: bool | None) -> bool:
    """Determine whether detector initialization failures must propagate."""
    if raise_on_error is not None:
        return raise_on_error
    return (not config.detector_fallback_mock) and is_synthetic_source(config.source)


def _handle_detector_failure(
    config: PipelineConfig,
    det_name: str,
    exc: Exception,
    should_raise: bool,
) -> tuple[Any, str, str | None]:
    """Resolve fallback detector or re-raise when strict mode is active."""
    if should_raise:
        if isinstance(exc, KeyError):
            raise ValueError(str(exc)) from exc
        raise exc
    if config.detector_fallback_mock:
        logger.warning(
            "Preferred detector '%s' failed (%s), falling back to mock",
            det_name,
            exc,
        )
        return DetectorFactory.create("mock"), "simulation", str(exc)
    logger.error(
        "Detector '%s' unavailable on live source (%s); using EmptyDetector",
        det_name,
        exc,
    )
    return EmptyDetector(), "unavailable", str(exc)


def build_detector_with_status(
    config: PipelineConfig,
    *,
    raise_on_error: bool | None = None,
) -> tuple[Any, str, str | None]:
    """Instantiate detector backend and return ``(detector, status, error_msg)``."""
    det_name = str(config.detector_model).strip().lower()
    det_kwargs = _build_detector_kwargs(config, det_name)
    should_raise = _should_raise_on_error(config, raise_on_error)
    try:
        detector = DetectorFactory.create(det_name, **det_kwargs)
        status = "simulation" if det_name in _MOCK_NAMES else "ready"
        return detector, status, None
    except Exception as exc:
        return _handle_detector_failure(config, det_name, exc, should_raise)
