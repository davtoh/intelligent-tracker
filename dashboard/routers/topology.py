#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Cross-Camera Topology, Spatial Transitions & Journey API Router.

Provides endpoints for spatial transition links between camera zones,
active predictive Re-ID priors, and multi-camera trajectory journey reconstruction/video export.
"""

import asyncio
import logging
import os
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from dashboard.camera_pool import CameraPool
from dashboard.dependencies import (
    VIDEOS_DIR,
    get_camera_pool,
    get_db,
    get_scenario_mgr,
)
from dashboard.schemas import JourneyExportRequest, SpatialTransitionRequest, WorldPoseRequest
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.journey import (
    JourneyVideoExporter,
    TrajectoryJourneySearcher,
)
from intelligent_tracker.scenarios import ScenarioManager
from intelligent_tracker.topology import SpatialTransitionLink
from intelligent_tracker.world import WorldGraph, WorldTacticalMinimap
from intelligent_tracker.world.coordinates import CameraWorldPose
from intelligent_tracker.world.nodes import CameraNode

logger = logging.getLogger("intelligent_tracker.dashboard.routers.topology")

router = APIRouter(tags=["Topology & Journey"])


@router.get("/api/topology/transitions")
async def list_spatial_transitions(sm: ScenarioManager = Depends(get_scenario_mgr)):
    """List registered cross-camera spatial transition links."""
    return [
        link.to_dict()
        for link in sm.topology.list_links()
        if not link.link_id.endswith("_rev")
    ]


@router.post("/api/topology/transitions")
async def create_spatial_transition(
    req: SpatialTransitionRequest,
    sm: ScenarioManager = Depends(get_scenario_mgr),
):
    """Define a predictive spatial transition link between camera zones."""
    link_id = (
        req.link_id
        or f"link_{req.source_camera}_{req.source_zone}_to_{req.target_camera}_{req.target_zone}".replace(
            " ", "_"
        ).lower()
    )
    link = SpatialTransitionLink(
        link_id=link_id,
        source_camera=req.source_camera,
        source_zone=req.source_zone,
        target_camera=req.target_camera,
        target_zone=req.target_zone,
        t_min=req.t_min or 2.0,
        t_max=req.t_max or 15.0,
        prior_boost=req.prior_boost or 0.35,
        bidirectional=bool(req.bidirectional),
        active=bool(req.active),
    )
    sm.topology.add_link(link)
    if sm.db:
        await asyncio.to_thread(
            sm.db.save_spatial_transition,
            link_id=link.link_id,
            source_camera=link.source_camera,
            source_zone=link.source_zone,
            target_camera=link.target_camera,
            target_zone=link.target_zone,
            t_min=link.t_min,
            t_max=link.t_max,
            prior_boost=link.prior_boost,
            bidirectional=link.bidirectional,
            active=link.active,
        )
    await asyncio.to_thread(sm.save_to_yaml)
    return {"status": "success", "link": link.to_dict()}


@router.delete("/api/topology/transitions/{link_id}")
async def delete_spatial_transition(
    link_id: str,
    sm: ScenarioManager = Depends(get_scenario_mgr),
):
    """Delete a spatial transition link by ID."""
    deleted = sm.topology.remove_link(link_id)
    if sm.db:
        db_del = await asyncio.to_thread(sm.db.delete_spatial_transition, link_id)
        deleted = deleted or db_del
    if deleted:
        await asyncio.to_thread(sm.save_to_yaml)
    return {"status": "success" if deleted else "not_found", "deleted": link_id}


@router.get("/api/topology/priors")
async def list_active_priors(
    camera_id: Optional[str] = None,
    sm: ScenarioManager = Depends(get_scenario_mgr),
):
    """List currently active predictive spatial priors within valid transit windows."""
    now = time.time()
    priors = sm.topology.active_priors
    out = []
    for p in priors:
        if not p.is_expired_at(now):
            if not camera_id or p.target_camera == camera_id:
                out.append(p.to_dict())
    return out


def _apply_pose_to_world(
    pose: dict,
    world_graph: WorldGraph,
    sm: ScenarioManager,
) -> None:
    """Hydrate a persisted world pose into WorldGraph and GlobalCoordinateMapper."""
    cid = str(pose.get("camera_id", ""))
    if not cid:
        return
    ox = float(pose.get("origin_x", 0.0))
    oy = float(pose.get("origin_y", 0.0))
    yaw = float(pose.get("yaw_deg", 0.0))
    scale = float(pose.get("scale", 1.0))
    extra = {"fov_deg": float(pose.get("fov_deg", 75.0)), "range_m": float(pose.get("range_m", 12.0))}
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


@router.get("/api/topology/world-pose")
async def list_world_poses(db: TrackerDB = Depends(get_db)):
    """List persisted camera world-coordinate poses."""
    poses = await asyncio.to_thread(db.list_world_poses)
    return {"poses": poses}


@router.put("/api/topology/world-pose/{camera_id}")
async def upsert_world_pose(
    camera_id: str,
    req: WorldPoseRequest,
    sm: ScenarioManager = Depends(get_scenario_mgr),
    pool: CameraPool | None = Depends(get_camera_pool),
    db: TrackerDB = Depends(get_db),
):
    """Persist a camera's world-coordinate pose and sync live WorldGraph."""
    await asyncio.to_thread(
        db.save_world_pose,
        camera_id,
        req.origin_x,
        req.origin_y,
        req.yaw_deg,
        req.scale,
        req.fov_deg,
        req.range_m,
    )
    pose = await asyncio.to_thread(db.get_world_pose, camera_id)
    world_graph = sm.world_graph or (getattr(pool, "world_graph", None) if pool else None)
    if world_graph is not None and pose is not None:
        _apply_pose_to_world(pose, world_graph, sm)
    return {"status": "ok", "pose": pose}


