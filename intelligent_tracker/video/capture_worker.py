"""Threaded capture worker and acquisition backend logic."""

import logging
import os
import queue
import time
from typing import Any, Optional, Tuple
import cv2
import numpy as np

from intelligent_tracker.camera_device import CameraDeviceHandler
from intelligent_tracker.video.capture_helpers import (
    compute_reconnect_backoff,
    probe_capture_dimensions,
)
from intelligent_tracker.video.frame_timing import advance_frame_deadline, read_media_time_s, resolve_effective_fps
from intelligent_tracker.video.synthetic import SyntheticFrameGenerator

logger = logging.getLogger(__name__)


def _rewind_or_reopen_loop_video(worker: Any, consecutive_empty: int) -> Tuple[bool, int]:
    """Rewind looping video files and reopen after repeated empty reads."""
    if worker._cap:
        try:
            worker._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        except Exception as e:
            logger.debug("Failed to rewind looping video: %s", e)
    consecutive_empty += 1
    if consecutive_empty > 5:
        CameraDeviceHandler.safe_release(worker._cap, settle_delay=0.0)
        worker._cap = None
        worker._open_capture()
        consecutive_empty = 0
    return not worker._stop_event.wait(timeout=0.02), consecutive_empty


class CaptureWorkerMixin:
    """Acquisition lifecycle, backend initialization, and polling worker loop mixin."""

    source: Any
    target_width: Optional[int]
    target_height: Optional[int]
    width: int
    height: int
    source_fps: float
    fps_limit: Optional[float]
    loop_video: bool
    auto_reconnect: bool
    reconnect_delay: float
    max_reconnect_attempts: int
    is_synthetic: bool
    is_rtsp: bool
    is_file: bool
    is_webcam: bool
    is_libcamera: bool
    read_timeout: float
    _read_guard: Optional[Any]

    def _get_read_guard(self) -> Any:
        """Return or lazily initialize the CaptureReadGuard."""
        if not hasattr(self, "_read_guard") or self._read_guard is None:
            from intelligent_tracker.video.capture_guard import CaptureReadGuard

            self._read_guard = CaptureReadGuard(
                timeout=getattr(self, "read_timeout", 2.0),
                warmup_timeout=getattr(self, "warmup_timeout", 5.0),
                safe_unbind_cb=lambda cap: CameraDeviceHandler.safe_release(cap, settle_delay=0.1),
            )
        return self._read_guard

    def _classify_source(self) -> None:
        """Inspect source attribute to determine capture protocol and backend."""
        s = str(self.source).strip()
        if s.lower() in ("mock", "synthetic", "test"):
            self.is_synthetic = True
            self.source = "synthetic"
        elif s.lower() in ("libcamera", "rpi", "picamera", "rpicam") or s.startswith("libcamerasrc"):
            self.is_libcamera = True
        elif s.isdigit():
            self.is_webcam = True
            self.source = int(s)
        elif s.startswith(("rtsp://", "rtsps://", "http://", "https://")):
            self.is_rtsp = True
        elif os.path.exists(s):
            self.is_file = True
        else:
            self._resolve_fallback_source(s)

    def _resolve_fallback_source(self, s: str) -> None:
        """Resolve ambiguous or non-standard filesystem paths and indices."""
        from intelligent_tracker.camera_resolver import CameraPathResolver

        resolved_file, _, _ = CameraPathResolver.resolve_file_source(s)
        if resolved_file:
            self.is_file = True
            self.source = resolved_file
        elif s.lower().endswith((".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v")):
            self.is_file = True
        else:
            try:
                self.source = int(self.source)
                self.is_webcam = True
            except (ValueError, TypeError):
                self.is_rtsp = s.startswith("rtsp")

    def _open_backend_capture(self) -> Any:
        """Instantiate cv2.VideoCapture handle for configured backend."""
        if self.is_libcamera:
            w, h = self.target_width or 640, self.target_height or 480
            fps = int(self.fps_limit or 30)
            gst = f"libcamerasrc ! video/x-raw, width={w}, height={h}, framerate={fps}/1 ! videoconvert ! videoscale ! appsink"
            cap = cv2.VideoCapture(gst, cv2.CAP_GSTREAMER)
            if not cap or not cap.isOpened():
                backend = cv2.CAP_V4L2 if hasattr(cv2, "CAP_V4L2") else 0
                return cv2.VideoCapture(0, backend)
            return cap
        if self.is_rtsp:
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|buffer_size;102400"
            return cv2.VideoCapture(str(self.source), cv2.CAP_FFMPEG)
        if self.is_webcam:
            cap, _ = CameraDeviceHandler.open_camera(
                self.source,
                width=self.target_width,
                height=self.target_height,
                test_read=False,
            )
            return cap
        if self.is_file:
            if not os.path.exists(str(self.source)):
                logger.warning("Video file not found for capture: %s", self.source)
                return None
            return cv2.VideoCapture(self.source)
        return cv2.VideoCapture(self.source)

    def _configure_capture_dimensions(self) -> None:
        """Probe frame dimensions, compute aspect ratio, and configure target bounds."""
        w, h, fps = probe_capture_dimensions(self._cap, self.target_width, self.target_height)
        if w is not None and h is not None:
            self.width, self.height = w, h
            if self.target_width and self.target_height:
                self.target_width, self.target_height = w, h
        elif w is not None:
            self.width = w
        elif h is not None:
            self.height = h
        if fps is not None:
            self.source_fps = fps

    def _open_capture(self) -> bool:
        """Open video capture stream or synthetic generator."""
        if self.is_synthetic:
            self._cap = SyntheticFrameGenerator(
                width=self.target_width or 640,
                height=self.target_height or 480,
                fps=int(self.fps_limit or 30),
            )
            self.width, self.height = self._cap.width, self._cap.height
            self.source_fps = float(self._cap.fps)
            self._is_connected = True
            self._needs_warmup = True
            return True

        try:
            self._cap = self._open_backend_capture()
            if not self._cap or not self._cap.isOpened():
                self._is_connected = False
                return False
            self._configure_capture_dimensions()
            self._is_connected = True
            self._needs_warmup = True
            return True
        except Exception as e:
            logger.warning("Error opening video capture '%s': %s", self.source, e)
            self._is_connected = False
            return False

    def _handle_reconnection(self, reconnect_attempts: int) -> Tuple[bool, int]:
        """Attempt auto-reconnect backoff when stream connection is lost."""
        self._is_connected = False
        can_retry = self.auto_reconnect and (
            self.max_reconnect_attempts == 0 or reconnect_attempts < self.max_reconnect_attempts
        )
        if not can_retry:
            logger.error("VideoSource '%s': Stream closed and reconnect exhausted.", self.source)
            return False, reconnect_attempts

        reconnect_attempts += 1
        self._reconnections += 1
        delay = compute_reconnect_backoff(
            reconnect_attempts,
            base_delay=self.reconnect_delay,
            max_backoff=getattr(self, "max_reconnect_backoff", 30.0),
        )
        logger.info(
            "VideoSource '%s': Attempting reconnect #%d in %.1fs...",
            self.source,
            reconnect_attempts,
            delay,
        )
        if self._stop_event.wait(timeout=delay):
            return False, reconnect_attempts
        if self._open_capture():
            logger.info("VideoSource '%s': Successfully reconnected.", self.source)
            return True, 0
        return True, reconnect_attempts

    def _handle_empty_frame(
        self,
        consecutive_empty: int,
        reconnect_attempts: int,
    ) -> Tuple[bool, int, int]:
        """Process empty frame conditions: video rewind, transient webcam retries, and reconnects."""
        if self.is_file and self.loop_video:
            keep_going, consecutive_empty = _rewind_or_reopen_loop_video(self, consecutive_empty)
            return keep_going, consecutive_empty, reconnect_attempts

        if self.is_webcam:
            consecutive_empty += 1
            if consecutive_empty < 15:
                should_exit = self._stop_event.wait(timeout=0.02)
                return not should_exit, consecutive_empty, reconnect_attempts

        self._is_connected = False
        if self.auto_reconnect and not self.is_file:
            reconnect_attempts += 1
            self._reconnections += 1
            delay = compute_reconnect_backoff(
                reconnect_attempts,
                base_delay=self.reconnect_delay,
                max_backoff=getattr(self, "max_reconnect_backoff", 30.0),
            )
            if self._stop_event.wait(timeout=delay):
                return False, consecutive_empty, reconnect_attempts
            if self._cap:
                CameraDeviceHandler.safe_release(self._cap, settle_delay=0.25)
                self._cap = None
            self._open_capture()
            return True, consecutive_empty, reconnect_attempts
        return False, consecutive_empty, reconnect_attempts

    def _record_fps_telemetry(self, now: float) -> None:
        """Update sliding window frame rate telemetry."""
        self._frames_read += 1
        if self._last_frame_time is not None:
            dt = now - self._last_frame_time
            if dt > 0:
                self._frame_interval_samples.append(dt)
                if len(self._frame_interval_samples) > 30:
                    self._frame_interval_samples.pop(0)
                avg_dt = sum(self._frame_interval_samples) / len(self._frame_interval_samples)
                self._measured_fps = 1.0 / avg_dt if avg_dt > 0 else 0.0
        self._last_frame_time = now

    def _enqueue_frame(
        self, frame: np.ndarray, loop_start: float, min_frame_time: float,
        media_time_s: Optional[float] = None, deadline: Optional[float] = None,
    ) -> bool:
        """Resize, update telemetry metrics, push frame to buffer, and throttle rate."""
        if self.target_width and self.target_height and frame is not None:
            if frame.shape[1] != self.target_width or frame.shape[0] != self.target_height:
                frame = cv2.resize(frame, (self.target_width, self.target_height), interpolation=cv2.INTER_AREA)

        if not self._first_frame_read:
            self._first_frame_read = True
            self._ready_event.set()

        self._record_fps_telemetry(time.time())

        if self._queue.full():
            try:
                self._queue.get_nowait()
                self._frames_dropped += 1
            except queue.Empty:
                pass

        payload: Any = (frame, media_time_s) if media_time_s is not None else frame
        try:
            self._queue.put(payload, timeout=0.01)
        except queue.Full:
            self._frames_dropped += 1

        if min_frame_time > 0:
            sleep_dur = (deadline - time.monotonic()) if deadline is not None else (min_frame_time - (time.time() - loop_start))
            if sleep_dur > 0 and self._stop_event.wait(timeout=sleep_dur):
                return False
        return True

    def _handle_read_failure(
        self, guard: Any, consecutive_empty: int, reconnect_attempts: int
    ) -> Tuple[bool, int, int]:
        """Handle failed/timed-out frame read with driver severing or empty-frame fallback."""
        if not self._running:
            return False, consecutive_empty, reconnect_attempts
        is_severed = getattr(guard, "last_read_timed_out", False)
        if is_severed or (guard.is_reconnecting and self.auto_reconnect and not self.is_file):
            logger.warning("VideoSource '%s': Driver timed out or breaker tripped. Severing driver.", self.source)
            guard.safe_driver_unbind(self._cap)
            self._cap = None
            self._is_connected = False
            if self.auto_reconnect and not self.is_file:
                should_continue, reconnect_attempts = self._handle_reconnection(reconnect_attempts)
                if not should_continue:
                    return False, consecutive_empty, reconnect_attempts
                guard.reset()
                return True, consecutive_empty, reconnect_attempts
            return False, consecutive_empty, reconnect_attempts
        return self._handle_empty_frame(consecutive_empty, reconnect_attempts)

    def _capture_worker(self) -> None:
        """Worker thread that continuously polls frames, buffers them, and safely owns cleanup."""
        reconnect_attempts, consecutive_empty = 0, 0
        effective_fps = resolve_effective_fps(self.is_file, self.source_fps, self.fps_limit)
        min_frame_time = (1.0 / effective_fps) if (self.is_file or self.fps_limit) else 0.0
        guard, next_deadline = self._get_read_guard(), time.monotonic()
        try:
            while self._running:
                if self._is_paused:
                    self._pause_event.wait(timeout=0.25)
                    next_deadline = time.monotonic()
                    continue
                loop_start = time.time()
                if not self._cap or not self._cap.isOpened():
                    if self.is_file:
                        break
                    ok, reconnect_attempts = self._handle_reconnection(reconnect_attempts)
                    if not ok:
                        break
                    continue
                timeout = getattr(self, "warmup_timeout", 5.0) if getattr(self, "_needs_warmup", True) else getattr(self, "read_timeout", 2.0)
                ret, frame = guard.read(self._cap, timeout=timeout, stop_event=self._stop_event)
                if not ret or frame is None:
                    keep, consecutive_empty, reconnect_attempts = self._handle_read_failure(guard, consecutive_empty, reconnect_attempts)
                    if not keep:
                        break
                    continue
                self._needs_warmup, consecutive_empty, reconnect_attempts = False, 0, 0
                media_t = read_media_time_s(self._cap, self.is_file, effective_fps)
                deadline = advance_frame_deadline(next_deadline, min_frame_time)
                next_deadline = deadline if deadline is not None else next_deadline
                if not self._enqueue_frame(frame, loop_start, min_frame_time, media_time_s=media_t, deadline=deadline):
                    break
        finally:
            with self._lock:
                guard.stop()
                if self._cap:
                    CameraDeviceHandler.safe_release(self._cap, settle_delay=0.0)
                    self._cap = None
                self._is_connected = False
                self._ready_event.set()


__all__ = ["CaptureWorkerMixin"]
