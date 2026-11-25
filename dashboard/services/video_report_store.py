#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Video Analytics Report & Frame Detection Persistence Service.

Uses ``TrackerDB`` (``video_runs`` SQLite table) as the primary Single Source
of Truth (SSOT) while transparently auto-migrating legacy ``data/reports/*.json``
artifacts on first access.
"""

import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

from dashboard.dependencies import VIDEOS_DIR, get_db
from dashboard.services.video_report_maintenance import (
    backfill_runs_resolution,
    clear_runs_across_aliases,
    extract_source_metadata as _extract_source_metadata,
    is_valid_resolution,
    load_runs_file as _load_runs_file,
    remove_run_across_aliases,
)
from dashboard.services.video_report_migration import migrate_legacy_json_for_aliases
from dashboard.services.video_transcoder import VideoTranscodeService
from intelligent_tracker.database import TrackerDB

logger = logging.getLogger(__name__)

REPORTS_DIR = os.path.join("data", "reports")
_DEFAULT_REPORTS_DIR_ABS = os.path.abspath(REPORTS_DIR)
_VIDEO_EXTENSIONS = (".mp4", ".mkv", ".avi", ".mov")
_store_lock = threading.RLock()


def _get_safe_filename(filename: str) -> str:
    """Extract canonical basename to prevent directory traversal."""
    return os.path.basename(str(filename).strip())


def _detections_file_path(safe_name: str, run_id: str) -> str:
    """Get legacy path to frame detections stream file for a specific run."""
    return os.path.join(REPORTS_DIR, f"{safe_name}_{run_id}_detections.json")


def _resolve_db(db: Optional[TrackerDB] = None) -> tuple[TrackerDB, bool]:
    """Resolve active TrackerDB, isolating monkeypatched test REPORTS_DIR."""
    if db is not None:
        return db, False
    if os.path.abspath(REPORTS_DIR) != _DEFAULT_REPORTS_DIR_ABS:
        scoped_dir = os.path.dirname(os.path.abspath(REPORTS_DIR))
        os.makedirs(scoped_dir, exist_ok=True)
        return TrackerDB(os.path.join(scoped_dir, "tracker.db")), True
    return get_db(), False


def _close_if_owned(db: TrackerDB, owns_db: bool) -> None:
    """Close scoped SQLite handle when opened by this service."""
    if owns_db:
        db.close()


def resolve_base_recording_name(filename: str) -> str:
    """Resolve _h264 child filenames to their canonical base recording name."""
    safe_name = _get_safe_filename(filename)
    stem, ext = os.path.splitext(safe_name)
    if not stem.lower().endswith("_h264"):
        return safe_name

    base_stem = stem[:-5]
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


def is_same_recording_alias(name_a: str, name_b: str) -> bool:
    """Return True if two filenames refer to the same parent/_h264 video pair."""
    safe_a = _get_safe_filename(name_a)
    safe_b = _get_safe_filename(name_b)
    if not safe_a or not safe_b:
        return False
    return safe_b in _get_alias_filenames(safe_a) or safe_a in _get_alias_filenames(safe_b)


def _infer_source_resolution_for_filename(filename: Optional[str]) -> Optional[List[int]]:
    """Probe the underlying video file in VIDEOS_DIR to infer [width, height]."""
    if not filename:
        return None
    safe = _get_safe_filename(filename)
    video_path = os.path.join(VIDEOS_DIR, safe) if safe else ""
    if not safe or not os.path.isfile(video_path):
        return None
    try:
        probe = VideoTranscodeService.probe_video(video_path)
    except Exception as err:
        logger.debug("Resolution probe failed for %s: %s", safe, err)
        return None
    width, height = int(probe.get("width") or 0), int(probe.get("height") or 0)
    return [width, height] if width > 0 and height > 0 else None


def _migrate_legacy_json_for_aliases(safe_name: str, db: TrackerDB) -> None:
    """Import any legacy *_reports.json / *_detections.json files into TrackerDB."""
    migrate_legacy_json_for_aliases(
        safe_name=safe_name,
        aliases=_get_alias_filenames(safe_name),
        reports_dir=REPORTS_DIR,
        db=db,
        resolve_base_fn=resolve_base_recording_name,
        infer_res_fn=_infer_source_resolution_for_filename,
        lock=_store_lock,
    )


def _resolve_run_metadata(
    safe_name: str,
    report: Dict[str, Any],
    source_resolution: Optional[List[int]],
    source_fps: Optional[float],
) -> tuple[Optional[List[int]], Optional[float]]:
    """Resolve and validate source resolution and FPS for a new report run."""
    resolved_res, resolved_fps = _extract_source_metadata(report, source_resolution, source_fps)
    if not is_valid_resolution(resolved_res):
        resolved_res = _infer_source_resolution_for_filename(safe_name)
    return resolved_res, resolved_fps


def save_report_run(
    filename: str,
    report: Dict[str, Any],
    config: Dict[str, Any],
    frame_detections: Optional[List[Dict[str, Any]]] = None,
    source_resolution: Optional[List[int]] = None,
    source_fps: Optional[float] = None,
    db: Optional[TrackerDB] = None,
    run_type: str = "batch",
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist an occurrence indexing run and optional detection stream to TrackerDB."""
    safe_name = _get_safe_filename(filename)
    canonical_name = resolve_base_recording_name(safe_name)
    resolved_res, resolved_fps = _resolve_run_metadata(
        safe_name, report, source_resolution, source_fps
    )
    active_db, owns_db = _resolve_db(db)
    try:
        saved = active_db.save_video_run(
            video_filename=safe_name,
            report=report,
            config=config,
            frame_detections=frame_detections,
            source_resolution=resolved_res,
            source_fps=resolved_fps,
            run_type=run_type,
            base_filename=canonical_name,
            run_id=run_id,
        )
    finally:
        _close_if_owned(active_db, owns_db)
    saved.pop("frame_detections", None)
    saved.setdefault("detections_file", None)
    return saved


def list_report_runs(filename: str, db: Optional[TrackerDB] = None) -> List[Dict[str, Any]]:
    """List all archived report runs for a video or its _h264 pair, newest first."""
    safe_name = _get_safe_filename(filename)
    if not safe_name:
        return []
    active_db, owns_db = _resolve_db(db)
    try:
        _migrate_legacy_json_for_aliases(safe_name, active_db)
        runs = active_db.list_video_runs(safe_name)
        probe_cache: Dict[str, Optional[List[int]]] = {}
        if backfill_runs_resolution(
            runs, safe_name, probe_cache, _infer_source_resolution_for_filename, _extract_source_metadata
        ):
            for run in runs:
                if is_valid_resolution(run.get("source_resolution")):
                    active_db.update_video_run_resolution(
                        run["run_id"], run["source_resolution"], run.get("source_fps")
                    )
        return runs
    finally:
        _close_if_owned(active_db, owns_db)


def get_detection_stream(
    filename: str, run_id: Optional[str] = None, db: Optional[TrackerDB] = None
) -> Optional[Dict[str, Any]]:
    """Retrieve frame detection stream for scrubber video canvas overlay."""
    safe_name = _get_safe_filename(filename)
    if not safe_name:
        return None
    active_db, owns_db = _resolve_db(db)
    try:
        _migrate_legacy_json_for_aliases(safe_name, active_db)
        stream = active_db.get_video_detection_stream(safe_name, run_id)
        if stream is None:
            return None
        if not is_valid_resolution(stream.get("source_resolution")):
            inferred = _infer_source_resolution_for_filename(stream.get("filename") or safe_name)
            if is_valid_resolution(inferred):
                stream["source_resolution"] = inferred
                active_db.update_video_run_resolution(stream["run_id"], inferred)
        return stream
    finally:
        _close_if_owned(active_db, owns_db)


def export_report_run_bundle(
    filename: str, run_id: str, db: Optional[TrackerDB] = None
) -> Optional[Dict[str, Any]]:
    """Build a portable JSON export bundle containing run metadata and frame detections."""
    safe_name = _get_safe_filename(filename)
    safe_run_id = _get_safe_filename(run_id)
    if not safe_name or not safe_run_id:
        return None
    active_db, owns_db = _resolve_db(db)
    try:
        _migrate_legacy_json_for_aliases(safe_name, active_db)
        run = active_db.get_video_run(safe_run_id, video_filename=safe_name, include_detections=True)
        if run is None:
            return None
        return {
            "schema_version": 1,
            "exported_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "run_id": run["run_id"],
            "filename": run["filename"],
            "base_filename": run["base_filename"],
            "run_type": run["run_type"],
            "generated_at": run["generated_at"],
            "timestamp": run["timestamp"],
            "source_resolution": run["source_resolution"],
            "source_fps": run["source_fps"],
            "config": run["config"],
            "metrics": run["metrics"],
            "report": run["report"],
            "frame_detections": run.get("frame_detections") or [],
        }
    finally:
        _close_if_owned(active_db, owns_db)


def delete_report_run(
    filename: str, run_id: str, db: Optional[TrackerDB] = None
) -> bool:
    """Delete a single report run from TrackerDB and any legacy alias files."""
    safe_name = _get_safe_filename(filename)
    safe_run_id = _get_safe_filename(run_id)
    if not safe_name or not safe_run_id:
        return False
    active_db, owns_db = _resolve_db(db)
    try:
        db_deleted = active_db.delete_video_run(safe_name, safe_run_id)
    finally:
        _close_if_owned(active_db, owns_db)
    file_deleted = remove_run_across_aliases(
        _get_alias_filenames(safe_name), safe_run_id, REPORTS_DIR, _load_runs_file, _store_lock
    )
    return db_deleted or file_deleted


def clear_report_runs(filename: str, db: Optional[TrackerDB] = None) -> int:
    """Delete all archived report runs from TrackerDB and any legacy alias files."""
    safe_name = _get_safe_filename(filename)
    if not safe_name:
        return 0
    active_db, owns_db = _resolve_db(db)
    try:
        _migrate_legacy_json_for_aliases(safe_name, active_db)
        db_cleared = active_db.clear_video_runs(safe_name)
    finally:
        _close_if_owned(active_db, owns_db)
    file_cleared = clear_runs_across_aliases(
        _get_alias_filenames(safe_name), REPORTS_DIR, _load_runs_file, _store_lock
    )
    return max(db_cleared, file_cleared)
