"""
Unit tests for CaptureReadGuard, camera read circuit-breaker, and lock-free pool teardown.
"""

import threading
import time
import unittest
from unittest.mock import MagicMock
import numpy as np

from dashboard.camera_pool import CameraPool
from intelligent_tracker.video.capture_guard import CaptureReadGuard, CircuitState
from intelligent_tracker.video.source import VideoSource


class DummyHangingCap:
    """Mock capture device that hangs indefinitely on read()."""

    def __init__(self, hang_delay: float = 5.0):
        self.hang_delay = hang_delay
        self.is_opened = True
        self.release_called = False
        self.unblock_event = threading.Event()

    def isOpened(self) -> bool:
        return self.is_opened

    def read(self):
        # Hang until unblocked or delay expires
        self.unblock_event.wait(timeout=self.hang_delay)
        return False, None

    def release(self):
        self.release_called = True
        self.is_opened = False
        self.unblock_event.set()


class DummyQuickCap:
    """Mock capture device that returns predictable frames or empty responses."""

    def __init__(self, ret: bool = True, frame: np.ndarray | None = None):
        self.ret = ret
        self.frame = frame if frame is not None else np.zeros((10, 10, 3), dtype=np.uint8)
        self.release_called = False

    def isOpened(self) -> bool:
        return True

    def read(self):
        return self.ret, self.frame

    def release(self):
        self.release_called = True


class TrackingHangingCap:
    """Mock capture device that records concurrent and total read()/release() calls."""

    def __init__(self, hang_delay: float = 3.0):
        self.hang_delay = hang_delay
        self.read_calls = 0
        self.release_calls = 0
        self.active_readers = 0
        self.max_concurrent_readers = 0
        self.is_opened = True
        self.unblock_event = threading.Event()
        self._lock = threading.Lock()

    def isOpened(self) -> bool:
        return self.is_opened

    def read(self):
        with self._lock:
            self.read_calls += 1
            self.active_readers += 1
            if self.active_readers > self.max_concurrent_readers:
                self.max_concurrent_readers = self.active_readers
        try:
            self.unblock_event.wait(timeout=self.hang_delay)
            return False, None
        finally:
            with self._lock:
                self.active_readers -= 1

    def release(self):
        with self._lock:
            self.release_calls += 1
            self.is_opened = False
        self.unblock_event.set()


