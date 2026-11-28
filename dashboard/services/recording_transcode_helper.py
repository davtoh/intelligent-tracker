"""Helpers for web-playable H.264 recording auto-transcode and active-recording guards."""

import logging
import os
import shutil
from typing import Any, Callable

from dashboard.services.video_transcoder import VideoTranscodeService

logger = logging.getLogger("intelligent_tracker.recording_transcode_helper")

WEB_PLAYABLE_CODECS: frozenset[str] = frozenset({"avc1", "h264", "x264", "avc3"})


def is_web_playable_codec(codec: str) -> bool:
    """Return True when a FourCC/codec identifier is natively web-playable H.264."""
    return str(codec or "").strip().lower() in WEB_PLAYABLE_CODECS


def _iter_recording_streams(pool: Any, stream_manager: Any) -> list[tuple[str, Any]]:
    """Collect unique StreamManager candidates from CameraPool and primary stream."""
    streams: list[tuple[str, Any]] = []
    seen_ids: set[int] = set()
    if pool is not None and (hasattr(pool, "streams") or hasattr(pool, "camera_configs")):
        from dashboard.services.camera_pool_queries import snapshot_pool_streams

        for cid, mgr in snapshot_pool_streams(pool).items():
            if mgr is not None and id(mgr) not in seen_ids:
                seen_ids.add(id(mgr))
                streams.append((cid, mgr))
    if stream_manager is not None and hasattr(stream_manager, "is_recording") and id(stream_manager) not in seen_ids:
        cid = str(getattr(stream_manager, "camera_id", None) or "primary")
        streams.append((cid, stream_manager))
    return streams


def _matches_recording_target(safe_name: str, target_abs: str | None, status: dict[str, Any]) -> bool:
    """Return True when active recording status targets the same filename or resolved path."""
    rec_filename = str(status.get("filename") or "").strip()
    rec_path = str(status.get("output_path") or "").strip()
    if rec_filename and os.path.basename(rec_filename) == safe_name:
        return True
    if rec_path and os.path.basename(rec_path) == safe_name:
        return True
    if target_abs and rec_path:
        try:
            return os.path.normcase(os.path.abspath(rec_path)) == target_abs
        except OSError:
            return False
    return False


def find_active_recording_for_file(filename: str, pool: Any, stream_manager: Any) -> dict[str, Any] | None:
    """Return active recording metadata if any live stream is currently writing ``filename``."""
    raw_name = str(filename or "").strip()
    safe_name = os.path.basename(raw_name)
    if not safe_name:
        return None
    target_abs = os.path.normcase(os.path.abspath(raw_name)) if (os.path.sep in raw_name or "/" in raw_name) else None
    for cid, mgr in _iter_recording_streams(pool, stream_manager):
        if not getattr(mgr, "is_recording", False):
            continue
        try:
            status = mgr.get_recording_status() if hasattr(mgr, "get_recording_status") else {}
        except Exception:
            continue
        if isinstance(status, dict) and status.get("is_recording") and _matches_recording_target(safe_name, target_abs, status):
            return {
                "camera_id": status.get("camera_id") or cid,
                "recording_id": status.get("recording_id"),
                "filename": status.get("filename") or safe_name,
                "output_path": status.get("output_path"),
            }
    return None


def _resolve_job_manager(job_mgr: Any) -> Any:
    """Return explicit job manager or lazily resolve the global VideoJobManager."""
    if job_mgr is not None:
        return job_mgr
    if shutil.which("ffmpeg") is None:
        return None
    try:
        from dashboard.services.video_jobs_service import get_video_job_manager

        return get_video_job_manager()
    except Exception as exc:
        logger.debug("VideoJobManager unavailable for auto-transcode: %s", exc)
        return None


def _build_transcode_runner(
    output_path: str, filename: str, target_path: str, target_name: str
) -> Callable[[Any, Any, Any], dict[str, Any]]:
    """Create a VideoJobManager runner closure for async H.264 transcoding."""
    def _runner(_job: Any, stop_event: Any, progress_cb: Any) -> dict[str, Any]:
        VideoTranscodeService.transcode_to_h264_async(
            input_path=output_path,
            output_path=target_path,
            target_resolution=None,
            progress_callback=progress_cb,
            stop_event=stop_event,
        )
        size_mb = round(os.path.getsize(target_path) / (1024 * 1024), 2) if os.path.isfile(target_path) else 0.0
        return {
            "original_filename": filename,
            "output_filename": target_name,
            "video_url": f"/videos/{target_name}",
            "size_mb": size_mb,
        }

    return _runner


def maybe_queue_h264_transcode(meta: dict[str, Any], job_mgr: Any = None, *, enabled: bool = True) -> str | None:
    """Queue an async H.264 transcode job for finalized non-H.264 recordings."""
    if not enabled or not isinstance(meta, dict) or int(meta.get("frames_written") or 0) <= 0:
        return None
    if is_web_playable_codec(str(meta.get("codec") or "")):
        return None
    output_path = str(meta.get("output_path") or "").strip()
    filename = str(meta.get("filename") or os.path.basename(output_path)).strip()
    if not output_path or not filename or not os.path.isfile(output_path):
        return None
    pair = VideoTranscodeService.get_h264_pair_info(output_path)
    if filename.lower().endswith("_h264.mp4") or pair.get("has_converted_h264"):
        return None
    mgr = _resolve_job_manager(job_mgr)
    if mgr is None or getattr(mgr, "is_shutdown", False) or getattr(mgr, "_is_shutdown", False):
        return None
    if hasattr(mgr, "get_active_job_for_file") and mgr.get_active_job_for_file(filename) is not None:
        return None
    runner = _build_transcode_runner(output_path, filename, pair["output_path"], pair["output_filename"])
    try:
        job = mgr.submit_job(
            job_type="transcode", filename=filename, runner_fn=runner,
            initial_metrics={"output_filename": pair["output_filename"], "auto_transcode": True},
        )
        return getattr(job, "job_id", None)
    except Exception as exc:
        logger.warning("Failed to queue H.264 auto-transcode for '%s': %s", filename, exc)
        return None
