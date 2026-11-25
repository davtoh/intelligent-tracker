#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Multi-View Streaming Limits & Layout Caps.

Parses environment-configurable per-layout FPS/width ceilings, session caps,
send timeouts, and thumbnail JPEG quality.
"""

from dataclasses import dataclass
import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_LAYOUT_CAPS_RAW = "2x2:15:640,3x3:10:480,4x4:6:320"
DEFAULT_LAYOUT_CAPS: dict[str, tuple[int, int]] = {
    "2x2": (15, 640),
    "3x3": (10, 480),
    "4x4": (6, 320),
}
MIN_THUMB_WIDTH = 64


@dataclass(frozen=True)
class MultiviewLimits:
    """Resolved server-side limits for `/ws/multiview` sessions."""

    layout_caps: dict[str, tuple[int, int]]
    max_subscriptions: int
    max_sessions: int
    send_timeout_s: float
    thumb_quality: int


def parse_layout_caps(raw: str | None = None) -> dict[str, tuple[int, int]]:
    """Parse ``layout:fps:width,...`` ceilings; falls back to defaults when invalid."""
    source = os.getenv("MULTIVIEW_LAYOUT_CAPS", DEFAULT_LAYOUT_CAPS_RAW) if raw is None else raw
    caps: dict[str, tuple[int, int]] = {}
    for entry in source.split(","):
        parts = [p.strip() for p in entry.split(":")]
        if len(parts) != 3 or not parts[0]:
            logger.debug("Ignoring malformed multiview layout cap entry: %r", entry)
            continue
        try:
            fps = max(1, int(parts[1]))
            width = max(MIN_THUMB_WIDTH, int(parts[2]))
        except ValueError:
            continue
        caps[parts[0]] = (fps, width)
    return caps or dict(DEFAULT_LAYOUT_CAPS)


def clamp_subscription_params(
    layout: str,
    max_fps: int | None = None,
    max_width: int | None = None,
    caps: dict[str, tuple[int, int]] | None = None,
) -> tuple[str, int, int]:
    """Validate ``layout`` and clamp ``max_fps`` / ``max_width`` to its ceiling."""
    resolved_caps = parse_layout_caps() if caps is None else caps
    if layout not in resolved_caps:
        raise ValueError(f"Unsupported layout {layout!r}; expected {tuple(resolved_caps)}")
    cap_fps, cap_width = resolved_caps[layout]
    fps = cap_fps if max_fps is None else min(max(int(max_fps), 1), cap_fps)
    width = cap_width if max_width is None else min(max(int(max_width), MIN_THUMB_WIDTH), cap_width)
    return layout, fps, width


def _parse_int_env(name: str, default: int, minimum: int, maximum: int | None = None) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        val = max(minimum, int(raw))
        return min(val, maximum) if maximum is not None else val
    except ValueError:
        return default


def _parse_float_env(name: str, default: float, minimum: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, float(raw))
    except ValueError:
        return default


def get_multiview_limits() -> MultiviewLimits:
    """Load current ``MultiviewLimits`` from environment variables."""
    return MultiviewLimits(
        layout_caps=parse_layout_caps(),
        max_subscriptions=_parse_int_env("MULTIVIEW_MAX_SUBSCRIPTIONS", 16, minimum=1),
        max_sessions=_parse_int_env("MULTIVIEW_MAX_SESSIONS", 16, minimum=0),
        send_timeout_s=_parse_float_env("MULTIVIEW_SEND_TIMEOUT_S", 0.5, minimum=0.05),
        thumb_quality=_parse_int_env("MULTIVIEW_THUMB_QUALITY", 70, minimum=10, maximum=100),
    )
