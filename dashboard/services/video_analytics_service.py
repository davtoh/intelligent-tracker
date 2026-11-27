#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Batch Video Analytics Execution & Report Finalization Service."""

import copy
import logging
import uuid
from typing import Any

from dashboard.dependencies import get_db, get_scenario_mgr
from dashboard.schemas import VideoAnalyzeRequest
from dashboard.services.progressive_stream_store import append_progressive_chunk, finalize_progressive_stream
from dashboard.services.video_jobs_service import VideoJob, VideoJobManager
from dashboard.services.video_report_store import save_report_run
from intelligent_tracker.active_learning import ActiveLearningManager
from intelligent_tracker.analytics.engine import AnalyticsEngine
from intelligent_tracker.batch import VideoIndexer
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.events.bus import EventBus
from intelligent_tracker.events.types import (
    IntrusionAlert, OccupancyThresholdEvent, RestrictedEntityAlert,
    RSACViolationEvent, TripwireCrossEvent, ZoneEvent,
)
from intelligent_tracker.memory.fts_index import EventFTSIndex
from intelligent_tracker.rsac import RSACManager

logger = logging.getLogger("intelligent_tracker.dashboard.services.video_analytics_service")
_ALERT_EVENT_TYPES = (
    RSACViolationEvent, IntrusionAlert, RestrictedEntityAlert,
    ZoneEvent, TripwireCrossEvent, OccupancyThresholdEvent,
)


def parse_analyze_options(
    sample_rate: int,
    detector: str | None,
    confidence: float | None,
    classes: str | None,
    async_mode: bool | None,
    req: VideoAnalyzeRequest | None,
    scenario_camera_id: str | None = None,
    tracked_categories: str | None = None,
    tracker: str | None = None,
) -> dict[str, Any]:
    """Normalize query and JSON body options for batch video analytics."""
    sr = req.sample_rate if (req and req.sample_rate is not None) else sample_rate
    det = req.detector if (req and req.detector is not None) else (detector or "yolov8")
    conf = req.confidence if (req and req.confidence is not None) else (confidence if confidence is not None else 0.40)

    def _norm_list(raw: Any) -> list[str] | None:
        if isinstance(raw, str):
            return [c.strip() for c in raw.split(",") if c.strip()] or None
        if isinstance(raw, (list, tuple, set)):
            return [str(c).strip() for c in raw if str(c).strip()] or None
        return None

    target_classes = _norm_list((req.classes if req and req.classes is not None else None) or classes)
    target_cats = _norm_list((req.tracked_categories if req and req.tracked_categories is not None else None) or tracked_categories)
    is_async = req.async_mode if (req and req.async_mode is not None) else None
    is_async = bool(async_mode) if is_async is None else is_async
    raw_scen = req.scenario_camera_id if (req and req.scenario_camera_id is not None) else scenario_camera_id
    scen_cam = str(raw_scen).strip() if raw_scen and str(raw_scen).strip() else None
    trk = (getattr(req, "tracker", None) if req else None) or tracker
    return {
        "sample_rate": sr,
        "detector": det,
        "confidence": conf,
        "classes": target_classes,
        "tracked_categories": target_cats,
        "tracker": str(trk).strip().lower() if trk and str(trk).strip() else None,
        "is_async": is_async,
        "scenario_camera_id": scen_cam,
    }


def _resolve_db() -> TrackerDB:
    return get_db()


def _serialize_offline_alert(event: Any, safe_name: str, offset_sec: float) -> dict[str, Any]:
    return {
        "event_type": getattr(event, "event_type", "alert"),
        "camera_id": getattr(event, "camera_id", ""),
        "zone_id": getattr(event, "zone_id", "") or "",
        "tripwire_id": getattr(event, "tripwire_id", "") or "",
        "entity_id": getattr(event, "entity_id", None),
        "entity_name": getattr(event, "entity_name", None) or getattr(event, "name", "") or "",
        "track_id": getattr(event, "track_id", None),
        "severity": getattr(event, "severity", "info"),
        "message": getattr(event, "reason", None) or getattr(event, "message", "") or "",
        "video_filename": safe_name,
        "media_offset_sec": offset_sec,
        "timestamp": offset_sec,
    }


