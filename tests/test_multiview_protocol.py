#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit tests for Multi-View WebSocket Protocol v1 and layout limits."""

import os
import unittest
from unittest.mock import patch

from dashboard.services.multiview.limits import (
    clamp_subscription_params,
    get_multiview_limits,
    parse_layout_caps,
)
from dashboard.services.multiview.protocol import (
    HEADER_SIZE,
    KIND_JPEG,
    PROTOCOL_VERSION,
    ProtocolError,
    pack_frame,
    parse_control_message,
    unpack_frame,
)


class TestMultiviewProtocol(unittest.TestCase):
    """Verify binary frame v1 packing/unpacking, limits, and control validation."""

    def test_pack_and_unpack_frame_roundtrip(self) -> None:
        jpeg = b"\xff\xd8\xff\xe0test-jpeg-bytes\xff\xd9"
        packed = pack_frame("cam_lobby_01", seq=42, capture_ts_ms=1700000000123, payload=jpeg)
        self.assertEqual(len(packed), HEADER_SIZE + len("cam_lobby_01") + len(jpeg))
        frame = unpack_frame(packed)
        self.assertEqual(frame.version, PROTOCOL_VERSION)
        self.assertEqual(frame.kind, KIND_JPEG)
        self.assertEqual(frame.camera_id, "cam_lobby_01")
        self.assertEqual(frame.seq, 42)
        self.assertEqual(frame.capture_ts_ms, 1700000000123)
        self.assertEqual(frame.payload, jpeg)

    def test_unpack_frame_rejects_short_or_bad_version(self) -> None:
        with self.assertRaises(ProtocolError) as ctx:
            unpack_frame(b"\x01\x01\x00")
        self.assertEqual(ctx.exception.code, "invalid_frame")

        bad_ver = pack_frame("cam_01", seq=1, capture_ts_ms=1, payload=b"x", version=2)
        with self.assertRaises(ProtocolError) as ctx2:
            unpack_frame(bad_ver)
        self.assertEqual(ctx2.exception.code, "unsupported_version")

    def test_layout_caps_and_clamping(self) -> None:
        caps = parse_layout_caps("2x2:15:640,3x3:10:480,4x4:6:320")
        self.assertEqual(caps["3x3"], (10, 480))
        self.assertEqual(clamp_subscription_params("3x3", max_fps=30, max_width=1920, caps=caps), ("3x3", 10, 480))
        self.assertEqual(clamp_subscription_params("4x4", max_fps=None, max_width=None, caps=caps), ("4x4", 6, 320))
        with self.assertRaises(ValueError):
            clamp_subscription_params("5x5", caps=caps)

    def test_parse_control_subscribe_and_clamping(self) -> None:
        with patch.dict(os.environ, {"MULTIVIEW_MAX_SUBSCRIPTIONS": "16"}):
            limits = get_multiview_limits()
        parsed = parse_control_message(
            {
                "v": 1,
                "action": "subscribe",
                "cameras": ["cam_01", "cam_02", "cam_01"],
                "layout": "3x3",
                "profile": "thumb",
                "max_fps": 60,
                "max_width": 1280,
            },
            limits=limits,
        )
        self.assertEqual(parsed["cameras"], ["cam_01", "cam_02"])
        self.assertEqual(parsed["max_fps"], 10)
        self.assertEqual(parsed["max_width"], 480)

    def test_parse_control_rejects_full_profile_and_invalid_inputs(self) -> None:
        with self.assertRaises(ProtocolError) as ctx:
            parse_control_message({"v": 1, "action": "subscribe", "cameras": ["cam_01"], "profile": "full"})
        self.assertEqual(ctx.exception.code, "profile_not_enabled")

        with self.assertRaises(ProtocolError) as ctx2:
            parse_control_message("{bad-json")
        self.assertEqual(ctx2.exception.code, "invalid_json")

        for act in ("unsubscribe_all", "pause", "resume", "ping"):
            self.assertEqual(parse_control_message({"v": 1, "action": act})["action"], act)


if __name__ == "__main__":
    unittest.main()
