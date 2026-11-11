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

logger = logging.getLogger(__name__)

REPORTS_DIR = os.path.join("data", "reports")


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


def save_report_run(
    filename: str,
    report: Dict[str, Any],
    config: Dict[str, Any],
    frame_detections: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Archive an occurrence indexing run and optional frame detection stream.

    :param filename: Target video file name.
    :param report: Full occurrence report dictionary.
    :param config: Execution configuration (model, stride, confidence, classes).
    :param frame_detections: Time-indexed detection bounding boxes for overlay.
    :return: Archived run record dictionary.
    """
    safe_name = _get_safe_filename(filename)
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    now = time.time()
    generated_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))

    detections_rel_path = None
    if frame_detections is not None:
        det_path = _detections_file_path(safe_name, run_id)
        det_payload = {
            "run_id": run_id,
            "filename": safe_name,
            "generated_at": generated_at,
            "frame_count": len(frame_detections),
            "frame_detections": frame_detections,
        }
        try:
            tmp_path = f"{det_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(det_payload, f)
            os.replace(tmp_path, det_path)
            detections_rel_path = det_path.replace("\\", "/")
        except Exception as e:
            logger.error("Failed saving detections file for %s (%s): %s", safe_name, run_id, e)

    run_record: Dict[str, Any] = {
        "run_id": run_id,
        "filename": safe_name,
        "timestamp": now,
        "generated_at": generated_at,
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

    # Load existing runs and prepend new run (newest first)
    existing_runs = list_report_runs(safe_name)
    updated_runs = [run_record] + existing_runs

    rep_path = _reports_file_path(safe_name)
    try:
        tmp_rep_path = f"{rep_path}.tmp"
        with open(tmp_rep_path, "w", encoding="utf-8") as f:
            json.dump(updated_runs, f, indent=2)
        os.replace(tmp_rep_path, rep_path)
    except Exception as e:
        logger.error("Failed writing stacked reports file for %s: %s", safe_name, e)

    return run_record


def list_report_runs(filename: str) -> List[Dict[str, Any]]:
    """List all archived report runs for a video file, newest first."""
    safe_name = _get_safe_filename(filename)
    path = _reports_file_path(safe_name)

    if not os.path.exists(path):
        # Check base file variant if searching for _h264 variant or vice versa
        base_name = safe_name.replace("_h264.", ".")
        alt_path = _reports_file_path(base_name)
        if base_name != safe_name and os.path.exists(alt_path):
            path = alt_path
        else:
            return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception as e:
        logger.warning("Could not read reports file for %s: %s", safe_name, e)
    return []


def get_detection_stream(filename: str, run_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve frame detection stream for scrubber video canvas overlay."""
    safe_name = _get_safe_filename(filename)
    runs = list_report_runs(safe_name)
    if not runs:
        return None

    target_run = None
    if run_id:
        for r in runs:
            if r.get("run_id") == run_id:
                target_run = r
                break
    else:
        target_run = runs[0]

    if not target_run:
        return None

    rid = target_run.get("run_id")
    det_path = _detections_file_path(safe_name, rid)

    if not os.path.exists(det_path):
        # Fallback to alternate variant if needed
        base_name = safe_name.replace("_h264.", ".")
        alt_det_path = _detections_file_path(base_name, rid)
        if os.path.exists(alt_det_path):
            det_path = alt_det_path
        else:
            return None

    try:
        with open(det_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("Error reading detections stream for %s (%s): %s", safe_name, rid, e)
        return None