@router.get("/api/topology/world-map")
async def get_topology_world_map(
    sm: ScenarioManager = Depends(get_scenario_mgr),
    pool: CameraPool | None = Depends(get_camera_pool),
    db: TrackerDB = Depends(get_db),
):
    """Return unified global world minimap telemetry across cameras, zones, edges, and entities."""
    world_graph = sm.world_graph or (getattr(pool, "world_graph", None) if pool else None) or WorldGraph()
    poses = await asyncio.to_thread(db.list_world_poses)
    for pose in poses:
        _apply_pose_to_world(pose, world_graph, sm)
    minimap = WorldTacticalMinimap(world_graph, coordinate_mapper=sm.coordinate_mapper)
    return minimap.build_world_minimap_telemetry()


@router.get("/api/entities/suggest")
async def suggest_entities_route(
    q: str = "",
    limit: int = 8,
    db: TrackerDB = Depends(get_db),
):
    """Return prefix-ranked entity suggestions for journey autocomplete."""
    items = await asyncio.to_thread(db.suggest_entities, q, limit)
    return {"items": items, "query": q}


@router.get("/api/journey/search")
async def search_trajectory_journey(
    entity_id: Optional[int] = None,
    entity_name: Optional[str] = None,
    track_id: Optional[int] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    db: TrackerDB = Depends(get_db),
):
    """Reconstruct an entity's complete chronological trajectory across multiple cameras."""
    searcher = TrajectoryJourneySearcher(db)
    journey = await asyncio.to_thread(
        searcher.search_journey,
        entity_id=entity_id,
        entity_name=entity_name,
        track_id=track_id,
        start_time=start_time,
        end_time=end_time,
    )
    return journey.to_dict()


@router.post("/api/journey/export")
async def export_journey_video_route(
    req: JourneyExportRequest,
    db: TrackerDB = Depends(get_db),
):
    """Slices and concatenates cross-camera video segments into a downloadable MP4 journey file."""
    searcher = TrajectoryJourneySearcher(db)
    journey = await asyncio.to_thread(
        searcher.search_journey,
        entity_id=req.entity_id,
        entity_name=req.entity_name,
        track_id=req.track_id,
        start_time=req.start_time,
        end_time=req.end_time,
    )

    if journey.total_hops == 0:
        raise HTTPException(
            status_code=404,
            detail="No sightings found to generate journey video",
        )

    exporter = JourneyVideoExporter(output_dir=VIDEOS_DIR)
    exported_file = await asyncio.to_thread(exporter.export_journey_video, journey)
    filename = os.path.basename(exported_file)

    return {
        "status": "success",
        "journey": journey.to_dict(),
        "video_file": filename,
        "video_url": f"/videos/{filename}",
    }

