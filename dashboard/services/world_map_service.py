#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - World Map Telemetry & Pose Hydration Service.

Hydrates persisted camera world poses into WorldGraph / GlobalCoordinateMapper
and prunes deleted/stale cameras absent from the active CameraPool.
"""

from typing import Any

from intelligent_tracker.world import WorldGraph, WorldTacticalMinimap
from intelligent_tracker.world.coordinates import CameraWorldPose
from intelligent_tracker.world.nodes import CameraNode


def apply_pose_to_world(
    pose: dict[str, Any],
    world_graph: WorldGraph,
    sm: Any,
) -> None:
    """Hydrate a persisted world pose into WorldGraph and GlobalCoordinateMapper."""
    cid = str(pose.get("camera_id", ""))
    if not cid:
        return
    ox = float(pose.get("origin_x", 0.0))
    oy = float(pose.get("origin_y", 0.0))
    yaw = float(pose.get("yaw_deg", 0.0))
    scale = float(pose.get("scale", 1.0))
    extra = {
        "fov_deg": float(pose.get("fov_deg", 75.0)),
        "range_m": float(pose.get("range_m", 12.0)),
    }
    existing = world_graph.snapshot().get("cameras", {}).get(cid) or {}
    merged_extra = {**(existing.get("extra") or {}), **extra}
    cam_node = CameraNode(
        camera_id=cid,
        name=existing.get("name") or cid,
        enabled=bool(existing.get("enabled", True)),
        homography=existing.get("homography"),
        world_pose=(ox, oy, yaw),
        extra=merged_extra,
    )
    world_graph.register_camera(cam_node, preserve_defaults=False)
    if getattr(sm, "coordinate_mapper", None) is not None:
        sm.coordinate_mapper.set_pose(
            CameraWorldPose(camera_id=cid, origin_x=ox, origin_y=oy, yaw_deg=yaw, scale=scale)
        )


def build_filtered_world_map(
    sm: Any,
    pool: Any | None,
    db: Any | None,
) -> dict[str, Any]:
    """Build world minimap telemetry, pruning stale cameras absent from active CameraPool."""
    world_graph = sm.world_graph or (getattr(pool, "world_graph", None) if pool else None) or WorldGraph()
    active_ids: set[str] | None = None
    if pool is not None:
        camera_configs = getattr(pool, "camera_configs", None)
        if isinstance(camera_configs, dict):
            active_ids = set(camera_configs.keys())

    if active_ids is not None:
        existing_cams = list(world_graph.snapshot().get("cameras", {}).keys())
        for cid in existing_cams:
            if cid not in active_ids:
                world_graph.remove_camera(cid)

    poses = db.list_world_poses() if db is not None else []
    for pose in poses:
        cid = str(pose.get("camera_id", ""))
        if active_ids is not None and cid not in active_ids:
            continue
        apply_pose_to_world(pose, world_graph, sm)

    minimap = WorldTacticalMinimap(world_graph, coordinate_mapper=getattr(sm, "coordinate_mapper", None))
    telemetry = minimap.build_world_minimap_telemetry()
    if active_ids is not None:
        cameras = [c for c in telemetry.get("cameras", []) if c.get("camera_id") in active_ids]
        telemetry["cameras"] = cameras
        if isinstance(telemetry.get("counts"), dict):
            telemetry["counts"]["cameras"] = len(cameras)
    return telemetry
