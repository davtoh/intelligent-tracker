"""Shared post-detection governance for live FrameProcessor and CachedReplayProvider.

Executes spatial analytics (zones, tripwires, RSAC rules, pet whitelist),
cross-camera topology zone-exit forwarding, Re-ID gallery matching/event
publishing, and WorldEntityBridge synchronization on tracked objects.
"""

import logging
from typing import Any

import numpy as np

from intelligent_tracker.events import EntityIdentifiedEvent, RestrictedEntityAlert, crop_to_base64
from intelligent_tracker.pipeline.bundle import PipelineBundle

logger = logging.getLogger("intelligent_tracker.pipeline.governance")
_RESTRICTED_CATEGORIES = frozenset({"restricted", "banned", "blacklisted"})


def resolve_camera_id(bundle: PipelineBundle) -> str:
    """Resolve active camera identifier from analytics or config."""
    return getattr(bundle.analytics, "camera_id", None) or getattr(bundle.config, "camera_id", None) or "default"


def build_zone_lookup(bundle: PipelineBundle, tracks: dict[int, Any]) -> dict[int, str]:
    """Map active track IDs to their occupied analytics zone name."""
    analytics = bundle.analytics
    if analytics is None or not tracks:
        return {}
    zone_lookup: dict[int, str] = {}
    for z_name, zone in getattr(analytics, "zones", {}).items():
        for tid in getattr(zone, "current_occupants", ()):
            if tid in tracks and tid not in zone_lookup:
                zone_lookup[tid] = str(z_name)
    return zone_lookup


def handle_zone_exits(
    bundle: PipelineBundle,
    analytics_res: dict[str, Any],
    tracks: dict[int, Any],
    timestamp: float,
    *,
    topology: Any = None,
    world_bridge: Any = None,
) -> None:
    """Forward zone exit events to optional cross-camera topology and handoff."""
    if topology is None or not analytics_res:
        return
    camera_id = resolve_camera_id(bundle)
    handoff = getattr(world_bridge, "handoff_coordinator", None) if world_bridge else None
    for ev in analytics_res.get("new_events", []):
        if (ev.get("action") or ev.get("event_type")) not in ("exit", "zone_exit"):
            continue
        tid = ev.get("track_id")
        trk = tracks.get(tid)
        ent_id = getattr(trk, "entity_id", None) if trk else None
        ent_name = getattr(trk, "entity_name", getattr(trk, "identity_label", f"Track #{tid}")) if trk else f"Track #{tid}"
        zone_id = ev.get("zone_id")
        topology.record_zone_exit(
            camera_id=camera_id, zone_name=zone_id, entity_name=ent_name, entity_id=ent_id, timestamp=timestamp
        )
        if handoff is not None:
            handoff.record_zone_exit(camera_id, zone_id or "", entity_id=ent_id, track_id=tid, timestamp=timestamp)


def sync_world_bridge(
    bundle: PipelineBundle,
    tracks: dict[int, Any],
    zone_lookup: dict[int, str],
    timestamp: float,
    *,
    world_bridge: Any = None,
) -> None:
    """Push throttled track/zone state and stale prunes into WorldEntityBridge."""
    bridge = world_bridge if world_bridge is not None else getattr(bundle, "world_bridge", None)
    if bridge is None:
        return
    matcher = bundle.gallery_matcher
    if matcher is not None and tracks and getattr(matcher, "world_bridge", None) is bridge:
        return
    camera_id = resolve_camera_id(bundle)
    try:
        bridge.prune_stale_tracks(camera_id=camera_id, active_track_ids=set(tracks.keys()), timestamp=timestamp)
        if tracks:
            bridge.sync_camera_tracks(camera_id, tracks, zone_lookup=zone_lookup, timestamp=timestamp)
    except Exception as exc:
        logger.debug("World bridge sync error: %s", exc)


def publish_id_events(
    bundle: PipelineBundle,
    frame: np.ndarray,
    tracks: dict[int, Any],
    events: list[Any],
    timestamp: float,
) -> None:
    """Publish EntityIdentifiedEvent and RestrictedEntityAlert to EventBus."""
    bus = bundle.event_bus
    if bus is None or not events:
        return
    camera_id = resolve_camera_id(bundle)
    for ev in events:
        try:
            trk = tracks.get(ev.track_id)
            snap_b64 = getattr(ev, "snapshot_base64", None)
            if snap_b64 is None and trk is not None and getattr(trk, "bbox", None) is not None:
                snap_b64 = crop_to_base64(frame, trk.bbox)
            if isinstance(ev, EntityIdentifiedEvent):
                ev.camera_id = ev.camera_id or camera_id
                ev.snapshot_base64 = ev.snapshot_base64 if ev.snapshot_base64 is not None else snap_b64
                id_ev = ev
            else:
                id_ev = EntityIdentifiedEvent(
                    camera_id=camera_id, track_id=ev.track_id, entity_id=getattr(ev, "entity_id", 0),
                    name=ev.name, category=ev.category, similarity=ev.similarity,
                    snapshot_base64=snap_b64, timestamp=timestamp,
                )
            bus.publish(id_ev)
            if str(getattr(ev, "category", "")).lower() in _RESTRICTED_CATEGORIES:
                bus.publish(RestrictedEntityAlert(
                    camera_id=camera_id, track_id=ev.track_id, entity_id=getattr(ev, "entity_id", 0),
                    name=ev.name, category=ev.category, severity="critical",
                    message=f"Restricted entity '{ev.name}' detected",
                    snapshot_base64=snap_b64, timestamp=timestamp,
                ))
        except Exception as exc:
            logger.debug("Event publish error: %s", exc)


def evaluate_tracks_governance(
    bundle: PipelineBundle,
    frame: np.ndarray,
    tracks: dict[int, Any],
    timestamp: float,
    *,
    topology: Any = None,
    world_bridge: Any = None,
    run_reid: bool = True,
) -> tuple[dict[str, Any], list[Any]]:
    """Run AnalyticsEngine, zone exits, optional Re-ID, and WorldEntityBridge sync."""
    bridge = world_bridge if world_bridge is not None else getattr(bundle, "world_bridge", None)
    analytics_res: dict[str, Any] = {}
    if bundle.analytics is not None:
        try:
            raw = bundle.analytics.update(tracks, timestamp=timestamp, current_frame=frame)
            analytics_res = dict(raw) if isinstance(raw, dict) else {}
        except Exception as exc:
            logger.warning("Analytics error: %s", exc, exc_info=True)
    handle_zone_exits(bundle, analytics_res, tracks, timestamp, topology=topology, world_bridge=bridge)
    zone_lookup = build_zone_lookup(bundle, tracks)
    identifications: list[Any] = []
    matcher = bundle.gallery_matcher if run_reid else None
    if matcher is not None and tracks:
        try:
            if topology is not None and getattr(matcher, "topology", None) is None:
                matcher.topology = topology
            if bridge is not None and getattr(matcher, "world_bridge", None) is None:
                matcher.world_bridge = bridge
            identifications = list(
                matcher.match_tracks(
                    tracks=tracks, frame=frame, source=resolve_camera_id(bundle),
                    timestamp=timestamp, zone_lookup=zone_lookup,
                ) or []
            )
            publish_id_events(bundle, frame, tracks, identifications, timestamp)
        except Exception as exc:
            logger.debug("Re-ID matching error: %s", exc)
    sync_world_bridge(bundle, tracks, zone_lookup, timestamp, world_bridge=bridge)
    return analytics_res, identifications
