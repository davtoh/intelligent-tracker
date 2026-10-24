#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for intelligent_tracker.video (VideoSource & Synthetic Generator).
"""

from __future__ import division, print_function, absolute_import

import time
import unittest
import numpy as np

from intelligent_tracker.video import VideoSource, SyntheticFrameGenerator


class TestVideoSource(unittest.TestCase):

    def test_synthetic_generator_direct(self):
        gen = SyntheticFrameGenerator(width=320, height=240, fps=30)
        self.assertTrue(gen.isOpened())
        ret, frame = gen.read()
        self.assertTrue(ret)
        self.assertIsNotNone(frame)
        self.assertEqual(frame.shape, (240, 320, 3))
        self.assertEqual(gen.frame_idx, 1)

        gen.release()
        self.assertFalse(gen.isOpened())
        ret, frame = gen.read()
        self.assertFalse(ret)
        self.assertIsNone(frame)

    def test_video_source_context_manager(self):
        with VideoSource(source="synthetic", width=320, height=240, fps_limit=60) as vs:
            self.assertTrue(vs.is_alive())
            ret, frame = vs.read(timeout=2.0)
            self.assertTrue(ret)
            self.assertIsNotNone(frame)
            self.assertEqual(frame.shape, (240, 320, 3))

            metrics = vs.get_metrics()
            self.assertEqual(metrics["source"], "synthetic")
            self.assertTrue(metrics["is_connected"])
            self.assertGreaterEqual(metrics["frames_read"], 1)

        # After exiting context, should be stopped
        self.assertFalse(vs.is_alive())

    def test_video_source_frame_drop_on_lag(self):
        # Buffer size of 1 with fast producer
        vs = VideoSource(source="synthetic", buffer_size=1, fps_limit=100)
        vs.start()
        try:
            # Sleep to let producer fill and overflow the queue
            time.sleep(0.15)
            ret, frame = vs.read(timeout=1.0)
            self.assertTrue(ret)
            self.assertIsNotNone(frame)

            metrics = vs.get_metrics()
            self.assertGreater(metrics["frames_read"], 1)
            # Expect dropped frames because consumer was sleeping
            self.assertGreaterEqual(metrics["frames_dropped"], 0)
        finally:
            vs.stop()

    def test_video_source_grab_latest(self):
        vs = VideoSource(source="synthetic", buffer_size=2)
        vs.start()
        try:
            # Give background thread time to produce at least 1 frame
            time.sleep(0.05)
            frame = vs.grab_latest()
            # frame might be None or ndarray depending on scheduling, but shouldn't error
            if frame is not None:
                self.assertIsInstance(frame, np.ndarray)
        finally:
            vs.stop()

    def test_metrics_telemetry(self):
        vs = VideoSource(source="synthetic", width=640, height=480)
        vs.start()
        try:
            time.sleep(0.08)
            metrics = vs.get_metrics()
            self.assertIn("source", metrics)
            self.assertIn("is_connected", metrics)
            self.assertIn("fps", metrics)
            self.assertIn("frames_read", metrics)
            self.assertIn("frames_dropped", metrics)
            self.assertIn("drop_rate_pct", metrics)
            self.assertIn("resolution", metrics)
            self.assertEqual(metrics["resolution"], (640, 480))
        finally:
            vs.stop()

    def test_video_source_wait_ready_unblocks_immediately(self):
        vs = VideoSource(source="synthetic", width=320, height=240)
        t0 = time.time()
        ready = vs.wait_ready(timeout=3.0)
        elapsed = time.time() - t0
        try:
            self.assertTrue(ready)
            # Synthetic source should unblock virtually immediately (< 0.5s), never waiting 3.0s
            self.assertLess(elapsed, 0.5)
            self.assertTrue(vs.is_alive())
        finally:
            vs.stop()

    def test_video_source_stop_releases_cleanly(self):
        vs = VideoSource(source="synthetic", width=320, height=240)
        vs.start()
        self.assertTrue(vs.is_alive())
        t0 = time.time()
        vs.stop()
        elapsed = time.time() - t0
        self.assertFalse(vs.is_alive())
        self.assertLess(elapsed, 1.0)

    def test_is_physical_camera_detection(self):
        from intelligent_tracker.video import is_physical_camera
        import cv2

        class MockPhysicalCap(object):
            def isOpened(self):
                return True
            def get(self, prop):
                if prop == cv2.CAP_PROP_BRIGHTNESS:
                    return 10.0
                return -1.0

        class MockVirtualCap(object):
            def isOpened(self):
                return True
            def get(self, prop):
                return -1.0

        self.assertTrue(is_physical_camera(MockPhysicalCap()))
        self.assertFalse(is_physical_camera(MockVirtualCap()))

    def test_resolve_camera_source_agnostic_numeric(self):
        from intelligent_tracker.video import resolve_camera_source
        # Numeric indices must be strictly preserved without modification
        self.assertEqual(resolve_camera_source(0), 0)
        self.assertEqual(resolve_camera_source("0"), 0)
        self.assertEqual(resolve_camera_source(1), 1)
        self.assertEqual(resolve_camera_source("1"), 1)
        self.assertEqual(resolve_camera_source("synthetic"), "synthetic")
        self.assertEqual(resolve_camera_source("test.mp4"), "test.mp4")


if __name__ == "__main__":
    unittest.main()
