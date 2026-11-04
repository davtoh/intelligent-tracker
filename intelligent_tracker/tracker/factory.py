"""Factory registry for multi-object tracking engines."""

from typing import Any, List

from intelligent_tracker.tracker.centroid import CentroidTracker
from intelligent_tracker.tracker.sort import SortTracker


class TrackerFactory:
    """Factory registry for multi-object tracking engines."""

    _registry = {
        "centroid": CentroidTracker,
        "sort": SortTracker,
    }

    @classmethod
    def register(cls, name: str, tracker_cls: type) -> None:
        """Register a new tracker implementation."""
        cls._registry[name.lower()] = tracker_cls

    @classmethod
    def create(cls, name: str = "centroid", **kwargs: Any) -> Any:
        """Instantiate registered tracker by name."""
        key = name.lower()
        if key not in cls._registry:
            raise ValueError(
                f"Unknown tracker '{name}'. Available trackers: {list(cls._registry.keys())}"
            )
        return cls._registry[key](**kwargs)

    @classmethod
    def available_trackers(cls) -> List[str]:
        """List registered tracker identifiers."""
        return list(cls._registry.keys())


__all__ = ["TrackerFactory"]

