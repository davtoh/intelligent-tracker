"""Multi-view WebSocket streaming package (protocol, limits, thumbnail cache, sessions)."""

from dashboard.services.multiview.limits import (
    DEFAULT_LAYOUT_CAPS_RAW,
    MultiviewLimits,
    clamp_subscription_params,
    get_multiview_limits,
    parse_layout_caps,
)
from dashboard.services.multiview.protocol import (
    HEADER_FORMAT,
    HEADER_SIZE,
    KIND_JPEG,
    PROTOCOL_VERSION,
    MultiviewFrame,
    ProtocolError,
    pack_frame,
    parse_control_message,
    unpack_frame,
)
from dashboard.services.multiview.session import (
    MultiviewSession,
    get_active_session_count,
    release_session_slot,
    resolve_camera_status,
    try_acquire_session_slot,
)
from dashboard.services.multiview.thumbnail_cache import (
    THUMB_TIERS,
    ThumbnailCache,
    ThumbnailSlot,
    normalize_tier,
)

__all__ = [
    "DEFAULT_LAYOUT_CAPS_RAW",
    "HEADER_FORMAT",
    "HEADER_SIZE",
    "KIND_JPEG",
    "MultiviewFrame",
    "MultiviewLimits",
    "MultiviewSession",
    "PROTOCOL_VERSION",
    "ProtocolError",
    "THUMB_TIERS",
    "ThumbnailCache",
    "ThumbnailSlot",
    "clamp_subscription_params",
    "get_active_session_count",
    "get_multiview_limits",
    "normalize_tier",
    "pack_frame",
    "parse_control_message",
    "parse_layout_caps",
    "release_session_slot",
    "resolve_camera_status",
    "try_acquire_session_slot",
    "unpack_frame",
]
