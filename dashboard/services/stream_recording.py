"""Live dashboard stream MP4 recording controller and StreamManager mixin."""

from datetime import datetime
import os
import re
import threading
import time
from typing import Any
import uuid

import numpy as np

from intelligent_tracker.video import PipelineVideoWriter

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_VALID_EXTS = (".mp4", ".avi", ".mkv", ".mov")


def _resolve_default_videos_dir() -> str:
    """Resolve default recording directory without circular top-level imports."""
    env_dir = os.environ.get("TRACKER_VIDEOS_DIR")
    if env_dir:
        return env_dir
    try:
        from dashboard.dependencies import VIDEOS_DIR

        return VIDEOS_DIR
    except Exception:
        return os.path.join("data", "videos")


def sanitize_recording_filename(camera_id: str, filename: str | None) -> str:
    """Validate explicit filename or generate a unique safe MP4 filename."""
    safe_cam = re.sub(r"[^A-Za-z0-9_-]+", "_", camera_id or "cam").strip("_") or "cam"
    if filename is None:
        return f"{safe_cam}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.mp4"
    cleaned = str(filename).strip()
    if not cleaned or "/" in cleaned or "\\" in cleaned or ".." in cleaned or not _SAFE_NAME_RE.match(cleaned):
        raise ValueError("Invalid recording filename")
    return cleaned if cleaned.lower().endswith(_VALID_EXTS) else f"{cleaned}.mp4"


def _idle_status(camera_id: str) -> dict[str, Any]:
    """Build default idle recording status dictionary."""
    return {
        "camera_id": camera_id, "is_recording": False, "status": "idle",
        "recording_id": None, "filename": None, "output_path": None, "codec": None,
        "fps": None, "width": None, "height": None, "frames_written": 0,
        "elapsed_s": 0.0, "size_bytes": 0, "annotated": True,
    }


class StreamRecordingController:
    """Thread-safe controller managing per-camera MP4 recording via PipelineVideoWriter."""

    def __init__(self, camera_id: str, output_dir: str | None = None, writer_factory: Any = None) -> None:
        self.camera_id = camera_id
        self._explicit_output_dir = output_dir is not None
        self.output_dir = output_dir or _resolve_default_videos_dir()
        self._writer_factory = writer_factory or PipelineVideoWriter
        self._lock = threading.RLock()
        self._writer: PipelineVideoWriter | None = None
        self._active_meta: dict[str, Any] | None = None
        self._last_meta: dict[str, Any] | None = None

    @property
    def is_recording(self) -> bool:
        """Return True while a recording writer is active and open."""
        with self._lock:
            return self._writer is not None and self._writer.is_open

    def start(
        self, *, filename: str | None = None, fps: float = 20.0,
        resolution: tuple[int, int] = (640, 480), annotated: bool = True,
        max_frames: int | None = None, max_duration_s: float | None = None,
        output_dir: str | None = None,
    ) -> dict[str, Any]:
        """Start MP4 recording for the camera stream."""
        with self._lock:
            if self._writer is not None and self._writer.is_open:
                raise RuntimeError(f"Camera '{self.camera_id}' is already recording")
            target_dir = output_dir if (output_dir and not self._explicit_output_dir) else self.output_dir
            safe_name = sanitize_recording_filename(self.camera_id, filename)
            os.makedirs(target_dir, exist_ok=True)
            out_path = os.path.join(target_dir, safe_name)
            self._writer = self._writer_factory(
                out_path, fps=float(fps), resolution=resolution,
                max_frames=max_frames, max_duration_s=max_duration_s,
            )
            self._active_meta = {
                "recording_id": uuid.uuid4().hex[:12], "camera_id": self.camera_id,
                "filename": safe_name, "output_path": out_path,
                "annotated": bool(annotated), "status": "recording",
                "started_at": time.time(), "stopped_at": None,
            }
            return self.status()

    def write_frame(self, raw_frame: np.ndarray, annotated_frame: np.ndarray | None = None) -> bool:
        """Write raw or annotated frame to active recording and auto-finalize on limit."""
        with self._lock:
            if self._writer is None or self._active_meta is None:
                return False
            use_ann = self._active_meta.get("annotated", True) and annotated_frame is not None
            written = self._writer.write(annotated_frame if use_ann else raw_frame)
            if not self._writer.is_open:
                self._finalize_locked(status="completed")
            return written

    def _finalize_locked(self, status: str) -> dict[str, Any]:
        """Release active writer and persist final metadata snapshot under lock."""
        meta = dict(self._active_meta or _idle_status(self.camera_id))
        if self._writer is not None:
            self._writer.release()
            meta.update(self._writer.snapshot())
        meta.update({"status": status, "is_recording": False, "stopped_at": time.time()})
        self._writer = None
        self._active_meta = None
        self._last_meta = meta
        return dict(meta)

    def stop(self) -> dict[str, Any]:
        """Stop an active recording and return finalized file telemetry."""
        with self._lock:
            if self._writer is None:
                raise RuntimeError(f"No active recording for camera '{self.camera_id}'")
            return self._finalize_locked(status="stopped")

    def finalize_if_active(self) -> dict[str, Any] | None:
        """Idempotently finalize any active recording during stream teardown."""
        with self._lock:
            return None if self._writer is None else self._finalize_locked(status="stopped")

    def status(self) -> dict[str, Any]:
        """Return active, last completed, or idle recording status snapshot."""
        with self._lock:
            if self._writer is not None and self._active_meta is not None:
                return {**self._active_meta, **self._writer.snapshot(), "is_recording": self._writer.is_open}
            if self._last_meta is not None:
                snap = dict(self._last_meta)
                if snap.get("output_path") and os.path.exists(snap["output_path"]):
                    snap["size_bytes"] = os.path.getsize(snap["output_path"])
                return snap
            return _idle_status(self.camera_id)


class StreamRecordingMixin:
    """Mixin exposing stream recording lifecycle methods on StreamManager."""

    @property
    def is_recording(self) -> bool:
        """Return True while the stream is actively recording to MP4."""
        controller = getattr(self, "_recording_controller", None)
        return bool(controller is not None and controller.is_recording)

    def start_recording(self, **kwargs: Any) -> dict[str, Any]:
        """Start MP4 recording and wake a hibernating video source if needed."""
        src_fps = getattr(self.video_source, "fps", None)
        cfg_fps = self.cfg.get("video", {}).get("framerate", 20.0)
        if kwargs.get("fps") is None:
            kwargs["fps"] = float(src_fps if src_fps and src_fps > 0 else cfg_fps)
        kwargs.setdefault("resolution", (self.width, self.height))
        res = self._recording_controller.start(**kwargs)
        with self._lock:
            self._is_hibernating = False
            if self._latest_telemetry and self._latest_telemetry.get("status") == "hibernating":
                self._latest_telemetry["status"] = "online"
        self._resume_video_source()
        return res

    def stop_recording(self) -> dict[str, Any]:
        """Stop active MP4 recording and return finalized metadata."""
        return self._recording_controller.stop()

    def get_recording_status(self) -> dict[str, Any]:
        """Return current or last completed recording telemetry."""
        return self._recording_controller.status()
