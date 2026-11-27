"""Decoupled capture read job, state mixin, and driver unbind helpers."""

import logging
import sys
import threading
import time
from enum import Enum
from typing import Any, Callable, Optional
import numpy as np

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Camera driver circuit-breaker operating states."""

    HEALTHY = "HEALTHY"
    STALLED = "STALLED"
    RECONNECTING = "RECONNECTING"


def _win32_com_init() -> bool:
    """Initialize Windows COM STA/MTA apartment on current thread if available."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        ole32 = getattr(ctypes, "windll", None)
        if ole32 is not None:
            hr = ole32.ole32.CoInitializeEx(None, 0)
            return hr in (0, 1)
    except Exception as exc:
        logger.debug("COM initialization skipped/failed: %s", exc)
    return False


def _win32_com_uninit(com_initialized: bool) -> None:
    """Uninitialize Windows COM apartment if initialized on current thread."""
    if not com_initialized:
        return
    try:
        import ctypes

        ole32 = getattr(ctypes, "windll", None)
        if ole32 is not None:
            ole32.ole32.CoUninitialize()
    except Exception:
        pass


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
        com_initialized = _win32_com_init()
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
                except Exception as exc:
                    logger.debug("Exception in cap.read() worker: %s", exc)
                    ret, frame = False, None
                finally:
                    self.is_reading = False
                self.ret, self.frame = ret, frame
                self.done.set()
        finally:
            _win32_com_uninit(com_initialized)

    def stop(self) -> None:
        """Signal worker to terminate loop."""
        self.stopped = True
        self.trigger.set()


class _CircuitStateMixin:
    """Thread-safe read-only circuit-breaker state properties."""

    _lock: threading.RLock
    _last_read_timed_out: bool
    _state: CircuitState
    _consecutive_failures: int

    @property
    def last_read_timed_out(self) -> bool:
        """Return True if the most recent read() timed out."""
        with self._lock:
            return self._last_read_timed_out

    @property
    def state(self) -> CircuitState:
        """Return current circuit-breaker state."""
        with self._lock:
            return self._state

    @property
    def consecutive_failures(self) -> int:
        """Return count of consecutive empty or timed-out read attempts."""
        with self._lock:
            return self._consecutive_failures

    @property
    def is_healthy(self) -> bool:
        """Return True if circuit-breaker is in HEALTHY state."""
        with self._lock:
            return self._state == CircuitState.HEALTHY

    @property
    def is_stalled(self) -> bool:
        """Return True if circuit-breaker is in STALLED state."""
        with self._lock:
            return self._state == CircuitState.STALLED

    @property
    def is_reconnecting(self) -> bool:
        """Return True if circuit-breaker is in RECONNECTING state."""
        with self._lock:
            return self._state == CircuitState.RECONNECTING


def wait_for_read_job(
    job: _CaptureReadJob,
    timeout: float,
    stop_event: Optional[threading.Event] = None,
) -> bool:
    """Wait for read job completion using monotonic clock and stop event checks."""
    deadline = time.monotonic() + timeout
    while True:
        if stop_event and stop_event.is_set():
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        if job.done.wait(timeout=min(0.05, remaining)):
            return True


def spawn_driver_unbind(
    cap: Any, safe_unbind_cb: Optional[Callable[[Any], None]] = None
) -> None:
    """Execute non-blocking driver unbind in background thread to prevent COM deadlock."""

    def _do_unbind() -> None:
        com_initialized = _win32_com_init()
        try:
            if safe_unbind_cb:
                safe_unbind_cb(cap)
            else:
                from intelligent_tracker.camera_device import CameraDeviceHandler

                CameraDeviceHandler.safe_release(cap, settle_delay=0.1)
        except Exception as exc:
            logger.debug("Exception during background driver unbind: %s", exc)
        finally:
            _win32_com_uninit(com_initialized)

    threading.Thread(
        target=_do_unbind, name="SafeDriverUnbindWorker", daemon=True
    ).start()


def advance_failure_state(guard: Any) -> None:
    """Increment consecutive failures and update circuit-breaker state under lock."""
    guard._consecutive_failures += 1
    if guard._consecutive_failures >= guard.reconnect_threshold:
        guard._state = CircuitState.RECONNECTING
    elif guard._consecutive_failures >= guard.stalled_threshold:
        guard._state = CircuitState.STALLED


def ensure_read_job(guard: Any, cap: Any) -> Optional[_CaptureReadJob]:
    """Ensure an active reader job matches the provided capture instance under lock."""
    if id(cap) in guard._timed_out_caps:
        return None
    if guard._current_job is not None:
        if guard._current_job.cap is cap:
            if guard._current_job.is_reading:
                return None
            if guard._current_job.thread.is_alive():
                return guard._current_job
        guard._current_job.stop()
        guard._current_job = None
        guard._active_cap = None
    guard._active_cap = cap
    guard._current_job = _CaptureReadJob(cap)
    return guard._current_job
