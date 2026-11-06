"""Re-ID Gallery Matching & Multi-Camera Re-Appearance Package.

Re-exports 100% of public gallery matching coordinators, session entities,
and Re-ID identification events.
"""

from intelligent_tracker.matching.types import EntityIdentifiedEvent, SessionEntity
from intelligent_tracker.matching.session_gallery import SessionGalleryManager
from intelligent_tracker.matching.adaptive_memory import apply_bounded_ema_update
from intelligent_tracker.matching.gallery import GalleryMatcher

__all__ = [
    "EntityIdentifiedEvent",
    "SessionEntity",
    "SessionGalleryManager",
    "apply_bounded_ema_update",
    "GalleryMatcher",
]

