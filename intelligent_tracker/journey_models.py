#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Pure journey dataclasses extracted from ``journey_segmenter.py``."""

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class JourneyHop:
    """Represents a discrete visit of an entity at a specific camera or zone."""

    hop_index: int
    camera_id: str
    camera_name: str
    zone_id: str | None
    start_time: float
    end_time: float
    duration_seconds: float
    sightings_count: int
    snapshot_path: str | None = None
    transit_time_from_prev: float | None = None
    sample_bboxes: list[list[int]] = field(default_factory=list)
    global_start_xy: tuple[float, float] | None = None
    global_end_xy: tuple[float, float] | None = None
    global_path: list[tuple[float, float]] = field(default_factory=list)
    video_filename: str = ""
    media_offset_sec: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EntityJourney:
    """Complete multi-camera chronological journey of an entity."""

    entity_id: int | None
    entity_name: str
    category: str
    total_hops: int
    total_duration_seconds: float
    first_seen: float
    last_seen: float
    hops: list[JourneyHop]
    summary_narrative: str
    global_start_xy: tuple[float, float] | None = None
    global_end_xy: tuple[float, float] | None = None
    global_path: list[tuple[float, float]] = field(default_factory=list)
    video_filename: str = ""
    media_offset_sec: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["hops"] = [h.to_dict() for h in self.hops]
        return d
