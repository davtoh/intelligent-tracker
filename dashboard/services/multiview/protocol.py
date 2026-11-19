#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Multi-View WebSocket Protocol v1.

Pure binary frame packing/unpacking (16-byte big-endian header + UTF-8 camera_id + JPEG)
and JSON control message validation.
"""

import json
import struct
from typing import Any, NamedTuple

from dashboard.services.multiview.limits import (
    MultiviewLimits,
    clamp_subscription_params,
    get_multiview_limits,
)

PROTOCOL_VERSION = 0x01
KIND_JPEG = 0x01
HEADER_FORMAT = ">BBHIQ"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 16 bytes
VALID_ACTIONS = frozenset({"subscribe", "unsubscribe_all", "pause", "resume", "ping"})


class ProtocolError(ValueError):
    """Structured protocol validation error carrying a wire ``code`` and ``message``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class MultiviewFrame(NamedTuple):
    """Decoded v1 binary frame."""

    version: int
    kind: int
    camera_id: str
    seq: int
    capture_ts_ms: int
    payload: bytes


def pack_frame(
    camera_id: str,
    seq: int,
    capture_ts_ms: int,
    payload: bytes,
    kind: int = KIND_JPEG,
    version: int = PROTOCOL_VERSION,
) -> bytes:
    """Pack a v1 binary multiview frame (big-endian header + UTF-8 camera_id + payload)."""
    cam_bytes = camera_id.encode("utf-8")
    if not cam_bytes or len(cam_bytes) > 65535:
        raise ValueError("camera_id UTF-8 length must be between 1 and 65535 bytes")
    header = struct.pack(
        HEADER_FORMAT,
        int(version) & 0xFF,
        int(kind) & 0xFF,
        len(cam_bytes),
        int(seq) & 0xFFFFFFFF,
        int(capture_ts_ms) & 0xFFFFFFFFFFFFFFFF,
    )
    return header + cam_bytes + payload


def unpack_frame(data: bytes) -> MultiviewFrame:
    """Unpack and validate a v1 binary multiview frame."""
    if len(data) < HEADER_SIZE:
        raise ProtocolError("invalid_frame", f"Frame too short ({len(data)} < {HEADER_SIZE})")
    version, kind, cam_id_len, seq, capture_ts_ms = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
    if version != PROTOCOL_VERSION:
        raise ProtocolError("unsupported_version", f"Unsupported frame version: {version}")
    if cam_id_len == 0 or len(data) < HEADER_SIZE + cam_id_len:
        raise ProtocolError("invalid_frame", "Truncated or empty camera_id in frame")
    cam_end = HEADER_SIZE + cam_id_len
    try:
        camera_id = data[HEADER_SIZE:cam_end].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolError("invalid_frame", "Invalid UTF-8 camera_id") from exc
    return MultiviewFrame(version, kind, camera_id, seq, capture_ts_ms, data[cam_end:])


def _validate_camera_ids(raw_cameras: Any, max_subscriptions: int) -> list[str]:
    """Validate, deduplicate, and cap a subscribe ``cameras`` list."""
    if not isinstance(raw_cameras, list):
        raise ProtocolError("invalid_cameras", "'cameras' must be a list of camera IDs")
    cameras: list[str] = []
    for item in raw_cameras:
        if not isinstance(item, str) or not item.strip():
            raise ProtocolError("invalid_cameras", "Each camera ID must be a non-empty string")
        cid = item.strip()
        if cid not in cameras:
            cameras.append(cid)
    if len(cameras) > max_subscriptions:
        raise ProtocolError(
            "too_many_subscriptions",
            f"Requested {len(cameras)} cameras; max is {max_subscriptions}",
        )
    return cameras


def _validate_subscribe(msg: dict[str, Any], limits: MultiviewLimits) -> dict[str, Any]:
    """Validate and normalize a ``subscribe`` control message."""
    profile = str(msg.get("profile", "thumb")).strip().lower()
    if profile == "full":
        raise ProtocolError("profile_not_enabled", "profile 'full' is reserved and not enabled in v1")
    if profile != "thumb":
        raise ProtocolError("invalid_profile", f"Unsupported profile: {profile!r}")

    cameras = _validate_camera_ids(msg.get("cameras"), limits.max_subscriptions)
    layout = str(msg.get("layout", "2x2")).strip()
    try:
        norm_layout, fps, width = clamp_subscription_params(
            layout,
            max_fps=msg.get("max_fps"),
            max_width=msg.get("max_width"),
            caps=limits.layout_caps,
        )
    except (ValueError, TypeError) as exc:
        raise ProtocolError("invalid_layout", str(exc)) from exc

    return {
        "v": PROTOCOL_VERSION,
        "action": "subscribe",
        "cameras": cameras,
        "layout": norm_layout,
        "profile": "thumb",
        "max_fps": fps,
        "max_width": width,
    }


def parse_control_message(
    raw: str | dict[str, Any],
    limits: MultiviewLimits | None = None,
) -> dict[str, Any]:
    """Parse and validate a client->server JSON control message."""
    if isinstance(raw, str):
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProtocolError("invalid_json", "Control message must be valid JSON") from exc
    else:
        msg = raw

    if not isinstance(msg, dict):
        raise ProtocolError("invalid_message", "Control message must be a JSON object")
    if msg.get("v") != PROTOCOL_VERSION:
        raise ProtocolError("unsupported_version", f"Expected protocol version {PROTOCOL_VERSION}")

    action = msg.get("action")
    if not isinstance(action, str) or action not in VALID_ACTIONS:
        raise ProtocolError("invalid_action", f"Unsupported action: {action!r}")
    if action == "subscribe":
        return _validate_subscribe(msg, limits or get_multiview_limits())
    return {"v": PROTOCOL_VERSION, "action": action}
