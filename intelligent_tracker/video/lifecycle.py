"""Thread lifecycle and context management for video streams."""

import atexit
import logging
import queue
import threading
import time
from typing import Any, Optional

from intelligent_tracker.camera_device import CameraDeviceHandler

logger = logging.getLogger(__name__)


class CaptureLifecycleMixin:
    """Thread lifecycle, worker management, and context management mixin."""

    source: Any
    auto_reconnect: bool
    _cap: Any
    _thread: Optional[threading.Thread]
    _running: bool
    _is_paused: bool
    _stop_event: threading.Event
    _pause_event: threading.Event
    _ready_event: threading.Event
    _first_frame_read: bool
    _lock: threading.Lock
    _queue: queue.Queue
    _is_connected: bool
    _start_time: Optional[float]

    def start(self, wait_for_ready: bool = True, timeout: float = 3.0) -> Any:
        """Start background capture thread and wait for first valid frame."""
        with self._lock:
            if self._running:
                return self

            success = self._open_capture()
            if not success and not self.auto_reconnect:
                raise RuntimeError(f"Could not open video source: {self.source}")

            self._running = True
            self._is_paused = False
            self._stop_event.clear()
            self._pause_event.set()
            self._first_frame_read = False
            self._ready_event.clear()
            self._start_time = time.time()
            self._thread = threading.Thread(
                target=self._capture_worker, name="VideoSourceWorker", daemon=True
            )
            self._thread.start()
            try:
                atexit.register(self.stop)
            except Exception:
                pass

        if wait_for_ready:
            self.wait_ready(timeout=timeout)
        return self

    def wait_ready(self, timeout: float = 3.0) -> bool:
        """Wait until stream delivers its first valid frame, unblocking immediately when ready."""
        if not self._running:
            self.start(wait_for_ready=False)
        return self._ready_event.wait(timeout=timeout)

    def signal_stop(self) -> None:
        """Signal background worker to terminate immediately without waiting for join."""
        self._running = False
        self._is_paused = False
        self._stop_event.set()
        self._pause_event.set()
        try:
            self._queue.put_nowait(None)
        except Exception:
            pass

    def stop(self) -> None:
        """Stop background worker and release camera hardware cleanly without cross-thread races."""
        if not self._running and self._cap is None:
            return
        self.signal_stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.6)
            self._thread = None

        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

        with self._lock:
            if self._cap is not None:
                try:
                    CameraDeviceHandler.safe_release(self._cap, settle_delay=0.0)
                except Exception as e:
                    logger.debug("Exception releasing VideoSource cap: %s", e)
                finally:
                    self._cap = None
                    self._is_connected = False
        try:
            atexit.unregister(self.stop)
        except Exception:
            pass

    def release(self) -> None:
        """Compatibility alias for stop()."""
        self.stop()

    def __del__(self) -> None:
        self.stop()

    def is_alive(self) -> bool:
        """Check if worker thread is actively running."""
        return self._running and (self._thread.is_alive() if self._thread else False)

    def __enter__(self) -> Any:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()


__all__ = ["CaptureLifecycleMixin"]
