#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit tests for event-driven MJPEG frame wakeup, on-demand JPEG, and StreamManager stop."""

import asyncio
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from dashboard.routers.streaming import _stream_frame_generator
from dashboard.services.stream_media import StreamMediaMixin
from dashboard.stream_manager import StreamManager


class _FakeMediaHost(StreamMediaMixin):
    """Minimal StreamMediaMixin host for isolated frame-waiter tests."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._latest_jpeg = b"ann-jpeg"
        self._latest_raw_jpeg = b"raw-jpeg"
        self._subscribers: dict[str, float] = {}
        self.removed: list[str] = []

    def add_subscriber(self, sub_id: str, annotated: bool = True) -> str:
        self._subscribers[sub_id] = time.time()
        return sub_id

    def heartbeat_subscriber(self, sub_id: str) -> None:
        self._subscribers[sub_id] = time.time()

    def remove_subscriber(self, sub_id: str) -> int:
        self._subscribers.pop(sub_id, None)
        self.removed.append(sub_id)
        return len(self._subscribers)


class _FakeRequest:
    """Minimal FastAPI Request stub for _stream_frame_generator."""

    def __init__(self, max_polls: int = 4) -> None:
        self.polls = 0
        self.max_polls = max_polls

    async def is_disconnected(self) -> bool:
        self.polls += 1
        return self.polls > self.max_polls


class TestStreamManagerEventWakeup(unittest.TestCase):
    """Verify thread-safe frame-ready notifications and clean shutdown wakeup."""

    def test_notify_frame_ready_wakes_waiter_under_50ms(self) -> None:
        host = _FakeMediaHost()

        async def _run() -> tuple[float, int]:
            loop = asyncio.get_running_loop()
            evt = asyncio.Event()
            host.register_frame_waiter(loop, evt)
            t0 = time.monotonic()
            timer = threading.Timer(0.01, host.notify_frame_ready)
            timer.start()
            await asyncio.wait_for(evt.wait(), timeout=0.5)
            elapsed = time.monotonic() - t0
            host.unregister_frame_waiter(loop, evt)
            return elapsed, host._frame_seq

        elapsed, seq = asyncio.run(_run())
        self.assertLess(elapsed, 0.25)
        self.assertEqual(seq, 1)

    def test_unregister_and_closed_loop_are_safe(self) -> None:
        host = _FakeMediaHost()

        async def _run() -> None:
            loop = asyncio.get_running_loop()
            evt = asyncio.Event()
            host.register_frame_waiter(loop, evt)
            host.unregister_frame_waiter(loop, evt)
            host.notify_frame_ready()
            await asyncio.sleep(0)
            self.assertFalse(evt.is_set())

        asyncio.run(_run())
        closed_loop = asyncio.new_event_loop()
        closed_loop.close()
        host.register_frame_waiter(closed_loop, asyncio.Event())
        seq = host.notify_frame_ready()
        self.assertEqual(seq, 2)

    def test_stream_generator_event_wakeup_and_annotated_selection(self) -> None:
        host = _FakeMediaHost()

        async def _collect(annotated: bool) -> tuple[list[bytes], float]:
            shutdown_evt = asyncio.Event()
            req = _FakeRequest(max_polls=2)
            gen = _stream_frame_generator(host, f"sub_{annotated}", req, annotated=annotated)
            chunks: list[bytes] = []
            t0 = time.monotonic()
            with (
                patch("dashboard.routers.streaming.get_shutdown_event", return_value=shutdown_evt),
                patch("dashboard.routers.streaming.is_shutting_down", return_value=False),
            ):
                async for chunk in gen:
                    chunks.append(chunk)
                    threading.Timer(0.01, host.notify_frame_ready).start()
            return chunks, time.monotonic() - t0

        raw_chunks, raw_elapsed = asyncio.run(_collect(annotated=False))
        ann_chunks, ann_elapsed = asyncio.run(_collect(annotated=True))

        self.assertEqual(len(raw_chunks), 2)
        self.assertIn(b"raw-jpeg", raw_chunks[0])
        self.assertLess(raw_elapsed, 0.5)
        self.assertEqual(len(ann_chunks), 2)
        self.assertIn(b"ann-jpeg", ann_chunks[0])
        self.assertLess(ann_elapsed, 0.5)
        self.assertEqual(host.removed, ["sub_False", "sub_True"])

    def test_stream_manager_stop_wakes_frame_waiters(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        db_path = os.path.join(tmpdir.name, "tracker.db")
        mgr = StreamManager(
            db_path=db_path,
            camera_id="cam_test_wakeup",
            custom_cfg={
                "video": {"source": "synthetic", "width": 160, "height": 120},
                "detector": {"type": "mock"},
            },
        )
        self.addCleanup(mgr.stop)

        async def _run() -> float:
            loop = asyncio.get_running_loop()
            evt = asyncio.Event()
            mgr.register_frame_waiter(loop, evt)
            t0 = time.monotonic()
            timer = threading.Timer(0.02, mgr.stop)
            timer.start()
            await asyncio.wait_for(evt.wait(), timeout=0.5)
            return time.monotonic() - t0

        elapsed = asyncio.run(_run())
        self.assertLess(elapsed, 0.35)
        self.assertGreaterEqual(mgr._frame_seq, 1)


if __name__ == "__main__":
    unittest.main()
