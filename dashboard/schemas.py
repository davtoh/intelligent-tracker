#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Dashboard Request and Response Pydantic Schemas.

Defines validated data transfer schemas for REST endpoints across cameras,
zones, tripwires, homography, RSAC access control, and active learning candidate reviews.
"""

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator


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
    detector: Optional[str] = Field("yolov8", description="Detector model name (yolov8, yolo11, haar, mock, etc.)")
    tracker: Optional[str] = Field("centroid", description="Tracking algorithm (centroid, sort)")
    confidence: Optional[float] = Field(0.40, ge=0.01, le=1.0, description="Detection confidence threshold (0.01 - 1.0)")
    classes: Optional[Union[List[str], str]] = Field(None, description="Target class filter list (e.g. ['person', 'car'])")
    enabled: Optional[bool] = True
    details: Optional[Dict[str, Any]] = None

    @field_validator("classes", mode="before")
    @classmethod
    def _parse_classes(cls, v: Any) -> Optional[List[str]]:
        if v is None:
            return None
        if isinstance(v, str):
            res = [c.strip() for c in v.split(",") if c.strip()]
            return res if res else None
        if isinstance(v, (list, tuple, set)):
            res = [str(c).strip() for c in v if str(c).strip()]
            return res if res else None
        return v


class CameraUpdateRequest(BaseModel):
    name: Optional[str] = None
    source: Optional[str] = None
    type: Optional[str] = None
    enabled: Optional[bool] = None
    detector: Optional[str] = None
    tracker: Optional[str] = None
    confidence: Optional[float] = Field(None, ge=0.01, le=1.0, description="Updated confidence threshold")
    classes: Optional[Union[List[str], str]] = Field(None, description="Updated target class filters")

    @field_validator("classes", mode="before")
    @classmethod
    def _parse_classes(cls, v: Any) -> Optional[List[str]]:
        if v is None:
            return None
        if isinstance(v, str):
            res = [c.strip() for c in v.split(",") if c.strip()]
            return res if res else None
        if isinstance(v, (list, tuple, set)):
            res = [str(c).strip() for c in v if str(c).strip()]
            return res if res else None
        return v


class VideoAnalyzeRequest(BaseModel):
    sample_rate: Optional[int] = Field(1, ge=1, description="Frame sample rate for offline analysis")
    detector: Optional[str] = Field("yolov8", description="Detector model name (yolov8, mock, etc.)")
    confidence: Optional[float] = Field(0.40, ge=0.01, le=1.0, description="Detection confidence threshold")
    classes: Optional[Union[List[str], str]] = Field(None, description="Optional target class filters")
    async_mode: Optional[bool] = Field(None, description="Run analysis asynchronously in background")

    @field_validator("classes", mode="before")
    @classmethod
    def _parse_classes(cls, v: Any) -> Optional[List[str]]:
        if v is None:
            return None
        if isinstance(v, str):
            res = [c.strip() for c in v.split(",") if c.strip()]
            return res if res else None
        if isinstance(v, (list, tuple, set)):
            res = [str(c).strip() for c in v if str(c).strip()]
            return res if res else None
        return v


class VideoAddAsCameraRequest(BaseModel):
    camera_id: Optional[str] = Field(None, description="Optional custom camera ID")
    name: Optional[str] = Field(None, description="Optional display label")
    detector: Optional[str] = Field("yolov8", description="Detector model name")
    tracker: Optional[str] = Field("centroid", description="Tracker algorithm")
    confidence: Optional[float] = Field(0.40, ge=0.01, le=1.0, description="Detection confidence threshold")
    classes: Optional[Union[List[str], str]] = Field(None, description="Target class filter list")

    @field_validator("classes", mode="before")
    @classmethod
    def _parse_classes(cls, v: Any) -> Optional[List[str]]:
        if v is None:
            return None
        if isinstance(v, str):
            res = [c.strip() for c in v.split(",") if c.strip()]
            return res if res else None
        if isinstance(v, (list, tuple, set)):
            res = [str(c).strip() for c in v if str(c).strip()]
            return res if res else None
        return v


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
    allowed_categories: Optional[List[str]] = Field(default_factory=list, description="Allowed category IDs")
    denied_categories: Optional[List[str]] = Field(default_factory=list, description="Denied category IDs")
    schedules: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Schedule windows")
    entity_overrides: Optional[Dict[str, str]] = Field(default_factory=dict, description="Entity allow/deny overrides")
    alarm_on_breach: Optional[bool] = Field(True, description="Trigger alarm on unauthorized presence")


class PetWhitelistRequest(BaseModel):
    label: str = Field(..., min_length=1, description="Pet category or label (e.g. dog, cat, pet)")
    notes: Optional[str] = Field("", description="Optional notes")


class RollbackRequest(BaseModel):
    notes: Optional[str] = Field(None, description="Optional reason for descriptor rollback")


class WorldQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Natural-language or keyword world timeline query")
    entity_id: Optional[int] = Field(None, description="Optional explicit entity ID filter")
    camera_id: Optional[str] = Field(None, description="Optional explicit camera ID filter")
    zone_id: Optional[str] = Field(None, description="Optional explicit zone ID filter")
    event_type: Optional[str] = Field(None, description="Optional explicit timeline event type filter")
    start_time: Optional[float] = Field(None, description="Optional UNIX start timestamp")
    end_time: Optional[float] = Field(None, description="Optional UNIX end timestamp")
    limit: int = Field(15, ge=1, le=200, description="Maximum number of timeline citations to return")
    include_world_snapshot: bool = Field(True, description="Include live WorldGraph snapshot context")


class CameraRecordStartRequest(BaseModel):
    filename: Optional[str] = Field(None, description="Optional target MP4 filename in data/videos/")
    fps: Optional[float] = Field(None, description="Optional target recording framerate")
    annotated: bool = Field(True, description="Record HUD-annotated frames (True) or raw frames (False)")
    max_frames: Optional[int] = Field(None, description="Optional maximum frame count bound")
    max_duration_s: Optional[float] = Field(None, description="Optional maximum recording duration in seconds")


class CameraRecordStatusResponse(BaseModel):
    camera_id: str
    is_recording: bool
    status: str
    recording_id: Optional[str] = None
    filename: Optional[str] = None
    output_path: Optional[str] = None
    codec: Optional[str] = None
    fps: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    frames_written: int = 0
    elapsed_s: float = 0.0
    size_bytes: int = 0
    annotated: bool = True
    started_at: Optional[float] = None
    stopped_at: Optional[float] = None