def _apply_scenario_to_analytics(analytics: AnalyticsEngine, scenario_camera_id: str | None) -> None:
    """Copy configured zones and tripwires from ScenarioManager onto offline AnalyticsEngine."""
    if not scenario_camera_id:
        return
    entry = (get_scenario_mgr().cameras or {}).get(scenario_camera_id) or {}
    for z in (entry.get("zones") or {}).values():
        analytics.add_zone(copy.deepcopy(z))
    for tw in (entry.get("tripwires") or {}).values():
        analytics.add_tripwire(copy.deepcopy(tw))


def _build_offline_analytics_and_bus(
    db: TrackerDB, scenario_camera_id: str | None, safe_name: str
) -> tuple[AnalyticsEngine, RSACManager, EventBus, list[dict[str, Any]], EventFTSIndex, dict[str, Any]]:
    rsac_mgr = RSACManager(db=db)
    event_bus = EventBus(capacity=500)
    event_bus.start()
    collected_alerts: list[dict[str, Any]] = []
    media_state: dict[str, Any] = {"offset_sec": 0.0, "start_wall_time": None, "run_id": ""}

    def _tag_and_collect(event: Any) -> None:
        raw_offset = getattr(event, "media_offset_sec", None)
        ev_ts = float(getattr(event, "timestamp", 0.0) or 0.0)
        base = media_state.get("start_wall_time")
        offset_sec = float(raw_offset) if raw_offset is not None else (
            round(ev_ts - float(base), 6) if base is not None and ev_ts >= float(base) else float(media_state["offset_sec"])
        )
        active_run_id = str(media_state.get("run_id") or "").strip()
        setattr(event, "video_filename", safe_name)
        setattr(event, "media_offset_sec", offset_sec)
        if active_run_id:
            setattr(event, "run_id", active_run_id)
        meta = getattr(event, "metadata", None)
        if isinstance(meta, dict):
            meta["video_filename"], meta["media_offset_sec"] = safe_name, offset_sec
            if active_run_id:
                meta["run_id"] = active_run_id
        if isinstance(event, _ALERT_EVENT_TYPES):
            collected_alerts.append(_serialize_offline_alert(event, safe_name, offset_sec))

    event_bus.subscribe(_tag_and_collect)
    fts_index = EventFTSIndex(db=db, event_bus=event_bus, auto_attach=True)
    analytics = AnalyticsEngine(
        camera_id=scenario_camera_id or "offline_video", event_bus=event_bus, rsac_manager=rsac_mgr,
    )
    _apply_scenario_to_analytics(analytics, scenario_camera_id)
    return analytics, rsac_mgr, event_bus, collected_alerts, fts_index, media_state


def _attach_run_id(indexer: VideoIndexer, run_id: str) -> None:
    """Attach pre-generated run_id onto indexer, matcher, active_learning, and media state."""
    rid = str(run_id or "").strip()
    if not rid:
        return
    setattr(indexer, "run_id", rid)
    matcher = getattr(indexer, "matcher", None)
    if matcher is not None:
        setattr(matcher, "run_id", rid)
    al_mgr = getattr(indexer, "active_learning", None)
    if al_mgr is not None:
        setattr(al_mgr, "run_id", rid)
        triage = getattr(al_mgr, "_triage", None)
        if triage is not None:
            setattr(triage, "run_id", rid)
    state = getattr(indexer, "_media_offset_state", None)
    if isinstance(state, dict):
        state["run_id"] = rid


