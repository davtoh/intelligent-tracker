"""Intelligent Tracker - Asynchronous Inference Worker.

Decouples heavy FrameProcessor AI stepping from live video capture and MJPEG
encoding using a single-slot latest-frame buffer so slow inference drops
intermediate frames without stalling live video delivery.
"""

import logging
import threading
from typing import Any

import numpy as np

from intelligent_tracker.pipeline import FrameStepResult

logger = logging.getLogger("intelligent_tracker.dashboard.async_inference")


class AsyncInferenceWorker:
    """Single-slot latest-frame background worker for FrameProcessor.step()."""

    def __init__(self, processor: Any, max_dim: int = 1280) -> None:
        self._processor = processor
        self._max_dim = max_dim
        self._lock = threading.Lock()
        self._work_event = threading.Event()
        self._stop_event = threading.Event()
        self._pending: tuple[np.ndarray, float] | None = None
        self._latest_result: FrameStepResult | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the background inference thread if not already running."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="async-inference-worker",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        """Signal shutdown and join the inference thread outside locks."""
        self._stop_event.set()
        self._work_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None

    def submit(self, frame: np.ndarray, timestamp: float) -> None:
        """Queue the latest frame for inference, overwriting any unconsumed frame."""
        frame_copy = frame.copy()
        with self._lock:
            self._pending = (frame_copy, timestamp)
        self._work_event.set()

    def get_latest_result(self) -> FrameStepResult | None:
        """Return the most recent completed FrameStepResult, or None."""
        with self._lock:
            return self._latest_result

    def _run_loop(self) -> None:
        """Consume latest pending frame and publish updated FrameStepResult."""
        while not self._stop_event.is_set():
            self._work_event.wait()
            if self._stop_event.is_set():
                break

            with self._lock:
                self._work_event.clear()
                item = self._pending
                self._pending = None

            if item is None:
                continue

            frame, ts = item
            try:
                result = self._processor.step(
                    frame, timestamp=ts, max_dim=self._max_dim
                )
            except Exception:
                logger.exception("AsyncInferenceWorker failed during processor.step")
                continue

            with self._lock:
                self._latest_result = result


def build_live_step_result(
    async_worker: AsyncInferenceWorker,
    frame: np.ndarray,
    now: float,
    frame_seq: int,
    run_vision: bool,
) -> FrameStepResult:
    """Submit frame to async AI when enabled and merge latest cached detections."""
    if run_vision:
        async_worker.submit(frame, now)
        cached = async_worker.get_latest_result()
        if cached is not None:
            return FrameStepResult(
                frame=frame,
                tracks=cached.tracks,
                analytics=cached.analytics,
                identifications=cached.identifications,
                timestamp=now,
                fps=cached.fps,
                frame_count=frame_seq,
            )
    return FrameStepResult(frame=frame, timestamp=now, fps=0.0, frame_count=frame_seq)
