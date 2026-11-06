"""Base interfaces and factory registry for Edge AI object detection."""

import abc
from collections import namedtuple
from typing import Any

Detection = namedtuple("Detection", ["bbox", "class_id", "confidence", "label"])


class BaseDetector(abc.ABC):
    """Abstract Base Detector defining the modern Edge AI detection interface."""

    @abc.abstractmethod
    def detect(self, frame):
        """Detect objects in a BGR image frame.

        :param frame: numpy array (H, W, 3) BGR format
        :return: list of Detection(bbox=(x, y, w, h), class_id=int, confidence=float, label=str)
        """
        raise NotImplementedError


class DetectorFactory:
    """Registry and factory for creating detectors by name from configuration or CLI.

    Supports 'haar', 'yolov8', 'yolo11', 'mock', 'color', 'face', 'eye', etc.
    """

    _registry: dict[str, Any] = {}

    @classmethod
    def register(cls, name: str, detector_class: Any) -> None:
        """Register a detector class or factory callable with a canonical lower-case key."""
        name_clean = name.lower().strip()
        cls._registry[name_clean] = detector_class
        try:
            # Sync to Detector.available_detectors if Detector is available
            from intelligent_tracker.detectors.core_detector import Detector

            if (
                isinstance(detector_class, type)
                and issubclass(detector_class, Detector)
                and detector_class is not Detector
            ):
                Detector.available_detectors[name_clean] = detector_class
        except (ImportError, NameError, TypeError):
            pass

    @classmethod
    def available(cls) -> list[str]:
        """Return sorted list of all registered detector identifier keys."""
        return sorted(list(cls._registry.keys()))

    @classmethod
    def create(cls, name: str, *args, **kwargs) -> Any:
        """Instantiate a detector by its registered name key."""
        name_clean = str(name).lower().strip()
        if name_clean not in cls._registry:
            raise KeyError(
                f"Detector '{name}' is not registered. Available: {cls.available()}"
            )

        target = cls._registry[name_clean]
        if callable(target):
            return target(*args, **kwargs)
        raise TypeError(f"Registered detector for '{name}' is not callable")

