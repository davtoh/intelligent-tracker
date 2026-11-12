#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Maintenance Helpers for Video Report Backfill and Alias-Complete Deletion.

All filesystem helpers accept explicit directory and callback parameters so
callers (and unit tests monkeypatching `video_report_store.REPORTS_DIR`) remain
the single source of truth for directory locations.
"""

import json
import logging
import os
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)


def is_valid_resolution(res: Any) -> bool:
    """Return True if `res` is a `[width, height]` sequence of positive numbers."""
    if not isinstance(res, (list, tuple)) or len(res) < 2:
        return False
    w, h = res[0], res[1]
    return (
        not isinstance(w, bool)
        and not isinstance(h, bool)
        and isinstance(w, (int, float))
        and isinstance(h, (int, float))
        and w > 0
        and h > 0
    )


def load_runs_file(path: str) -> list[dict[str, Any]]:
    """Load report runs array from JSON file safely."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception as e:
        logger.warning("Could not read reports file %s: %s", path, e)
    return []


def extract_source_metadata(
    report: dict[str, Any],
    source_resolution: list[int] | None,
    source_fps: float | None,
) -> tuple[list[int] | None, float | None]:
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


def write_json_atomic(path: str, payload: Any, indent: int | None = None) -> None:
    """Atomically write JSON payload via thread-unique temporary file replacement."""
    tmp_path = f"{path}.{threading.get_ident()}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=indent)
    os.replace(tmp_path, path)


def is_within_dir(target_path: str, base_dir: str) -> bool:
    """Return True if `target_path` resolves strictly inside `base_dir`."""
    try:
        abs_target = os.path.abspath(target_path)
        abs_base = os.path.abspath(base_dir)
        return os.path.commonpath([abs_target, abs_base]) == abs_base
    except (ValueError, OSError):
        return False


def remove_file_safe(path: str) -> bool:
    """Remove a file if it exists, returning True when deleted."""
    if not path or not os.path.isfile(path):
        return False
    try:
        os.remove(path)
        return True
    except OSError as err:
        logger.warning("Failed removing file %s: %s", path, err)
        return False


def backfill_runs_resolution(
    runs: list[dict[str, Any]],
    fallback_filename: str,
    probe_cache: dict[str, list[int] | None],
    infer_res_fn: Callable[[str], list[int] | None],
    extract_meta_fn: Callable[[dict[str, Any], Any, Any], tuple[list[int] | None, float | None]],
) -> bool:
    """Populate missing `source_resolution` on legacy runs; return True if mutated."""
    dirty = False
    for run in runs:
        if not isinstance(run, dict) or is_valid_resolution(run.get("source_resolution")):
            continue
        report_dict = run.get("report") if isinstance(run.get("report"), dict) else {}
        meta_res, meta_fps = extract_meta_fn(report_dict, None, run.get("source_fps"))
        if is_valid_resolution(meta_res):
            run["source_resolution"] = list(meta_res)  # type: ignore[arg-type]
            if run.get("source_fps") is None and meta_fps is not None:
                run["source_fps"] = meta_fps
            dirty = True
            continue
        target_fn = run.get("filename") or fallback_filename
        if target_fn not in probe_cache:
            probe_cache[target_fn] = infer_res_fn(target_fn)
        inferred = probe_cache[target_fn]
        if is_valid_resolution(inferred):
            run["source_resolution"] = list(inferred)  # type: ignore[arg-type]
            dirty = True
    return dirty


def _filter_run_from_reports_file(
    rep_path: str,
    safe_run_id: str,
    load_runs_fn: Callable[[str], list[dict[str, Any]]],
    recorded_det_paths: list[str],
) -> bool:
    """Remove `safe_run_id` from one reports JSON file, deleting the file if now empty."""
    if not os.path.isfile(rep_path):
        return False
    runs = load_runs_fn(rep_path)
    remaining: list[dict[str, Any]] = []
    matched = False
    for run in runs:
        if isinstance(run, dict) and run.get("run_id") == safe_run_id:
            matched = True
            det_file = run.get("detections_file")
            if isinstance(det_file, str) and det_file:
                recorded_det_paths.append(det_file)
        else:
            remaining.append(run)
    if not matched:
        return False
    if remaining:
        write_json_atomic(rep_path, remaining, indent=2)
    else:
        remove_file_safe(rep_path)
    return True