def _teardown_indexer_bus(indexer: VideoIndexer | None) -> None:
    if indexer is None:
        return
    bus = getattr(indexer, "event_bus", None)
    if bus is not None:
        bus.wait_until_empty(timeout=2.0)
    fts = getattr(indexer, "_fts_index", None)
    if fts is not None:
        fts.stop()
    if bus is not None:
        bus.stop(timeout=2.0)


def _resolve_shared_singletons(
    opts: dict[str, Any], confidence_engine: Any, world_graph: Any
) -> tuple[Any, Any]:
    """Resolve pool/app-shared ConfidenceEngine and WorldGraph for offline VideoIndexer."""
    ce = confidence_engine or opts.get("confidence_engine")
    wg = world_graph or opts.get("world_graph")
    if ce is None or wg is None:
        try:
            import dashboard.dependencies as deps

            pool = deps.get_camera_pool()
            if ce is None:
                ce = getattr(pool, "confidence_engine", None) if pool else None
                ce = ce or getattr(deps, "_confidence_engine", None)
            if wg is None:
                wg = getattr(pool, "world_graph", None) if pool else None
                wg = wg or getattr(deps, "_world_graph", None)
        except Exception:
            pass
    return ce, wg


def create_video_indexer(
    db: TrackerDB,
    opts: dict[str, Any],
    safe_name: str = "",
    *,
    confidence_engine: Any = None,
    world_graph: Any = None,
    run_id: str = "",
) -> VideoIndexer:
    """Instantiate VideoIndexer with spatial scenario, RSAC, ActiveLearning, and EventBus wiring."""
    analytics, rsac_mgr, event_bus, collected_alerts, fts_index, media_state = _build_offline_analytics_and_bus(
        db, opts.get("scenario_camera_id"), safe_name
    )
    resolved_ce, resolved_wg = _resolve_shared_singletons(opts, confidence_engine, world_graph)
    al_mgr = ActiveLearningManager(db=db, event_bus=event_bus)
    det = opts["detector"]
    kwargs: dict[str, Any] = {
        "db": db, "reid_name": opts.get("reid_model") or "dual",
        "sample_rate": opts["sample_rate"], "conf_threshold": opts["confidence"],
        "classes": opts["classes"], "tracked_categories": opts.get("tracked_categories"),
        "analytics": analytics, "rsac_manager": rsac_mgr,
        "active_learning": al_mgr, "event_bus": event_bus, "video_filename": safe_name,
        "fts_index": fts_index, "confidence_engine": resolved_ce, "world_graph": resolved_wg,
    }
    if opts.get("tracker"):
        kwargs["tracker_type"] = opts["tracker"]
    try:
        indexer = VideoIndexer(detector_name=det, **kwargs)
    except Exception as err:
        logger.warning("VideoIndexer initialization with detector '%s' failed (%s), falling back to mock", det, err)
        indexer = VideoIndexer(detector_name="mock", **kwargs)
    if getattr(indexer, "matcher", None) is not None:
        indexer.matcher.fts_index = fts_index
    setattr(indexer, "_collected_alerts", collected_alerts)
    setattr(indexer, "_fts_index", fts_index)
    setattr(indexer, "_media_offset_state", media_state)
    _attach_run_id(indexer, run_id)
    return indexer


def _extract_spatial_report_fields(indexer: VideoIndexer, config_meta: dict[str, Any]) -> dict[str, Any]:
    analytics = getattr(indexer, "analytics", None)
    summary_data = analytics.export_summary() if analytics is not None else {}
    zones_list = [
        {
            "name": name,
            "polygon": z.polygon.tolist() if hasattr(z.polygon, "tolist") else list(z.polygon),
            "category_filter": getattr(z, "category_filter", ""),
            "dwell_threshold": z.dwell_threshold,
            "capacity_limit": z.capacity_limit,
        }
        for name, z in (analytics.zones.items() if analytics is not None else [])
    ]
    tripwires_list = [
        {"name": name, "line_segment": [list(tw.pt1), list(tw.pt2)], "bidirectional": tw.bidirectional}
        for name, tw in (analytics.tripwires.items() if analytics is not None else [])
    ]
    return {
        "scenario_camera_id": config_meta.get("scenario_camera_id"),
        "zones": zones_list,
        "tripwires": tripwires_list,
        "zone_metrics": summary_data.get("zones", {}),
        "tripwire_counts": summary_data.get("tripwires", {}),
        "alerts": list(getattr(indexer, "_collected_alerts", [])),
    }


