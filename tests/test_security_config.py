#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit tests for WebSocket/CORS security_config and /ws/{camera_id} handshake enforcement."""

import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from dashboard.app import create_app
from dashboard.dependencies import get_active_stream_manager
from dashboard.services.security_config import (
    is_origin_allowed,
    parse_allowed_origins,
    sign_token,
    verify_token,
)


class TestSecurityConfig(unittest.TestCase):
    """Verify origin parsing, same-origin checks, HMAC tokens, and WS handshake gates."""

    def test_parse_allowed_origins(self) -> None:
        self.assertEqual(parse_allowed_origins(""), [])
        self.assertEqual(
            parse_allowed_origins(" https://hub.example.com/ , http://10.0.0.5:8080 , https://hub.example.com "),
            ["https://hub.example.com", "http://10.0.0.5:8080"],
        )

    def test_is_origin_allowed_same_origin_and_allowlist(self) -> None:
        self.assertTrue(is_origin_allowed(None, "localhost:8000", []))
        self.assertTrue(is_origin_allowed("http://localhost:8000", "localhost:8000", []))
        self.assertTrue(is_origin_allowed("https://hub.example.com", "edge:8000", ["https://hub.example.com"]))
        self.assertFalse(is_origin_allowed("https://evil.example", "localhost:8000", []))
        self.assertFalse(is_origin_allowed("null", "localhost:8000", []))

    def test_sign_and_verify_token_roundtrip_and_expiry(self) -> None:
        secret = "test-secret-key"
        tok = sign_token("viewer-1", ttl_s=60, secret=secret, now=1000.0)
        payload = verify_token(tok, secret=secret, now=1050.0)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["sub"], "viewer-1")
        self.assertIsNone(verify_token(tok, secret=secret, now=1061.0))
        self.assertIsNone(verify_token(tok + "tamper", secret=secret, now=1010.0))
        self.assertIsNone(verify_token(tok, secret="wrong-secret", now=1010.0))

    def test_sign_token_clamps_ttl_and_requires_secret(self) -> None:
        with self.assertRaises(ValueError):
            sign_token("u", secret="")
        tok = sign_token("u", ttl_s=9999, secret="s", now=100.0)
        payload = verify_token(tok, secret="s", now=400.0)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["exp"], 400)

    def test_ws_rejects_evil_origin_with_1008(self) -> None:
        app = create_app()
        fake_mgr = MagicMock()
        app.dependency_overrides[get_active_stream_manager] = lambda: fake_mgr
        client = TestClient(app)
        with self.assertRaises(WebSocketDisconnect) as ctx:
            with client.websocket_connect("/ws/cam_01", headers={"origin": "https://evil.example"}):
                pass
        self.assertEqual(ctx.exception.code, 1008)

    def test_ws_enforces_token_when_secret_configured(self) -> None:
        app = create_app()
        with patch.dict(os.environ, {"MULTIVIEW_TOKEN_SECRET": "hub-secret"}):
            client = TestClient(app)
            with self.assertRaises(WebSocketDisconnect) as ctx:
                with client.websocket_connect("/ws/cam_01", headers={"origin": "http://testserver"}):
                    pass
            self.assertEqual(ctx.exception.code, 1008)

            tok = sign_token("hub", ttl_s=60, secret="hub-secret")
            with self.assertRaises(WebSocketDisconnect) as ctx2:
                with client.websocket_connect(
                    f"/ws/nonexistent_cam?token={tok}",
                    headers={"origin": "http://testserver"},
                ) as ws:
                    ws.receive_text()
            self.assertEqual(ctx2.exception.code, 1013)


if __name__ == "__main__":
    unittest.main()
