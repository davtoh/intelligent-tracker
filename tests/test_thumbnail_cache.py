#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit tests for ThumbnailCache and StreamWorker thumbnail hook (E9, E15)."""

import threading
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from dashboard.services.multiview.thumbnail_cache import ThumbnailCache, normalize_tier
from dashboard.services.stream_worker import FrameStepResult, StreamWorker


class TestThumbnailCache(unittest.TestCase):
    """Verify lease gating, tier normalization, FPS throttling, and pruning."""

    def test_normalize_tier_snaps_to_canonical_widths(self) -> None:
        self.assertEqual(normalize_tier(200), 320)
        self.assertEqual(normalize_tier(320), 320)
        self.assertEqual(normalize_tier(400), 480)
        self.assertEqual(normalize_tier(480), 480)
        self.assertEqual(normalize_tier(640), 640)
        self.assertEqual(normalize_tier(1280), 640)

    def test_no_leases_skips_encode(self) -> None:
        cache = ThumbnailCache("cam_01")
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        updated = cache.update_frame(frame, seq=1, timestamp_s=10.0)
        self.assertEqual(updated, [])
        self.assertFalse(cache.has_leases())
        self.assertIsNone(cache.get_latest(480))

    def test_shared_tier_encodes_once_at_highest_fps(self) -> None:
        cache = ThumbnailCache("cam_01", quality=70)
        self.assertEqual(cache.acquire_lease("s1", 480, 5), 480)
        self.assertEqual(cache.acquire_lease("s2", 400, 10), 480)
        self.assertEqual(cache.active_tier_fps(), {480: 10.0})

        frame = np.full((720, 1280, 3), 120, dtype=np.uint8)
        self.assertEqual(cache.update_frame(frame, seq=1, timestamp_s=1.0), [480])
        slot = cache.get_latest(480)
        self.assertIsNotNone(slot)
        self.assertEqual(slot.seq, 1)
        arr = cv2.imdecode(np.frombuffer(slot.data, np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(arr.shape[1], 480)
        self.assertEqual(arr.shape[0], 270)

    def test_fps_gate_and_lease_release_prune(self) -> None:
        cache = ThumbnailCache("cam_01")
        cache.acquire_lease("s1", 320, 2)
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        self.assertEqual(cache.update_frame(frame, seq=1, timestamp_s=10.0), [320])
        self.assertEqual(cache.update_frame(frame, seq=2, timestamp_s=10.2), [])
        self.assertEqual(cache.update_frame(frame, seq=3, timestamp_s=10.5), [320])
        self.assertEqual(cache.get_latest(320).seq, 3)

        cache.release_lease("s1")
        self.assertFalse(cache.has_leases())
        self.assertIsNone(cache.get_latest(320))

    def test_worker_uses_raw_frame_when_no_annotated_subscribers(self) -> None:
        mgr = MagicMock()
        mgr._lock = threading.RLock()
        mgr._latest_raw_jpeg = b"raw"
        mgr._latest_jpeg = b"ann"
        mgr.has_raw_subscribers = False
        mgr.has_annotated_subscribers = False
        mgr._recording_controller = None
        mgr.thumbnail_cache = ThumbnailCache("cam_01")
        mgr.thumbnail_cache.acquire_lease("s1", 320, 10)
        worker = StreamWorker(mgr)
        step_res = FrameStepResult(
            frame=np.zeros((240, 320, 3), dtype=np.uint8),
            tracks={}, timestamp=5.0, fps=10.0, frame_count=7,
        )
        with patch.object(worker, "_encode_annotated_frame") as enc_ann:
            worker._process_single_frame(step_res)
            enc_ann.assert_not_called()
        self.assertEqual(mgr.thumbnail_cache.get_latest(320).seq, 7)


if __name__ == "__main__":
    unittest.main()
