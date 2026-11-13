#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Central orchestration engine for retail, occupancy, and security telemetry."""

import json
import os
import time
from typing import Any

import cv2
import numpy as np

from intelligent_tracker.analytics.heatmap import OccupancyHeatmap
from intelligent_tracker.analytics.zone_stats import (
    draw_track_overlays,
    evaluate_tripwire_crossings,
    evaluate_zone_capacity_limits,
    evaluate_zone_updates,
)
from intelligent_tracker.geometry import Tripwire, ZoneROI
from intelligent_tracker.tracker import Track


class AnalyticsEngine:
    """
    Central orchestration engine for retail, occupancy, and security telemetry.

    Integrates:
    - Polygonal Zone ROIs (occupancy counting, dwell time monitoring)
    - Virtual Tripwires (bidirectional entry/exit tallying)
    - Occupancy Heatmap (spatial pedestrian flow)
    - Event Bus & audit log
    """

    def __init__(
        self,
        zones: list[ZoneROI] | None = None,
        tripwires: list[Tripwire] | None = None,
        heatmap_enabled: bool = True,
        resolution: tuple[int, int] = (640, 480),
        heatmap_decay: float | None = 0.998,
        event_bus: Any | None = None,
        camera_id: str = "cam_01",
        rsac_manager: Any | None = None,
        pet_whitelist: Any | None = None,
    ):
        self.width, self.height = resolution
        self.event_bus = event_bus
        self.camera_id = str(camera_id)
        self.rsac_manager = rsac_manager
        self.pet_whitelist = {s.lower().strip() for s in pet_whitelist} if pet_whitelist else None
        self.zones: dict[str, ZoneROI] = {}
        self.tripwires: dict[str, Tripwire] = {}

        if zones:
            for z in zones:
                self.add_zone(z)
        if tripwires:
            for tw in tripwires:
                self.add_tripwire(tw)

        self.heatmap: OccupancyHeatmap | None = (
            OccupancyHeatmap(width=self.width, height=self.height, decay_rate=heatmap_decay)
            if heatmap_enabled
            else None
        )
        self.events: list[Any] = []
        self._prev_centroids: dict[int, tuple[float, float]] = {}
        self._start_time = time.time()
        self.total_frames_analyzed = 0

    def add_zone(self, zone: ZoneROI):
        """Register a ZoneROI by name."""
        self.zones[zone.name] = zone

    def add_tripwire(self, tripwire: Tripwire):
        """Register a Tripwire by name."""
        self.tripwires[tripwire.name] = tripwire

    def update(
        self, tracks: dict[int, Track], timestamp: float | None = None,
        frame_time: float | None = None, current_frame: np.ndarray | None = None,
        frame: np.ndarray | None = None, **kwargs: Any,
    ) -> dict[str, Any]:
        """Process active tracks across zones, tripwires, and heatmap, returning telemetry."""
        now = timestamp if timestamp is not None else (frame_time if frame_time is not None else time.time())
        active_frame = current_frame if current_frame is not None else frame
        self.total_frames_analyzed += 1

        new_events = (
            evaluate_tripwire_crossings(
                tracks, self._prev_centroids, self.tripwires, self.camera_id,
                self.event_bus, active_frame, now, self.events,
            )
            + evaluate_zone_updates(
                tracks, self.zones, self.camera_id, self.event_bus,
                self.rsac_manager, self.pet_whitelist, active_frame, now, self.events,
            )
            + evaluate_zone_capacity_limits(
                self.zones, self.camera_id, self.event_bus, active_frame, now, self.events,
            )
        )
        if self.heatmap is not None:
            self.heatmap.update(tracks)
        self._prev_centroids = {tid: track.centroid for tid, track in tracks.items()}

        return {
            "timestamp": now,
            "total_active_tracks": len(tracks),
            "zone_occupancy": {name: z.occupancy for name, z in self.zones.items()},
            "tripwire_tallies": {name: {"in": tw.total_in, "out": tw.total_out} for name, tw in self.tripwires.items()},
            "new_events_count": len(new_events),
            "new_events": [ev.to_dict() for ev in new_events],
        }

    def draw(
        self,
        frame: np.ndarray,
        draw_zones: bool = True,
        draw_tripwires: bool = True,
        draw_heatmap: bool = False,
        draw_tracks: bool = True,
        tracks: dict[int, Track] | None = None,
        draw_hud: bool = True,
        fps: float = 0.0,
    ) -> np.ndarray:
        """Render comprehensive analytics visualization onto frame."""
        out = frame
        if draw_heatmap and self.heatmap is not None:
            out = self.heatmap.draw(out, alpha=0.45)
        if draw_zones:
            for zone in self.zones.values():
                out = zone.draw(out)
        if draw_tripwires:
            for tw in self.tripwires.values():
                out = tw.draw(out)
        if draw_tracks and tracks:
            draw_track_overlays(out, tracks)
        if draw_hud:
            out = self._render_hud(out, fps=fps, active_tracks=len(tracks) if tracks else 0)
        return out

    def _render_hud(self, frame: np.ndarray, fps: float, active_tracks: int) -> np.ndarray:
        """Render top translucent telemetry banner."""
        _, w = frame.shape[:2]
        banner_h = 36

        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, banner_h), (20, 20, 25), -1)
        cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)

        zones_summary = " | ".join(["{}: {}".format(name, z.occupancy) for name, z in self.zones.items()])
        tw_summary = " | ".join(["{}: +{}/-{}".format(name, tw.total_in, tw.total_out) for name, tw in self.tripwires.items()])

        stats_left = "FPS: {:.1f} | Active: {}".format(fps, active_tracks)
        if zones_summary:
            stats_left += " | [Zones] " + zones_summary
        if tw_summary:
            stats_left += " | [Tripwires] " + tw_summary

        cv2.putText(
            frame,
            stats_left,
            (12, 23),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (240, 240, 240),
            1,
            cv2.LINE_AA,
        )
        return frame

    def export_summary(self, filepath: str | None = None) -> dict[str, Any]:
        """Generate comprehensive summary report of foot traffic and occupancy."""
        uptime = time.time() - self._start_time
        summary: dict[str, Any] = {
            "uptime_seconds": round(uptime, 2),
            "total_frames_analyzed": self.total_frames_analyzed,
            "total_events_recorded": len(self.events),
            "zones": {},
            "tripwires": {},
        }

        for name, z in self.zones.items():
            summary["zones"][name] = {
                "current_occupancy": z.occupancy,
                "total_entries": z.total_entries,
                "total_exits": z.total_exits,
                "max_occupancy": z.max_occupancy,
            }

        for name, tw in self.tripwires.items():
            summary["tripwires"][name] = {
                "total_in": tw.total_in,
                "total_out": tw.total_out,
                "net_flow": tw.total_in - tw.total_out,
            }

        if filepath:
            os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)

        return summary
