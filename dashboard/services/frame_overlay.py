#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Frame Overlay Renderer Service.
Renders computer vision HUD annotations, bounding boxes, dwell timers,
velocity vectors, zone polygons, and BEV minimap overlays onto video frames.
"""

import logging
import time
from typing import Any, Dict, Optional
import cv2
import numpy as np

logger = logging.getLogger(__name__)


def _draw_heatmap_layer(
    annotated: np.ndarray, analytics: Any, overlays: Dict[str, bool], draw_heatmap: bool
) -> np.ndarray:
    """Render spatial occupancy heatmap when enabled and available."""
    if not ((draw_heatmap or overlays.get("heatmap", False)) and analytics):
        return annotated
    heatmap = getattr(analytics, "heatmap", None)
    if heatmap is None:
        return annotated
    try:
        return heatmap.draw(annotated, alpha=0.55)
    except Exception as e:
        logger.debug("Heatmap overlay rendering error: %s", e)
        return annotated


def _draw_zones_layer(annotated: np.ndarray, analytics: Any, overlays: Dict[str, bool]) -> None:
    """Render analytics zone polygons, fills, and centroid occupancy tags."""
    if not (overlays.get("zones", True) and analytics):
        return
    for zone in list(analytics.zones.values()):
        pts = zone.polygon.reshape((-1, 1, 2)).astype(np.int32)
        z_col = (0, 0, 255) if getattr(zone, "_threshold_breached", False) else zone.color
        overlay = annotated.copy()
        cv2.fillPoly(overlay, [pts], z_col)
        cv2.addWeighted(overlay, 0.25, annotated, 0.75, 0, annotated)
        cv2.polylines(annotated, [pts], True, z_col, 2)
        # Centroid computation via spatial moments: cx = M10/M00, cy = M01/M00
        M = cv2.moments(pts)
        if M["m00"] != 0:
            cx, cy = int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"])
        else:
            cx, cy = int(pts[0][0][0]), int(pts[0][0][1])
        cap_text = f"/{zone.capacity_limit}" if getattr(zone, "capacity_limit", None) else ""
        tag = f"{zone.name} [{zone.occupancy}{cap_text}]"
        cv2.putText(annotated, tag, (cx - 30, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)


def _draw_tripwires_layer(annotated: np.ndarray, analytics: Any, overlays: Dict[str, bool]) -> None:
    """Render analytics tripwire segments and passage counters."""
    if not (overlays.get("tripwires", True) and analytics):
        return
    for tw in list(analytics.tripwires.values()):
        p1, p2 = tw.line_segment
        ip1, ip2 = (int(round(p1[0])), int(round(p1[1]))), (int(round(p2[0])), int(round(p2[1])))
        cv2.line(annotated, ip1, ip2, tw.color, 2)
        mid = ((ip1[0] + ip2[0]) // 2, (ip1[1] + ip2[1]) // 2)
        tw_tag = f"{tw.name}: IN={tw.in_count} OUT={tw.out_count}"
        cv2.putText(annotated, tw_tag, (mid[0] + 5, mid[1] - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, tw.color, 1)


def _resolve_track_color(trk: Any, rsac_manager: Optional[Any]) -> tuple[int, int, int]:
    """Resolve BGR bounding-box color from RSAC category and track state."""
    color = (0, 255, 0)
    cat_id = getattr(trk, "category", "person")
    if rsac_manager:
        cat_obj = rsac_manager.get_category(cat_id)
        if cat_obj and cat_obj.color:
            hex_c = cat_obj.color.lstrip("#")
            if len(hex_c) == 6:
                color = (int(hex_c[4:6], 16), int(hex_c[2:4], 16), int(hex_c[0:2], 16))
    if getattr(trk, "category", None) == "restricted":
        return (0, 0, 255)
    if getattr(trk, "category", None) == "vip":
        return (0, 215, 255)
    if trk.state == "predicting":
        return (255, 165, 0)
    return color


def _draw_single_track(
    annotated: np.ndarray, tid: int, trk: Any, overlays: Dict[str, bool], rsac_manager: Optional[Any]
) -> None:
    """Render bounding box, clutter warning, ID/dwell label, and velocity vector."""
    bx, by, bw, bh = trk.bbox
    color = _resolve_track_color(trk, rsac_manager)
    if overlays.get("bboxes", True):
        cv2.rectangle(annotated, (bx, by), (bx + bw, by + bh), color, 2)
    if getattr(trk, "is_cluttered", False) and overlays.get("clutter", True):
        partner_info = f" with #{trk.clutter_partner_id}" if getattr(trk, "clutter_partner_id", None) else ""
        cv2.putText(annotated, f"[CLUTTER{partner_info}]", (bx, by + bh + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 140, 255), 2)
    if overlays.get("track_ids", True):
        name_disp = getattr(trk, "entity_name", None) or getattr(trk, "identity_label", None) or f"#{tid}"
        dwell_str = f" [{trk.dwell_time:.1f}s]" if overlays.get("dwell_timers", True) else ""
        cv2.putText(annotated, f"{name_disp} ({trk.confidence:.2f}){dwell_str}", (bx, max(15, by - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    if overlays.get("velocity", True):
        vx, vy = trk.velocity if hasattr(trk, "velocity") else (0.0, 0.0)
        if float(np.hypot(vx, vy)) > 0.5:
            cx, cy = trk.centroid
            cv2.arrowedLine(annotated, (int(cx), int(cy)), (int(cx + vx * 3), int(cy + vy * 3)), (255, 255, 0), 2, tipLength=0.3)


def _draw_hud_and_bev(
    annotated: np.ndarray, tracks: Dict[int, Any], overlays: Dict[str, bool], camera_id: str,
    measured_fps: float, start_time: float, analytics: Optional[Any], homography: Optional[Any],
) -> None:
    """Render top status HUD bar and optional BEV minimap PiP overlay."""
    h, w = annotated.shape[:2]
    if overlays.get("hud_bar", True):
        uptime = int(time.time() - start_time)
        hud_summary = f"CAM: {camera_id} | FPS: {measured_fps:.1f} | TRACKS: {len(tracks)} | TIME: {uptime}s"
        cv2.rectangle(annotated, (0, 0), (w, 24), (15, 23, 42), -1)
        cv2.putText(annotated, hud_summary, (10, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 220, 255), 1)
    if overlays.get("bev_minimap", False) and homography:
        try:
            pip_size = (160, 160)
            bev_small = homography.render_bev_minimap(
                tracks, zones=analytics.zones if analytics else None, canvas_size=pip_size, margin=16
            )
            px, py = w - pip_size[0] - 12, h - pip_size[1] - 12
            if px > 0 and py > 0:
                annotated[py : py + pip_size[1], px : px + pip_size[0]] = bev_small
                cv2.rectangle(annotated, (px, py), (px + pip_size[0], py + pip_size[1]), (0, 220, 255), 1)
        except Exception as e:
            logger.debug("BEV minimap overlay error: %s", e)


class FrameOverlayRenderer:
    """
    Renders visual HUD annotations, analytics polygons, tracking labels,
    and Bird's-Eye-View (BEV) minimap picture-in-picture onto raw BGR video frames.
    """

    @staticmethod
    def render(
        frame: np.ndarray,
        tracks: Dict[int, Any],
        overlays: Dict[str, bool],
        camera_id: str,
        measured_fps: float,
        start_time: float,
        analytics: Optional[Any] = None,
        rsac_manager: Optional[Any] = None,
        homography: Optional[Any] = None,
        draw_heatmap: bool = False,
    ) -> np.ndarray:
        """Render configured visual overlays onto a copy of the video frame."""
        annotated = frame.copy()
        annotated = _draw_heatmap_layer(annotated, analytics, overlays, draw_heatmap)
        _draw_zones_layer(annotated, analytics, overlays)
        _draw_tripwires_layer(annotated, analytics, overlays)
        for tid, trk in list(tracks.items()):
            _draw_single_track(annotated, tid, trk, overlays, rsac_manager)
        _draw_hud_and_bev(annotated, tracks, overlays, camera_id, measured_fps, start_time, analytics, homography)
        return annotated

