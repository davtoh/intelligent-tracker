"""Non-blocking camera read circuit-breaker and driver unbind watchdog.

Decouples synchronous native C++ driver reads (DirectShow/MSMF on Windows,
V4L2 on Linux, AVFoundation on macOS) to prevent driver hangs post-sleep/hibernation
from deadlocking acquisition worker threads or blocking server shutdown.
"""

import logging
import threading
from typing import Any, Callable, Optional, Set, Tuple
import numpy as np

from intelligent_tracker.video._capture_guard_worker import (
    CircuitState,
    _CaptureReadJob,
    _CircuitStateMixin,
    advance_failure_state,
    ensure_read_job,
    spawn_driver_unbind,
    wait_for_read_job,
)

logger = logging.getLogger(__name__)


class CaptureReadGuard(_CircuitStateMixin):
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
        warmup_timeout: Optional[float] = None,
    ):
        self.timeout = float(timeout)
        self.warmup_timeout = float(warmup_timeout) if warmup_timeout is not None else self.timeout * 2.5
        self.stalled_threshold = int(stalled_threshold)
        self.reconnect_threshold = int(reconnect_threshold)
        self._safe_unbind_cb = safe_unbind_cb

        self._state = CircuitState.HEALTHY
        self._consecutive_failures = 0
        self._current_job: Optional[_CaptureReadJob] = None
        self._active_cap: Any = None
        self._timed_out_caps: Set[int] = set()
        self._unbound_caps: Set[int] = set()
        self._warmed_caps: Set[int] = set()
        self._last_read_timed_out: bool = False
        self._lock = threading.RLock()

    def is_cap_severed(self, cap: Any) -> bool:
        """Return True if safe unbind was dispatched or cap timed out."""
        if cap is None:
            return True
        with self._lock:
            return id(cap) in self._timed_out_caps or id(cap) in self._unbound_caps

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

    def _prepare_read(
        self, cap: Any, timeout: Optional[float]
    ) -> Tuple[Optional[_CaptureReadJob], float, bool]:
        """Validate cap and trigger read job under lock. Returns (job, timeout_s, timed_out)."""
        with self._lock:
            if cap is None:
                advance_failure_state(self)
                self._last_read_timed_out = False
                return None, 0.0, False
            if id(cap) in self._timed_out_caps:
                advance_failure_state(self)
                self._last_read_timed_out = True
                return None, 0.0, True
            is_warm = id(cap) in self._warmed_caps
            eff_timeout = float(timeout) if timeout is not None else (
                self.timeout if is_warm else self.warmup_timeout
            )
            job = ensure_read_job(self, cap)
            if job is None:
                advance_failure_state(self)
                self._last_read_timed_out = True
                return None, eff_timeout, True
            job.done.clear()
            job.trigger.set()
            return job, eff_timeout, False

    def read(
        self,
        cap: Any,
        timeout: Optional[float] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> Tuple[bool, Optional[np.ndarray]]:
        """Execute bounded read decoupling synchronous driver calls."""
        job, eff_timeout, _ = self._prepare_read(cap, timeout)
        if job is None:
            return False, None

        completed = wait_for_read_job(job, eff_timeout, stop_event)
        if not completed:
            if stop_event and stop_event.is_set():
                return False, None
            logger.warning(
                "CaptureReadGuard: Driver read timed out after %.2fs. Tripping breaker.",
                eff_timeout,
            )
            with self._lock:
                self._last_read_timed_out = True
                self._timed_out_caps.add(id(cap))
                self._warmed_caps.discard(id(cap))
                if self._current_job is job:
                    self._current_job.stop()
                    self._current_job = None
                    self._active_cap = None
                advance_failure_state(self)
            self.safe_driver_unbind(cap)
            return False, None

        ret, frame = job.ret, job.frame
        with self._lock:
            self._last_read_timed_out = False
            if ret and frame is not None:
                self._warmed_caps.add(id(cap))
                self.reset()
                return True, frame
            advance_failure_state(self)
            return False, None

    def safe_driver_unbind(self, cap: Any) -> None:
        """Execute non-blocking driver unbind in background thread to prevent COM deadlock."""
        if cap is None:
            return
        cap_id = id(cap)
        with self._lock:
            if cap_id in self._unbound_caps:
                return
            self._unbound_caps.add(cap_id)
        spawn_driver_unbind(cap, self._safe_unbind_cb)

    def stop(self) -> None:
        """Clean up active reader job without blocking."""
        with self._lock:
            if self._current_job:
                self._current_job.stop()
                self._current_job = None
                self._active_cap = None
            self._timed_out_caps.clear()
            self._unbound_caps.clear()
            self._warmed_caps.clear()
            self._last_read_timed_out = False


__all__ = ["CaptureReadGuard", "CircuitState"]

