"""Processing mode & deferred indexing coordinator for dashboard pipelines."""

import logging
import os
import threading
import time
from typing import Any

from dashboard.dependencies import VIDEOS_DIR
from dashboard.services.video_analytics_service import submit_async_analytics_job
from dashboard.services.video_jobs_service import get_video_job_manager

logger = logging.getLogger("intelligent_tracker.dashboard.processing_mode")

VALID_PROCESSING_MODES: tuple[str, ...] = (
    "focus_only",
    "full_realtime",
    "capture_only",
    "paused",
)


class ProcessingModeService:
    """Thread-safe coordinator for backend processing modes and deferred indexing."""

    def __init__(
        self,
        mode: str = "focus_only",
        focused_camera_id: str | None = "cam_01",
        active_tab: str = "live",
    ) -> None:
        if mode not in VALID_PROCESSING_MODES:
            raise ValueError(f"Invalid processing mode: {mode!r}")
        self._lock = threading.RLock()
        self._mode: str = mode
        self._focused_camera_id: str | None = focused_camera_id
        self._active_tab: str = active_tab or "live"
        self._deferred_jobs: list[dict[str, Any]] = []
        self._updated_at: float = time.time()

    @property
    def mode(self) -> str:
        with self._lock:
            return self._mode

    @property
    def focused_camera_id(self) -> str | None:
        with self._lock:
            return self._focused_camera_id

    @property
    def active_tab(self) -> str:
        with self._lock:
            return self._active_tab

    def update(
        self, mode: str | None = None, focused_camera_id: str | None = None, active_tab: str | None = None
    ) -> dict[str, Any]:
        """Validate and apply processing mode, focus, or active-tab updates."""
        with self._lock:
            if mode is not None:
                normalized = mode.strip().lower()
                if normalized not in VALID_PROCESSING_MODES:
                    raise ValueError(f"Invalid processing mode {mode!r}; expected {VALID_PROCESSING_MODES}")
                self._mode = normalized
            if focused_camera_id is not None:
                self._focused_camera_id = focused_camera_id.strip() or None
            if active_tab is not None:
                self._active_tab = active_tab.strip().lower() or "live"
            self._updated_at = time.time()
            return self.get_state()

    def should_hibernate_camera(
        self, camera_id: str, subscriber_count: int = 0, is_recording: bool = False, in_camera_pool: bool = True
    ) -> bool:
        """Return True when a camera worker should pause frame capture."""
        if is_recording:
            return False
        with self._lock:
            mode, focused, tab = self._mode, self._focused_camera_id, self._active_tab
        if mode == "paused":
            return True
        if mode == "full_realtime":
            return not in_camera_pool and subscriber_count <= 0
        if mode == "capture_only":
            return subscriber_count <= 0
        if subscriber_count > 0:
            return False
        if tab != "live":
            return True
        return bool(in_camera_pool and focused and camera_id != focused)

    def should_run_vision_step(self, camera_id: str, is_recording: bool = False) -> bool:
        """Return True when FrameProcessor.step() AI inference should execute."""
        with self._lock:
            mode, focused, tab = self._mode, self._focused_camera_id, self._active_tab
        if mode in ("paused", "capture_only"):
            return False
        if mode == "full_realtime":
            return True
        if tab != "live" and not is_recording:
            return False
        if focused and camera_id != focused and not is_recording:
            return False
        return True

    def _build_camera_states(self, pool: Any) -> dict[str, dict[str, Any]]:
        """Build per-camera policy and runtime state snapshot from CameraPool."""
        streams = getattr(pool, "streams", {}) or {} if pool is not None else {}
        states: dict[str, dict[str, Any]] = {}
        for cam_id, sm in streams.items():
            sub_count = int(getattr(sm, "subscriber_count", 0))
            is_rec = bool(getattr(sm, "is_recording", False))
            states[cam_id] = {
                "is_running": bool(getattr(sm, "is_running", False)),
                "is_hibernating": bool(getattr(sm, "_is_hibernating", False)),
                "is_recording": is_rec,
                "subscriber_count": sub_count,
                "should_hibernate": self.should_hibernate_camera(
                    cam_id, subscriber_count=sub_count, is_recording=is_rec, in_camera_pool=True
                ),
                "should_run_vision": self.should_run_vision_step(cam_id, is_recording=is_rec),
            }
        return states

    def apply_to_pool(self, pool: Any) -> dict[str, dict[str, Any]]:
        """Synchronize CameraPool stream hibernation state with current mode."""
        if pool is None:
            return {}
        if hasattr(pool, "sync_processing_mode"):
            pool.sync_processing_mode(self)
        else:
            for cam_id, sm in (getattr(pool, "streams", {}) or {}).items():
                sub_count = int(getattr(sm, "subscriber_count", 0))
                is_rec = bool(getattr(sm, "is_recording", False))
                should_hib = self.should_hibernate_camera(
                    cam_id, subscriber_count=sub_count, is_recording=is_rec, in_camera_pool=True
                )
                if not should_hib and getattr(sm, "_is_hibernating", False):
                    sm._is_hibernating = False
                    vs = getattr(sm, "video_source", None)
                    if vs is not None and hasattr(vs, "resume"):
                        vs.resume()
        return self._build_camera_states(pool)

    def enqueue_deferred_indexing(
        self,
        filename: str,
        camera_id: str = "",
        recording_id: str = "",
        job_mgr: Any = None,
        opts: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Submit a deferred VideoIndexer job for a capture-only recording."""
        resolved_mgr = job_mgr if job_mgr is not None else get_video_job_manager()
        resolved_opts = {
            "detector": "yolov8n",
            "sample_rate": 2,
            "confidence": 0.4,
            "classes": [0],
            "scenario_camera_id": camera_id or None,
        }
        if opts:
            resolved_opts.update(opts)
        video_path = resolved_opts.pop("video_path", None) or os.path.join(VIDEOS_DIR, filename)
        job = submit_async_analytics_job(resolved_mgr, filename, video_path, resolved_opts)
        entry = {
            "job_id": job.job_id, "filename": filename, "camera_id": camera_id,
            "recording_id": recording_id, "status": job.status, "created_at": time.time(),
        }
        with self._lock:
            self._deferred_jobs = (self._deferred_jobs + [entry])[-50:]
        return dict(entry)

    def get_state(self, pool: Any = None) -> dict[str, Any]:
        """Return current processing mode status snapshot."""
        with self._lock:
            return {
                "mode": self._mode, "focused_camera_id": self._focused_camera_id,
                "active_tab": self._active_tab, "valid_modes": list(VALID_PROCESSING_MODES),
                "deferred_jobs": list(self._deferred_jobs),
                "camera_states": self._build_camera_states(pool), "updated_at": self._updated_at,
            }


_service_lock = threading.Lock()
_service_instance: ProcessingModeService | None = None


def get_processing_mode_service() -> ProcessingModeService:
    """Return the process-wide singleton ProcessingModeService instance."""
    global _service_instance
    if _service_instance is None:
        with _service_lock:
            if _service_instance is None:
                _service_instance = ProcessingModeService()
    return _service_instance
