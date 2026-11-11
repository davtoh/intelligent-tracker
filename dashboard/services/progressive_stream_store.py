#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Progressive Frame Detection Stream Buffer for Active Batch Analytics Jobs.

Buffers partial frame detection chunks emitted by ``VideoIndexer.process_video``
in thread-safe memory and atomic partial JSON snapshots so clients can scrub
and render bounding boxes while an analytics job is still running.
"""

import json
import logging
import os
import threading
import time
from typing import Any

from dashboard.services import video_report_store

logger = logging.getLogger(__name__)

_MAX_PROGRESSIVE_STREAMS = 24
_stream_lock = threading.Lock()
_streams: dict[str, dict[str, Any]] = {}


def _partial_file_path(canonical_name: str, job_id: str) -> str:
    """Compute disk path for an in-flight progressive detection snapshot."""
    reports_dir = video_report_store.REPORTS_DIR
    return os.path.join(reports_dir, f"{canonical_name}_{job_id}_partial_detections.json")


def _prune_streams_unlocked() -> None:
    """Evict oldest completed entries if in-memory buffer exceeds capacity."""
    if len(_streams) <= _MAX_PROGRESSIVE_STREAMS:
        return
    ordered = sorted(
        _streams.items(),
        key=lambda item: (0 if item[1].get("final") else 1, float(item[1].get("updated_at", 0.0))),
    )
    for jid, _ in ordered[: len(_streams) - _MAX_PROGRESSIVE_STREAMS]:
        _streams.pop(jid, None)


def _write_partial_snapshot(partial_path: str, payload: dict[str, Any]) -> None:
    """Persist progressive snapshot atomically outside locks."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(partial_path)), exist_ok=True)
        tmp_path = f"{partial_path}.{threading.get_ident()}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp_path, partial_path)
    except Exception as e:
        logger.debug("Failed writing progressive snapshot %s: %s", partial_path, e)


def _format_stream_slice(entry: dict[str, Any], since: int) -> dict[str, Any]:
    """Build a slice response dict from a stored progressive stream entry."""
    all_frames = entry.get("frame_detections", [])
    start = max(0, int(since))
    sliced = list(all_frames[start:])
    return {
        "job_id": entry.get("job_id"),
        "filename": entry.get("filename"),
        "base_filename": entry.get("base_filename"),
        "source_resolution": entry.get("source_resolution"),
        "source_fps": entry.get("source_fps"),
        "processed_frames": entry.get("processed_frames", 0),
        "read_frames": entry.get("read_frames", 0),
        "total_frames": entry.get("total_frames", 0),
        "latest_time": entry.get("latest_time", 0.0),
        "since": start,
        "next_index": len(all_frames),
        "frame_count": len(sliced),
        "total_buffered_frames": len(all_frames),
        "final": bool(entry.get("final", False)),
        "frame_detections": sliced,
    }


def append_progressive_chunk(
    job_id: str,
    filename: str,
    chunk: list[dict[str, Any]],
    meta: dict[str, Any],
    persist_disk: bool = True,
) -> None:
    """Append newly flushed detection frames to memory cache and partial disk snapshot."""
    safe_name = os.path.basename(str(filename).strip())
    canonical = video_report_store.resolve_base_recording_name(safe_name)
    partial_path = _partial_file_path(canonical, job_id)
    now = time.time()

    with _stream_lock:
        entry = _streams.get(job_id)
        if entry is None:
            entry = {
                "job_id": job_id,
                "filename": safe_name,
                "base_filename": canonical,
                "partial_path": partial_path,
                "frame_detections": [],
                "source_resolution": None,
                "source_fps": None,
                "processed_frames": 0,
                "read_frames": 0,
                "total_frames": 0,
                "latest_time": 0.0,
                "final": False,
                "updated_at": now,
            }
            _streams[job_id] = entry

        if chunk:
            entry["frame_detections"].extend(chunk)
        for key in ("source_resolution", "source_fps", "processed_frames", "read_frames", "total_frames", "latest_time"):
            if meta.get(key) is not None:
                entry[key] = meta[key]
        entry["final"] = bool(meta.get("final", False))
        entry["updated_at"] = now
        _prune_streams_unlocked()
        snapshot = _format_stream_slice(entry, 0) if (persist_disk and not entry["final"]) else None

    if snapshot is not None:
        _write_partial_snapshot(partial_path, snapshot)


def finalize_progressive_stream(job_id: str) -> None:
    """Mark stream final in memory and delete any temporary partial disk snapshot."""
    partial_path = None
    with _stream_lock:
        entry = _streams.get(job_id)
        if entry is not None:
            entry["final"] = True
            entry["updated_at"] = time.time()
            partial_path = entry.get("partial_path")

    if partial_path and os.path.isfile(partial_path):
        try:
            os.remove(partial_path)
        except OSError as e:
            logger.debug("Could not remove partial detection snapshot %s: %s", partial_path, e)


def get_progressive_stream(
    job_id: str,
    since: int = 0,
    filename: str | None = None,
) -> dict[str, Any] | None:
    """Retrieve progressive detection frames starting at ``since``."""
    with _stream_lock:
        entry = _streams.get(job_id)
        if entry is not None:
            return _format_stream_slice(entry, since)

    if filename:
        canonical = video_report_store.resolve_base_recording_name(filename)
        partial_path = _partial_file_path(canonical, job_id)
        if os.path.isfile(partial_path):
            try:
                with open(partial_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return _format_stream_slice(data, since)
            except Exception as e:
                logger.debug("Failed reading partial snapshot %s: %s", partial_path, e)
    return None


def build_job_stream_response(job: Any, requested_filename: str, since: int = 0) -> dict[str, Any]:
    """Assemble progressive stream payload for GET /api/videos/{filename}/jobs/{job_id}/stream."""
    run_id = job.result.get("run_id") if isinstance(job.result, dict) else None
    stream = get_progressive_stream(job.job_id, since=since, filename=job.filename)

    if stream is None and run_id:
        persisted = video_report_store.get_detection_stream(requested_filename, run_id)
        if persisted is not None:
            all_frames = persisted.get("frame_detections", [])
            stream = _format_stream_slice(
                {
                    "job_id": job.job_id,
                    "filename": job.filename,
                    "base_filename": persisted.get("base_filename")
                    or video_report_store.resolve_base_recording_name(job.filename),
                    "source_resolution": persisted.get("source_resolution"),
                    "source_fps": persisted.get("source_fps"),
                    "processed_frames": len(all_frames),
                    "read_frames": len(all_frames),
                    "total_frames": len(all_frames),
                    "latest_time": all_frames[-1]["time"] if all_frames else 0.0,
                    "final": True,
                    "frame_detections": all_frames,
                },
                since,
            )

    if stream is None:
        status_val = job.status.value if hasattr(job.status, "value") else str(job.status)
        stream = _format_stream_slice(
            {
                "job_id": job.job_id,
                "filename": job.filename,
                "base_filename": video_report_store.resolve_base_recording_name(job.filename),
                "processed_frames": int(job.metrics.get("processed_frames", 0) or 0),
                "read_frames": int(job.metrics.get("read_frames", 0) or 0),
                "total_frames": int(job.metrics.get("total_frames", 0) or 0),
                "final": status_val in ("completed", "cancelled", "failed"),
                "frame_detections": [],
            },
            since,
        )

    stream["status"] = job.status.value if hasattr(job.status, "value") else str(job.status)
    stream["progress"] = job.progress
    stream["run_id"] = run_id
    return stream

