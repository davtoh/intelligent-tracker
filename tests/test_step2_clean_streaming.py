#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit tests for Step 2 Milestone 1: clean un-burned MJPEG streaming."""

import asyncio
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from dashboard.routers.streaming import _stream_frame_generator, get_live_stream
from dashboard.services.stream_media import StreamMediaMixin
from dashboard.services.stream_worker import StreamWorker


class _DummyMediaHost(StreamMediaMixin):
    """Minimal isolated host for StreamMediaMixin frame selection tests."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._latest_jpeg = None
        self._latest_raw_jpeg = None


class TestCleanStreamingMedia(unittest.TestCase):
    """Verify annotated=True vs annotated=False frame selection and fallback."""

    def test_get_latest_frame_jpeg_selects_raw_when_unannotated(self) -> None:
        host = _DummyMediaHost()
        host._latest_jpeg = b"ANNOTATED_BYTES"
        host._latest_raw_jpeg = b"RAW_BYTES"

        self.assertEqual(host.get_latest_frame_jpeg(annotated=True), b"ANNOTATED_BYTES")
        self.assertEqual(host.get_latest_frame_jpeg(annotated=False), b"RAW_BYTES")
        self.assertEqual(host.get_latest_frame_jpeg(), b"ANNOTATED_BYTES")

    def test_get_latest_frame_jpeg_falls_back_when_raw_missing(self) -> None:
        host = _DummyMediaHost()
        host._latest_jpeg = b"FALLBACK_ANNOTATED"
        self.assertEqual(host.get_latest_frame_jpeg(annotated=False), b"FALLBACK_ANNOTATED")

        host._latest_jpeg = None
        placeholder = host.get_latest_frame_jpeg(annotated=False)
        self.assertTrue(placeholder.startswith(b"\xff\xd8"))


class TestStreamWorkerRawEncoding(unittest.TestCase):
    """Verify StreamWorker._encode_raw_frame preserves clean un-burned pixels."""

    def test_encode_raw_frame_stores_clean_jpeg(self) -> None:
        manager = SimpleNamespace(
            _lock=threading.RLock(),
            _latest_raw_jpeg=None,
            _latest_jpeg=None,
            camera_id="cam_test",
            overlays={"bboxes": True},
            start_time=0.0,
            analytics=None,
            rsac_manager=None,
            homography=None,
            draw_heatmap=False,
        )
        burned = np.full((120, 160, 3), 240, dtype=np.uint8)
        manager._overlay_renderer = SimpleNamespace(render=MagicMock(return_value=burned))
        worker = StreamWorker(manager)

        clean_frame = np.full((120, 160, 3), 20, dtype=np.uint8)
        worker._encode_raw_frame(clean_frame)
        worker._encode_annotated_frame(clean_frame, tracks={}, measured_fps=30.0)

        self.assertIsNotNone(manager._latest_raw_jpeg)
        self.assertIsNotNone(manager._latest_jpeg)

        raw_img = cv2.imdecode(np.frombuffer(manager._latest_raw_jpeg, np.uint8), cv2.IMREAD_COLOR)
        ann_img = cv2.imdecode(np.frombuffer(manager._latest_jpeg, np.uint8), cv2.IMREAD_COLOR)
        self.assertLess(float(np.mean(raw_img)), 35.0)
        self.assertGreater(float(np.mean(ann_img)), 220.0)


class TestStreamingRouterQueryFlag(unittest.TestCase):
    """Verify get_live_stream forwards annotated query flag to StreamManager."""

    def test_stream_frame_generator_forwards_annotated_flag(self) -> None:
        mgr = MagicMock()
        mgr.get_latest_frame_jpeg.return_value = b"FRAME_BYTES"

        request = MagicMock()
        request.is_disconnected = MagicMock(side_effect=[False, True])

        async def _async_false_then_true():
            for val in (False, True):
                yield val

        gen_iter = _async_false_then_true()

        async def _is_disconnected():
            return await gen_iter.__anext__()

        request.is_disconnected = _is_disconnected

        async def _collect():
            chunks = []
            async for chunk in _stream_frame_generator(mgr, "sub1", request, annotated=False):
                chunks.append(chunk)
            return chunks

        fake_evt = MagicMock()
        fake_evt.is_set.return_value = False
        async def _never_set():
            await asyncio.sleep(1.0)
        fake_evt.wait = _never_set

        with patch("dashboard.routers.streaming.is_shutting_down", return_value=False), \
             patch("dashboard.routers.streaming.get_shutdown_event", return_value=fake_evt):
            chunks = asyncio.run(_collect())

        mgr.get_latest_frame_jpeg.assert_called_with(annotated=False)
        self.assertEqual(len(chunks), 1)
        self.assertIn(b"FRAME_BYTES", chunks[0])

    def test_get_live_stream_returns_503_when_manager_missing(self) -> None:
        from fastapi import HTTPException

        req = MagicMock()
        with patch("dashboard.routers.streaming.get_active_stream_manager", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(get_live_stream("missing_cam", req, annotated=False))
        self.assertEqual(ctx.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
