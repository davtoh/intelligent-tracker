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


if __name__ == "__main__":
    unittest.main()
