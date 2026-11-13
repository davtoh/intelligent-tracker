"""Internal helpers for registering configured zones and tripwires into WorldGraph."""

from typing import Any

from intelligent_tracker.analytics import AnalyticsEngine
from intelligent_tracker.pipeline.config import PipelineConfig
from intelligent_tracker.world import TripwireNode, WorldGraph, ZoneNode


def register_world_children(
    graph: WorldGraph,
    config: PipelineConfig,
    analytics: AnalyticsEngine | None,
) -> None:
    """Register camera zones and tripwires in WorldGraph from analytics or config."""
    zones: list[tuple[str, Any, Any]] = (
        [(z.name, z.polygon, z.capacity_limit) for z in analytics.zones.values()]
        if analytics is not None
        else [
            (str(z.get("name", "zone")), z.get("polygon"), z.get("capacity_limit", z.get("max_occupancy")))
            for z in config.zones if z.get("polygon") and len(z["polygon"]) >= 3
        ]
    )
    for name, poly, cap in zones:
        graph.register_zone(ZoneNode(
            zone_id=name, camera_id=config.camera_id, name=name,
            points=[(float(pt[0]), float(pt[1])) for pt in poly], max_occupancy=cap,
        ))
    tripwires: list[tuple[str, Any, Any, bool]] = (
        [(tw.name, tw.pt1, tw.pt2, tw.bidirectional) for tw in analytics.tripwires.values()]
        if analytics is not None
        else [
            (str(tw.get("name", "tripwire")), tw["line"][0], tw["line"][1], bool(tw.get("bidirectional", True)))
            for tw in config.tripwires if tw.get("line") and len(tw["line"]) >= 2
        ]
    )
    for name, pt1, pt2, bidir in tripwires:
        graph.register_tripwire(TripwireNode(
            tripwire_id=name, camera_id=config.camera_id, name=name,
            pt1=(float(pt1[0]), float(pt1[1])), pt2=(float(pt2[0]), float(pt2[1])),
            direction="both" if bidir else "in",
        ))

