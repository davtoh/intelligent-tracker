"""Gallery Matcher & Re-Appearance Engine Module Facade.

Backward-compatibility facade re-exporting 100% of public gallery matching coordinators,
session entities, and Re-ID identification events from `intelligent_tracker.matching`.
"""

from intelligent_tracker.matching import (
    EntityIdentifiedEvent,
    GalleryMatcher,
    SessionEntity,
    SessionGalleryManager,
    apply_bounded_ema_update,
)

__all__ = [
    "EntityIdentifiedEvent",
    "SessionEntity",
    "SessionGalleryManager",
    "apply_bounded_ema_update",
    "GalleryMatcher",
]