def finalize_analytics_report(
    indexer: VideoIndexer,
    summary: dict[str, Any],
    safe_name: str,
    config_meta: dict[str, Any],
    run_id: str | None = None,
) -> dict[str, Any]:
    """Assemble occurrence report metrics and persist stacked report + detection stream."""
    _teardown_indexer_bus(indexer)
    report = indexer.generate_occurrence_report(video_filename=safe_name)
    report["frames_processed"] = summary.get("processed_frames", 0)
    report["total_detections"] = summary.get("total_detections", 0)
    report["total_sightings"] = summary.get("identifications_count", 0)
    report["unique_entities_identified"] = len(summary.get("unique_entities_identified", []))
    report["source_resolution"] = summary.get("source_resolution")
    report["source_fps"] = summary.get("source_fps")
    report["execution_summary"] = summary
    report.update(_extract_spatial_report_fields(indexer, config_meta))

    resolved_run_id = str(run_id or getattr(indexer, "run_id", "") or "").strip() or None
    run_rec = save_report_run(
        filename=safe_name,
        report=report,
        config=config_meta,
        frame_detections=summary.get("frame_detections"),
        source_resolution=summary.get("source_resolution"),
        source_fps=summary.get("source_fps"),
        run_id=resolved_run_id,
    )
    report["run_id"] = run_rec.get("run_id")
    return report


def submit_async_analytics_job(
    job_mgr: VideoJobManager,
    safe_name: str,
    path: str,
    opts: dict[str, Any],
) -> VideoJob:
    """Submit a background VideoIndexer job with progressive detection streaming."""
    db = _resolve_db()
    config_meta = {
        "detector": opts["detector"], "sample_rate": opts["sample_rate"],
        "confidence": opts["confidence"], "classes": opts["classes"],
        "tracked_categories": opts.get("tracked_categories"), "scenario_camera_id": opts.get("scenario_camera_id"),
    }

    def _runner(job, stop_event, progress_cb):
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        indexer = create_video_indexer(db, opts, safe_name=safe_name, run_id=run_id)
        try:
            summary = indexer.process_video(
                video_path=path, verbose=False, progress_callback=progress_cb, stop_event=stop_event,
                frame_flush_callback=lambda chunk, meta: append_progressive_chunk(job.job_id, safe_name, chunk, meta),
            )
            return finalize_analytics_report(indexer, summary, safe_name, config_meta, run_id=run_id)
        finally:
            _teardown_indexer_bus(indexer)
            finalize_progressive_stream(job.job_id)

    return job_mgr.submit_job(
        job_type="analytics", filename=safe_name, runner_fn=_runner, initial_metrics=config_meta,
    )


def run_sync_analytics(safe_name: str, path: str, opts: dict[str, Any]) -> dict[str, Any]:
    """Execute synchronous VideoIndexer analytics and return persisted report."""
    db = _resolve_db()
    config_meta = {
        "detector": opts["detector"], "sample_rate": opts["sample_rate"],
        "confidence": opts["confidence"], "classes": opts["classes"],
        "tracked_categories": opts.get("tracked_categories"), "scenario_camera_id": opts.get("scenario_camera_id"),
    }
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    indexer = create_video_indexer(db, opts, safe_name=safe_name, run_id=run_id)
    try:
        summary = indexer.process_video(video_path=path, verbose=False)
        return finalize_analytics_report(indexer, summary, safe_name, config_meta, run_id=run_id)
    finally:
        _teardown_indexer_bus(indexer)

