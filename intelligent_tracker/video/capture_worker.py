"""Threaded capture worker and acquisition backend logic."""

import logging
import os
import queue
import time
from typing import Any, Optional, Tuple
import cv2
import numpy as np

from intelligent_tracker.camera_device import CameraDeviceHandler
from intelligent_tracker.video.synthetic import SyntheticFrameGenerator

logger = logging.getLogger(__name__)


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
        if self.target_width and self.target_height:
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(self.target_width))
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self.target_height))

        w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(self._cap.get(cv2.CAP_PROP_FPS))

        if w > 0 and h > 0:
            self.width, self.height = w, h
            if self.target_width and self.target_height:
                src_ratio = w / float(h)
                target_ratio = self.target_width / float(self.target_height)
                if src_ratio >= target_ratio:
                    adj_w = self.target_width
                    adj_h = int(round(self.target_width / src_ratio))
                else:
                    adj_h = self.target_height
                    adj_w = int(round(self.target_height * src_ratio))
                self.target_width = adj_w if adj_w % 2 == 0 else adj_w - 1
                self.target_height = adj_h if adj_h % 2 == 0 else adj_h - 1
                self.width, self.height = self.target_width, self.target_height
        elif w > 0:
            self.width = w
        elif h > 0:
            self.height = h

        if fps > 0 and not np.isnan(fps):
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
            return True

        try:
            self._cap = self._open_backend_capture()
            if not self._cap or not self._cap.isOpened():
                self._is_connected = False
                return False
            self._configure_capture_dimensions()
            self._is_connected = True
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
        logger.info(
            "VideoSource '%s': Attempting reconnect #%d in %.1fs...",
            self.source,
            reconnect_attempts,
            self.reconnect_delay,
        )
        if self._stop_event.wait(timeout=self.reconnect_delay):
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
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self._cap.read()
            if not ret or frame is None:
                try:
                    self._cap.release()
                except Exception:
                    pass
                if self._open_capture():
                    ret, frame = self._cap.read()
            if not ret or frame is None:
                should_exit = self._stop_event.wait(timeout=0.02)
                return not should_exit, consecutive_empty, reconnect_attempts

        elif self.is_webcam:
            consecutive_empty += 1
            if consecutive_empty < 15:
                should_exit = self._stop_event.wait(timeout=0.02)
                return not should_exit, consecutive_empty, reconnect_attempts

        self._is_connected = False
        if self.auto_reconnect and not self.is_file:
            reconnect_attempts += 1
            self._reconnections += 1
            if self._stop_event.wait(timeout=self.reconnect_delay):
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

    def _enqueue_frame(self, frame: np.ndarray, loop_start: float, min_frame_time: float) -> bool:
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

        try:
            self._queue.put(frame, timeout=0.01)
        except queue.Full:
            self._frames_dropped += 1

        if min_frame_time > 0:
            elapsed = time.time() - loop_start
            sleep_dur = min_frame_time - elapsed
            if sleep_dur > 0 and self._stop_event.wait(timeout=sleep_dur):
                return False
        return True

    def _capture_worker(self) -> None:
        """Worker thread that continuously polls frames, buffers them, and safely owns cleanup."""
        reconnect_attempts = 0
        consecutive_empty = 0
        effective_fps = self.fps_limit or (self.source_fps if self.source_fps > 0 else 30.0)
        min_frame_time = (1.0 / effective_fps) if (self.is_file or self.fps_limit) else 0.0

        try:
            while self._running:
                if self._is_paused:
                    self._pause_event.wait(timeout=0.25)
                    continue

                loop_start = time.time()
                if not self._cap or not self._cap.isOpened():
                    should_continue, reconnect_attempts = self._handle_reconnection(reconnect_attempts)
                    if not should_continue:
                        break
                    continue

                ret, frame = self._cap.read()
                if not ret or frame is None:
                    keep_going, consecutive_empty, reconnect_attempts = self._handle_empty_frame(
                        consecutive_empty, reconnect_attempts
                    )
                    if not keep_going:
                        break
                    continue

                consecutive_empty = 0
                if not self._enqueue_frame(frame, loop_start, min_frame_time):
                    break
        finally:
            with self._lock:
                if self._cap:
                    CameraDeviceHandler.safe_release(self._cap, settle_delay=0.0)
                    self._cap = None
                self._is_connected = False


__all__ = ["CaptureWorkerMixin"]
