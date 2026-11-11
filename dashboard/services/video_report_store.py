#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Video Analytics Report & Frame Detection Persistence Service.

Persists occurrence indexing reports and time-indexed frame detections
to disk so historical runs are stackable and survive server restarts.
"""

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from dashboard.dependencies import VIDEOS_DIR

logger = logging.getLogger(__name__)

REPORTS_DIR = os.path.join("data", "reports")
_VIDEO_EXTENSIONS = (".mp4", ".mkv", ".avi", ".mov")


def _get_safe_filename(filename: str) -> str:
    """Extract canonical basename to prevent directory traversal."""
    return os.path.basename(str(filename).strip())


def _ensure_reports_dir() -> str:
    """Ensure data/reports directory exists."""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    return REPORTS_DIR


def _reports_file_path(safe_name: str) -> str:
    """Get path to stacked reports file for a video."""
    return os.path.join(_ensure_reports_dir(), f"{safe_name}_reports.json")


def _detections_file_path(safe_name: str, run_id: str) -> str:
    """Get path to frame detections stream file for a specific run."""
    return os.path.join(_ensure_reports_dir(), f"{safe_name}_{run_id}_detections.json")


def resolve_base_recording_name(filename: str) -> str:
    """Resolve _h264 child filenames to their canonical base recording name."""
    safe_name = _get_safe_filename(filename)
    stem, ext = os.path.splitext(safe_name)
    if not stem.lower().endswith("_h264"):
        return safe_name

    base_stem = stem[:-5]
    # Prefer .mp4 first, then check alternate container extensions in videos/reports dirs
    candidate_exts = [".mp4"] + [e for e in _VIDEO_EXTENSIONS if e != ".mp4"]
    if ext and ext.lower() not in candidate_exts:
        candidate_exts.append(ext.lower())

    for cand_ext in candidate_exts:
        candidate = f"{base_stem}{cand_ext}"
        if os.path.isfile(os.path.join(VIDEOS_DIR, candidate)):
            return candidate
        if os.path.isfile(os.path.join(REPORTS_DIR, f"{candidate}_reports.json")):
            return candidate

    return f"{base_stem}.mp4"


def _get_alias_filenames(safe_name: str) -> List[str]:
    """Return ordered unique filename aliases for unified report lookup."""
    canonical = resolve_base_recording_name(safe_name)
    stem, _ = os.path.splitext(canonical)
    h264_variant = f"{stem}_h264.mp4"
    aliases: List[str] = []
    for name in (canonical, safe_name, h264_variant):
        if name and name not in aliases:
            aliases.append(name)

    if safe_name.lower().endswith("_h264.mp4"):
        base_stem = safe_name[:-9]
        for ext in _VIDEO_EXTENSIONS:
            cand = f"{base_stem}{ext}"
            if cand not in aliases:
                aliases.append(cand)
    return aliases


def _extract_source_metadata(
    report: Dict[str, Any],
    source_resolution: Optional[List[int]],
    source_fps: Optional[float],
) -> tuple[Optional[List[int]], Optional[float]]:
    """Resolve source_resolution and source_fps from explicit args or execution summary."""
    exec_summary = report.get("execution_summary")
    summary_dict = exec_summary if isinstance(exec_summary, dict) else {}

    res = source_resolution if source_resolution is not None else (
        report.get("source_resolution") or summary_dict.get("source_resolution")
    )
    if isinstance(res, tuple):
        res = list(res)

    fps = source_fps if source_fps is not None else report.get("source_fps")
    if fps is None:
        fps = summary_dict.get("source_fps")
    return res, fps


def _load_runs_file(path: str) -> List[Dict[str, Any]]:
    """Load report runs array from JSON file safely."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception as e:
        logger.warning("Could not read reports file %s: %s", path, e)
    return []


def _write_json_atomic(path: str, payload: Any, indent: Optional[int] = None) -> None:
    """Atomically write JSON payload via temporary file replacement."""
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=indent)
    os.replace(tmp_path, path)


def _save_detections_file(
    canonical_name: str,
    safe_name: str,
    run_id: str,
    generated_at: str,
    frame_detections: List[Dict[str, Any]],
    resolved_res: Optional[List[int]],
    resolved_fps: Optional[float],
) -> Optional[str]:
    """Persist detection stream payload and return normalized relative path."""
    det_path = _detections_file_path(canonical_name, run_id)
    det_payload = {
        "run_id": run_id,
        "filename": safe_name,
        "base_filename": canonical_name,
        "generated_at": generated_at,
        "source_resolution": resolved_res,
        "source_fps": resolved_fps,
        "frame_count": len(frame_detections),
        "frame_detections": frame_detections,
    }
    try:
        _write_json_atomic(det_path, det_payload)
        return det_path.replace("\\", "/")
    except Exception as e:
        logger.error("Failed saving detections file for %s (%s): %s", canonical_name, run_id, e)
        return None


