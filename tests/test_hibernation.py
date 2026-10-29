#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Unit Tests for Deep Hibernation & Leased Subscriber Registry.
Verifies zero-load hibernation, self-healing leased subscriber eviction,
and VideoSource pause/resume lifecycle without deadlocks.
"""

import time
import unittest
from unittest.mock import MagicMock, AsyncMock

from intelligent_tracker.video import VideoSource
from dashboard.stream_manager import StreamManager


class TestVideoSourceHibernation(unittest.TestCase):
    """Verifies VideoSource pause/resume behavior."""

    def test_pause_and_resume_lifecycle(self):
        vs = VideoSource(source="synthetic", fps_limit=30, buffer_size=1)
        vs.start(wait_for_ready=True)

        self.assertFalse(vs.is_paused)

        # Pause capture
        vs.pause()
        self.assertTrue(vs.is_paused)

        # Resume capture
        vs.resume()
        self.assertFalse(vs.is_paused)

        # Verify frames continue flowing
        ret, frame = vs.read(timeout=2.0)
        self.assertTrue(ret)
        self.assertIsNotNone(frame)

        vs.stop()

    def test_stop_while_paused_does_not_deadlock(self):
        vs = VideoSource(source="synthetic", fps_limit=30, buffer_size=1)
        vs.start(wait_for_ready=True)

        vs.pause()
        self.assertTrue(vs.is_paused)

        # Stopping while paused should cleanly unblock worker and join
        vs.stop()
        self.assertFalse(vs.is_paused)


class TestStreamManagerLeasedSubscribers(unittest.TestCase):
    """Verifies StreamManager leased subscriber registry and auto-pruning."""

    def setUp(self):
        self.sm = StreamManager(
            camera_id="test_cam",
            source_override="synthetic",
            custom_cfg={"detector": {"model": "mock"}, "tracker": {"type": "centroid"}},
        )

    def tearDown(self):
        if self.sm.is_running:
            self.sm.stop()

    def test_add_and_remove_subscriber(self):
        self.assertEqual(self.sm.subscriber_count, 0)

        token = self.sm.add_subscriber("client_abc")
        self.assertEqual(token, "client_abc")
        self.assertEqual(self.sm.subscriber_count, 1)

        self.sm.heartbeat_subscriber("client_abc")
        self.assertEqual(self.sm.subscriber_count, 1)

        rem = self.sm.remove_subscriber("client_abc")
        self.assertEqual(rem, 0)
        self.assertEqual(self.sm.subscriber_count, 0)

    def test_stale_subscriber_auto_pruning(self):
        self.sm.add_subscriber("stale_client")
        self.assertEqual(self.sm.subscriber_count, 1)

        # Artificially age the subscriber lease beyond 3.0s
        with self.sm._subscriber_lock:
            self.sm._subscribers["stale_client"] = time.time() - 5.0

        # subscriber_count property must automatically prune expired lease
        count = self.sm.subscriber_count
        self.assertEqual(count, 0)
        with self.sm._subscriber_lock:
            self.assertNotIn("stale_client", self.sm._subscribers)

    def test_hibernation_state_transitions(self):
        self.sm.start()
        time.sleep(0.3)

        # Initially no subscribers -> should transition to hibernating
        # Let worker run one cycle
        time.sleep(0.5)
        self.assertTrue(self.sm.is_hibernating)
        if self.sm.video_source:
            self.assertTrue(self.sm.video_source.is_paused)

        # Client connects -> wakes up immediately
        token = self.sm.add_subscriber("active_viewer")
        time.sleep(0.4)
        self.assertFalse(self.sm.is_hibernating)
        if self.sm.video_source:
            self.assertFalse(self.sm.video_source.is_paused)

        # Client disconnects -> returns to hibernation
        self.sm.remove_subscriber(token)
        time.sleep(0.5)
        self.assertTrue(self.sm.is_hibernating)


if __name__ == "__main__":
    unittest.main()

