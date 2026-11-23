"""Live dashboard stream MP4 recording controller and StreamManager mixin."""

from datetime import datetime
import logging
import os
import re
import threading
import time
from typing import Any, Callable
import uuid

import numpy as np

from intelligent_tracker.video import PipelineVideoWriter

logger = logging.getLogger("intelligent_tracker.stream_recording")

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
        "processing_mode": None, "deferred_job_id": None,
    }


class StreamRecordingController:
    """Thread-safe controller managing per-camera MP4 recording via PipelineVideoWriter."""

    def __init__(
        self,
        camera_id: str,
        output_dir: str | None = None,
        writer_factory: Any = None,
        db_getter: Callable[[], Any] | None = None,
        mode_service_getter: Callable[[], Any] | None = None,
    ) -> None:
        self.camera_id = camera_id
        self._explicit_output_dir = output_dir is not None
        self.output_dir = output_dir or _resolve_default_videos_dir()
        self._writer_factory = writer_factory or PipelineVideoWriter
        self._db_getter = db_getter
        self._mode_service_getter = mode_service_getter
        self._lock = threading.RLock()
        self._writer: PipelineVideoWriter | None = None
        self._active_meta: dict[str, Any] | None = None
        self._last_meta: dict[str, Any] | None = None
        self._recorded_frames: list[dict[str, Any]] = []
        self._live_stats: dict[str, Any] = {}

    def _current_processing_mode(self) -> tuple[Any, str | None]:
        """Return (ProcessingModeService | None, active mode string | None)."""
        svc = self._mode_service_getter() if callable(self._mode_service_getter) else None
        mode = getattr(svc, "mode", None) if svc is not None else None
        return svc, mode

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
            _, proc_mode = self._current_processing_mode()
            self._writer = self._writer_factory(
                out_path, fps=float(fps), resolution=resolution,
                max_frames=max_frames, max_duration_s=max_duration_s,
            )
            self._active_meta = {
                "recording_id": uuid.uuid4().hex[:12], "camera_id": self.camera_id,
                "filename": safe_name, "output_path": out_path,
                "fps": float(fps), "annotated": False if proc_mode == "capture_only" else bool(annotated),
                "status": "recording", "started_at": time.time(), "stopped_at": None,
                "processing_mode": proc_mode, "deferred_job_id": None,
            }
            self._recorded_frames = []
            self._live_stats = {
                "frames_processed": 0, "total_detections": 0, "total_sightings": 0,
                "entity_ids": set(), "start_ts": None,
            }
            return self.status()

    def write_frame(
        self,
        raw_frame: np.ndarray,
        annotated_frame: np.ndarray | None = None,
        step_res: Any = None,
    ) -> bool:
        """Write raw or annotated frame to active recording and auto-finalize on limit."""
        with self._lock:
            if self._writer is None or self._active_meta is None:
                return False
            _, curr_mode = self._current_processing_mode()
            is_capture_only = curr_mode == "capture_only" or self._active_meta.get("processing_mode") == "capture_only"
            use_ann = (not is_capture_only) and self._active_meta.get("annotated", True) and annotated_frame is not None
            written = self._writer.write(annotated_frame if use_ann else raw_frame)
            if written and step_res is not None and not is_capture_only:
                self._capture_step_snapshot(step_res, raw_frame)
            if not self._writer.is_open:
                self._finalize_locked(status="completed")
            return written

    def _capture_step_snapshot(self, step_res: Any, raw_frame: np.ndarray) -> None:
        """Buffer time-indexed tracks and sighting tallies for instant Video Studio handoff."""
        ts = float(getattr(step_res, "timestamp", 0.0) or 0.0)
        if self._live_stats.get("start_ts") is None:
            self._live_stats["start_ts"] = ts
        fps = float((self._active_meta or {}).get("fps") or 20.0)
        frame_idx = int(self._live_stats.get("frames_processed", 0))
        rel_time = round(max(0.0, ts - self._live_stats["start_ts"]), 3) if ts > 0 else round(frame_idx / max(1.0, fps), 3)
        frame_obj = getattr(step_res, "frame", None)
        h, w = (frame_obj.shape[:2] if frame_obj is not None and hasattr(frame_obj, "shape") else raw_frame.shape[:2])
        tracks_raw = getattr(step_res, "tracks", None) or {}
        track_objs = tracks_raw.values() if isinstance(tracks_raw, dict) else tracks_raw
        active_tracks = [t.to_dict() if hasattr(t, "to_dict") else dict(t) for t in track_objs if hasattr(t, "to_dict") or isinstance(t, dict)]
        detections_raw = getattr(step_res, "detections", None) or []
        self._live_stats["frames_processed"] = frame_idx + 1
        self._live_stats["total_detections"] += len(detections_raw) if detections_raw else len(active_tracks)
        for ev in (getattr(step_res, "identifications", None) or []):
            eid = getattr(ev, "entity_id", None) if not isinstance(ev, dict) else ev.get("entity_id")
            if eid is not None:
                self._live_stats["entity_ids"].add(eid)
                self._live_stats["total_sightings"] += 1
        for tr in active_tracks:
            if tr.get("entity_id") is not None:
                self._live_stats["entity_ids"].add(tr["entity_id"])
        if active_tracks:
            self._recorded_frames.append({"time": rel_time, "frame": frame_idx, "source_resolution": [int(w), int(h)], "tracks": active_tracks})

    def _persist_live_capture_run(
        self, meta: dict[str, Any], frames: list[dict[str, Any]], stats: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Persist buffered live-capture track stream as a TrackerDB video run."""
        db = self._db_getter() if callable(self._db_getter) else None
        if db is None or not meta.get("filename") or not stats.get("frames_processed"):
            return None
        w = meta.get("width") or (frames[0]["source_resolution"][0] if frames else 640)
        h = meta.get("height") or (frames[0]["source_resolution"][1] if frames else 480)
        fps = float(meta.get("fps") or 20.0)
        report = {
            "frames_processed": int(stats.get("frames_processed", 0)),
            "total_detections": int(stats.get("total_detections", 0)),
            "total_sightings": int(stats.get("total_sightings", 0)),
            "unique_entities_identified": len(stats.get("entity_ids") or ()),
            "source_resolution": [int(w), int(h)],
            "source_fps": fps,
            "camera_id": self.camera_id,
        }
        config = {"detector": "live_pipeline", "sample_rate": 1, "confidence": 0.4, "camera_id": self.camera_id}
        try:
            from dashboard.services.video_report_store import save_report_run

            return save_report_run(
                filename=meta["filename"], report=report, config=config, frame_detections=frames,
                source_resolution=[int(w), int(h)], source_fps=fps, db=db, run_type="live_capture",
            )
        except Exception as exc:
            logger.warning("Failed to persist live_capture run for '%s': %s", meta.get("filename"), exc)
            return None

    def _finalize_locked(self, status: str) -> dict[str, Any]:
        """Release active writer and persist final metadata snapshot under lock."""
        meta = dict(self._active_meta or _idle_status(self.camera_id))
        recorded_frames = list(self._recorded_frames)
        stats = dict(self._live_stats)
        self._recorded_frames = []
        self._live_stats = {}
        if self._writer is not None:
            self._writer.release()
            meta.update(self._writer.snapshot())
        svc, curr_mode = self._current_processing_mode()
        final_mode = curr_mode or meta.get("processing_mode")
        is_capture_only = final_mode == "capture_only" or meta.get("processing_mode") == "capture_only"
        meta.update({"status": status, "is_recording": False, "stopped_at": time.time(), "processing_mode": final_mode})
        if is_capture_only:
            meta["annotated"] = False
            if svc is not None and meta.get("filename") and hasattr(svc, "enqueue_deferred_indexing"):
                try:
                    opts = {"video_path": meta["output_path"]} if meta.get("output_path") else None
                    entry = svc.enqueue_deferred_indexing(
                        meta["filename"], camera_id=self.camera_id,
                        recording_id=meta.get("recording_id") or "", opts=opts,
                    )
                    meta["deferred_job_id"] = entry.get("job_id")
                except Exception as exc:
                    logger.warning("Failed to enqueue deferred indexing for '%s': %s", meta.get("filename"), exc)
        else:
            run_rec = self._persist_live_capture_run(meta, recorded_frames, stats)
            if run_rec and run_rec.get("run_id"):
                meta["report_run_id"] = run_rec["run_id"]
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