def remove_run_across_aliases(
    aliases: list[str],
    safe_run_id: str,
    reports_dir: str,
    load_runs_fn: Callable[[str], list[dict[str, Any]]],
    lock: threading.RLock,
) -> bool:
    """Delete a specific `run_id` across all alias `*_reports.json` and `*_detections.json` files."""
    if not safe_run_id or not os.path.isdir(reports_dir):
        return False
    deleted = False
    recorded_det_paths: list[str] = []

    with lock:
        for alias in aliases:
            rep_path = os.path.join(reports_dir, f"{alias}_reports.json")
            if _filter_run_from_reports_file(rep_path, safe_run_id, load_runs_fn, recorded_det_paths):
                deleted = True
            det_candidate = os.path.join(reports_dir, f"{alias}_{safe_run_id}_detections.json")
            if remove_file_safe(det_candidate):
                deleted = True

        for det_path in recorded_det_paths:
            if is_within_dir(det_path, reports_dir) and remove_file_safe(det_path):
                deleted = True

    return deleted


def _remove_alias_detection_files(aliases: list[str], reports_dir: str) -> int:
    """Remove all `{alias}_*_detections.json` files inside `reports_dir`."""
    try:
        entries = os.listdir(reports_dir)
    except OSError:
        return 0
    removed = 0
    for fname in entries:
        if fname.endswith("_detections.json") and any(fname.startswith(f"{a}_") for a in aliases):
            if remove_file_safe(os.path.join(reports_dir, fname)):
                removed += 1
    return removed


def clear_runs_across_aliases(
    aliases: list[str],
    reports_dir: str,
    load_runs_fn: Callable[[str], list[dict[str, Any]]],
    lock: threading.RLock,
) -> int:
    """Delete all report runs and detection files across all recording aliases."""
    if not aliases or not os.path.isdir(reports_dir):
        return 0
    removed_run_ids: set[str] = set()
    recorded_det_paths: list[str] = []
    removed_files = 0

    with lock:
        for alias in aliases:
            rep_path = os.path.join(reports_dir, f"{alias}_reports.json")
            if os.path.isfile(rep_path):
                for run in load_runs_fn(rep_path):
                    if isinstance(run, dict):
                        if run.get("run_id"):
                            removed_run_ids.add(str(run["run_id"]))
                        det_file = run.get("detections_file")
                        if isinstance(det_file, str) and det_file:
                            recorded_det_paths.append(det_file)
                if remove_file_safe(rep_path):
                    removed_files += 1

        removed_files += _remove_alias_detection_files(aliases, reports_dir)
        for det_path in recorded_det_paths:
            if is_within_dir(det_path, reports_dir) and remove_file_safe(det_path):
                removed_files += 1

    return len(removed_run_ids) if removed_run_ids else removed_files


def persist_healed_runs(
    path: str,
    healed_runs: list[dict[str, Any]],
    load_runs_fn: Callable[[str], list[dict[str, Any]]],
    lock: threading.RLock,
) -> None:
    """Persist backfilled resolution metadata to disk without clobbering concurrent writes."""
    healed_by_id = {
        r["run_id"]: (r.get("source_resolution"), r.get("source_fps"))
        for r in healed_runs
        if isinstance(r, dict) and r.get("run_id") and is_valid_resolution(r.get("source_resolution"))
    }
    if not healed_by_id:
        return
    with lock:
        if not os.path.isfile(path):
            return
        current = load_runs_fn(path)
        changed = False
        for item in current:
            rid = item.get("run_id") if isinstance(item, dict) else None
            if rid in healed_by_id and not is_valid_resolution(item.get("source_resolution")):
                res, fps = healed_by_id[rid]
                item["source_resolution"] = res
                if item.get("source_fps") is None and fps is not None:
                    item["source_fps"] = fps
                changed = True
        if changed:
            try:
                write_json_atomic(path, current, indent=2)
            except Exception as err:
                logger.warning("Could not persist backfilled runs to %s: %s", path, err)


def heal_detection_stream_metadata(
    stream: dict[str, Any],
    det_path: str,
    target_run: dict[str, Any],
    safe_name: str,
    infer_res_fn: Callable[[str], list[int] | None],
    lock: threading.RLock,
) -> dict[str, Any]:
    """Backfill missing source_resolution/source_fps on a loaded detection stream and persist."""
    dirty = False
    if not is_valid_resolution(stream.get("source_resolution")):
        stream_fn = stream.get("filename")
        inferred = (
            infer_res_fn(stream_fn)
            if stream_fn and stream_fn != target_run.get("filename")
            else None
        )
        resolved = (
            inferred
            or target_run.get("source_resolution")
            or infer_res_fn(stream_fn or target_run.get("filename") or safe_name)
        )
        if is_valid_resolution(resolved):
            stream["source_resolution"] = resolved
            dirty = True
    if stream.get("source_fps") is None and target_run.get("source_fps") is not None:
        stream["source_fps"] = target_run.get("source_fps")
        dirty = True
    if dirty:
        with lock:
            write_json_atomic(det_path, stream)
    return stream
