#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Cross-Camera Topology, Spatial Transitions & Journey API Router.

Provides endpoints for spatial transition links between camera zones,
active predictive Re-ID priors, and multi-camera trajectory journey reconstruction/video export.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

from fastapi import APIRouter, HTTPException

from dashboard.dependencies import (
    VIDEOS_DIR,
    get_active_stream_manager,
    get_scenario_mgr,
)
from dashboard.schemas import JourneyExportRequest, SpatialTransitionRequest
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.journey import (
    JourneyVideoExporter,
    TrajectoryJourneySearcher,
)
from intelligent_tracker.topology import SpatialTransitionLink

logger = logging.getLogger("intelligent_tracker.dashboard.routers.topology")

router = APIRouter(tags=["Topology & Journey"])


@router.get("/api/topology/transitions")
async def list_spatial_transitions():
    """List registered cross-camera spatial transition links."""
    sm = get_scenario_mgr()
    return [
        l.to_dict()
        for l in sm.topology.list_links()
        if not l.link_id.endswith("_rev")
    ]


@router.post("/api/topology/transitions")
async def create_spatial_transition(req: SpatialTransitionRequest):
    """Define a predictive spatial transition link between camera zones."""
    sm = get_scenario_mgr()
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
        sm.db.save_spatial_transition(
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
    sm.save_to_yaml()
    return {"status": "success", "link": link.to_dict()}


@router.delete("/api/topology/transitions/{link_id}")
async def delete_spatial_transition(link_id: str):
    """Delete a spatial transition link by ID."""
    sm = get_scenario_mgr()
    deleted = sm.topology.remove_link(link_id)
    if sm.db:
        db_del = sm.db.delete_spatial_transition(link_id)
        deleted = deleted or db_del
    if deleted:
        sm.save_to_yaml()
    return {"status": "success" if deleted else "not_found", "deleted": link_id}


@router.get("/api/topology/priors")
async def list_active_priors(camera_id: Optional[str] = None):
    """List currently active predictive spatial priors within valid transit windows."""
    sm = get_scenario_mgr()
    now = time.time()
    priors = sm.topology.active_priors
    out = []
    for p in priors:
        if not p.is_expired_at(now):
            if not camera_id or p.target_camera == camera_id:
                out.append(p.to_dict())
    return out


@router.get("/api/journey/search")
async def search_trajectory_journey(
    entity_id: Optional[int] = None,
    entity_name: Optional[str] = None,
    track_id: Optional[int] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
):
    """Reconstruct an entity's complete chronological trajectory across multiple cameras."""
    mgr = get_active_stream_manager()
    db = mgr.db if (mgr and mgr.db) else TrackerDB()
    searcher = TrajectoryJourneySearcher(db)
    journey = searcher.search_journey(
        entity_id=entity_id,
        entity_name=entity_name,
        track_id=track_id,
        start_time=start_time,
        end_time=end_time,
    )
    return journey.to_dict()


@router.post("/api/journey/export")
async def export_journey_video_route(req: JourneyExportRequest):
    """Slices and concatenates cross-camera video segments into a downloadable MP4 journey file."""
    mgr = get_active_stream_manager()
    db = mgr.db if (mgr and mgr.db) else TrackerDB()
    searcher = TrajectoryJourneySearcher(db)
    journey = searcher.search_journey(
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
    exported_file = exporter.export_journey_video(journey)
    filename = os.path.basename(exported_file)

    return {
        "status": "success",
        "journey": journey.to_dict(),
        "video_file": filename,
        "video_url": f"/videos/{filename}",
    }

