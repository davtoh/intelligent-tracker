#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit tests for MultiviewSession lifecycle, leases, slow skips, and shutdown."""

import asyncio
import json
import unittest

from fastapi import WebSocketDisconnect
import numpy as np

from dashboard.services.multiview.limits import MultiviewLimits
from dashboard.services.multiview.protocol import unpack_frame
from dashboard.services.multiview.session import MultiviewSession
from dashboard.services.multiview.thumbnail_cache import ThumbnailCache


class _FakeStreamManager:
    def __init__(self, camera_id: str) -> None:
        self.camera_id = camera_id
        self.thumbnail_cache = ThumbnailCache(camera_id)
        self.is_running = True
        self.is_hibernating = False
        self._source_error = False
        self.added: list[tuple[str, bool]] = []
        self.removed: list[str] = []
        self.heartbeats: list[str] = []
        self.waiters: list[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = []

    def add_subscriber(self, sub_id: str, annotated: bool = True) -> str:
        self.added.append((sub_id, annotated))
        return sub_id

    def heartbeat_subscriber(self, sub_id: str) -> None:
        self.heartbeats.append(sub_id)

    def remove_subscriber(self, sub_id: str) -> int:
        self.removed.append(sub_id)
        return 0

    def register_frame_waiter(self, loop: asyncio.AbstractEventLoop, event: asyncio.Event) -> None:
        self.waiters.append((loop, event))

    def unregister_frame_waiter(self, loop: asyncio.AbstractEventLoop, event: asyncio.Event) -> None:
        self.waiters = [(lp, ev) for lp, ev in self.waiters if ev is not event]

    def notify(self) -> None:
        for _lp, ev in list(self.waiters):
            ev.set()


class _FakePool:
    def __init__(self, streams: dict[str, _FakeStreamManager], configs: dict[str, dict] | None = None) -> None:
        self.streams = streams
        self.camera_configs = configs or {}

    def get_stream(self, camera_id: str) -> _FakeStreamManager | None:
        return self.streams.get(camera_id)


class _FakeWebSocket:
    def __init__(self, incoming: list[str], send_delay: float = 0.0) -> None:
        self._incoming = asyncio.Queue()
        for item in incoming:
            self._incoming.put_nowait(item)
        self.accepted = False
        self.closed: tuple[int, str] | None = None
        self.sent_json: list[dict] = []
        self.sent_bytes: list[bytes] = []
        self._send_delay = send_delay

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = (code, reason)
        self._incoming.put_nowait(None)

    async def receive_text(self) -> str:
        item = await self._incoming.get()
        if item is None:
            raise WebSocketDisconnect(code=1000)
        return item

    async def send_json(self, data: dict) -> None:
        self.sent_json.append(data)

    async def send_bytes(self, data: bytes) -> None:
        if self._send_delay > 0:
            await asyncio.sleep(self._send_delay)
        self.sent_bytes.append(data)


def _limits(send_timeout_s: float = 0.2) -> MultiviewLimits:
    return MultiviewLimits(
        layout_caps={"2x2": (15, 640), "3x3": (10, 480), "4x4": (6, 320)},
        max_subscriptions=16,
        max_sessions=4,
        send_timeout_s=send_timeout_s,
        thumb_quality=70,
    )


class TestMultiviewSession(unittest.TestCase):
    """Verify replace-set subscriptions, pause/resume, slow skips, and shutdown."""

    def test_replace_set_and_rejected_cameras(self) -> None:
        async def _run() -> None:
            cam1 = _FakeStreamManager("cam_01")
            cam2 = _FakeStreamManager("cam_02")
            pool = _FakePool({"cam_01": cam1, "cam_02": cam2}, {"cam_03": {"enabled": False}})
            msgs = [
                json.dumps({"v": 1, "action": "subscribe", "cameras": ["cam_01", "cam_03", "missing"], "layout": "2x2"}),
                json.dumps({"v": 1, "action": "subscribe", "cameras": ["cam_02"], "layout": "2x2"}),
            ]
            ws = _FakeWebSocket(msgs)
            session = MultiviewSession(ws, pool=pool, limits=_limits(), session_id="s1")

            async def _close_soon() -> None:
                await asyncio.sleep(0.05)
                await ws.close()

            await asyncio.gather(session.run(), _close_soon())
            sub_msgs = [m for m in ws.sent_json if m.get("type") == "subscribed"]
            self.assertEqual(sub_msgs[0]["accepted"], ["cam_01"])
            self.assertEqual(sub_msgs[0]["rejected"], {"cam_03": "disabled", "missing": "unknown_camera"})
            self.assertEqual(cam1.added, [("s1:cam_01", False)])
            self.assertIn("s1:cam_01", cam1.removed)
            self.assertIn("s1:cam_02", cam2.removed)
            self.assertFalse(cam1.thumbnail_cache.has_leases())

        asyncio.run(_run())

    def test_pause_releases_leases_and_resume_reacquires(self) -> None:
        async def _run() -> None:
            cam1 = _FakeStreamManager("cam_01")
            pool = _FakePool({"cam_01": cam1})
            ws = _FakeWebSocket([])
            session = MultiviewSession(ws, pool=pool, limits=_limits(), session_id="s1")

            async def _drive() -> None:
                await asyncio.sleep(0.02)
                ws._incoming.put_nowait(json.dumps({"v": 1, "action": "subscribe", "cameras": ["cam_01"], "layout": "3x3"}))
                await asyncio.sleep(0.02)
                self.assertTrue(cam1.thumbnail_cache.has_leases())
                ws._incoming.put_nowait(json.dumps({"v": 1, "action": "pause"}))
                await asyncio.sleep(0.02)
                self.assertFalse(cam1.thumbnail_cache.has_leases())
                ws._incoming.put_nowait(json.dumps({"v": 1, "action": "resume"}))
                await asyncio.sleep(0.02)
                self.assertTrue(cam1.thumbnail_cache.has_leases())
                await ws.close()

            await asyncio.gather(session.run(), _drive())

        asyncio.run(_run())

    def test_binary_delivery_and_slow_send_skip(self) -> None:
        async def _run() -> None:
            cam1 = _FakeStreamManager("cam_01")
            pool = _FakePool({"cam_01": cam1})
            ws = _FakeWebSocket([], send_delay=0.08)
            session = MultiviewSession(ws, pool=pool, limits=_limits(send_timeout_s=0.02), session_id="s1")

            async def _drive() -> None:
                await asyncio.sleep(0.02)
                ws._incoming.put_nowait(json.dumps({"v": 1, "action": "subscribe", "cameras": ["cam_01"], "layout": "2x2"}))
                await asyncio.sleep(0.02)
                cam1.thumbnail_cache.update_frame(np.zeros((120, 160, 3), dtype=np.uint8), seq=5, timestamp_s=1.0)
                cam1.notify()
                await asyncio.sleep(0.06)
                await ws.close()

            await asyncio.gather(session.run(), _drive())
            self.assertGreaterEqual(session._slow_skips, 1)
            self.assertEqual(ws.sent_bytes, [])

        asyncio.run(_run())

    def test_fast_delivery_and_shutdown_closes_1001(self) -> None:
        async def _run() -> None:
            cam1 = _FakeStreamManager("cam_01")
            pool = _FakePool({"cam_01": cam1})
            ws = _FakeWebSocket([])
            shutdown_evt = asyncio.Event()
            session = MultiviewSession(ws, pool=pool, limits=_limits(), shutdown_event=shutdown_evt, session_id="s1")

            async def _drive() -> None:
                await asyncio.sleep(0.02)
                ws._incoming.put_nowait(json.dumps({"v": 1, "action": "subscribe", "cameras": ["cam_01"], "layout": "2x2"}))
                await asyncio.sleep(0.02)
                cam1.thumbnail_cache.update_frame(np.zeros((120, 160, 3), dtype=np.uint8), seq=9, timestamp_s=2.0)
                cam1.notify()
                await asyncio.sleep(0.03)
                shutdown_evt.set()

            await asyncio.gather(session.run(), _drive())
            self.assertEqual(len(ws.sent_bytes), 1)
            self.assertEqual(unpack_frame(ws.sent_bytes[0]).seq, 9)
            self.assertEqual(ws.closed[0], 1001)
            self.assertFalse(cam1.thumbnail_cache.has_leases())

        asyncio.run(_run())

    def test_removed_camera_emits_offline_once(self) -> None:
        async def _run() -> None:
            cam1 = _FakeStreamManager("cam_01")
            pool = _FakePool({"cam_01": cam1})
            ws = _FakeWebSocket([])
            session = MultiviewSession(ws, pool=pool, limits=_limits(), session_id="s1")

            async def _drive() -> None:
                await asyncio.sleep(0.02)
                ws._incoming.put_nowait(json.dumps({"v": 1, "action": "subscribe", "cameras": ["cam_01"], "layout": "2x2"}))
                await asyncio.sleep(0.03)
                pool.streams.pop("cam_01")
                cam1.notify()
                await asyncio.sleep(0.03)
                await ws.close()

            await asyncio.gather(session.run(), _drive())
            statuses = [m for m in ws.sent_json if m.get("type") == "source_status"]
            self.assertEqual([s["status"] for s in statuses], ["online", "offline"])

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
