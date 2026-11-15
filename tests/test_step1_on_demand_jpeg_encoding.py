"""Tests for subscriber-aware on-demand raw and annotated JPEG encoding."""

import asyncio
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from dashboard.routers.streaming import _stream_frame_generator
from dashboard.services.stream_subscribers import StreamSubscriberMixin, StreamSubscriberRegistry
from dashboard.services.stream_worker import StreamWorker
from intelligent_tracker.pipeline import FrameStepResult


class _DummySubscriberOwner(StreamSubscriberMixin):
    """Minimal host for testing StreamSubscriberMixin delegation."""

    def __init__(self, lease_ttl: float = 3.0) -> None:
        self._subscriber_registry = StreamSubscriberRegistry(lease_ttl=lease_ttl)


def _make_worker_manager(
    *,
    has_raw: bool = False,
    has_annotated: bool = False,
    raw_cached: bytes | None = b"raw",
    ann_cached: bytes | None = b"ann",
    is_recording: bool = False,
) -> MagicMock:
    """Build a lightweight mock StreamManager for StreamWorker frame-encoding tests."""
    mgr = MagicMock()
    mgr._lock = threading.Lock()
    mgr._stop_event = threading.Event()
    mgr._latest_raw_jpeg = raw_cached
    mgr._latest_jpeg = ann_cached
    mgr.has_raw_subscribers = has_raw
    mgr.has_annotated_subscribers = has_annotated
    mgr.camera_id = "cam0"
    mgr.start_time = 0.0
    mgr.overlays = {}
    mgr.draw_heatmap = False
    mgr.homography.is_calibrated = False
    mgr.homography.track_to_ground.return_value = (0.0, 0.0)
    mgr.analytics = None
    mgr.rsac_manager = None
    mgr.event_bus = None
    mgr._overlay_renderer.render.side_effect = lambda **kw: kw["frame"]
    recorder = MagicMock()
    recorder.is_recording = is_recording
    mgr._recording_controller = recorder
    return mgr


def _make_step_result() -> FrameStepResult:
    """Create a minimal 16x16 FrameStepResult fixture."""
    frame = np.zeros((16, 16, 3), dtype=np.uint8)
    return FrameStepResult(frame=frame, tracks={}, frame_count=2, timestamp=1.0, fps=30.0)


class TestStreamSubscriberModes(unittest.TestCase):
    """Verify raw/annotated lease tracking and TTL expiration."""

    def test_tracks_raw_and_annotated_modes_independently(self) -> None:
        reg = StreamSubscriberRegistry(lease_ttl=5.0)
        self.assertFalse(reg.has_raw_subscribers)
        self.assertFalse(reg.has_annotated_subscribers)

        reg.add_subscriber("raw1", annotated=False)
        self.assertTrue(reg.has_raw_subscribers)
        self.assertFalse(reg.has_annotated_subscribers)

        reg.add_subscriber("ann1", annotated=True)
        self.assertTrue(reg.has_raw_subscribers)
        self.assertTrue(reg.has_annotated_subscribers)

        reg.remove_subscriber("raw1")
        self.assertFalse(reg.has_raw_subscribers)
        self.assertTrue(reg.has_annotated_subscribers)

    def test_ttl_expiration_clears_mode_flags(self) -> None:
        reg = StreamSubscriberRegistry(lease_ttl=0.02)
        reg.add_subscriber("raw_only", annotated=False)
        self.assertTrue(reg.has_raw_subscribers)

        time.sleep(0.05)
        self.assertFalse(reg.has_raw_subscribers)
        self.assertFalse(reg.has_annotated_subscribers)
        self.assertEqual(reg.subscriber_count, 0)

    def test_ws_only_subscriber_leaves_jpeg_modes_false(self) -> None:
        reg = StreamSubscriberRegistry(lease_ttl=5.0)
        reg.register_ws_subscriber(MagicMock())
        self.assertEqual(reg.subscriber_count, 1)
        self.assertFalse(reg.has_raw_subscribers)
        self.assertFalse(reg.has_annotated_subscribers)

    def test_mixin_delegates_mode_properties(self) -> None:
        owner = _DummySubscriberOwner()
        owner.add_subscriber("r1", annotated=False)
        self.assertTrue(owner.has_raw_subscribers)
        self.assertFalse(owner.has_annotated_subscribers)


class TestOnDemandJpegEncoding(unittest.TestCase):
    """Verify StreamWorker skips redundant cv2.imencode calls based on subscribers."""

    def test_skips_annotated_encode_when_only_raw_subscriber_connected(self) -> None:
        mgr = _make_worker_manager(has_raw=True, has_annotated=False)
        worker = StreamWorker(mgr)
        with patch("dashboard.services.stream_worker.cv2.imencode", return_value=(True, np.array([1, 2], dtype=np.uint8))) as enc:
            worker._process_single_frame(_make_step_result())
        self.assertEqual(enc.call_count, 1)
        mgr._overlay_renderer.render.assert_not_called()

    def test_skips_raw_encode_when_only_annotated_subscriber_connected(self) -> None:
        mgr = _make_worker_manager(has_raw=False, has_annotated=True)
        worker = StreamWorker(mgr)
        with patch("dashboard.services.stream_worker.cv2.imencode", return_value=(True, np.array([1, 2], dtype=np.uint8))) as enc:
            worker._process_single_frame(_make_step_result())
        self.assertEqual(enc.call_count, 1)
        mgr._overlay_renderer.render.assert_called_once()

    def test_skips_all_jpeg_encoding_when_only_ws_subscriber_connected(self) -> None:
        mgr = _make_worker_manager(has_raw=False, has_annotated=False)
        worker = StreamWorker(mgr)
        with patch("dashboard.services.stream_worker.cv2.imencode", return_value=(True, np.array([1, 2], dtype=np.uint8))) as enc:
            worker._process_single_frame(_make_step_result())
        enc.assert_not_called()
        mgr._overlay_renderer.render.assert_not_called()

    def test_seeds_missing_cache_and_encodes_for_active_recording(self) -> None:
        mgr = _make_worker_manager(
            has_raw=False, has_annotated=False, raw_cached=None, ann_cached=None, is_recording=True
        )
        worker = StreamWorker(mgr)
        with patch("dashboard.services.stream_worker.cv2.imencode", return_value=(True, np.array([1, 2], dtype=np.uint8))) as enc:
            worker._process_single_frame(_make_step_result())
        self.assertEqual(enc.call_count, 2)
        mgr._recording_controller.write_frame.assert_called_once()

    def test_streaming_generator_forwards_annotated_flag(self) -> None:
        mgr = MagicMock()
        mgr.get_latest_frame_jpeg.return_value = b"jpg"
        req = MagicMock()

        async def _disconnect_immediately() -> bool:
            return True

        req.is_disconnected = _disconnect_immediately

        async def _consume() -> None:
            async for _ in _stream_frame_generator(mgr, "sub1", req, annotated=False):
                pass

        asyncio.run(_consume())
        mgr.add_subscriber.assert_called_once_with("sub1", annotated=False)
        mgr.remove_subscriber.assert_called_once_with("sub1")