class TestCaptureCircuitBreaker(unittest.TestCase):
    """Test suite for CaptureReadGuard, driver unbind, and circuit state machine."""

    def setUp(self) -> None:
        self.guard = CaptureReadGuard(
            timeout=0.15,
            stalled_threshold=3,
            reconnect_threshold=5,
        )

    def tearDown(self) -> None:
        self.guard.stop()

    def test_healthy_read(self) -> None:
        """Verify successful frame read keeps circuit in HEALTHY state."""
        frame = np.ones((20, 20, 3), dtype=np.uint8)
        cap = DummyQuickCap(ret=True, frame=frame)

        ret, res_frame = self.guard.read(cap, timeout=0.2)
        self.assertTrue(ret)
        self.assertIsNotNone(res_frame)
        self.assertEqual(self.guard.state, CircuitState.HEALTHY)
        self.assertEqual(self.guard.consecutive_failures, 0)
        self.assertTrue(self.guard.is_healthy)

    def test_empty_frame_transitions_to_stalled_and_reconnecting(self) -> None:
        """Verify consecutive empty frames trip HEALTHY -> STALLED -> RECONNECTING."""
        cap = DummyQuickCap(ret=False, frame=None)

        # 1st and 2nd failures
        for expected in range(1, 3):
            self.guard.read(cap, timeout=0.2)
            self.assertEqual(self.guard.consecutive_failures, expected)
            self.assertEqual(self.guard.state, CircuitState.HEALTHY)

        # 3rd failure -> trips to STALLED (stalled_threshold=3)
        self.guard.read(cap, timeout=0.2)
        self.assertEqual(self.guard.consecutive_failures, 3)
        self.assertEqual(self.guard.state, CircuitState.STALLED)
        self.assertTrue(self.guard.is_stalled)

        # 4th failure
        self.guard.read(cap, timeout=0.2)
        self.assertEqual(self.guard.consecutive_failures, 4)
        self.assertEqual(self.guard.state, CircuitState.STALLED)

        # 5th failure -> trips to RECONNECTING (reconnect_threshold=5)
        self.guard.read(cap, timeout=0.2)
        self.assertEqual(self.guard.consecutive_failures, 5)
        self.assertEqual(self.guard.state, CircuitState.RECONNECTING)
        self.assertTrue(self.guard.is_reconnecting)

        # Recovery on valid frame
        valid_cap = DummyQuickCap(ret=True)
        ret, frame = self.guard.read(valid_cap, timeout=0.2)
        self.assertTrue(ret)
        self.assertEqual(self.guard.state, CircuitState.HEALTHY)
        self.assertEqual(self.guard.consecutive_failures, 0)

    def test_timeout_tripping_on_hung_camera(self) -> None:
        """Verify bounded read timeout trips when cap.read() deadlocks in C++."""
        hanging_cap = DummyHangingCap(hang_delay=5.0)
        start = time.time()

        # Bounded read with 0.15s timeout
        ret, frame = self.guard.read(hanging_cap, timeout=0.15)
        elapsed = time.time() - start

        # Must return in ~0.15s, strictly well under 0.6s
        self.assertLess(elapsed, 0.6)
        self.assertFalse(ret)
        self.assertIsNone(frame)
        self.assertGreaterEqual(self.guard.consecutive_failures, 1)

        # Clean up hanging cap
        hanging_cap.release()

    def test_safe_driver_unbind_invoked_on_timeout(self) -> None:
        """Verify safe unbind callback is triggered in background when read times out."""
        unbind_event = threading.Event()
        hanging_cap = DummyHangingCap(hang_delay=5.0)

        def mock_unbind(cap):
            cap.release()
            unbind_event.set()

        guard = CaptureReadGuard(timeout=0.1, safe_unbind_cb=mock_unbind)
        try:
            ret, frame = guard.read(hanging_cap, timeout=0.1)
            self.assertFalse(ret)
            # Safe unbind should be invoked asynchronously
            self.assertTrue(unbind_event.wait(timeout=1.0))
            self.assertTrue(hanging_cap.release_called)
        finally:
            guard.stop()
            hanging_cap.release()

    def test_manual_trip_and_reset(self) -> None:
        """Verify manual trip and reset controls."""
        self.guard.trip(CircuitState.STALLED)
        self.assertEqual(self.guard.state, CircuitState.STALLED)
        self.assertGreaterEqual(self.guard.consecutive_failures, 3)

        self.guard.reset()
        self.assertEqual(self.guard.state, CircuitState.HEALTHY)
        self.assertEqual(self.guard.consecutive_failures, 0)

    def test_stop_event_cancels_read_immediately(self) -> None:
        """Verify stop_event interrupts pending read without waiting for timeout."""
        hanging_cap = DummyHangingCap(hang_delay=5.0)
        stop_event = threading.Event()
        stop_event.set()  # pre-set stop event

        start = time.time()
        ret, frame = self.guard.read(hanging_cap, timeout=2.0, stop_event=stop_event)
        elapsed = time.time() - start

        self.assertLess(elapsed, 0.1)
        self.assertFalse(ret)
        self.assertIsNone(frame)
        hanging_cap.release()

    def test_video_source_with_hung_camera_terminates_promptly(self) -> None:
        """Verify VideoSource background worker doesn't deadlock when camera read hangs."""
        hanging_cap = DummyHangingCap(hang_delay=10.0)
        source = VideoSource(source="synthetic", auto_reconnect=False, read_timeout=0.15)
        # Substitute internal cap with hanging mock
        source._cap = hanging_cap
        source._running = True
        source._stop_event.clear()
        source._thread = threading.Thread(target=source._capture_worker, daemon=True)
        source._thread.start()

        time.sleep(0.1)
        # Calling stop() must finish within 1.0s and not hang for 10s
        stop_start = time.time()
        source.stop()
        stop_duration = time.time() - stop_start

        self.assertLess(stop_duration, 1.0)
        self.assertFalse(source.is_alive())
        hanging_cap.release()

    def test_timeout_severs_cap_without_spawning_concurrent_readers(self) -> None:
        """Verify stalled capture device receives at most 1 read() call before release and self._cap is cleared."""
        hanging_cap = TrackingHangingCap(hang_delay=3.0)
        source = VideoSource(source="synthetic", auto_reconnect=False, read_timeout=0.1)
        source._cap = hanging_cap
        source._running = True
        source._stop_event.clear()
        source._thread = threading.Thread(target=source._capture_worker, daemon=True)
        source._thread.start()

        # Wait for read timeout to trigger and worker to sever handle and exit
        for _ in range(30):
            if source._cap is None and hanging_cap.release_calls > 0:
                break
            time.sleep(0.05)

        source.stop()

        # Invariants:
        # 1. Stalled cap was read at most once (zero iterations 2-4 concurrent cascade)
        self.assertEqual(hanging_cap.read_calls, 1)
        self.assertEqual(hanging_cap.max_concurrent_readers, 1)
        # 2. Release was dispatched
        self.assertGreaterEqual(hanging_cap.release_calls, 1)
        # 3. self._cap was immediately cleared without waiting for reconnect threshold
        self.assertIsNone(source._cap)
        self.assertFalse(source.is_connected)
        hanging_cap.release()

    def test_auto_reconnect_recovers_after_timeout(self) -> None:
        """Verify VideoSource successfully re-opens capture after a timed-out driver is severed."""
        hanging_cap = TrackingHangingCap(hang_delay=3.0)
        source = VideoSource(source="synthetic", auto_reconnect=True, reconnect_delay=0.02, read_timeout=0.1)
        source._cap = hanging_cap
        source._running = True
        source._stop_event.clear()
        source._thread = threading.Thread(target=source._capture_worker, daemon=True)
        source._thread.start()

        # Should recover and read a synthetic frame
        ret, frame = source.read(timeout=1.0)
        source.stop()

        self.assertTrue(ret)
        self.assertIsNotNone(frame)
        self.assertEqual(hanging_cap.read_calls, 1)
        self.assertGreaterEqual(hanging_cap.release_calls, 1)
        hanging_cap.release()

    def test_com_initialization_on_win32_worker(self) -> None:
        """Verify Windows COM apartment is initialized and uninitialized on reader worker thread."""
        mock_ole32 = MagicMock()
        mock_ole32.CoInitializeEx.return_value = 0  # S_OK

        mock_windll = MagicMock()
        mock_windll.ole32 = mock_ole32

        with unittest.mock.patch("sys.platform", "win32"), \
             unittest.mock.patch("ctypes.windll", mock_windll, create=True):
            cap = DummyQuickCap(ret=True)
            guard = CaptureReadGuard(timeout=0.2)
            job = None
            try:
                ret, frame = guard.read(cap, timeout=0.2)
                self.assertTrue(ret)
                job = guard._current_job
            finally:
                guard.stop()
                if job and job.thread and job.thread.is_alive():
                    job.thread.join(timeout=1.0)

            # Ensure COM was initialized and cleanly uninitialized
            mock_ole32.CoInitializeEx.assert_called_once_with(None, 0)
            mock_ole32.CoUninitialize.assert_called_once()


