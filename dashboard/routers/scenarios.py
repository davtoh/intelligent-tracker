"""
Intelligent Tracker Dashboard - Scenarios, Zones, Tripwires & Calibration Router.

Handles zone creation, tripwire line segments, 4-point homography calibration,
and real-time Bird's-Eye-View (BEV) minimap rendering.
"""

from __future__ import annotations

import io
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

import dashboard.dependencies as deps
from dashboard.schemas import (
    ZoneCreateRequest,
    TripwireCreateRequest,
    HomographyCalibrationRequest,
)
from intelligent_tracker.homography import GroundPlaneHomography

logger = logging.getLogger("intelligent_tracker.dashboard.scenarios")

router = APIRouter(tags=["Scenarios"])


@router.get("/zones")
async def list_zones(camera_id: Optional[str] = None):
    """List configured zones and their real-time occupancy counts."""
    mgr = deps.get_active_stream_manager(camera_id)
    if not mgr or not mgr.analytics:
        return []
    zones = []
    for z in mgr.analytics.zones.values():
        zones.append({
            "name": z.name,
            "occupancy": z.occupancy,
            "category_filter": getattr(z, "category_filter", ""),
            "dwell_threshold": z.dwell_threshold,
            "capacity_limit": getattr(z, "capacity_limit", None),
        })
    return zones


@router.get("/api/scenarios")
async def get_all_scenarios():
    """Retrieve full scenario configuration across all cameras (zones, tripwires, homography, transitions)."""
    sm = deps.get_scenario_manager()
    result = {
        "version": "1.0",
        "cameras": {},
        "spatial_transitions": [l.to_dict() for l in sm.topology.list_links() if not l.link_id.endswith("_rev")],
    }
    for cam_id, c_data in sm.cameras.items():
        result["cameras"][cam_id] = {
            "zones": [
                {
                    "name": z.name,
                    "polygon": z.polygon.tolist() if hasattr(z.polygon, "tolist") else list(z.polygon),
                    "dwell_threshold": z.dwell_threshold,
                    "capacity_limit": getattr(z, "capacity_limit", None),
                    "category_filter": getattr(z, "category_filter", ""),
                    "color": list(z.color),
                }
                for z in c_data["zones"].values()
            ],
            "tripwires": [
                {
                    "name": tw.name,
                    "line_segment": [list(tw.line_segment[0]), list(tw.line_segment[1])],
                    "bidirectional": tw.bidirectional,
                    "color": list(tw.color),
                }
                for tw in c_data["tripwires"].values()
            ],
            "homography": c_data["homography"].to_dict(),
        }
    return result


@router.get("/api/scenarios/{camera_id}")
async def get_camera_scenario(camera_id: str):
    """Retrieve scenario details for a specific camera channel."""
    sm = deps.get_scenario_manager()
    c_data = sm._ensure_camera_entry(camera_id)
    return {
        "camera_id": camera_id,
        "zones": [
            {
                "name": z.name,
                "polygon": z.polygon.tolist() if hasattr(z.polygon, "tolist") else list(z.polygon),
                "dwell_threshold": z.dwell_threshold,
                "capacity_limit": getattr(z, "capacity_limit", None),
                "category_filter": getattr(z, "category_filter", ""),
                "color": list(z.color),
            }
            for z in c_data["zones"].values()
        ],
        "tripwires": [
            {
                "name": tw.name,
                "line_segment": [list(tw.line_segment[0]), list(tw.line_segment[1])],
                "bidirectional": tw.bidirectional,
                "color": list(tw.color),
            }
            for tw in c_data["tripwires"].values()
        ],
        "homography": c_data["homography"].to_dict(),
    }


@router.post("/api/scenarios/zones")
async def create_or_update_zone(req: ZoneCreateRequest):
    """Create or update a polygonal zone for a camera, persisting to YAML & SQLite."""
    sm = deps.get_scenario_manager()
    color_tuple = tuple(req.color) if req.color and len(req.color) >= 3 else (0, 200, 100)
    zone = sm.save_zone(
        camera_id=req.camera_id,
        name=req.name,
        polygon=req.polygon,
        category_filter=req.category_filter or "",
        dwell_threshold=req.dwell_threshold or 5.0,
        capacity_limit=req.capacity_limit,
        color=color_tuple,
    )

    # Hot reload into active stream manager if camera is active
    mgr = deps.get_active_stream_manager(req.camera_id)
    if mgr and mgr.analytics:
        mgr.analytics.add_zone(zone)

    return {
        "status": "success",
        "zone": {
            "camera_id": req.camera_id,
            "name": zone.name,
            "polygon": req.polygon,
            "dwell_threshold": zone.dwell_threshold,
            "capacity_limit": zone.capacity_limit,
            "category_filter": getattr(zone, "category_filter", ""),
            "color": list(zone.color),
        },
    }


