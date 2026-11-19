"""Stream telemetry serialization helpers for StreamWorker and StreamManager."""

from dataclasses import asdict
from typing import Any


def _extract_recent_alerts(event_bus: Any) -> list[dict[str, Any]]:
    """Extract serialized dictionary list from event bus."""
    alerts: list[dict[str, Any]] = []
    if event_bus:
        for ev in event_bus.get_recent_events(limit=8):
            if hasattr(ev, "to_dict"):
                alerts.append(ev.to_dict())
            elif hasattr(ev, "__dataclass_fields__"):
                alerts.append(asdict(ev))
            else:
                alerts.append({"event_type": getattr(ev, "event_type", "event")})
    return alerts


def _extract_track_telemetry(tracks: dict[int, Any], homography: Any) -> list[dict[str, Any]]:
    """Map active vision tracks into telemetry dictionaries with homography coordinates."""
    telemetry_tracks: list[dict[str, Any]] = []
    for tid, trk in tracks.items():
        gx, gy = homography.track_to_ground(trk.bbox)
        telemetry_tracks.append({
            "id": tid,
            "bbox": [int(x) for x in trk.bbox],
            "centroid": [float(trk.centroid[0]), float(trk.centroid[1])],
            "ground_pos": [round(gx, 2), round(gy, 2)],
            "velocity": [round(float(trk.velocity[0]), 2), round(float(trk.velocity[1]), 2)],
            "label": trk.label,
            "confidence": round(float(trk.confidence), 2),
            "dwell_time": round(float(trk.dwell_time), 1),
            "entity_name": getattr(trk, "entity_name", getattr(trk, "identity_label", None)),
            "category": getattr(trk, "category", "person"),
            "is_cluttered": bool(getattr(trk, "is_cluttered", False)),
            "clutter_partner_id": getattr(trk, "clutter_partner_id", None),
            "state": trk.state,
        })
    return telemetry_tracks


def _build_zones_data(analytics: Any) -> list[dict[str, Any]]:
    """Serialize zones from analytics engine."""
    if not analytics:
        return []
    return [
        {
            "name": z.name,
            "occupancy": z.occupancy,
            "capacity_limit": getattr(z, "capacity_limit", None),
            "dwell_threshold": z.dwell_threshold,
            "is_breached": getattr(z, "_threshold_breached", False),
            "polygon": z.polygon.tolist() if hasattr(z.polygon, "tolist") else list(z.polygon),
        }
        for z in list(analytics.zones.values())
    ]


def _build_tripwires_data(analytics: Any) -> list[dict[str, Any]]:
    """Serialize tripwires from analytics engine."""
    if not analytics:
        return []
    return [
        {
            "name": tw.name,
            "in_count": tw.in_count,
            "out_count": tw.out_count,
            "line": list(tw.line_segment),
        }
        for tw in list(analytics.tripwires.values())
    ]


def _resolve_detector_telemetry(manager: Any) -> tuple[str, str]:
    """Resolve ``(detector_model, detector_status)`` from bundle or fallback attrs."""
    bundle = getattr(manager, "_pipeline_bundle", None)
    if bundle is not None:
        cfg = getattr(bundle, "config", None)
        model = str(getattr(cfg, "detector_model", "") or "").strip().lower()
        status = str(getattr(bundle, "detector_status", "ready") or "ready")
        return model or "unknown", status

    cfg_dict = getattr(manager, "cfg", None) or {}
    det_cfg = cfg_dict.get("detector", {}) if isinstance(cfg_dict, dict) else {}
    model = str(det_cfg.get("model", "") or "").strip().lower()
    detector = getattr(manager, "detector", None)
    if detector is None:
        return model or "unknown", "unavailable"
    if not model:
        model = getattr(detector, "name", None) or type(detector).__name__.lower()
    status = "simulation" if model == "mock" else "ready"
    return str(model), status


def build_stream_telemetry(
    manager: Any, tracks: dict[int, Any], curr_t: float,
    measured_fps: float, shape: tuple[int, ...], frame_count: int, *, step_res: Any = None,
) -> dict[str, Any]:
    """Construct comprehensive telemetry payload with ground plane projections."""
    rec_status = (
        manager.get_recording_status()
        if hasattr(manager, "get_recording_status")
        else {"is_recording": False}
    )
    detector_model, detector_status = _resolve_detector_telemetry(manager)
    src_w = int(shape[1]) if len(shape) >= 2 else 0
    src_h = int(shape[0]) if len(shape) >= 1 else 0
    inf_seq = int(getattr(step_res, "inference_frame_seq", frame_count) if step_res is not None else frame_count)
    inf_lag = round(max(0.0, float(getattr(step_res, "inference_lag_ms", 0.0) if step_res is not None else 0.0)), 1)
    svc = getattr(manager, "_processing_mode_service", None)
    sched = getattr(svc, "scheduler", None) if svc is not None else None
    cam_sched = sched.get_camera_summary(manager.camera_id) if sched is not None else {}
    return {
        "camera_id": manager.camera_id, "status": "online",
        "detector_model": detector_model, "detector_status": detector_status,
        "timestamp": curr_t, "fps": round(measured_fps, 1),
        "resolution": f"{src_w}x{src_h}", "source_resolution": [src_w, src_h],
        "frame_count": frame_count, "frame_seq": frame_count,
        "inference_frame_seq": inf_seq, "inference_lag_ms": inf_lag,
        "homography_calibrated": bool(getattr(manager, "homography", None) and manager.homography.is_calibrated),
        "overlays": dict(manager.overlays),
        "active_tracks": _extract_track_telemetry(tracks, manager.homography),
        "zones": _build_zones_data(manager.analytics),
        "tripwires": _build_tripwires_data(manager.analytics),
        "recent_alerts": _extract_recent_alerts(manager.event_bus),
        "recording": rec_status,
        "priority_tier": getattr(step_res, "priority_tier", cam_sched.get("priority_tier", "P2")),
        "target_fps": getattr(step_res, "target_fps", cam_sched.get("target_fps", 0.0)),
        "motion_active": bool(getattr(step_res, "motion_active", cam_sched.get("motion_active", False))),
        "load_shed_stage": getattr(step_res, "load_shed_stage", cam_sched.get("load_shed_stage", "normal")),
        "replay_active": bool(getattr(step_res, "replay_active", False)),
    }
