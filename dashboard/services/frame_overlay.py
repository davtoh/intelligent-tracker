"""
Intelligent Tracker Dashboard - Frame HUD & Spatial Overlay Renderer.

Responsible for drawing bounding boxes, identity tags, dwell timers, velocity vectors,
zone polygons, tripwires, heatmaps, and bird's-eye-view (BEV) picture-in-picture minimaps
onto video frames.
"""

from __future__ import annotations

import time
import logging
from typing import Dict, Any, Optional

import cv2
import numpy as np

logger = logging.getLogger("intelligent_tracker.dashboard.overlays")


class FrameOverlayRenderer:
    """Renders visual analytics overlays, HUD bars, and spatial telemetry annotations."""

    def render(
        self,
        frame: np.ndarray,
        tracks: Dict[int, Any],
        overlays: Dict[str, bool],
        analytics: Optional[Any] = None,
        draw_heatmap: bool = False,
        rsac_manager: Optional[Any] = None,
        homography: Optional[Any] = None,
        camera_id: str = "cam_01",
        measured_fps: float = 0.0,
        start_time: float = 0.0,
    ) -> np.ndarray:
        """
        Render active overlays onto a copy of the input video frame.
        Preserves all OpenCV drawing calculations, coordinate projections, and color mappings.
        """
        annotated = frame.copy()
        h, w = annotated.shape[:2]

        # 1. Heatmap Overlay
        if (draw_heatmap or overlays.get("heatmap", False)) and analytics:
            try:
                annotated = analytics.draw_heatmap_overlay(annotated, alpha=0.55)
            except Exception:
                pass

        # 2. Zone Polygons & Occupancy Tags
        if overlays.get("zones", True) and analytics:
            for zone in list(analytics.zones.values()):
                pts = zone.polygon.reshape((-1, 1, 2)).astype(np.int32)
                is_breached = getattr(zone, "_threshold_breached", False)
                z_col = (0, 0, 255) if is_breached else zone.color

                # Semi-transparent polygon fill
                overlay = annotated.copy()
                cv2.fillPoly(overlay, [pts], z_col)
                cv2.addWeighted(overlay, 0.25, annotated, 0.75, 0, annotated)
                cv2.polylines(annotated, [pts], True, z_col, 2)

                # Centroid via spatial moments: cx = M10 / M00, cy = M01 / M00
                M = cv2.moments(pts)
                if M["m00"] != 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                else:
                    cx, cy = pts[0][0][0], pts[0][0][1]

                cap_text = f"/{zone.capacity_limit}" if getattr(zone, "capacity_limit", None) else ""
                tag = f"{zone.name} [{zone.occupancy}{cap_text}]"
                cv2.putText(annotated, tag, (cx - 30, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        # 3. Tripwires & Cross Counters
        if overlays.get("tripwires", True) and analytics:
            for tw in list(analytics.tripwires.values()):
                p1, p2 = tw.line_segment
                ip1 = (int(round(p1[0])), int(round(p1[1])))
                ip2 = (int(round(p2[0])), int(round(p2[1])))
                cv2.line(annotated, ip1, ip2, tw.color, 2)
                mid = ((ip1[0] + ip2[0]) // 2, (ip1[1] + ip2[1]) // 2)
                tw_tag = f"{tw.name}: IN={tw.in_count} OUT={tw.out_count}"
                cv2.putText(annotated, tw_tag, (mid[0] + 5, mid[1] - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, tw.color, 1)

        # 4. Tracks: Bounding Boxes, Identities, Dwell Timers & Velocity Vectors
        for tid, trk in list(tracks.items()):
            bx, by, bw, bh = trk.bbox
            color = (0, 255, 0)
            cat_id = getattr(trk, "category", "person")
            if rsac_manager:
                cat_obj = rsac_manager.get_category(cat_id)
                if cat_obj and cat_obj.color:
                    hex_c = cat_obj.color.lstrip("#")
                    if len(hex_c) == 6:
                        r, g, b = int(hex_c[0:2], 16), int(hex_c[2:4], 16), int(hex_c[4:6], 16)
                        color = (b, g, r)

            if hasattr(trk, "category") and trk.category == "restricted":
                color = (0, 0, 255)
            elif hasattr(trk, "category") and trk.category == "vip":
                color = (0, 215, 255)
            elif trk.state == "predicting":
                color = (255, 165, 0)

            # Bounding Box
            if overlays.get("bboxes", True):
                cv2.rectangle(annotated, (bx, by), (bx + bw, by + bh), color, 2)

            # Clutter / Interacting warning banner
            if getattr(trk, "is_cluttered", False) and overlays.get("clutter", True):
                partner_info = f" with #{trk.clutter_partner_id}" if getattr(trk, "clutter_partner_id", None) else ""
                clutter_tag = f"[CLUTTER{partner_info}]"
                cv2.putText(annotated, clutter_tag, (bx, by + bh + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 140, 255), 2)

            # Track Label & Dwell Timer
            if overlays.get("track_ids", True):
                name_disp = trk.entity_name or trk.identity_label or f"#{tid}"
                dwell_str = f" [{trk.dwell_time:.1f}s]" if overlays.get("dwell_timers", True) else ""
                hud_text = f"{name_disp} ({trk.confidence:.2f}){dwell_str}"
                cv2.putText(annotated, hud_text, (bx, max(15, by - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

            # Velocity Vector Arrow
            if overlays.get("velocity", True):
                vx, vy = trk.velocity if hasattr(trk, "velocity") else (0.0, 0.0)
                if np.hypot(vx, vy) > 0.5:
                    cx, cy = trk.centroid
                    cv2.arrowedLine(
                        annotated,
                        (int(cx), int(cy)),
                        (int(cx + vx * 3), int(cy + vy * 3)),
                        (255, 255, 0),
                        2,
                        tipLength=0.3,
                    )

        # 5. Top Status HUD Bar
        if overlays.get("hud_bar", True):
            uptime = int(time.time() - start_time) if start_time > 0 else 0
            hud_summary = f"CAM: {camera_id} | FPS: {measured_fps:.1f} | TRACKS: {len(tracks)} | TIME: {uptime}s"
            cv2.rectangle(annotated, (0, 0), (w, 24), (15, 23, 42), -1)
            cv2.putText(annotated, hud_summary, (10, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 220, 255), 1)

        # 6. BEV Minimap Picture-in-Picture (PiP) Overlay
        if overlays.get("bev_minimap", False) and homography:
            try:
                pip_size = (160, 160)
                bev_small = homography.render_bev_minimap(
                    tracks,
                    zones=analytics.zones if analytics else None,
                    canvas_size=pip_size,
                    margin=16,
                )
                px, py = w - pip_size[0] - 12, h - pip_size[1] - 12
                if px > 0 and py > 0:
                    annotated[py:py + pip_size[1], px:px + pip_size[0]] = bev_small
                    cv2.rectangle(annotated, (px, py), (px + pip_size[0], py + pip_size[1]), (0, 220, 255), 1)
            except Exception as e:
                logger.debug("BEV PiP overlay error: %s", e)

        return annotated