class TestCameraPoolLockFreeTeardown(unittest.TestCase):
    """Verify CameraPool.stop_all releases locks before joining worker threads."""

    def test_stop_all_releases_lock_during_worker_teardown(self) -> None:
        """Verify self._lock is accessible while managers are stopping."""
        pool = CameraPool(autostart=False)
        stop_entered = threading.Event()
        can_proceed_stop = threading.Event()

        class SlowStreamManager:
            def signal_stop(self):
                pass

            def stop(self):
                stop_entered.set()
                # Simulate blocking IO / hardware teardown in stream manager
                can_proceed_stop.wait(timeout=1.0)

        mock_stream = SlowStreamManager()
        pool.streams = {"cam_01": mock_stream}

        # Launch stop_all in a background thread
        stop_thread = threading.Thread(target=lambda: pool.stop_all(parallel=True), daemon=True)
        stop_thread.start()

        # Wait until mock_stream.stop() is running
        self.assertTrue(stop_entered.wait(timeout=1.0))

        # While mock_stream is still stopping, verify another thread can acquire pool._lock
        # If stop_all holds the lock across stop(), acquire will time out!
        lock_acquired = pool._lock.acquire(timeout=0.2)
        try:
            self.assertTrue(lock_acquired, "CameraPool._lock was blocked during worker stop()!")
        finally:
            if lock_acquired:
                pool._lock.release()

        # Unblock the stream manager stop and let stop_thread finish
        can_proceed_stop.set()
        stop_thread.join(timeout=1.0)
        self.assertFalse(stop_thread.is_alive())
        self.assertEqual(len(pool.streams), 0)


if __name__ == "__main__":
    unittest.main()

