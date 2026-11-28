"""Zero-GPU Video Scenario Re-Evaluation Service.

Re-evaluates pre-indexed ``video_runs.frame_detections_json`` against current
``ScenarioManager`` zones/tripwires and ``RSACManager`` rules without invoking
YOLO or Re-ID models.
"""

import copy
import os
from typing import Any, cast

from dashboard.services.file_detection_replay import _hydrate_replay_track
from dashboard.services.video_analytics_service import (
    _ALERT_EVENT_TYPES,
    _serialize_offline_alert,
)
from dashboard.services.video_run_relabel_service import invalidate_pool_replay_caches
from intelligent_tracker.analytics import AnalyticsEngine
from intelligent_tracker.events import EventBus
from intelligent_tracker.pipeline import PipelineBundle, PipelineConfig
from intelligent_tracker.pipeline.post_detection_governance import evaluate_tracks_governance
from intelligent_tracker.rsac import RSACManager


def _resolve_target_run(db: Any, safe_name: str, run_id: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fetch target video_runs metadata and its frame_detections stream."""
    if db is None or getattr(db, "_conn", None) is None:
        raise RuntimeError("Database connection is unavailable")
    run_row = db.get_video_run(run_id) if run_id else None
    if run_row is None and not run_id:
        runs = db.list_video_runs(video_filename=safe_name)
        run_row = runs[0] if runs else None
    if run_row is None:
        raise LookupError(f"No indexed video run found for '{safe_name}'")
    resolved_run_id = str(run_row["run_id"])
    det_stream = db.get_video_detection_stream(safe_name, run_id=resolved_run_id)
    if det_stream is None or not isinstance(det_stream.get("frame_detections"), list):
        raise LookupError(f"No frame detections stored for run '{resolved_run_id}'")
    return run_row, det_stream


def _build_isolated_governance_bundle(
    db: Any,
    scenario_mgr: Any,
    camera_id: str,
    safe_name: str,
) -> tuple[PipelineBundle, AnalyticsEngine, EventBus, list[dict[str, Any]], dict[str, Any]]:
    """Build an isolated in-memory AnalyticsEngine + EventBus + PipelineBundle."""
    rsac_mgr = RSACManager(db=db)
    event_bus = EventBus(capacity=500)
    event_bus.start()
    collected_alerts: list[dict[str, Any]] = []
    media_state: dict[str, Any] = {"offset_sec": 0.0}

    def _collect(event: Any) -> None:
        if isinstance(event, _ALERT_EVENT_TYPES):
            offset = float(getattr(event, "media_offset_sec", None) or media_state["offset_sec"])
            collected_alerts.append(_serialize_offline_alert(event, safe_name, offset))

    event_bus.subscribe(_collect)
    analytics = AnalyticsEngine(camera_id=camera_id, event_bus=event_bus, rsac_manager=rsac_mgr)
    entry = (getattr(scenario_mgr, "cameras", None) or {}).get(camera_id) or {}
    for z in (entry.get("zones") or {}).values():
        analytics.add_zone(copy.deepcopy(z))
    for tw in (entry.get("tripwires") or {}).values():
        analytics.add_tripwire(copy.deepcopy(tw))
    bundle = PipelineBundle(
        config=PipelineConfig(),
        analytics=analytics,
        rsac_manager=rsac_mgr,
        event_bus=event_bus,
        _owns_event_bus=False,
        _owns_fts_index=False,
    )
    return bundle, analytics, event_bus, collected_alerts, media_state


def _replay_frame_detections(
    bundle: PipelineBundle,
    event_bus: EventBus,
    frame_detections: list[Any],
    media_state: dict[str, Any],
) -> None:
    """Hydrate and evaluate each stored frame detection record without GPU inference."""
    try:
        records = sorted(
            [r for r in frame_detections if isinstance(r, dict)],
            key=lambda r: (float(r.get("timestamp") or r.get("media_offset_sec") or 0.0), int(r.get("frame_idx", 0))),
        )
        for rec in records:
            tracks = {}
            for idx, raw_trk in enumerate(rec.get("tracks") or []):
                if isinstance(raw_trk, dict):
                    hydrated = _hydrate_replay_track(raw_trk, idx)
                    if hydrated is not None:
                        tracks[hydrated[0]] = hydrated[1]
            ts = float(rec.get("timestamp") or rec.get("media_offset_sec") or 0.0)
            media_offset = rec.get("media_offset_sec")
            media_state["offset_sec"] = float(media_offset) if media_offset is not None else ts
            evaluate_tracks_governance(bundle, cast(Any, None), tracks, ts, run_reid=False)
        event_bus.wait_until_empty(timeout=2.0)
    finally:
        event_bus.stop(timeout=2.0)


def _serialize_spatial_snapshot(analytics: AnalyticsEngine, camera_id: str, alerts: list[dict[str, Any]]) -> dict[str, Any]:
    """Serialize re-evaluated zones, tripwires, metrics, and alerts for report_json."""
    summary_data = analytics.export_summary()
    zones_list = [
        {
            "name": name,
            "polygon": z.polygon.tolist() if hasattr(z.polygon, "tolist") else list(z.polygon),
            "category_filter": getattr(z, "category_filter", ""),
            "dwell_threshold": z.dwell_threshold,
            "capacity_limit": z.capacity_limit,
        }
        for name, z in analytics.zones.items()
    ]
    tripwires_list = [
        {"name": name, "line_segment": [list(tw.pt1), list(tw.pt2)], "bidirectional": tw.bidirectional}
        for name, tw in analytics.tripwires.items()
    ]
    return {
        "scenario_camera_id": camera_id,
        "zones": zones_list,
        "tripwires": tripwires_list,
        "zone_metrics": summary_data.get("zones", {}),
        "tripwire_counts": summary_data.get("tripwires", {}),
        "alerts": alerts,
    }


def _collect_reeval_track_stats(frame_detections: list[Any]) -> dict[int, dict[str, Any]]:
    """Aggregate per-track dwell, similarity, entity, and bbox metadata from cached detections."""
    stats: dict[int, dict[str, Any]] = {}
    for rec in [r for r in frame_detections if isinstance(r, dict)]:
        ts = float(rec.get("timestamp") or rec.get("media_offset_sec") or 0.0)
        raw_off = rec.get("media_offset_sec")
        offset = float(raw_off) if raw_off is not None else ts
        for trk in rec.get("tracks") or []:
            if not isinstance(trk, dict):
                continue
            tid = int(trk.get("track_id") or trk.get("id") or 0)
            st = stats.setdefault(
                tid,
                {"first": ts, "last": ts, "dwell": 0.0, "sim": 0.0, "eid": None, "name": "", "cat": "", "bbox": None, "offset": offset},
            )
            st["first"], st["last"] = min(st["first"], ts), max(st["last"], ts)
            st["dwell"] = max(st["dwell"], float(trk.get("dwell_time") or 0.0), st["last"] - st["first"])
            sim = float(trk.get("similarity") or trk.get("reid_confidence") or trk.get("confidence") or 0.0)
            if trk.get("entity_id") is not None:
                st["eid"] = int(trk["entity_id"])
                st["name"] = str(trk.get("entity_name") or st["name"])
            if sim >= st["sim"]:
                st["sim"], st["bbox"], st["offset"] = sim, trk.get("bbox") or st["bbox"], offset
            st["cat"] = str(trk.get("category") or trk.get("label") or st["cat"] or "person")
    return stats


def _queue_reeval_review_candidates(
    db: Any,
    frame_detections: list[Any],
    *,
    camera_id: str,
    video_filename: str,
    run_id: str,
    unknown_min_dwell_sec: float = 3.0,
    min_confidence: float = 0.45,
    max_confidence: float = 0.70,
) -> int:
    """Queue recurring unknown and borderline tracks from cached detections (0-GPU)."""
    if not hasattr(db, "add_review_item"):
        return 0
    existing = {
        int(item.get("track_id") or 0)
        for item in (db.list_review_items(status="pending", limit=500) if hasattr(db, "list_review_items") else [])
        if (run_id and str(item.get("run_id") or "") == run_id) or str(item.get("video_filename") or "") == video_filename
    }
    queued = 0
    for tid, st in _collect_reeval_track_stats(frame_detections).items():
        if tid in existing:
            continue
        is_borderline = st["eid"] is not None and min_confidence <= st["sim"] < max_confidence
        is_unknown = st["eid"] is None and st["dwell"] >= unknown_min_dwell_sec
        if not (is_borderline or is_unknown):
            continue
        reason = "borderline" if is_borderline else "recurring_unknown"
        db.add_review_item(
            camera_id=camera_id, track_id=tid, crop_path="",
            suggested_entity_id=st["eid"] if is_borderline else None,
            suggested_name=st["name"] if is_borderline else "",
            suggested_category=st["cat"], similarity=st["sim"] if is_borderline else 0.0,
            status="pending", video_filename=video_filename, media_offset_sec=st["offset"],
            bbox=st["bbox"], run_id=run_id, reason=reason,
        )
        queued += 1
    return queued


def reevaluate_video_run_scenarios(
    db: Any, video_filename: str, *, run_id: str | None = None,
    scenario_camera_id: str | None = None, scenario_mgr: Any = None,
    pool: Any = None, queue_review_candidates: bool = True, unknown_min_dwell_sec: float = 3.0,
) -> dict[str, Any]:
    """Re-evaluate cached video detections against current ScenarioManager & RSAC rules (0-GPU)."""
    safe_name = os.path.basename(str(video_filename or "").strip())
    run_row, det_stream = _resolve_target_run(db, safe_name, run_id)
    resolved_run_id = str(run_row["run_id"])
    existing_report, existing_cfg = dict(run_row.get("report") or {}), dict(run_row.get("config") or {})
    effective_cam = (
        str(scenario_camera_id).strip()
        if scenario_camera_id and str(scenario_camera_id).strip()
        else str(existing_report.get("scenario_camera_id") or existing_cfg.get("scenario_camera_id") or "cam_01")
    )
    bundle, analytics, event_bus, collected_alerts, media_state = _build_isolated_governance_bundle(
        db, scenario_mgr, effective_cam, safe_name
    )
    _replay_frame_detections(bundle, event_bus, det_stream["frame_detections"], media_state)
    queued_reviews = _queue_reeval_review_candidates(
        db, det_stream["frame_detections"], camera_id=effective_cam,
        video_filename=safe_name, run_id=resolved_run_id, unknown_min_dwell_sec=unknown_min_dwell_sec,
    ) if queue_review_candidates else 0
    updated_report = {**existing_report, **_serialize_spatial_snapshot(analytics, effective_cam, collected_alerts)}
    db.update_video_run_payload(resolved_run_id, report=updated_report)
    invalidate_pool_replay_caches(pool)
    return {
        "status": "success", "run_id": resolved_run_id, "video_filename": safe_name,
        "scenario_camera_id": effective_cam, "queued_review_count": queued_reviews, "report": updated_report,
    }
