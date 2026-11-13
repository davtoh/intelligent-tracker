#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tripwire, zone ROI, RSAC/pet-whitelist, capacity, and overlay evaluation helpers."""

from typing import Any

import cv2
import numpy as np

from intelligent_tracker.geometry import Tripwire, ZoneROI
from intelligent_tracker.tracker import Track


def evaluate_tripwire_crossings(
    tracks: dict[int, Track],
    prev_centroids: dict[int, tuple[float, float]],
    tripwires: dict[str, Tripwire],
    camera_id: str,
    event_bus: Any | None,
    active_frame: np.ndarray | None,
    now: float,
    events_log: list[Any],
) -> list[Any]:
    """Evaluate tripwire crossings for active tracks and publish bus events."""
    new_events: list[Any] = []
    for tid, track in tracks.items():
        prev_c = prev_centroids.get(tid)
        if prev_c is None:
            continue
        curr_c = track.centroid
        for tw in tripwires.values():
            ev = tw.check_crossing(tid, prev_c, curr_c, timestamp=now)
            if ev is None:
                continue
            new_events.append(ev)
            events_log.append(ev)
            if event_bus is not None:
                _publish_tripwire_bus_event(event_bus, camera_id, tw.name, tid, track, ev, curr_c, active_frame, now)
    return new_events


def _publish_tripwire_bus_event(
    event_bus: Any, camera_id: str, tripwire_name: str, track_id: int,
    track: Track, ev: Any, curr_c: tuple[float, float], active_frame: np.ndarray | None, now: float,
) -> None:
    """Publish a TripwireCrossEvent with optional cropped track snapshot."""
    try:
        from intelligent_tracker.events import TripwireCrossEvent, crop_to_base64

        snap_b64 = crop_to_base64(active_frame, track.bbox) if active_frame is not None and getattr(track, "bbox", None) is not None else None
        event_bus.publish(TripwireCrossEvent(
            camera_id=camera_id, tripwire_id=tripwire_name, track_id=track_id, direction=ev.direction,
            pt1=ev.pt1, pt2=ev.pt2, centroid=curr_c,
            entity_id=getattr(track, "entity_id", None),
            entity_name=getattr(track, "entity_name", getattr(track, "identity_label", None)),
            entity_category=getattr(track, "entity_category", None),
            timestamp=now, snapshot_base64=snap_b64,
        ))
    except Exception:
        pass


def _make_pet_event(
    camera_id: str, zone_id: str, track_id: int, trk: Track | None,
    trk_eid: Any, trk_cat: str, now: float, snap_b64: str | None,
) -> Any:
    """Build a PetActivityEvent for RSAC suppression or pet-whitelist hits."""
    from intelligent_tracker.events import PetActivityEvent

    return PetActivityEvent(
        camera_id=camera_id, zone_id=zone_id, track_id=track_id, entity_id=trk_eid,
        entity_name=getattr(trk, "entity_name", getattr(trk, "identity_label", "Pet")),
        entity_category=trk_cat, timestamp=now, snapshot_base64=snap_b64,
    )


def _evaluate_zone_access_events(
    z_ev: Any, trk: Track | None, camera_id: str, event_bus: Any,
    rsac_manager: Any | None, pet_whitelist: set[str] | None, snap_b64: str | None, now: float,
) -> list[Any]:
    """Evaluate RSAC rules and pet whitelist policy for a zone event."""
    trk_cat = getattr(trk, "entity_category", getattr(trk, "label", "object")) if trk else "object"
    trk_eid = getattr(trk, "entity_id", None) if trk else None
    emitted: list[Any] = []

    if rsac_manager is not None:
        decision = rsac_manager.evaluate_access(
            camera_id=camera_id, zone_id=z_ev.zone_id, entity_category=trk_cat, entity_id=trk_eid, timestamp=now,
        )
        if decision.is_pet_suppressed:
            emitted.append(_make_pet_event(camera_id, z_ev.zone_id, z_ev.track_id, trk, trk_eid, trk_cat, now, snap_b64))
        elif not decision.allowed and z_ev.event_type in ("enter", "dwell"):
            from intelligent_tracker.events import RSACViolationEvent

            emitted.append(RSACViolationEvent(
                camera_id=camera_id, zone_id=z_ev.zone_id, track_id=z_ev.track_id, entity_id=trk_eid,
                entity_name=getattr(trk, "entity_name", getattr(trk, "identity_label", None)),
                entity_category=trk_cat, reason=decision.reason, severity=decision.severity,
                message=decision.reason, timestamp=now, snapshot_base64=snap_b64,
            ))
    elif pet_whitelist and trk_cat.lower().strip() in pet_whitelist:
        emitted.append(_make_pet_event(camera_id, z_ev.zone_id, z_ev.track_id, trk, trk_eid, trk_cat, now, snap_b64))

    for ev in emitted:
        event_bus.publish(ev)
    return emitted


