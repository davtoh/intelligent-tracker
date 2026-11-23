#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Legacy JSON Report & Detection Stream Auto-Migration Helper.

Transparently imports historical ``*_reports.json`` and ``*_detections.json``
files from ``REPORTS_DIR`` into ``TrackerDB`` on first access.
"""

import json
import logging
import os
import threading
from typing import Any, Callable

from dashboard.services.video_report_maintenance import (
    backfill_runs_resolution,
    extract_source_metadata,
    heal_detection_stream_metadata,
    is_valid_resolution,
    load_runs_file,
    persist_healed_runs,
)
from intelligent_tracker.database import TrackerDB

logger = logging.getLogger(__name__)
_MIGRATION_CACHE_LOCK = threading.Lock()
_MIGRATED_REPORT_FILES: set[tuple[str, str, int]] = set()


def clear_migration_cache() -> None:
    """Clear the mtime-aware legacy report migration cache."""
    with _MIGRATION_CACHE_LOCK:
        _MIGRATED_REPORT_FILES.clear()


def _db_cache_key(db: TrackerDB) -> str:
    """Build a stable cache key distinguishing distinct TrackerDB targets."""
    raw = str(getattr(db, "db_path", "") or "")
    if not raw or raw == ":memory:":
        return f"{raw}:{id(db)}"
    return os.path.abspath(raw)


def _stat_mtime_ns(path: str) -> int | None:
    """Return file mtime in nanoseconds, or None if unavailable."""
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


def find_legacy_detections_path(
    aliases: list[str], reports_dir: str, target_run: dict[str, Any]
) -> str | None:
    """Locate legacy detection stream file across aliases or recorded path."""
    rid = target_run.get("run_id")
    if rid:
        for alias in aliases:
            candidate = os.path.join(reports_dir, f"{alias}_{rid}_detections.json")
            if os.path.exists(candidate):
                return candidate
    recorded_path = target_run.get("detections_file")
    if recorded_path and os.path.isfile(recorded_path):
        return recorded_path
    return None


def _load_legacy_detections(
    aliases: list[str],
    reports_dir: str,
    run: dict[str, Any],
    safe_name: str,
    infer_res_fn: Callable[[str | None], list[int] | None],
    lock: threading.RLock,
) -> list[dict[str, Any]] | None:
    """Read and heal legacy detection JSON stream if present on disk."""
    det_path = find_legacy_detections_path(aliases, reports_dir, run)
    if det_path is None:
        return None
    try:
        with lock:
            with open(det_path, "r", encoding="utf-8") as f:
                stream = json.load(f)
        if isinstance(stream, dict):
            healed = heal_detection_stream_metadata(
                stream, det_path, run, safe_name, infer_res_fn, lock
            )
            dets = healed.get("frame_detections")
            return dets if isinstance(dets, list) else []
    except Exception as err:
        logger.warning("Failed migrating legacy detections %s: %s", det_path, err)
    return None


def _migrate_single_legacy_run(
    alias: str, aliases: list[str], reports_dir: str, run: dict[str, Any],
    safe_name: str, db: TrackerDB, resolve_base_fn: Callable[[str], str],
    infer_res_fn: Callable[[str | None], list[int] | None], lock: threading.RLock,
) -> None:
    """Upsert one legacy JSON run into TrackerDB when absent or incomplete."""
    rid = run.get("run_id") if isinstance(run, dict) else None
    if not rid:
        return
    existing = db.get_video_run(str(rid), include_detections=False)
    need_dets = existing is None or not existing.get("has_detections")
    frame_dets = _load_legacy_detections(aliases, reports_dir, run, safe_name, infer_res_fn, lock) if need_dets else None
    needs_res = existing is not None and not is_valid_resolution(existing.get("source_resolution")) and is_valid_resolution(run.get("source_resolution"))
    if existing is not None and frame_dets is None and not needs_res:
        return
    run_fn = os.path.basename(str(run.get("filename") or alias).strip()) or alias
    base_fn = os.path.basename(str(run.get("base_filename") or "").strip()) or resolve_base_fn(run_fn)
    db.save_video_run(
        video_filename=run_fn,
        report=run.get("report") if isinstance(run.get("report"), dict) else {},
        config=run.get("config") if isinstance(run.get("config"), dict) else {},
        frame_detections=frame_dets,
        source_resolution=run.get("source_resolution"),
        source_fps=run.get("source_fps"),
        run_type=str(run.get("run_type") or "batch"),
        base_filename=base_fn,
        run_id=str(rid),
        timestamp=run.get("timestamp"),
        generated_at=run.get("generated_at"),
        metrics=run.get("metrics") if isinstance(run.get("metrics"), dict) else None,
    )


def migrate_legacy_json_for_aliases(
    safe_name: str, aliases: list[str], reports_dir: str, db: TrackerDB,
    resolve_base_fn: Callable[[str], str], infer_res_fn: Callable[[str | None], list[int] | None],
    lock: threading.RLock,
) -> None:
    """Import any legacy *_reports.json / *_detections.json files into TrackerDB."""
    if not os.path.isdir(reports_dir):
        return
    db_key = _db_cache_key(db)
    probe_cache: dict[str, list[int] | None] = {}
    for alias in aliases:
        rep_path = os.path.join(reports_dir, f"{alias}_reports.json")
        abs_rep = os.path.abspath(rep_path)
        with lock:
            if not os.path.isfile(rep_path):
                continue
            mtime_ns = _stat_mtime_ns(rep_path)
            with _MIGRATION_CACHE_LOCK:
                if mtime_ns is not None and (db_key, abs_rep, mtime_ns) in _MIGRATED_REPORT_FILES:
                    continue
            runs = load_runs_file(rep_path)
        if backfill_runs_resolution(runs, alias, probe_cache, infer_res_fn, extract_source_metadata):
            persist_healed_runs(rep_path, runs, load_runs_file, lock)
        for run in runs:
            _migrate_single_legacy_run(
                alias, aliases, reports_dir, run, safe_name, db, resolve_base_fn, infer_res_fn, lock,
            )
        final_mtime = _stat_mtime_ns(rep_path) or mtime_ns
        if final_mtime is not None:
            with _MIGRATION_CACHE_LOCK:
                _MIGRATED_REPORT_FILES.add((db_key, abs_rep, final_mtime))