@router.delete("/api/scenarios/zones/{camera_id}/{zone_name}")
async def delete_zone_route(camera_id: str, zone_name: str):
    """Delete a zone from a camera, updating memory, YAML, and SQLite."""
    sm = deps.get_scenario_manager()
    deleted = sm.delete_zone(camera_id, zone_name)

    # Hot reload in active stream manager
    mgr = deps.get_active_stream_manager(camera_id)
    if mgr and mgr.analytics and zone_name in mgr.analytics.zones:
        del mgr.analytics.zones[zone_name]

    return {"status": "success" if deleted else "not_found", "deleted": zone_name}


@router.post("/api/scenarios/tripwires")
async def create_or_update_tripwire(req: TripwireCreateRequest):
    """Create or update a directional tripwire line for a camera."""
    sm = deps.get_scenario_manager()
    color_tuple = tuple(req.color) if req.color and len(req.color) >= 3 else (0, 255, 255)
    tw = sm.save_tripwire(
        camera_id=req.camera_id,
        name=req.name,
        line_segment=req.line_segment,
        bidirectional=req.bidirectional if req.bidirectional is not None else True,
        color=color_tuple,
    )

    # Hot reload into active stream manager if camera is active
    mgr = deps.get_active_stream_manager(req.camera_id)
    if mgr and mgr.analytics:
        mgr.analytics.add_tripwire(tw)

    return {
        "status": "success",
        "tripwire": {
            "camera_id": req.camera_id,
            "name": tw.name,
            "line_segment": req.line_segment,
            "bidirectional": tw.bidirectional,
            "color": list(tw.color),
        },
    }


@router.delete("/api/scenarios/tripwires/{camera_id}/{tripwire_name}")
async def delete_tripwire_route(camera_id: str, tripwire_name: str):
    """Delete a tripwire line from a camera."""
    sm = deps.get_scenario_manager()
    deleted = sm.delete_tripwire(camera_id, tripwire_name)

    mgr = deps.get_active_stream_manager(camera_id)
    if mgr and mgr.analytics and tripwire_name in mgr.analytics.tripwires:
        del mgr.analytics.tripwires[tripwire_name]

    return {"status": "success" if deleted else "not_found", "deleted": tripwire_name}


@router.post("/api/scenarios/homography")
async def save_homography_route(req: HomographyCalibrationRequest):
    """Calibrate 4-point perspective ground plane homography matrix for camera."""
    sm = deps.get_scenario_manager()
    try:
        homo = sm.save_homography(
            camera_id=req.camera_id,
            src_points=req.src_points,
            dst_points=req.dst_points,
            metric_width=req.metric_width or 10.0,
            metric_height=req.metric_height or 10.0,
        )

        # Apply to live stream manager if running
        mgr = deps.get_active_stream_manager(req.camera_id)
        if mgr:
            mgr.homography = homo

        return {"status": "success", "homography": homo.to_dict()}
    except Exception as e:
        logger.error("Homography calibration failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/scenarios/homography/{camera_id}")
async def get_homography_route(camera_id: str):
    """Get ground plane homography calibration profile for a camera."""
    sm = deps.get_scenario_manager()
    homo = sm.get_homography(camera_id)
    return homo.to_dict()


@router.delete("/api/scenarios/homography/{camera_id}")
async def delete_homography_route(camera_id: str):
    """Reset homography calibration for a camera channel."""
    sm = deps.get_scenario_manager()
    c_entry = sm._ensure_camera_entry(camera_id)
    c_entry["homography"] = GroundPlaneHomography(camera_id=camera_id)
    if sm.db:
        sm.db.delete_homography_calibration(camera_id)
    sm.save_to_yaml()

    mgr = deps.get_active_stream_manager(camera_id)
    if mgr:
        mgr.homography = c_entry["homography"]

    return {"status": "success", "deleted": camera_id}


@router.get("/api/scenarios/bev/{camera_id}")
async def get_bev_minimap_image(camera_id: str):
    """Retrieve live 2D Bird's-Eye-View (BEV) top-down minimap image."""
    mgr = deps.get_active_stream_manager(camera_id)
    if mgr:
        jpeg_bytes = mgr.get_bev_minimap_jpeg()
        return StreamingResponse(io.BytesIO(jpeg_bytes), media_type="image/jpeg")
    raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
