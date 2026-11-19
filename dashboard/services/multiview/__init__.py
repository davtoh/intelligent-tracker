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

__all__ = [
    "DEFAULT_LAYOUT_CAPS_RAW",
    "HEADER_FORMAT",
    "HEADER_SIZE",
    "KIND_JPEG",
    "MultiviewFrame",
    "MultiviewLimits",
    "PROTOCOL_VERSION",
    "ProtocolError",
    "clamp_subscription_params",
    "get_multiview_limits",
    "pack_frame",
    "parse_control_message",
    "parse_layout_caps",
    "unpack_frame",
]
