"""
Intelligent Tracker Dashboard - Pydantic Request & Response Schemas.

Type-validated schemas for VMS REST API endpoints.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


class EntityCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Entity full name or identifier")
    category: str = Field("person", description="Category: staff, vip, restricted, customer, person")
    notes: Optional[str] = Field("", description="Optional notes or security clearances")


class EntityUpdateRequest(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class TagRequest(BaseModel):
    entity_name: str = Field(..., min_length=1)
    category: str = Field("person")
    track_id: Optional[int] = None
    bbox: Optional[List[int]] = None
    notes: Optional[str] = ""
    camera_id: Optional[str] = "cam_01"


class CameraAddRequest(BaseModel):
    id: str = Field(..., min_length=1, description="Unique camera ID (e.g. cam_02)")
    name: str = Field(..., min_length=1, description="Friendly display label")
    source: str = Field(..., description="RTSP URL, video file path, or USB index")
    type: Optional[str] = "rtsp"
    detector: Optional[str] = "mock"
    tracker: Optional[str] = "centroid"
    enabled: Optional[bool] = True
    details: Optional[Dict[str, Any]] = None


class CameraUpdateRequest(BaseModel):
    name: Optional[str] = None
    source: Optional[str] = None
    type: Optional[str] = None
    enabled: Optional[bool] = None
    detector: Optional[str] = None
    tracker: Optional[str] = None


class CameraTestRequest(BaseModel):
    source: Optional[Any] = None
    preset: Optional[str] = None
    ip: Optional[str] = None
    port: Optional[int] = 554
    username: Optional[str] = ""
    password: Optional[str] = ""
    channel: Optional[int] = 1
    stream: Optional[str] = "main"


class ZoneCreateRequest(BaseModel):
    camera_id: str = Field("cam_01", description="Camera channel identifier")
    name: str = Field(..., min_length=1, description="Unique zone name")
    polygon: List[List[float]] = Field(..., min_length=3, description="List of [x, y] coordinates")
    category_filter: Optional[str] = Field("", description="Filter category (e.g. restricted, staff)")
    dwell_threshold: Optional[float] = Field(5.0, description="Dwell threshold in seconds")
    capacity_limit: Optional[int] = Field(None, description="Maximum occupant capacity limit")
    color: Optional[List[int]] = Field([0, 200, 100], description="BGR or RGB color list")


class TripwireCreateRequest(BaseModel):
    camera_id: str = Field("cam_01", description="Camera channel identifier")
    name: str = Field(..., min_length=1, description="Unique tripwire name")
    line_segment: List[List[float]] = Field(..., min_length=2, description="Two points: [[x1, y1], [x2, y2]]")
    bidirectional: Optional[bool] = Field(True, description="Detect crossing in both directions")
    color: Optional[List[int]] = Field([0, 255, 255], description="BGR or RGB color list")


class HomographyCalibrationRequest(BaseModel):
    camera_id: str = Field("cam_01", description="Camera channel identifier")
    src_points: List[List[float]] = Field(..., min_length=4, max_length=4, description="4 camera ground corners")
    dst_points: Optional[List[List[float]]] = Field(None, description="4 ground metric points")
    metric_width: Optional[float] = Field(10.0, description="Real world ground width in meters")
    metric_height: Optional[float] = Field(10.0, description="Real world ground height in meters")


class SpatialTransitionRequest(BaseModel):
    link_id: Optional[str] = Field(None, description="Optional custom link ID")
    source_camera: str = Field(..., description="Source camera ID")
    source_zone: str = Field(..., description="Source zone name")
    target_camera: str = Field(..., description="Target camera ID")
    target_zone: str = Field(..., description="Target zone name")
    t_min: Optional[float] = Field(2.0, description="Minimum expected transit time in seconds")
    t_max: Optional[float] = Field(15.0, description="Maximum expected transit time in seconds")
    prior_boost: Optional[float] = Field(0.35, description="Spatial predictive bonus to visual Re-ID score")
    bidirectional: Optional[bool] = Field(False, description="Bidirectional transition")
    active: Optional[bool] = Field(True, description="Whether link is active")


class OverlayUpdateRequest(BaseModel):
    bboxes: Optional[bool] = None
    track_ids: Optional[bool] = None
    dwell_timers: Optional[bool] = None
    velocity: Optional[bool] = None
    zones: Optional[bool] = None
    tripwires: Optional[bool] = None
    heatmap: Optional[bool] = None
    bev_minimap: Optional[bool] = None
    hud_bar: Optional[bool] = None
    clutter: Optional[bool] = None


class JourneyExportRequest(BaseModel):
    entity_id: Optional[int] = None
    entity_name: Optional[str] = None
    track_id: Optional[int] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None


class EnrollmentRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Entity full name or label")
    category: Optional[str] = Field("person", description="Semantic category")
    security_role: Optional[str] = Field("", description="Security role or clearance level")
    notes: Optional[str] = Field("", description="Optional entity notes or tags")
    is_anchor: Optional[bool] = Field(True, description="Mark as locked ground-truth anchor")
    camera_id: Optional[str] = Field("cam_01", description="Camera channel identifier for freeze-frame crop")
    bbox: Optional[List[int]] = Field(None, description="Bounding box [x, y, w, h] from freeze-frame")
    crop_base64: Optional[str] = Field(None, description="Optional Base64-encoded image crop")


class ReviewConfirmRequest(BaseModel):
    notes: Optional[str] = Field(None, description="Optional notes on confirmation")


class ReviewReassignRequest(BaseModel):
    target_entity_id: int = Field(..., description="Target entity ID to reassign signature to")
    notes: Optional[str] = Field(None, description="Optional notes on reassigning")


class ReviewEnrollNewRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Name for newly enrolled entity")
    category: Optional[str] = Field("person", description="Category for new entity")
    security_role: Optional[str] = Field("", description="Security role for new entity")
    notes: Optional[str] = Field("", description="Notes for new entity")


class ReviewDismissRequest(BaseModel):
    notes: Optional[str] = Field(None, description="Optional reason or notes on dismissal")


class CustomCategoryCreateRequest(BaseModel):
    id: str = Field(..., min_length=1, description="Unique category slug")
    name: str = Field(..., min_length=1, description="Human readable category name")
    color: Optional[str] = Field("#3B82F6", description="HEX color string")
    badge_icon: Optional[str] = Field("", description="Badge icon identifier")
    description: Optional[str] = Field("", description="Category description")


class RSACRuleCreateRequest(BaseModel):
    camera_id: str = Field(..., description="Camera ID")
    zone_id: str = Field(..., description="Zone ID")
    allowed_categories: Optional[List[str]] = Field(default_factory=list, description="List of allowed category IDs")
    denied_categories: Optional[List[str]] = Field(default_factory=list, description="List of denied category IDs")
    schedules: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="List of schedule windows")
    entity_overrides: Optional[Dict[str, str]] = Field(default_factory=dict, description="Entity ID to allow/deny overrides")
    alarm_on_breach: Optional[bool] = Field(True, description="Trigger alarm on unauthorized presence")


class PetWhitelistRequest(BaseModel):
    label: str = Field(..., min_length=1, description="Pet category or label")
    notes: Optional[str] = Field("", description="Optional notes")


class RollbackRequest(BaseModel):
    notes: Optional[str] = Field(None, description="Optional reason for descriptor rollback")

