#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Trajectory Journey Search & Video Exporter Module.

Provides historical trajectory reconstruction across cameras and zones,
chronological journey hop segmentation, dwell/transit durations, and MP4 export.
"""

import logging
import time
from typing import Any

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.homography import GroundPlaneHomography
from intelligent_tracker.journey_exporter import JourneyVideoExporter
from intelligent_tracker.journey_segmenter import (
    EntityJourney,
    JourneyHop,
    build_journey_hop,
    build_journey_narrative,
    compute_hop_global_path,
    parse_sighting_timestamp,
    segment_sightings_into_hops,
)

logger = logging.getLogger("intelligent_tracker.journey")

__all__ = [
    "JourneyHop",
    "EntityJourney",
    "TrajectoryJourneySearcher",
    "JourneyVideoExporter",
    "parse_sighting_timestamp",
    "build_journey_hop",
    "compute_hop_global_path",
    "segment_sightings_into_hops",
    "build_journey_narrative",
]


class TrajectoryJourneySearcher:
    """Reconstructs cross-camera trajectories and journey hops from TrackerDB sightings."""

    def __init__(
        self,
        db: TrackerDB,
        coordinate_mapper: Any = None,
        homographies: dict[str, GroundPlaneHomography] | None = None,
    ):
        self.db = db
        self.coordinate_mapper = coordinate_mapper
        self.homographies = dict(homographies) if homographies else {}

    def _resolve_entity_metadata(
        self, entity_id: int | None, entity_name: str | None
    ) -> tuple[int | None, str, str]:
        resolved_id = entity_id
        resolved_name = entity_name or "Unknown Entity"
        resolved_category = "person"

        if entity_name and not resolved_id:
            ent = self.db.get_entity_by_name(entity_name)
            if ent:
                resolved_id, resolved_name, resolved_category = ent["id"], ent["name"], ent["category"]

        if resolved_id:
            ent = self.db.get_entity(resolved_id)
            if ent:
                resolved_name, resolved_category = ent["name"], ent["category"]
        return resolved_id, resolved_name, resolved_category

    def _fetch_sightings(
        self, resolved_id: int | None, track_id: int | None, start_time: str | None, end_time: str | None
    ) -> tuple[list[dict[str, Any]], str | None]:
        sightings = self.db.query_sightings(
            entity_id=resolved_id, start_time=start_time, end_time=end_time, limit=500
        )
        override_name: str | None = None
        if not sightings and track_id is not None:
            with self.db._lock:
                cur = self.db._conn.cursor()
                try:
                    cur.execute(
                        "SELECT * FROM sightings WHERE track_id = ? ORDER BY timestamp ASC LIMIT 500",
                        (track_id,),
                    )
                    sightings = [dict(r) for r in cur.fetchall()]
                    if sightings:
                        override_name = f"Track #{track_id}"
                finally:
                    cur.close()
        return sightings, override_name

    def _resolve_homographies(
        self, sightings: list[dict[str, Any]], mapper: Any
    ) -> dict[str, GroundPlaneHomography]:
        resolved = dict(self.homographies)
        for cam_id in {s.get("source") or "cam_01" for s in sightings}:
            if cam_id in resolved or (mapper is not None and mapper.has_camera(cam_id)):
                continue
            h_data = self.db.get_homography_calibration(cam_id)
            if h_data:
                resolved[cam_id] = GroundPlaneHomography.from_dict(h_data)
        return resolved

    def search_journey(
        self, entity_id: int | None = None, entity_name: str | None = None,
        track_id: int | None = None, start_time: str | None = None,
        end_time: str | None = None, max_hop_gap_seconds: float = 60.0,
        coordinate_mapper: Any = None,
    ) -> EntityJourney:
        """Reconstruct the chronological cross-camera journey for an entity or track."""
        resolved_id, resolved_name, resolved_category = self._resolve_entity_metadata(entity_id, entity_name)
        sightings, override_name = self._fetch_sightings(resolved_id, track_id, start_time, end_time)
        if override_name:
            resolved_name = override_name
        if not sightings:
            now = time.time()
            return EntityJourney(
                entity_id=resolved_id, entity_name=resolved_name, category=resolved_category,
                total_hops=0, total_duration_seconds=0.0, first_seen=now, last_seen=now,
                hops=[], summary_narrative="No sightings found matching search criteria.",
            )
        mapper = coordinate_mapper or self.coordinate_mapper
        homographies = self._resolve_homographies(sightings, mapper)
        hops = segment_sightings_into_hops(
            sightings, max_hop_gap_seconds=max_hop_gap_seconds,
            coordinate_mapper=mapper, homographies=homographies,
        )
        first_ts = hops[0].start_time if hops else time.time()
        last_ts = hops[-1].end_time if hops else first_ts
        global_path = [pt for hop in hops for pt in hop.global_path]
        return EntityJourney(
            entity_id=resolved_id, entity_name=resolved_name, category=resolved_category,
            total_hops=len(hops), total_duration_seconds=round(max(0.0, last_ts - first_ts), 1),
            first_seen=first_ts, last_seen=last_ts, hops=hops,
            summary_narrative=build_journey_narrative(resolved_name, hops),
            global_start_xy=global_path[0] if global_path else None,
            global_end_xy=global_path[-1] if global_path else None,
            global_path=global_path,
        )

    def _build_hop(
        self, index: int, camera_id: str, sightings: list[dict[str, Any]], previous_hops: list[JourneyHop]
    ) -> JourneyHop:
        """Build a JourneyHop dataclass from a sightings list."""
        return build_journey_hop(
            index, camera_id, sightings, previous_hops,
            coordinate_mapper=self.coordinate_mapper, homographies=self.homographies,
        )
