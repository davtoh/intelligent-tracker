"""Thread-safe video writer utilities shared by CLI pipelines and dashboard recording."""

import os
import threading
import time
from typing import Any

import cv2
import numpy as np

DEFAULT_CODEC_FALLBACKS: tuple[str, ...] = ("mp4v", "avc1", "MJPG", "XVID")


def _open_cv_writer(
    output_path: str,
    fps: float,
    width: int,
    height: int,
    codecs: tuple[str, ...],
) -> tuple[cv2.VideoWriter, str]:
    """Try opening cv2.VideoWriter across fallback FourCC codecs."""
    parent = os.path.dirname(os.path.abspath(output_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    for codec in codecs:
        fourcc = cv2.VideoWriter_fourcc(*codec)
        writer = cv2.VideoWriter(output_path, fourcc, float(fps), (int(width), int(height)))
        if writer is not None and writer.isOpened():
            return writer, codec
        if writer is not None:
            writer.release()
        if os.path.exists(output_path) and os.path.getsize(output_path) == 0:
            try:
                os.remove(output_path)
            except OSError:
                pass
    raise RuntimeError(
        f"Failed to open VideoWriter for '{output_path}' using codecs {codecs}"
    )


def _normalize_frame(frame: np.ndarray, width: int, height: int) -> np.ndarray | None:
    """Convert grayscale/shape-mismatched frames to contiguous BGR of target size."""
    if frame is None or not hasattr(frame, "shape") or frame.size == 0:
        return None
    out = frame
    if out.ndim == 2:
        out = cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)
    elif out.ndim == 3 and out.shape[2] == 4:
        out = cv2.cvtColor(out, cv2.COLOR_BGRA2BGR)
    if out.shape[1] != width or out.shape[0] != height:
        out = cv2.resize(out, (width, height))
    if out.dtype != np.uint8:
        out = np.clip(out, 0, 255).astype(np.uint8)
    return out


class PipelineVideoWriter:
    """Thread-safe MP4/AVI video writer with codec fallback, resize, and telemetry."""

    def __init__(
        self,
        output_path: str | os.PathLike[str],
        *,
        fps: float = 20.0,
        resolution: tuple[int, int] = (640, 480),
        codecs: tuple[str, ...] = DEFAULT_CODEC_FALLBACKS,
        max_frames: int | None = None,
        max_duration_s: float | None = None,
    ) -> None:
        width, height = int(resolution[0]), int(resolution[1])
        if fps <= 0:
            raise ValueError(f"fps must be positive, got {fps}")
        if width <= 0 or height <= 0:
            raise ValueError(f"resolution must be positive, got {(width, height)}")
        if max_frames is not None and max_frames <= 0:
            raise ValueError(f"max_frames must be positive, got {max_frames}")
        if max_duration_s is not None and max_duration_s <= 0:
            raise ValueError(f"max_duration_s must be positive, got {max_duration_s}")

        self.output_path = os.fspath(output_path)
        self.fps = float(fps)
        self.width = width
        self.height = height
        self.max_frames = max_frames
        self.max_duration_s = max_duration_s

        self._lock = threading.RLock()
        self._writer, self.codec = _open_cv_writer(
            self.output_path, self.fps, self.width, self.height, tuple(codecs)
        )
        self._released = False
        self.frames_written = 0
        self.started_at = time.time()
        self.stopped_at: float | None = None
        self._start_mono = time.monotonic()
        self._stop_mono: float | None = None

    @property
    def is_open(self) -> bool:
        """Return True when the underlying writer is active and not yet released."""
        with self._lock:
            return not self._released and self._writer is not None

    def _bounds_exceeded_locked(self) -> bool:
        """Check whether configured frame or duration limits have been reached."""
        if self.max_frames is not None and self.frames_written >= self.max_frames:
            return True
        if self.max_duration_s is not None:
            if (time.monotonic() - self._start_mono) >= self.max_duration_s:
                return True
        return False

    def write(self, frame: np.ndarray) -> bool:
        """Resize if needed and write a single BGR frame thread-safely."""
        with self._lock:
            if self._released or self._writer is None:
                return False
            if self._bounds_exceeded_locked():
                self.release()
                return False
            normalized = _normalize_frame(frame, self.width, self.height)
            if normalized is None:
                return False
            self._writer.write(normalized)
            self.frames_written += 1
            if self._bounds_exceeded_locked():
                self.release()
            return True

    def release(self) -> None:
        """Idempotently flush and release the underlying cv2.VideoWriter."""
        with self._lock:
            if self._released:
                return
            self._released = True
            self.stopped_at = time.time()
            self._stop_mono = time.monotonic()
            if self._writer is not None:
                try:
                    self._writer.release()
                finally:
                    self._writer = None

    def snapshot(self) -> dict[str, Any]:
        """Return current recording statistics and output file metadata."""
        with self._lock:
            end_mono = self._stop_mono if self._stop_mono is not None else time.monotonic()
            elapsed = max(0.0, round(end_mono - self._start_mono, 3))
            size_bytes = os.path.getsize(self.output_path) if os.path.exists(self.output_path) else 0
            return {
                "output_path": self.output_path,
                "codec": self.codec,
                "fps": self.fps,
                "width": self.width,
                "height": self.height,
                "frames_written": self.frames_written,
                "elapsed_s": elapsed,
                "size_bytes": size_bytes,
                "is_open": not self._released and self._writer is not None,
                "max_frames": self.max_frames,
                "max_duration_s": self.max_duration_s,
            }

    def __enter__(self) -> "PipelineVideoWriter":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.release()
