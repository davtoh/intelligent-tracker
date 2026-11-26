"""Non-destructive in-place zone and tripwire editing helpers for ScenarioManager."""

from typing import Any

import numpy as np

from intelligent_tracker.geometry import Tripwire, ZoneROI
from intelligent_tracker.repositories.spatial_edit_helpers import (
    ScenarioConflictError,
    ScenarioNotFoundError,
    update_spatial_tripwire_sync,
    update_spatial_zone_sync,
)
from intelligent_tracker.scenario_storage import (
    remove_child_from_world,
    sync_tripwire_to_world,
    sync_zone_to_world,
)

_UNSET = object()


def _resolve_target_and_rename(
    items: dict[str, Any], kind: str, camera_id: str, old_id: str, name: str | None
) -> tuple[Any, str]:
    item = items.get(old_id)
    if item is None:
        raise ScenarioNotFoundError(f"{kind} '{old_id}' not found for camera '{camera_id}'")
    new_name = str(name).strip() if name is not None else old_id
    if not new_name:
        raise ValueError(f"{kind} name must not be empty")
    if new_name != old_id and new_name in items:
        raise ScenarioConflictError(f"{kind} '{new_name}' already exists for camera '{camera_id}'")
    return item, new_name


def _mutate_zone_fields(
    zone: ZoneROI,
    new_name: str,
    polygon: list[list[float]] | list[tuple[float, float]] | None,
    category_filter: str | None,
    dwell_threshold: float | None,
    capacity_limit: Any,
    color: list[int] | tuple[int, ...] | None,
) -> None:
    """Apply geometry and config updates to a ZoneROI instance while preserving live state."""
    zone.name = new_name
    if polygon is not None:
        pts = [[float(pt[0]), float(pt[1])] for pt in polygon]
        zone.points = np.array(pts, dtype=np.float32)
        zone.contour = np.array(pts, dtype=np.int32).reshape((-1, 1, 2))
    if category_filter is not None:
        setattr(zone, "category_filter", str(category_filter))
    if dwell_threshold is not None:
        zone.dwell_threshold = float(dwell_threshold)
    if capacity_limit is not _UNSET:
        zone.capacity_limit = int(capacity_limit) if capacity_limit is not None else None
    if color is not None and len(color) >= 3:
        zone.color = (int(color[0]), int(color[1]), int(color[2]))


def _sync_live_analytics_zone(
    stream_manager: Any,
    old_name: str,
    new_name: str,
    zone: ZoneROI,
    polygon: list[list[float]] | list[tuple[float, float]] | None,
    category_filter: str | None,
    dwell_threshold: float | None,
    capacity_limit: Any,
    color: list[int] | tuple[int, ...] | None,
) -> None:
    """Sync in-place zone update onto an active StreamManager.analytics instance."""
    analytics = getattr(stream_manager, "analytics", None) if stream_manager is not None else None
    if analytics is None:
        return
    live_zone = analytics.zones.get(old_name)
    if live_zone is None:
        analytics.add_zone(zone)
        return
    if live_zone is not zone:
        _mutate_zone_fields(live_zone, new_name, polygon, category_filter, dwell_threshold, capacity_limit, color)
    if new_name != old_name:
        analytics.zones.pop(old_name, None)
        analytics.zones[new_name] = live_zone


def update_zone_in_place(
    sm: Any,
    camera_id: str,
    zone_id: str,
    *,
    name: str | None = None,
    polygon: list[list[float]] | list[tuple[float, float]] | None = None,
    category_filter: str | None = None,
    dwell_threshold: float | None = None,
    capacity_limit: Any = _UNSET,
    color: list[int] | tuple[int, ...] | None = None,
    stream_manager: Any = None,
) -> ZoneROI:
    """Update an existing ZoneROI in place, persisting to SQLite, YAML, and WorldGraph."""
    zones: dict[str, ZoneROI] = sm._ensure_camera_entry(camera_id)["zones"]
    zone, new_name = _resolve_target_and_rename(zones, "Zone", camera_id, zone_id, name)
    if getattr(sm, "db", None) is not None:
        cap_val = None if capacity_limit is _UNSET else capacity_limit
        update_spatial_zone_sync(
            sm.db, camera_id, zone_id, name=new_name, polygon=polygon, category_filter=category_filter,
            dwell_threshold=dwell_threshold, capacity_limit=cap_val, capacity_limit_set=capacity_limit is not _UNSET, color=color,
        )
    _mutate_zone_fields(zone, new_name, polygon, category_filter, dwell_threshold, capacity_limit, color)
    if new_name != zone_id:
        zones.pop(zone_id, None)
        zones[new_name] = zone
        remove_child_from_world(getattr(sm, "world_graph", None), camera_id, "zone", zone_id)
    _sync_live_analytics_zone(stream_manager, zone_id, new_name, zone, polygon, category_filter, dwell_threshold, capacity_limit, color)
    sm.save_to_yaml()
    poly_pts = zone.polygon.tolist() if hasattr(zone.polygon, "tolist") else list(zone.polygon)
    sync_zone_to_world(getattr(sm, "world_graph", None), camera_id, new_name, poly_pts, zone.capacity_limit)
    return zone


