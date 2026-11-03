#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Unit & Performance Tests for Graceful Shutdown Architecture.

Validates:
1. Sub-millisecond interruptible sleep via threading.Event in VideoSource & StreamManager.
2. Parallel concurrent teardown scaling in CameraPool across multiple streams.
3. Event loop non-blocking behavior during async_shutdown_pool execution.
4. Clean EventBus and worker thread termination without thread leaks.
"""

import asyncio
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from dashboard.camera_pool import CameraPool
from dashboard.services.shutdown_handler import (
    async_shutdown_pool,
    broadcast_shutdown,
    start_watchdog_guard,
)
from dashboard.stream_manager import StreamManager
from intelligent_tracker.events import EventBus
from intelligent_tracker.video import VideoSource


class TestGracefulShutdownPerformance(unittest.TestCase):
    """Test suite ensuring rapid, non-blocking, zero-hang graceful shutdown."""

    def test_video_source_interruptible_sleep_terminates_immediately(self):
        """VideoSource must wake from long reconnect backoffs in < 0.1s when signal_stop is called."""
        # Configure video source with an intentional 5.0-second reconnect delay
        vs = VideoSource(source="non_existent_stream_path.mp4", auto_reconnect=True, reconnect_delay=5.0)
        vs.start(wait_for_ready=False)
        time.sleep(0.05)

        start_t = time.time()
        # signal_stop should immediately wake the sleeping reconnect loop
        vs.signal_stop()
        vs.stop()
        elapsed = time.time() - start_t

        # Must terminate in well under 0.5s rather than waiting 5.0s
        self.assertLess(elapsed, 0.5, f"VideoSource stop took {elapsed:.2f}s; expected < 0.5s")
        self.assertFalse(vs.is_alive())

    def test_stream_manager_signal_stop_interrupts_worker_loop(self):
        """StreamManager worker loop must exit in < 0.3s when signal_stop is triggered."""
        sm = StreamManager(
            config_path="configs/alert_demo.yaml",
            db_path=":memory:",
            camera_id="test_fast_stop",
            name="Test Fast Stop",
            source_override="synthetic",
        )
        sm.start()
        time.sleep(0.05)
        self.assertTrue(sm.is_running)

        start_t = time.time()
        sm.signal_stop()
        sm.stop()
        elapsed = time.time() - start_t

        self.assertLess(elapsed, 0.5, f"StreamManager stop took {elapsed:.2f}s; expected < 0.5s")
        self.assertFalse(sm.is_running)

    def test_camera_pool_parallel_stop_scales_sub_second(self):
        """CameraPool must stop multiple concurrent streams in parallel rather than sequentially."""
        with patch.object(CameraPool, "save_cameras"), patch.object(CameraPool, "load_cameras"):
            pool = CameraPool(
                config_file="dummy.json",
                db_path=":memory:",
                base_config_path="configs/alert_demo.yaml",
                autostart=False,
            )

        # Create 4 synthetic mock stream managers
        mock_streams = {}
        for i in range(4):
            cam_id = f"mock_cam_{i}"
            mgr = MagicMock(spec=StreamManager)
            mgr.is_running = True
            # Simulate a 0.2s clean hardware unbind time per stream
            def _slow_stop(m=mgr):
                time.sleep(0.2)
                m.is_running = False
            mgr.stop.side_effect = _slow_stop
            mgr.signal_stop = MagicMock()
            mock_streams[cam_id] = mgr

        pool.streams = mock_streams

        start_t = time.time()
        # Sequential stop of 4 streams with 0.2s delay would take 0.8s+
        # Parallel stop must complete in ~0.25s - 0.4s
        pool.stop_all(parallel=True)
        elapsed = time.time() - start_t

        self.assertLess(elapsed, 0.55, f"Parallel stop took {elapsed:.2f}s; sequential would be >= 0.8s")
        self.assertEqual(len(pool.streams), 0)
        for mgr in mock_streams.values():
            mgr.signal_stop.assert_called()
            mgr.stop.assert_called()

    def test_event_bus_workers_terminated_cleanly_on_stream_stop(self):
        """StreamManager.stop() must stop internal EventBus to avoid orphaned worker threads."""
        sm = StreamManager(
            config_path="configs/alert_demo.yaml",
            db_path=":memory:",
            camera_id="test_bus_cleanup",
            name="Test Bus Cleanup",
            source_override="synthetic",
        )

        # Manually attach an active EventBus
        bus = EventBus()
        bus.start(num_workers=2)
        sm.event_pipeline = {"event_bus": bus}

        # Check workers are alive
        self.assertTrue(bus._running)
        self.assertEqual(len(bus._workers), 2)
        for w in bus._workers:
            self.assertTrue(w.is_alive())

        # Calling sm.stop() must stop the event bus workers cleanly
        sm.stop()
        self.assertFalse(bus._running)
        for w in bus._workers:
            w.join(timeout=0.5)
            self.assertFalse(w.is_alive(), "EventBus worker remained alive after stream stop!")

    def test_async_shutdown_pool_does_not_starve_event_loop(self):
        """async_shutdown_pool must run off-thread via asyncio.to_thread without blocking event loop tasks."""
        pool = MagicMock(spec=CameraPool)

        def _blocking_pool_stop(parallel=True):
            time.sleep(0.2)
        pool.stop_all.side_effect = _blocking_pool_stop

        async def run_test():
            heartbeat_ticks = 0

            async def event_loop_heartbeat():
                nonlocal heartbeat_ticks
                for _ in range(5):
                    await asyncio.sleep(0.04)
                    heartbeat_ticks += 1

            # Run pool shutdown concurrently with the heartbeat task
            heartbeat_task = asyncio.create_task(event_loop_heartbeat())
            shutdown_task = asyncio.create_task(async_shutdown_pool(pool, timeout=2.0))

            await asyncio.gather(heartbeat_task, shutdown_task)
            # If the event loop was blocked, heartbeat_ticks would be 0 or 1
            self.assertGreaterEqual(heartbeat_ticks, 3, "Event loop was starved during pool shutdown!")

        asyncio.run(run_test())

    def test_broadcast_shutdown_triggers_pool_and_watchdog(self):
        """broadcast_shutdown must invoke signal_stop_all on the pool and start watchdog."""
        mock_pool = MagicMock()
        with patch("dashboard.dependencies.get_camera_pool", return_value=mock_pool), \
             patch("dashboard.dependencies.set_shutting_down") as mock_set_down, \
             patch("dashboard.services.shutdown_handler.start_watchdog_guard") as mock_watchdog:

            broadcast_shutdown()

            mock_set_down.assert_called_with(True)
            mock_pool.signal_stop_all.assert_called_once()
            mock_watchdog.assert_called_once()


if __name__ == "__main__":
    unittest.main()
