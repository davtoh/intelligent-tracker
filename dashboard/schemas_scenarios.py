"""Pydantic schemas for non-destructive scenario editing and zero-GPU video re-evaluation."""

from typing import List, Optional

from pydantic import BaseModel, Field


class ZoneUpdateRequest(BaseModel):
    """Request payload for in-place zone geometry, metadata, or rename updates."""

    name: Optional[str] = Field(None, min_length=1, description="Optional renamed zone identifier")
    polygon: Optional[List[List[float]]] = Field(None, min_length=3, description="Updated [x, y] polygon vertices")
    category_filter: Optional[str] = Field(None, description="Updated semantic category filter")
    dwell_threshold: Optional[float] = Field(None, ge=0.0, description="Updated dwell threshold in seconds")
    capacity_limit: Optional[int] = Field(None, ge=1, description="Updated occupant capacity limit")
    color: Optional[List[int]] = Field(None, min_length=3, description="Updated BGR or RGB color list")


class TripwireUpdateRequest(BaseModel):
    """Request payload for in-place tripwire endpoint, direction, or rename updates."""

    name: Optional[str] = Field(None, min_length=1, description="Optional renamed tripwire identifier")
    line_segment: Optional[List[List[float]]] = Field(
        None, min_length=2, description="Updated endpoints [[x1, y1], [x2, y2]]"
    )
    bidirectional: Optional[bool] = Field(None, description="Updated bidirectional crossing flag")
    color: Optional[List[int]] = Field(None, min_length=3, description="Updated BGR or RGB color list")


class VideoReevalRequest(BaseModel):
    """Request payload for zero-GPU scenario re-evaluation of an indexed video run."""

    video_filename: str = Field(..., min_length=1, description="Indexed video filename")
    run_id: Optional[str] = Field(None, description="Specific video_runs.run_id (defaults to latest run)")
    scenario_camera_id: Optional[str] = Field(
        None, description="Camera/profile ID whose ScenarioManager zones/tripwires apply"
    )