def save_report_run(
    filename: str,
    report: Dict[str, Any],
    config: Dict[str, Any],
    frame_detections: Optional[List[Dict[str, Any]]] = None,
    source_resolution: Optional[List[int]] = None,
    source_fps: Optional[float] = None,
) -> Dict[str, Any]:
    """Archive an occurrence indexing run and optional frame detection stream."""
    safe_name = _get_safe_filename(filename)
    canonical_name = resolve_base_recording_name(safe_name)
    resolved_res, resolved_fps = _extract_source_metadata(report, source_resolution, source_fps)

    run_id = f"run_{uuid.uuid4().hex[:8]}"
    now = time.time()
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))

    detections_rel_path = None
    if frame_detections is not None:
        detections_rel_path = _save_detections_file(
            canonical_name, safe_name, run_id, generated_at,
            frame_detections, resolved_res, resolved_fps,
        )

    run_record: Dict[str, Any] = {
        "run_id": run_id,
        "filename": safe_name,
        "base_filename": canonical_name,
        "timestamp": now,
        "generated_at": generated_at,
        "source_resolution": resolved_res,
        "source_fps": resolved_fps,
        "config": config,
        "metrics": {
            "frames_processed": report.get("frames_processed", 0),
            "total_detections": report.get("total_detections", 0),
            "total_sightings": report.get("total_sightings", 0),
            "unique_entities_identified": report.get("unique_entities_identified", 0),
        },
        "report": report,
        "detections_file": detections_rel_path,
    }

    existing_runs = list_report_runs(canonical_name)
    rep_path = _reports_file_path(canonical_name)
    try:
        _write_json_atomic(rep_path, [run_record] + existing_runs, indent=2)
    except Exception as e:
        logger.error("Failed writing stacked reports file for %s: %s", canonical_name, e)

    return run_record


def list_report_runs(filename: str) -> List[Dict[str, Any]]:
    """List all archived report runs for a video or its _h264 pair, newest first."""
    safe_name = _get_safe_filename(filename)
    seen_ids = set()
    merged: List[Dict[str, Any]] = []

    for alias in _get_alias_filenames(safe_name):
        path = _reports_file_path(alias)
        if not os.path.exists(path):
            continue
        for run in _load_runs_file(path):
            rid = run.get("run_id")
            if rid and rid in seen_ids:
                continue
            if rid:
                seen_ids.add(rid)
            merged.append(run)

    merged.sort(key=lambda r: float(r.get("timestamp", 0.0)), reverse=True)
    return merged


def _find_detections_path(safe_name: str, target_run: Dict[str, Any]) -> Optional[str]:
    """Locate detection stream file across base/child aliases or recorded path."""
    rid = target_run.get("run_id")
    if rid:
        for alias in _get_alias_filenames(safe_name):
            candidate = _detections_file_path(alias, rid)
            if os.path.exists(candidate):
                return candidate
    recorded_path = target_run.get("detections_file")
    if recorded_path and os.path.isfile(recorded_path):
        return recorded_path
    return None


def get_detection_stream(filename: str, run_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve frame detection stream for scrubber video canvas overlay."""
    safe_name = _get_safe_filename(filename)
    runs = list_report_runs(safe_name)
    if not runs:
        return None

    target_run = next((r for r in runs if r.get("run_id") == run_id), None) if run_id else runs[0]
    if not target_run:
        return None

    det_path = _find_detections_path(safe_name, target_run)
    if det_path is None:
        return None

    try:
        with open(det_path, "r", encoding="utf-8") as f:
            stream = json.load(f)
        if isinstance(stream, dict):
            if stream.get("source_resolution") is None and target_run.get("source_resolution") is not None:
                stream["source_resolution"] = target_run.get("source_resolution")
            if stream.get("source_fps") is None and target_run.get("source_fps") is not None:
                stream["source_fps"] = target_run.get("source_fps")
        return stream
    except Exception as e:
        logger.error("Error reading detections stream for %s (%s): %s", safe_name, target_run.get("run_id"), e)
        return None
