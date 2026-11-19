#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Router integration tests for /ws/multiview (Origin, token, session cap, framing)."""

import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import numpy as np

from dashboard.dependencies import bind_app_state, clear_app_state, set_shutting_down
from dashboard.routers.multiview import router as multiview_router
from dashboard.services.multiview.protocol import unpack_frame
from dashboard.services.multiview.session import get_active_session_count
from dashboard.services.security_config import sign_token
from tests.test_multiview_session import _FakePool, _FakeStreamManager


def _build_test_app(pool: _FakePool) -> FastAPI:
    app = FastAPI()
    app.include_router(multiview_router)
    bind_app_state(app, camera_pool=pool)
    return app


class TestMultiviewRouter(unittest.TestCase):
    """Verify /ws/multiview handshake security, session cap, and binary streaming."""

    def setUp(self) -> None:
        set_shutting_down(False)
        self.cam = _FakeStreamManager("cam_01")
        self.pool = _FakePool({"cam_01": self.cam})
        self.app = _build_test_app(self.pool)
        self.client = TestClient(self.app)
        self.addCleanup(set_shutting_down, False)
        self.addCleanup(clear_app_state, self.app)
        self.addCleanup(self.client.close)

    def test_rejects_disallowed_origin_with_1008(self) -> None:
        with self.assertRaises(Exception):
            with self.client.websocket_connect("/ws/multiview", headers={"origin": "https://evil.example"}):
                pass
        self.assertEqual(get_active_session_count(), 0)

    def test_enforces_token_when_secret_configured(self) -> None:
        with patch.dict(os.environ, {"MULTIVIEW_TOKEN_SECRET": "super-secret"}, clear=False):
            with self.assertRaises(Exception):
                with self.client.websocket_connect("/ws/multiview"):
                    pass
            tok = sign_token("viewer1", secret="super-secret")
            with self.client.websocket_connect(f"/ws/multiview?token={tok}") as ws:
                hello = ws.receive_json()
                self.assertEqual(hello["type"], "hello")

    def test_session_cap_rejects_when_zero(self) -> None:
        with patch.dict(os.environ, {"MULTIVIEW_MAX_SESSIONS": "0"}, clear=False):
            with self.assertRaises(Exception):
                with self.client.websocket_connect("/ws/multiview"):
                    pass
        self.assertEqual(get_active_session_count(), 0)

    def test_ping_subscribe_and_binary_frame_roundtrip(self) -> None:
        with self.client.websocket_connect("/ws/multiview") as ws:
            hello = ws.receive_json()
            self.assertEqual(hello["type"], "hello")
            ws.send_json({"v": 1, "action": "ping"})
            self.assertEqual(ws.receive_json()["type"], "pong")

            ws.send_json({"v": 1, "action": "subscribe", "cameras": ["cam_01"], "layout": "2x2"})
            sub = ws.receive_json()
            self.assertEqual(sub["type"], "subscribed")
            self.assertEqual(sub["accepted"], ["cam_01"])

            status = ws.receive_json()
            self.assertEqual(status["type"], "source_status")
            self.assertEqual(status["status"], "online")

            self.cam.thumbnail_cache.update_frame(np.zeros((120, 160, 3), dtype=np.uint8), seq=42, timestamp_s=3.0)
            for _lp, ev in list(self.cam.waiters):
                _lp.call_soon_threadsafe(ev.set)

            frame = unpack_frame(ws.receive_bytes())
            self.assertEqual(frame.camera_id, "cam_01")
            self.assertEqual(frame.seq, 42)
        self.assertEqual(get_active_session_count(), 0)


if __name__ == "__main__":
    unittest.main()
