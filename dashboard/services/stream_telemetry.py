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
    manager: Any,
    tracks: dict[int, Any],
    curr_t: float,
    measured_fps: float,
    shape: tuple[int, ...],
    frame_count: int,
) -> dict[str, Any]:
    """Construct comprehensive telemetry payload with ground plane projections."""
    rec_status = (
        manager.get_recording_status()
        if hasattr(manager, "get_recording_status")
        else {"is_recording": False}
    )
    detector_model, detector_status = _resolve_detector_telemetry(manager)
    return {
        "camera_id": manager.camera_id,
        "status": "online",
        "detector_model": detector_model,
        "detector_status": detector_status,
        "timestamp": curr_t,
        "fps": round(measured_fps, 1),
        "resolution": f"{shape[1]}x{shape[0]}",
        "frame_count": frame_count,
        "homography_calibrated": bool(getattr(manager, "homography", None) and manager.homography.is_calibrated),
        "overlays": dict(manager.overlays),
        "active_tracks": _extract_track_telemetry(tracks, manager.homography),
        "zones": _build_zones_data(manager.analytics),
        "tripwires": _build_tripwires_data(manager.analytics),
        "recent_alerts": _extract_recent_alerts(manager.event_bus),
        "recording": rec_status,
    }
