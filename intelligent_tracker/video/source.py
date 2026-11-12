"""Thread-safe non-blocking video stream reader and telemetry provider."""

import logging
import queue
import threading
import time
from typing import Any, Dict, Optional, Tuple, Union
import numpy as np

from intelligent_tracker.video.capture_worker import CaptureWorkerMixin
from intelligent_tracker.video.hibernation import StreamHibernationMixin
from intelligent_tracker.video.lifecycle import CaptureLifecycleMixin

logger = logging.getLogger(__name__)


class VideoSource(StreamHibernationMixin, CaptureLifecycleMixin, CaptureWorkerMixin):
    """Thread-safe non-blocking video stream reader.

    Runs a background acquisition thread that keeps reading frames from OpenCV
    or the synthetic generator into an internal bounded buffer.
    """

    def __init__(
        self,
        source: Union[str, int] = "synthetic",
        buffer_size: int = 1,
        auto_reconnect: bool = True,
        reconnect_delay: float = 1.0,
        max_reconnect_attempts: int = 10,
        fps_limit: Optional[float] = None,
        loop_video: bool = False,
        width: Optional[int] = None,
        height: Optional[int] = None,
        read_timeout: float = 2.0,
    ):
        self.source = source
        self.buffer_size = max(1, int(buffer_size))
        self.auto_reconnect = bool(auto_reconnect)
        self.reconnect_delay = float(reconnect_delay)
        self.max_reconnect_attempts = int(max_reconnect_attempts)
        self.fps_limit = float(fps_limit) if fps_limit else None
        self.loop_video = bool(loop_video)
        self.target_width = width
        self.target_height = height
        self.read_timeout = float(read_timeout)

        self.is_synthetic = False
        self.is_rtsp = False
        self.is_file = False
        self.is_webcam = False
        self.is_libcamera = False

        self._classify_source()
        self._init_state_and_queues()

        self.width = self.target_width or 640
        self.height = self.target_height or 480
        self.source_fps = 30.0

    def _init_state_and_queues(self) -> None:
        """Initialize concurrency synchronization events, lock, queue, and telemetry."""
        self._cap = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._is_paused = False
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._ready_event = threading.Event()
        self._first_frame_read = False
        self._lock = threading.Lock()
        self._queue: queue.Queue = queue.Queue(maxsize=self.buffer_size)

        self._frames_read = 0
        self._frames_dropped = 0
        self._reconnections = 0
        self._is_connected = False
        self._start_time: Optional[float] = None
        self._last_frame_time: Optional[float] = None
        self._measured_fps = 0.0
        self._frame_interval_samples: list = []

    def read(self, timeout: float = 1.0) -> Tuple[bool, Optional[np.ndarray]]:
        """Retrieve latest frame from buffer, waiting up to timeout seconds."""
        if not self._running:
            self.start()

        try:
            frame = self._queue.get(block=True, timeout=timeout)
            if frame is None or not self._running:
                return False, None
            return True, frame
        except queue.Empty:
            return False, None

    def grab_latest(self) -> Optional[np.ndarray]:
        """Non-blocking fetch of latest available frame, or None if buffer is empty."""
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def get_metrics(self) -> Dict[str, Any]:
        """Retrieve real-time connection and telemetry statistics."""
        total = self._frames_read + self._frames_dropped
        drop_rate = (self._frames_dropped / float(total)) * 100.0 if total > 0 else 0.0
        uptime = time.time() - self._start_time if self._start_time else 0.0

        return {
            "source": str(self.source),
            "is_connected": bool(self._is_connected),
            "fps": round(self._measured_fps, 1),
            "source_fps": round(self.source_fps, 1),
            "frames_read": self._frames_read,
            "frames_dropped": self._frames_dropped,
            "drop_rate_pct": round(drop_rate, 2),
            "reconnections": self._reconnections,
            "resolution": (self.width, self.height),
            "uptime_seconds": round(uptime, 1),
        }

    @property
    def is_connected(self) -> bool:
        """Return True if acquisition backend is actively connected."""
        return bool(getattr(self, "_is_connected", False))

    @property
    def read_guard(self) -> Any:
        """Return the CaptureReadGuard protecting frame acquisition."""
        return self._get_read_guard()


__all__ = ["VideoSource"]
