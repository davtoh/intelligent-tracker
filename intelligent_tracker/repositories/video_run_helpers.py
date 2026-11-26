"""Pure helper functions for VideoRunRepositoryMixin."""

import json
import time
import uuid
from typing import Any

from intelligent_tracker.repositories.video_schema import (
    canonical_video_base_name,
    safe_video_basename,
)


def normalize_detector_sig(cfg: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize detector signature fields for replay compatibility checks."""
    data = cfg if isinstance(cfg, dict) else {}
    det = str(data.get("detector") or data.get("detector_model") or "").strip().lower()
    raw_classes = data.get("classes") if data.get("classes") is not None else data.get("detector_classes")
    if isinstance(raw_classes, str):
        classes = sorted(c.strip().lower() for c in raw_classes.split(",") if c.strip())
    elif isinstance(raw_classes, (list, tuple, set)):
        classes = sorted(str(c.strip()).lower() if isinstance(c, str) else str(c).strip().lower() for c in raw_classes if str(c).strip())
    else:
        classes = []
    raw_conf = data.get("confidence") if data.get("confidence") is not None else data.get("detector_confidence")
    conf = round(float(raw_conf), 3) if raw_conf is not None else None
    raw_nms = data.get("agnostic_nms") if data.get("agnostic_nms") is not None else data.get("detector_agnostic_nms")
    agnostic_nms = bool(True if raw_nms is None else raw_nms)
    return {"detector": det, "confidence": conf, "classes": classes, "agnostic_nms": agnostic_nms}


def detector_signature_matches(run_cfg: dict[str, Any] | None, expected_sig: dict[str, Any] | None) -> bool:
    """Return True when a cached video_run config matches the active detector signature."""
    if not expected_sig:
        return True
    exp, got = normalize_detector_sig(expected_sig), normalize_detector_sig(run_cfg)
    if exp["detector"] and got["detector"] and exp["detector"] != got["detector"]:
        return False
    if exp["confidence"] is not None and got["confidence"] is not None and exp["confidence"] != got["confidence"]:
        return False
    if exp["classes"] != got["classes"]:
        return False
    return exp["agnostic_nms"] == got["agnostic_nms"]


def build_save_params(
    video_filename: str, report: dict[str, Any], config: dict[str, Any] | None,
    frame_detections: list[dict[str, Any]] | None, source_resolution: list[int] | None,
    source_fps: float | None, run_type: str, base_filename: str | None,
    run_id: str | None, timestamp: float | None, generated_at: str | None,
    metrics: dict[str, Any] | None,
) -> tuple[str, tuple[Any, ...]]:
    """Validate and serialize arguments for ``UPSERT_VIDEO_RUN_SQL``."""
    safe_name = safe_video_basename(video_filename)
    if not safe_name:
        raise ValueError("video_filename must not be empty")
    canonical = safe_video_basename(base_filename) if base_filename else canonical_video_base_name(safe_name)
    rid = str(run_id).strip() if run_id else f"run_{uuid.uuid4().hex[:8]}"
    ts = float(timestamp) if timestamp is not None else time.time()
    gen_at = generated_at or time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    resolved_metrics = metrics if metrics is not None else {
        k: report.get(k, 0) for k in (
            "frames_processed", "total_detections", "total_sightings", "unique_entities_identified"
        )
    }
    res_json = json.dumps(source_resolution) if source_resolution is not None else None
    det_json = json.dumps(frame_detections) if frame_detections is not None else None
    return rid, (
        rid, safe_name, canonical, run_type or "batch", gen_at, ts, res_json, source_fps,
        json.dumps(config or {}), json.dumps(resolved_metrics), json.dumps(report or {}), det_json,
    )