def evaluate_zone_updates(
    tracks: dict[int, Track], zones: dict[str, ZoneROI], camera_id: str, event_bus: Any | None,
    rsac_manager: Any | None, pet_whitelist: set[str] | None,
    active_frame: np.ndarray | None, now: float, events_log: list[Any],
) -> list[Any]:
    """Update Zone ROIs, publish zone bus events, and evaluate RSAC/pet rules."""
    new_events: list[Any] = []
    for zone in zones.values():
        z_events = zone.update(tracks, timestamp=now)
        if not z_events:
            continue
        new_events.extend(z_events)
        events_log.extend(z_events)
        if event_bus is None:
            continue
        try:
            from intelligent_tracker.events import ZoneEvent as BusZoneEvent, crop_to_base64

            for z_ev in z_events:
                trk = tracks.get(z_ev.track_id)
                ev_box = z_ev.bbox or (getattr(trk, "bbox", None) if trk else None)
                snap_b64 = crop_to_base64(active_frame, ev_box) if (active_frame is not None and ev_box is not None) else None
                event_bus.publish(BusZoneEvent(
                    camera_id=camera_id, zone_id=z_ev.zone_id, track_id=z_ev.track_id,
                    action=z_ev.event_type, dwell_time=z_ev.dwell_time, centroid=z_ev.centroid, bbox=z_ev.bbox,
                    entity_id=getattr(trk, "entity_id", None) if trk else None,
                    entity_name=getattr(trk, "entity_name", getattr(trk, "identity_label", None)) if trk else None,
                    entity_category=getattr(trk, "entity_category", None) if trk else None,
                    timestamp=now, snapshot_base64=snap_b64,
                ))
                access_events = _evaluate_zone_access_events(
                    z_ev, trk, camera_id, event_bus, rsac_manager, pet_whitelist, snap_b64, now,
                )
                new_events.extend(access_events)
                events_log.extend(access_events)
        except Exception:
            pass
    return new_events


def _emit_occupancy_threshold_event(
    camera_id: str, z_name: str, occupancy: int, cap: int,
    breach_type: str, severity: str, message: str,
    active_frame: np.ndarray | None, now: float, event_bus: Any | None,
) -> Any | None:
    """Build and publish an OccupancyThresholdEvent, returning None on error."""
    try:
        from intelligent_tracker.events import OccupancyThresholdEvent, frame_to_base64

        snap_b64 = frame_to_base64(active_frame) if active_frame is not None else None
        thresh_ev = OccupancyThresholdEvent(
            camera_id=camera_id, zone_id=z_name, current_occupancy=occupancy, threshold=cap,
            breach_type=breach_type, severity=severity, message=message, timestamp=now, snapshot_base64=snap_b64,
        )
        if event_bus is not None:
            event_bus.publish(thresh_ev)
        return thresh_ev
    except Exception:
        return None


def evaluate_zone_capacity_limits(
    zones: dict[str, ZoneROI], camera_id: str, event_bus: Any | None,
    active_frame: np.ndarray | None, now: float, events_log: list[Any],
) -> list[Any]:
    """Check zone occupancy capacity thresholds and emit exceeded/cleared events."""
    new_events: list[Any] = []
    for z_name, zone in zones.items():
        cap = getattr(zone, "capacity_limit", None)
        if cap is None or cap <= 0:
            continue
        breached = getattr(zone, "_threshold_breached", False)
        if zone.occupancy > cap and not breached:
            zone._threshold_breached = True
            ev = _emit_occupancy_threshold_event(
                camera_id, z_name, zone.occupancy, cap, "exceeded", "warning",
                "Zone '{}' exceeded occupancy capacity ({}/max {})".format(z_name, zone.occupancy, cap),
                active_frame, now, event_bus,
            )
        elif zone.occupancy <= cap and breached:
            zone._threshold_breached = False
            ev = _emit_occupancy_threshold_event(
                camera_id, z_name, zone.occupancy, cap, "cleared", "info",
                "Zone '{}' occupancy cleared within capacity ({}/max {})".format(z_name, zone.occupancy, cap),
                active_frame, now, event_bus,
            )
        else:
            ev = None
        if ev is not None:
            new_events.append(ev)
            events_log.append(ev)
    return new_events


def draw_track_overlays(out: np.ndarray, tracks: dict[int, Track]) -> None:
    """Render bounding boxes, state badges, and motion history trails onto frame."""
    for tid, trk in tracks.items():
        x, y, w, h = trk.bbox
        if trk.state == "predicting":
            col, border_th = (0, 165, 255), 1  # Orange for predictive dead-reckoning
        elif trk.state == "confirmed":
            col, border_th = (0, 255, 0), 2
        else:
            col, border_th = (0, 220, 255), 2

        cv2.rectangle(out, (x, y), (x + w, y + h), col, border_th)

        if getattr(trk, "entity_name", None):
            label_text = "#{}: {} ({:.0f}%)".format(tid, trk.entity_name, getattr(trk, "reid_score", 1.0) * 100)
        elif getattr(trk, "identity_label", None):
            suffix = " [PREDICTING]" if trk.state == "predicting" else " [Active]"
            label_text = "#{}: {}{}".format(tid, trk.identity_label, suffix)
        else:
            suffix = " [PREDICTING]" if trk.state == "predicting" else ""
            label_text = "#{}: {} ({:.2f}){}".format(tid, trk.label, trk.confidence, suffix)

        (tw_val, th_val), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        cv2.rectangle(out, (x, max(0, y - th_val - 6)), (x + tw_val + 6, y), col, -1)
        cv2.putText(out, label_text, (x + 3, max(10, y - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)

        if len(trk.history) > 1:
            pts = np.array([(int(p[0]), int(p[1])) for p in trk.history], dtype=np.int32).reshape((-1, 1, 2))
            cv2.polylines(out, [pts], False, (0, 200, 255), 2, cv2.LINE_AA)
