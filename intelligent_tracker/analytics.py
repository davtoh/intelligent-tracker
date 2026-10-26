#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Retail & Occupancy Analytics Engine.

Provides:

- ``OccupancyHeatmap``: Real-time 2D spatial density accumulation with Gaussian
  dispersion, temporal decay, false-color overlay, and PNG/CSV exports.
- ``AnalyticsEngine``: Orchestrates multi-zone occupancy, tripwire crossing
  tallies, dwell times, event logging, and telemetry reporting.
"""

import os
import csv
import json
import time
from typing import List, Dict, Tuple, Optional, Any, Union

import cv2
import numpy as np

from intelligent_tracker.geometry import Tripwire, ZoneROI, ZoneEvent, TripwireEvent
from intelligent_tracker.tracker import Track


class OccupancyHeatmap:
    """
    2D Spatial Density Heatmap Engine.

    Accumulates entity centroids over time, applies Gaussian kernel dispersion,
    supports continuous temporal decay (fading older dwell points), and renders
    translucent colormap overlays onto video frames.

    Parameters:
    -----------
    width : int
        Width of the video frame in pixels.
    height : int
        Height of the video frame in pixels.
    decay_rate : Optional[float]
        Frame-by-frame exponential decay multiplier (e.g. 0.995). None = cumulative.
    radius : int
        Gaussian footprint radius in pixels around each centroid.
    colormap : int
        OpenCV colormap enum (e.g. cv2.COLORMAP_JET, cv2.COLORMAP_INFERNO).
    """

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        decay_rate: Optional[float] = 0.998,
        radius: int = 25,
        colormap: int = cv2.COLORMAP_JET,
    ):
        self.width = int(width)
        self.height = int(height)
        self.decay_rate = float(decay_rate) if decay_rate is not None else None
        self.radius = max(5, int(radius))
        self.colormap = colormap

        self.density = np.zeros((self.height, self.width), dtype=np.float32)
        self._kernel = self._generate_gaussian_kernel(self.radius)

    def _generate_gaussian_kernel(self, r: int) -> np.ndarray:
        """Create a 2D Gaussian footprint normalized to peak 1.0."""
        size = 2 * r + 1
        x = np.arange(0, size, 1, float)
        y = x[:, np.newaxis]
        x0 = y0 = size // 2
        sigma = r / 2.5
        kernel = np.exp(-((x - x0) ** 2 + (y - y0) ** 2) / (2.0 * sigma ** 2))
        return kernel.astype(np.float32)

    def update(self, tracks: Union[Dict[int, Any], List[Any]]):
        """
        Accumulate density from current tracked entities.

        :param tracks: Dict[track_id, Track] or List of Track / centroid objects
        """
        # Apply temporal decay
        if self.decay_rate is not None and 0.0 < self.decay_rate < 1.0:
            self.density *= self.decay_rate

        centroids = []
        if isinstance(tracks, dict):
            for t in tracks.values():
                c = getattr(t, "centroid", None)
                if c is None and isinstance(t, (tuple, list)) and len(t) >= 2:
                    c = t[:2]
                if c is not None:
                    centroids.append(c)
        elif isinstance(tracks, (list, tuple)):
            for t in tracks:
                c = getattr(t, "centroid", None)
                if c is None and isinstance(t, (tuple, list)) and len(t) >= 2:
                    c = t[:2]
                if c is not None:
                    centroids.append(c)

        r = self.radius
        k_size = 2 * r + 1

        for cx, cy in centroids:
            cx_int = int(round(cx))
            cy_int = int(round(cy))

            # Bounding coordinates in density map
            x_min = max(0, cx_int - r)
            x_max = min(self.width, cx_int + r + 1)
            y_min = max(0, cy_int - r)
            y_max = min(self.height, cy_int + r + 1)

            if x_min >= x_max or y_min >= y_max:
                continue

            # Corresponding coordinates in kernel
            k_xmin = x_min - (cx_int - r)
            k_xmax = k_xmin + (x_max - x_min)
            k_ymin = y_min - (cy_int - r)
            k_ymax = k_ymin + (y_max - y_min)

            self.density[y_min:y_max, x_min:x_max] += self._kernel[k_ymin:k_ymax, k_xmin:k_xmax]

    def get_normalized(self, min_threshold: float = 0.05) -> Tuple[np.ndarray, np.ndarray]:
        """
        Normalize density map to uint8 [0, 255] and compute heat mask.
        :return: (normalized_density: np.ndarray, mask: np.ndarray)
        """
        max_val = np.max(self.density)
        if max_val <= 0.0:
            return np.zeros((self.height, self.width), dtype=np.uint8), np.zeros((self.height, self.width), dtype=bool)

        norm = (self.density / max_val)
        mask = norm >= min_threshold
        norm_uint8 = (norm * 255.0).astype(np.uint8)
        return norm_uint8, mask

    def get_colored_map(self, colormap: Optional[int] = None) -> np.ndarray:
        """
        Render standalone false-color mapped heatmap image.
        :return: Colorized BGR image (H, W, 3)
        """
        cmap = colormap if colormap is not None else self.colormap
        norm_uint8, _ = self.get_normalized(min_threshold=0.0)
        return cv2.applyColorMap(norm_uint8, cmap)

    def draw(
        self,
        frame: np.ndarray,
        alpha: float = 0.5,
        colormap: Optional[int] = None,
        min_threshold: float = 0.05,
    ) -> np.ndarray:
        """
        Render colormap overlay blended on top of video frame.

        :param frame: Video frame (H, W, 3) BGR
        :param alpha: Transparency blending weight (0.0 = only frame, 1.0 = only heatmap)
        :param colormap: OpenCV colormap enum
        :param min_threshold: Minimum normalized density threshold to display heat
        :return: Blended output frame
        """
        cmap = colormap if colormap is not None else self.colormap
        norm_uint8, mask = self.get_normalized(min_threshold=min_threshold)

        if not np.any(mask):
            return frame

        # Colorize
        heat_bgr = cv2.applyColorMap(norm_uint8, cmap)

        # Alpha blend only in active heat mask regions to preserve clean background
        out_frame = frame.copy()
        mask_3ch = np.repeat(mask[:, :, np.newaxis], 3, axis=2)
        blended = cv2.addWeighted(out_frame, 1.0 - alpha, heat_bgr, alpha, 0)
        out_frame[mask_3ch] = blended[mask_3ch]
        return out_frame

    def export_image(
        self,
        filepath: str,
        frame: Optional[np.ndarray] = None,
        alpha: float = 0.5,
        colormap: Optional[int] = None,
    ) -> bool:
        """Save a snapshot of the heatmap (or blended on a background frame) to PNG/JPG."""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        cmap = colormap if colormap is not None else self.colormap

        if frame is not None:
            rendered = self.draw(frame, alpha=alpha, colormap=cmap)
        else:
            norm_uint8, _ = self.get_normalized(min_threshold=0.0)
            rendered = cv2.applyColorMap(norm_uint8, cmap)

        return cv2.imwrite(filepath, rendered)

    def export_csv(self, filepath: str, grid_cells_x: int = 32, grid_cells_y: int = 24) -> bool:
        """
        Downsample the density array into an aggregated grid matrix and save to CSV.
        """
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        cell_w = self.width / float(grid_cells_x)
        cell_h = self.height / float(grid_cells_y)

        grid = np.zeros((grid_cells_y, grid_cells_x), dtype=np.float32)
        for gy in range(grid_cells_y):
            for gx in range(grid_cells_x):
                y0 = int(gy * cell_h)
                y1 = int((gy + 1) * cell_h)
                x0 = int(gx * cell_w)
                x1 = int((gx + 1) * cell_w)
                grid[gy, gx] = np.sum(self.density[y0:y1, x0:x1])

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["grid_y", "grid_x", "density_sum", "bbox_x0", "bbox_y0", "bbox_x1", "bbox_y1"])
            for gy in range(grid_cells_y):
                for gx in range(grid_cells_x):
                    writer.writerow([
                        gy,
                        gx,
                        round(float(grid[gy, gx]), 4),
                        int(gx * cell_w),
                        int(gy * cell_h),
                        int((gx + 1) * cell_w),
                        int((gy + 1) * cell_h),
                    ])
        return True

    def reset(self):
        """Clear density accumulation."""
        self.density.fill(0.0)


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
        zones: Optional[List[ZoneROI]] = None,
        tripwires: Optional[List[Tripwire]] = None,
        heatmap_enabled: bool = True,
        resolution: Tuple[int, int] = (640, 480),
        heatmap_decay: Optional[float] = 0.998,
        event_bus: Optional[Any] = None,
        camera_id: str = "cam_01",
    ):
        self.width, self.height = resolution
        self.event_bus = event_bus
        self.camera_id = str(camera_id)
        self.zones: Dict[str, ZoneROI] = {}
        self.tripwires: Dict[str, Tripwire] = {}

        if zones:
            for z in zones:
                self.add_zone(z)
        if tripwires:
            for tw in tripwires:
                self.add_tripwire(tw)

        self.heatmap: Optional[OccupancyHeatmap] = None
        if heatmap_enabled:
            self.heatmap = OccupancyHeatmap(
                width=self.width,
                height=self.height,
                decay_rate=heatmap_decay,
            )

        self.events: List[Any] = []
        self._prev_centroids: Dict[int, Tuple[float, float]] = {}
        self._start_time = time.time()
        self.total_frames_analyzed = 0

    def add_zone(self, zone: ZoneROI):
        self.zones[zone.name] = zone

    def add_tripwire(self, tripwire: Tripwire):
        self.tripwires[tripwire.name] = tripwire

    def update(
        self,
        tracks: Dict[int, Track],
        timestamp: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Process active tracks across all zones, tripwires, and heatmaps.

        :param tracks: Dict[track_id, Track] of confirmed or active tracks
        :param timestamp: Current frame timestamp
        :return: Telemetry update dictionary
        """
        now = timestamp if timestamp is not None else time.time()
        self.total_frames_analyzed += 1
        new_events = []

        # 1. Check Tripwire crossings
        for tid, track in tracks.items():
            curr_c = track.centroid
            prev_c = self._prev_centroids.get(tid)

            if prev_c is not None:
                for tw in self.tripwires.values():
                    ev = tw.check_crossing(tid, prev_c, curr_c, timestamp=now)
                    if ev is not None:
                        new_events.append(ev)
                        self.events.append(ev)
                        if self.event_bus is not None:
                            try:
                                from intelligent_tracker.events import TripwireCrossEvent
                                bus_ev = TripwireCrossEvent(
                                    camera_id=self.camera_id,
                                    tripwire_id=tw.name,
                                    track_id=tid,
                                    direction=ev.direction,
                                    pt1=ev.pt1,
                                    pt2=ev.pt2,
                                    centroid=curr_c,
                                    entity_id=getattr(track, "entity_id", None),
                                    entity_name=getattr(track, "entity_name", getattr(track, "identity_label", None)),
                                    entity_category=getattr(track, "entity_category", None),
                                    timestamp=now,
                                )
                                self.event_bus.publish(bus_ev)
                            except Exception as ex:
                                pass

        # 2. Update Zone ROIs
        for z in self.zones.values():
            z_events = z.update(tracks, timestamp=now)
            if z_events:
                new_events.extend(z_events)
                self.events.extend(z_events)
                if self.event_bus is not None:
                    try:
                        from intelligent_tracker.events import ZoneEvent as BusZoneEvent
                        for z_ev in z_events:
                            trk = tracks.get(z_ev.track_id)
                            bus_ev = BusZoneEvent(
                                camera_id=self.camera_id,
                                zone_id=z_ev.zone_id,
                                track_id=z_ev.track_id,
                                action=z_ev.event_type,
                                dwell_time=z_ev.dwell_time,
                                centroid=z_ev.centroid,
                                bbox=z_ev.bbox,
                                entity_id=getattr(trk, "entity_id", None) if trk else None,
                                entity_name=getattr(trk, "entity_name", getattr(trk, "identity_label", None)) if trk else None,
                                entity_category=getattr(trk, "entity_category", None) if trk else None,
                                timestamp=now,
                            )
                            self.event_bus.publish(bus_ev)
                    except Exception as ex:
                        pass

        # 2b. Check Capacity Limits per Zone
        for z_name, z in self.zones.items():
            cap = getattr(z, "capacity_limit", None)
            if cap is not None and cap > 0:
                breached = getattr(z, "_threshold_breached", False)
                if z.occupancy > cap and not breached:
                    z._threshold_breached = True
                    try:
                        from intelligent_tracker.events import OccupancyThresholdEvent
                        thresh_ev = OccupancyThresholdEvent(
                            camera_id=self.camera_id,
                            zone_id=z_name,
                            current_occupancy=z.occupancy,
                            threshold=cap,
                            breach_type="exceeded",
                            severity="warning",
                            message="Zone '{}' exceeded occupancy capacity ({}/max {})".format(z_name, z.occupancy, cap),
                            timestamp=now,
                        )
                        new_events.append(thresh_ev)
                        self.events.append(thresh_ev)
                        if self.event_bus is not None:
                            self.event_bus.publish(thresh_ev)
                    except Exception:
                        pass
                elif z.occupancy <= cap and breached:
                    z._threshold_breached = False
                    try:
                        from intelligent_tracker.events import OccupancyThresholdEvent
                        thresh_ev = OccupancyThresholdEvent(
                            camera_id=self.camera_id,
                            zone_id=z_name,
                            current_occupancy=z.occupancy,
                            threshold=cap,
                            breach_type="cleared",
                            severity="info",
                            message="Zone '{}' occupancy cleared within capacity ({}/max {})".format(z_name, z.occupancy, cap),
                            timestamp=now,
                        )
                        new_events.append(thresh_ev)
                        self.events.append(thresh_ev)
                        if self.event_bus is not None:
                            self.event_bus.publish(thresh_ev)
                    except Exception:
                        pass

        # 3. Update Heatmap
        if self.heatmap is not None:
            self.heatmap.update(tracks)

        # 4. Cache current centroids for next frame crossing checks
        self._prev_centroids = {tid: track.centroid for tid, track in tracks.items()}

        # 5. Compile snapshot metrics
        return {
            "timestamp": now,
            "total_active_tracks": len(tracks),
            "zone_occupancy": {name: z.occupancy for name, z in self.zones.items()},
            "tripwire_tallies": {
                name: {"in": tw.total_in, "out": tw.total_out} for name, tw in self.tripwires.items()
            },
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
        tracks: Optional[Dict[int, Track]] = None,
        draw_hud: bool = True,
        fps: float = 0.0,
    ) -> np.ndarray:
        """
        Render comprehensive analytics visualization onto frame.
        """
        out = frame

        # Render Heatmap if requested
        if draw_heatmap and self.heatmap is not None:
            out = self.heatmap.draw(out, alpha=0.45)

        # Render Zone ROIs
        if draw_zones:
            for zone in self.zones.values():
                out = zone.draw(out)

        # Render Tripwires
        if draw_tripwires:
            for tw in self.tripwires.values():
                out = tw.draw(out)

        # Render Tracked Entities (Bounding box, ID, centroid trajectory trail)
        if draw_tracks and tracks:
            for tid, trk in tracks.items():
                x, y, w, h = trk.bbox

                # Color-code by state (confirmed = green, predicting = orange, tentative = yellow)
                if trk.state == "predicting":
                    col = (0, 165, 255)  # Orange for predictive dead-reckoning
                    border_th = 1
                elif trk.state == "confirmed":
                    col = (0, 255, 0)
                    border_th = 2
                else:
                    col = (0, 220, 255)
                    border_th = 2

                cv2.rectangle(out, (x, y), (x + w, y + h), col, border_th)

                # Track header badge
                if getattr(trk, "entity_name", None):
                    label_text = "#{}: {} ({:.0f}%)".format(
                        tid, trk.entity_name, getattr(trk, "reid_score", 1.0) * 100
                    )
                elif getattr(trk, "identity_label", None):
                    suffix = " [PREDICTING]" if trk.state == "predicting" else " [Active]"
                    label_text = "#{}: {}{}".format(tid, trk.identity_label, suffix)
                else:
                    suffix = " [PREDICTING]" if trk.state == "predicting" else ""
                    label_text = "#{}: {} ({:.2f}){}".format(tid, trk.label, trk.confidence, suffix)
                (tw_val, th_val), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
                cv2.rectangle(out, (x, max(0, y - th_val - 6)), (x + tw_val + 6, y), col, -1)
                cv2.putText(
                    out,
                    label_text,
                    (x + 3, max(10, y - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    (0, 0, 0),
                    1,
                    cv2.LINE_AA,
                )

                # Centroid motion history trail
                if len(trk.history) > 1:
                    pts = np.array([(int(p[0]), int(p[1])) for p in trk.history], dtype=np.int32).reshape((-1, 1, 2))
                    cv2.polylines(out, [pts], False, (0, 200, 255), 2, cv2.LINE_AA)

        # Render HUD Banner
        if draw_hud:
            out = self._render_hud(out, fps=fps, active_tracks=len(tracks) if tracks else 0)

        return out

    def _render_hud(self, frame: np.ndarray, fps: float, active_tracks: int) -> np.ndarray:
        """Render top translucent telemetry banner."""
        h, w = frame.shape[:2]
        banner_h = 36

        # Translucent bar
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, banner_h), (20, 20, 25), -1)
        cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)

        # Stats text
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

    def export_summary(self, filepath: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate comprehensive summary report of foot traffic and occupancy.
        """
        uptime = time.time() - self._start_time
        summary = {
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