def _mutate_tripwire_fields(
    tw: Tripwire,
    new_name: str,
    line_segment: list[list[float]] | list[tuple[float, float]] | None,
    bidirectional: bool | None,
    color: list[int] | tuple[int, ...] | None,
) -> None:
    """Apply geometry and config updates to a Tripwire instance while preserving live counts."""
    tw.name = new_name
    if line_segment is not None and len(line_segment) >= 2:
        p1, p2 = line_segment[0], line_segment[1]
        tw.pt1 = (float(p1[0]), float(p1[1]))
        tw.pt2 = (float(p2[0]), float(p2[1]))
        tw.dx = tw.pt2[0] - tw.pt1[0]
        tw.dy = tw.pt2[1] - tw.pt1[1]
    if bidirectional is not None:
        tw.bidirectional = bool(bidirectional)
    if color is not None and len(color) >= 3:
        tw.color = (int(color[0]), int(color[1]), int(color[2]))


def _sync_live_analytics_tripwire(
    stream_manager: Any,
    old_name: str,
    new_name: str,
    tw: Tripwire,
    line_segment: list[list[float]] | list[tuple[float, float]] | None,
    bidirectional: bool | None,
    color: list[int] | tuple[int, ...] | None,
) -> None:
    """Sync in-place tripwire update onto an active StreamManager.analytics instance."""
    analytics = getattr(stream_manager, "analytics", None) if stream_manager is not None else None
    if analytics is None:
        return
    live_tw = analytics.tripwires.get(old_name)
    if live_tw is None:
        analytics.add_tripwire(tw)
        return
    if live_tw is not tw:
        _mutate_tripwire_fields(live_tw, new_name, line_segment, bidirectional, color)
    if new_name != old_name:
        analytics.tripwires.pop(old_name, None)
        analytics.tripwires[new_name] = live_tw


def update_tripwire_in_place(
    sm: Any,
    camera_id: str,
    tripwire_id: str,
    *,
    name: str | None = None,
    line_segment: list[list[float]] | list[tuple[float, float]] | None = None,
    bidirectional: bool | None = None,
    color: list[int] | tuple[int, ...] | None = None,
    stream_manager: Any = None,
) -> Tripwire:
    """Update an existing Tripwire in place, persisting to SQLite, YAML, and WorldGraph."""
    tripwires: dict[str, Tripwire] = sm._ensure_camera_entry(camera_id)["tripwires"]
    tw, new_name = _resolve_target_and_rename(tripwires, "Tripwire", camera_id, tripwire_id, name)
    if getattr(sm, "db", None) is not None:
        update_spatial_tripwire_sync(
            sm.db, camera_id, tripwire_id, name=new_name, line_segment=line_segment, bidirectional=bidirectional, color=color,
        )
    _mutate_tripwire_fields(tw, new_name, line_segment, bidirectional, color)
    if new_name != tripwire_id:
        tripwires.pop(tripwire_id, None)
        tripwires[new_name] = tw
        remove_child_from_world(getattr(sm, "world_graph", None), camera_id, "tripwire", tripwire_id)
    _sync_live_analytics_tripwire(stream_manager, tripwire_id, new_name, tw, line_segment, bidirectional, color)
    sm.save_to_yaml()
    sync_tripwire_to_world(
        getattr(sm, "world_graph", None), camera_id, new_name, [list(tw.pt1), list(tw.pt2)], tw.bidirectional
    )
    return tw
