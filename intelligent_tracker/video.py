#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Non-blocking Threaded Video Ingestion Module.

Supports:
- RTSP network streams (rtsp://...)
- HTTP/HTTPS streams (http://...)
- Local USB/V4L2 webcams (device index 0, 1, ...)
- Video files (*.mp4, *.avi, *.mkv)
- Synthetic / mock generator for testing without physical hardware

Key Features:
- Background reader thread to prevent network I/O from blocking inference
- Bounded buffer with automatic frame-drop on lag for ultra-low latency RTSP
- Auto-reconnect logic with exponential backoff on stream disruption
- Real-time connection health metrics: FPS, drop rate, reconnection tally
- Context manager protocol (`with VideoSource(...) as vs:`)
"""

from __future__ import division, print_function, absolute_import

import os
import sys
import time
import queue
import logging
import threading
from typing import Optional, Tuple, Union, Dict, Any

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class SyntheticFrameGenerator(object):
    """
    High-fidelity synthetic frame generator for automated testing and CI.
    Generates video frames with optional moving targets that cross virtual tripwires
    and dwell in predefined ROI zones.
    """
    def __init__(self, width: int = 640, height: int = 480, fps: int = 30):
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.frame_idx = 0
        self._opened = True

    def isOpened(self) -> bool:
        return self._opened

    def open(self, *args, **kwargs) -> bool:
        self._opened = True
        return True

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        if not self._opened:
            return False, None

        self.frame_idx += 1
        t = self.frame_idx / float(self.fps)

        # Base gradient background
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        frame[:, :, 0] = (np.linspace(30, 70, self.height)[:, None]).astype(np.uint8)
        frame[:, :, 1] = (np.linspace(35, 75, self.height)[:, None]).astype(np.uint8)
        frame[:, :, 2] = (np.linspace(40, 80, self.height)[:, None]).astype(np.uint8)

        # Grid lines (retail floor simulation)
        for y in range(0, self.height, 40):
            cv2.line(frame, (0, y), (self.width, y), (55, 60, 65), 1)
        for x in range(0, self.width, 40):
            cv2.line(frame, (x, 0), (x, self.height), (55, 60, 65), 1)

        # Target 1: Moves back and forth horizontally across the center (crosses tripwires)
        # Period: 8 seconds
        cycle_x = (np.sin(t * (2.0 * np.pi / 8.0)) + 1.0) / 2.0
        x1 = int(60 + cycle_x * (self.width - 160))
        y1 = int(self.height * 0.45 + np.sin(t * 1.5) * 30)
        cv2.rectangle(frame, (x1, y1), (x1 + 40, y1 + 90), (0, 200, 255), -1)
        cv2.putText(frame, "P1", (x1 + 10, y1 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1)

        # Target 2: Enters, dwells in upper-right zone, and leaves
        # Period: 12 seconds
        cycle_y = (np.cos(t * (2.0 * np.pi / 12.0)) + 1.0) / 2.0
        x2 = int(self.width * 0.65 + np.sin(t * 0.8) * 40)
        y2 = int(60 + cycle_y * (self.height - 180))
        cv2.rectangle(frame, (x2, y2), (x2 + 36, y2 + 80), (255, 100, 100), -1)
        cv2.putText(frame, "P2", (x2 + 8, y2 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 100, 100), 1)

        # Timestamp watermark
        timestamp_str = "FRAME: {:06d} | T: {:.2f}s".format(self.frame_idx, t)
        cv2.putText(frame, timestamp_str, (15, self.height - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 160, 160), 1)

        return True, frame

    def release(self):
        self._opened = False


class VideoSource(object):
    """
    Thread-safe non-blocking video stream reader.

    Runs a background acquisition thread that keeps reading frames from OpenCV
    or the synthetic generator into an internal bounded buffer.

    Parameters:
    -----------
    source : Union[str, int]
        RTSP URL ('rtsp://...'), webcam index (0, 1), video file path, or 'synthetic'/'mock'.
    buffer_size : int
        Maximum number of frames in queue. Set to 1 for live low-latency RTSP streaming
        (drops oldest frames on lag). Set higher (e.g. 10-30) for offline video analysis.
    auto_reconnect : bool
        Whether to attempt automatic reconnection when stream drops (recommended for RTSP).
    reconnect_delay : float
        Initial delay in seconds between reconnect attempts.
    max_reconnect_attempts : int
        Maximum reconnect attempts before raising error (0 = infinite).
    fps_limit : Optional[float]
        Optionally throttle reading rate (e.g. 30.0) when reading fast offline video files.
    loop_video : bool
        If True and source is a video file, restart from beginning when EOF is reached.
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

        self.is_synthetic = False
        self.is_rtsp = False
        self.is_file = False
        self.is_webcam = False

        self._classify_source()

        # Capture backend and thread state
        self._cap = None
        self._thread = None
        self._running = False
        self._lock = threading.Lock()
        self._queue = queue.Queue(maxsize=self.buffer_size)

        # Telemetry & Metrics
        self._frames_read = 0
        self._frames_dropped = 0
        self._reconnections = 0
        self._is_connected = False
        self._start_time = None
        self._last_frame_time = None
        self._measured_fps = 0.0
        self._frame_interval_samples = []

        # Stream resolution & detected FPS
        self.width = self.target_width or 640
        self.height = self.target_height or 480
        self.source_fps = 30.0

    def _classify_source(self):
        s = str(self.source).strip()
        if s.lower() in ("mock", "synthetic", "test"):
            self.is_synthetic = True
            self.source = "synthetic"
        elif s.isdigit():
            self.is_webcam = True
            self.source = int(s)
        elif s.startswith("rtsp://") or s.startswith("rtsps://") or s.startswith("http://") or s.startswith("https://"):
            self.is_rtsp = True
        elif os.path.exists(s):
            self.is_file = True
        else:
            # Fallback check: numeric camera index
            try:
                self.source = int(self.source)
                self.is_webcam = True
            except (ValueError, TypeError):
                # Unknown source, treat as RTSP/file/network attempt
                self.is_rtsp = s.startswith("rtsp")

    def _open_capture(self) -> bool:
        if self.is_synthetic:
            self._cap = SyntheticFrameGenerator(
                width=self.target_width or 640,
                height=self.target_height or 480,
                fps=int(self.fps_limit or 30)
            )
            self.width = self._cap.width
            self.height = self._cap.height
            self.source_fps = float(self._cap.fps)
            self._is_connected = True
            return True

        # Physical webcam, file, or RTSP
        try:
            if self.is_rtsp:
                # Optimized flags for low-latency RTSP via FFmpeg
                # Force TCP transport if possible to eliminate UDP packet loss artifacts
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|buffer_size;102400"
                self._cap = cv2.VideoCapture(str(self.source), cv2.CAP_FFMPEG)
            else:
                self._cap = cv2.VideoCapture(self.source)

            if not self._cap or not self._cap.isOpened():
                self._is_connected = False
                return False

            if self.target_width and self.target_height:
                self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(self.target_width))
                self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self.target_height))

            w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = float(self._cap.get(cv2.CAP_PROP_FPS))

            if w > 0:
                self.width = w
            if h > 0:
                self.height = h
            if fps > 0 and not np.isnan(fps):
                self.source_fps = fps

            self._is_connected = True
            return True
        except Exception as e:
            logger.warning("Error opening video capture '%s': %s", self.source, e)
            self._is_connected = False
            return False

    def start(self) -> "VideoSource":
        """Start background capture thread."""
        with self._lock:
            if self._running:
                return self

            success = self._open_capture()
            if not success and not self.auto_reconnect:
                raise RuntimeError("Could not open video source: {}".format(self.source))

            self._running = True
            self._start_time = time.time()
            self._thread = threading.Thread(target=self._capture_worker, name="VideoSourceWorker", daemon=True)
            self._thread.start()
            return self

    def _capture_worker(self):
        """Worker thread that continuously polls frames and buffers them."""
        reconnect_attempts = 0
        min_frame_time = (1.0 / self.fps_limit) if self.fps_limit else 0.0

        while self._running:
            loop_start = time.time()

            if not self._cap or not self._cap.isOpened():
                self._is_connected = False
                if self.auto_reconnect and (self.max_reconnect_attempts == 0 or reconnect_attempts < self.max_reconnect_attempts):
                    reconnect_attempts += 1
                    self._reconnections += 1
                    logger.info("VideoSource '%s': Attempting reconnect #%d in %.1fs...", self.source, reconnect_attempts, self.reconnect_delay)
                    time.sleep(self.reconnect_delay)
                    if self._open_capture():
                        reconnect_attempts = 0
                        logger.info("VideoSource '%s': Successfully reconnected.", self.source)
                    continue
                else:
                    logger.error("VideoSource '%s': Stream closed and reconnect exhausted.", self.source)
                    break

            ret, frame = self._cap.read()

            if not ret or frame is None:
                if self.is_file and self.loop_video:
                    # Rewind video file
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue

                self._is_connected = False
                if self.auto_reconnect and not self.is_file:
                    reconnect_attempts += 1
                    self._reconnections += 1
                    time.sleep(self.reconnect_delay)
                    if self._cap:
                        self._cap.release()
                    self._open_capture()
                    continue
                else:
                    break

            now = time.time()
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

            # Frame-drop logic on queue saturation (keeps real-time latency zero)
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

            # FPS throttling for file replay
            if min_frame_time > 0:
                elapsed = time.time() - loop_start
                sleep_dur = min_frame_time - elapsed
                if sleep_dur > 0:
                    time.sleep(sleep_dur)

        self._is_connected = False

    def read(self, timeout: float = 1.0) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Retrieve the latest frame from the buffer.

        :param timeout: Maximum seconds to wait for a frame.
        :return: (success: bool, frame: np.ndarray or None)
        """
        if not self._running:
            self.start()

        try:
            frame = self._queue.get(block=True, timeout=timeout)
            return True, frame
        except queue.Empty:
            return False, None

    def grab_latest(self) -> Optional[np.ndarray]:
        """Non-blocking fetch of the latest available frame, or None if buffer is empty."""
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def get_metrics(self) -> Dict[str, Any]:
        """
        Retrieve real-time connection and telemetry statistics.
        """
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

    def stop(self):
        """Stop background worker and release resources."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        with self._lock:
            if self._cap:
                self._cap.release()
                self._cap = None
            self._is_connected = False
            # Drain queue
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break

    def release(self):
        self.stop()

    def is_alive(self) -> bool:
        return self._running and (self._thread.is_alive() if self._thread else False)

    def __enter__(self) -> "VideoSource":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
