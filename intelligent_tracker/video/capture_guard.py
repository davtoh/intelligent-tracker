"""Non-blocking camera read circuit-breaker and driver unbind watchdog.

Decouples synchronous native C++ driver reads (DirectShow/MSMF on Windows,
V4L2 on Linux, AVFoundation on macOS) to prevent driver hangs post-sleep/hibernation
from deadlocking acquisition worker threads or blocking server shutdown.
"""

import logging
import sys
import threading
import time
from enum import Enum
from typing import Any, Callable, Optional, Set, Tuple
import numpy as np

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Camera driver circuit-breaker operating states."""

    HEALTHY = "HEALTHY"
    STALLED = "STALLED"
    RECONNECTING = "RECONNECTING"


class _CaptureReadJob:
    """Encapsulates a decoupled read operation in a persistent daemon worker."""

    def __init__(self, cap: Any):
        self.cap = cap
        self.trigger = threading.Event()
        self.done = threading.Event()
        self.stopped = False
        self.is_reading = False
        self.ret: bool = False
        self.frame: Optional[np.ndarray] = None
        self.thread = threading.Thread(
            target=self._run,
            name="CaptureReadJobWorker",
            daemon=True,
        )
        self.thread.start()

    def _run(self) -> None:
        """Worker loop executing cap.read() upon trigger notification."""
        com_initialized = False
        if sys.platform == "win32":
            try:
                import ctypes

                ole32 = getattr(ctypes, "windll", None)
                if ole32 is not None:
                    hr = ole32.ole32.CoInitializeEx(None, 0)
                    com_initialized = hr in (0, 1)
            except Exception as e:
                logger.debug("COM initialization skipped/failed: %s", e)

        try:
            while not self.stopped:
                if not self.trigger.wait(timeout=0.1):
                    continue
                self.trigger.clear()
                if self.stopped:
                    break
                self.is_reading = True
                try:
                    ret, frame = self.cap.read()
                except Exception as e:
                    logger.debug("Exception in cap.read() worker: %s", e)
                    ret, frame = False, None
                finally:
                    self.is_reading = False

                self.ret = ret
                self.frame = frame
                self.done.set()
        finally:
            if com_initialized:
                try:
                    import ctypes

                    ole32 = getattr(ctypes, "windll", None)
                    if ole32 is not None:
                        ole32.ole32.CoUninitialize()
                except Exception:
                    pass

    def stop(self) -> None:
        """Signal worker to terminate loop."""
        self.stopped = True
        self.trigger.set()


class CaptureReadGuard:
    """Decouples synchronous C++ driver reads with timeout and circuit-breaker.

    Transitions through states:
    HEALTHY -> STALLED (on consecutive empty frames or timeout) -> RECONNECTING.
    Triggers safe driver unbind when kernel graph stalls.
    """

    def __init__(
        self,
        timeout: float = 2.0,
        stalled_threshold: int = 3,
        reconnect_threshold: int = 5,
        safe_unbind_cb: Optional[Callable[[Any], None]] = None,
    ):
        self.timeout = float(timeout)
        self.stalled_threshold = int(stalled_threshold)
        self.reconnect_threshold = int(reconnect_threshold)
        self._safe_unbind_cb = safe_unbind_cb

        self._state = CircuitState.HEALTHY
        self._consecutive_failures = 0
        self._current_job: Optional[_CaptureReadJob] = None
        self._active_cap: Any = None
        self._timed_out_caps: Set[int] = set()
        self._unbound_caps: Set[int] = set()
        self._last_read_timed_out: bool = False
        self._lock = threading.RLock()

    @property
    def last_read_timed_out(self) -> bool:
        """Return True if the most recent read() timed out."""
        return self._last_read_timed_out

    def is_cap_severed(self, cap: Any) -> bool:
        """Return True if safe unbind was dispatched or cap timed out."""
        if cap is None:
            return True
        with self._lock:
            return id(cap) in self._timed_out_caps or id(cap) in self._unbound_caps

    @property
    def state(self) -> CircuitState:
        """Return current circuit-breaker state."""
        return self._state

    @property
    def consecutive_failures(self) -> int:
        """Return count of consecutive empty or timed-out read attempts."""
        return self._consecutive_failures

    @property
    def is_healthy(self) -> bool:
        """Return True if circuit-breaker is in HEALTHY state."""
        return self._state == CircuitState.HEALTHY

    @property
    def is_stalled(self) -> bool:
        """Return True if circuit-breaker is in STALLED state."""
        return self._state == CircuitState.STALLED

    @property
    def is_reconnecting(self) -> bool:
        """Return True if circuit-breaker is in RECONNECTING state."""
        return self._state == CircuitState.RECONNECTING

    def reset(self) -> None:
        """Reset circuit breaker to HEALTHY with zero failures."""
        with self._lock:
            self._state = CircuitState.HEALTHY
            self._consecutive_failures = 0
            self._last_read_timed_out = False
            self._timed_out_caps.clear()
            self._unbound_caps.clear()

    def trip(self, state: CircuitState = CircuitState.STALLED) -> None:
        """Manually trip circuit-breaker state."""
        with self._lock:
            self._state = state
            if self._consecutive_failures < self.stalled_threshold:
                self._consecutive_failures = self.stalled_threshold

    def _ensure_job(self, cap: Any) -> Optional[_CaptureReadJob]:
        """Ensure an active reader job matches the provided capture instance."""
        if id(cap) in self._timed_out_caps:
            return None

        if self._current_job is not None:
            if self._current_job.cap is cap:
                if self._current_job.is_reading:
                    return None
                if self._current_job.thread.is_alive():
                    return self._current_job
            self._current_job.stop()
            self._current_job = None
            self._active_cap = None

        self._active_cap = cap
        self._current_job = _CaptureReadJob(cap)
        return self._current_job

    def _wait_interruptible(
        self,
        job: _CaptureReadJob,
        timeout: float,
        stop_event: Optional[threading.Event] = None,
    ) -> bool:
        """Wait for read job completion with bounded timeout and stop event checks."""
        deadline = time.time() + timeout
        while True:
            if stop_event and stop_event.is_set():
                return False
            remaining = deadline - time.time()
            if remaining <= 0:
                return False
            slice_dur = min(0.05, remaining)
            if job.done.wait(timeout=slice_dur):
                return True

    def read(
        self,
        cap: Any,
        timeout: Optional[float] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> Tuple[bool, Optional[np.ndarray]]:
        """Execute bounded read decoupling synchronous driver calls.

        Returns (ret, frame). Returns (False, None) on empty frame or timeout.
        """
        if cap is None:
            self._record_failure()
            self._last_read_timed_out = False
            return False, None

        if id(cap) in self._timed_out_caps:
            self._last_read_timed_out = True
            self._record_failure()
            return False, None

        effective_timeout = float(timeout) if timeout is not None else self.timeout

        with self._lock:
            job = self._ensure_job(cap)
            if job is None:
                self._record_failure()
                self._last_read_timed_out = True
                return False, None
            job.done.clear()
            job.trigger.set()

        completed = self._wait_interruptible(job, effective_timeout, stop_event)

        if not completed:
            if stop_event and stop_event.is_set():
                return False, None

            logger.warning(
                "CaptureReadGuard: Driver read timed out after %.2fs. Tripping breaker.",
                effective_timeout,
            )
            with self._lock:
                self._last_read_timed_out = True
                self._timed_out_caps.add(id(cap))
                if self._current_job is job:
                    self._current_job.stop()
                    self._current_job = None
                    self._active_cap = None
                self._record_failure()
            self.safe_driver_unbind(cap)
            return False, None

        self._last_read_timed_out = False
        ret, frame = job.ret, job.frame
        if ret and frame is not None:
            self.reset()
            return True, frame

        self._record_failure()
        return False, None

    def _record_failure(self) -> None:
        """Update consecutive failures and state machine transitions."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.reconnect_threshold:
            self._state = CircuitState.RECONNECTING
        elif self._consecutive_failures >= self.stalled_threshold:
            self._state = CircuitState.STALLED

    def safe_driver_unbind(self, cap: Any) -> None:
        """Execute non-blocking driver unbind in background thread to prevent COM deadlock."""
        if cap is None:
            return

        cap_id = id(cap)
        with self._lock:
            if cap_id in self._unbound_caps:
                return
            self._unbound_caps.add(cap_id)

        def _do_unbind() -> None:
            try:
                if self._safe_unbind_cb:
                    self._safe_unbind_cb(cap)
                else:
                    from intelligent_tracker.camera_device import CameraDeviceHandler
                    CameraDeviceHandler.safe_release(cap, settle_delay=0.1)
            except Exception as e:
                logger.debug("Exception during background driver unbind: %s", e)

        t = threading.Thread(target=_do_unbind, name="SafeDriverUnbindWorker", daemon=True)
        t.start()

    def stop(self) -> None:
        """Clean up active reader job without blocking."""
        with self._lock:
            if self._current_job:
                self._current_job.stop()
                self._current_job = None
                self._active_cap = None
            self._timed_out_caps.clear()
            self._unbound_caps.clear()
            self._last_read_timed_out = False


__all__ = ["CaptureReadGuard", "CircuitState"]

