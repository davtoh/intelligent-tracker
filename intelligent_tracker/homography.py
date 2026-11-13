#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Ground Plane Homography & Bird's-Eye-View (BEV) Minimap Module.

Provides:
- 4-point perspective transformation between camera image space and metric ground plane.
- Coordinate mapping for track contact points: (x + w/2, y + h) -> (X, Y) in meters or BEV pixels.
- Ground plane polygon projection for zones and boundaries.
- Real-time 2D Bird's-Eye-View (BEV) minimap rendering with metric grid, zones, track positions,
  and kinematic velocity vectors.
- Serialization and persistence of homography calibration profiles.
"""

import logging
from collections.abc import Callable
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger("intelligent_tracker.homography")


class GroundPlaneHomography:
    """
    Computes and applies 2D planar homography between camera image coordinates
    and a metric top-down ground plane (Bird's-Eye-View).
    
    Mathematical Formulation:
    -------------------------
    Given 4 non-collinear source points in camera image space P_src = [(x_i, y_i)]
    and corresponding destination points on the ground plane P_dst = [(X_i, Y_i)],
    the 3x3 homography matrix H satisfies:
        s * [X, Y, 1]^T = H * [x, y, 1]^T
    where s is a scale factor. The cartesian ground coordinates are:
        X = (h_11*x + h_12*y + h_13) / (h_31*x + h_32*y + h_33)
        Y = (h_21*x + h_22*y + h_23) / (h_31*x + h_32*y + h_33)
    
    The inverse homography H_inv maps ground coordinates back to camera pixels:
        s' * [x, y, 1]^T = H_inv * [X, Y, 1]^T
    """

    def __init__(
        self,
        src_points: list[tuple[float, float]] | None = None,
        dst_points: list[tuple[float, float]] | None = None,
        metric_width: float = 10.0,
        metric_height: float = 10.0,
        camera_id: str = "cam_01",
    ):
        """
        :param src_points: 4 camera frame corner points [(x, y), ...]
        :param dst_points: 4 target ground plane points [(X, Y), ...]. If None,
                           defaults to a rectangle [(0,0), (W,0), (W,H), (0,H)].
        :param metric_width: Ground width in meters (or metric units) when dst_points is auto-generated.
        :param metric_height: Ground height in meters (or metric units) when dst_points is auto-generated.
        :param camera_id: Identifier for the associated camera channel.
        """
        self.camera_id = camera_id
        self.metric_width = float(metric_width)
        self.metric_height = float(metric_height)

        self.src_points: np.ndarray | None = None
        self.dst_points: np.ndarray | None = None
        self.H: np.ndarray | None = None
        self.H_inv: np.ndarray | None = None

        if src_points is not None and len(src_points) == 4:
            self.set_calibration(src_points, dst_points, metric_width, metric_height)

    @property
    def is_calibrated(self) -> bool:
        """Returns True if a valid homography matrix has been computed."""
        return self.H is not None and self.H.shape == (3, 3)

    def set_calibration(
        self, src_points: list[tuple[float, float]], dst_points: list[tuple[float, float]] | None = None,
        metric_width: float | None = None, metric_height: float | None = None,
    ):
        """Calculate 3x3 perspective homography matrix from 4 camera points and 4 ground points."""
        if len(src_points) != 4:
            raise ValueError(f"GroundPlaneHomography requires exactly 4 source points, got {len(src_points)}")
        if metric_width is not None:
            self.metric_width = float(metric_width)
        if metric_height is not None:
            self.metric_height = float(metric_height)

        src_arr = np.array(src_points, dtype=np.float32)
        if dst_points is not None and len(dst_points) == 4:
            dst_arr = np.array(dst_points, dtype=np.float32)
        else:
            # Default rectangular ground plane: [top-left, top-right, bottom-right, bottom-left]
            dst_arr = np.array(
                [[0.0, 0.0], [self.metric_width, 0.0], [self.metric_width, self.metric_height], [0.0, self.metric_height]],
                dtype=np.float32,
            )

        # Compute 3x3 perspective transform and inverse homography matrix
        H = cv2.getPerspectiveTransform(src_arr, dst_arr)
        ret, H_inv = cv2.invert(H)
        if not ret:
            H_inv = np.linalg.pinv(H)

        self.src_points, self.dst_points, self.H, self.H_inv = src_arr, dst_arr, H, H_inv
        logger.info("Homography calibration updated for camera %s (matrix det=%.4f)", self.camera_id, np.linalg.det(H))

    def camera_to_ground(self, point: tuple[float, float]) -> tuple[float, float]:
        """
        Transforms camera image point (x, y) to ground plane (X, Y) via homography.
        
        :param point: (x, y) camera coordinates
        :return: (X, Y) ground coordinates
        """
        if not self.is_calibrated:
            return float(point[0]), float(point[1])

        pt = np.array([[[point[0], point[1]]]], dtype=np.float32)
        dst = cv2.perspectiveTransform(pt, self.H)
        return float(dst[0][0][0]), float(dst[0][0][1])

    def ground_to_camera(self, point: tuple[float, float]) -> tuple[float, float]:
        """
        Transforms ground plane coordinate (X, Y) back to camera image pixel (x, y).
        
        :param point: (X, Y) ground coordinates
        :return: (x, y) camera coordinates
        """
        if not self.is_calibrated or self.H_inv is None:
            return float(point[0]), float(point[1])

        pt = np.array([[[point[0], point[1]]]], dtype=np.float32)
        dst = cv2.perspectiveTransform(pt, self.H_inv)
        return float(dst[0][0][0]), float(dst[0][0][1])

    def track_to_ground(self, bbox: tuple[float, float, float, float]) -> tuple[float, float]:
        """
        Maps a bounding box (x, y, w, h) to ground plane by taking its bottom-center
        contact point: (x + w/2, y + h).
        
        :param bbox: (x, y, w, h)
        :return: (X, Y) on ground plane
        """
        x, y, w, h = bbox
        contact_x = x + (w / 2.0)
        contact_y = y + h
        return self.camera_to_ground((contact_x, contact_y))

    def transform_polygon(self, polygon: list[tuple[float, float]]) -> list[tuple[float, float]]:
        """
        Transforms a sequence of 2D polygon vertices from camera space to ground space.
        
        :param polygon: List of (x, y) vertices
        :return: List of transformed (X, Y) vertices
        """
        if not self.is_calibrated or not polygon:
            return list(polygon)

        pts = np.array([polygon], dtype=np.float32)
        dst = cv2.perspectiveTransform(pts, self.H)
        return [(float(p[0]), float(p[1])) for p in dst[0]]

    def render_bev_minimap(
        self,
        tracks: dict[int, Any],
        zones: dict[str, Any] | None = None,
        canvas_size: tuple[int, int] = (400, 400),
        margin: int = 40,
    ) -> np.ndarray:
        """
        Renders a 2D top-down Bird's-Eye-View (BEV) minimap image.
        
        :param tracks: Dictionary of active Track objects (or dicts containing bbox, label, id, velocity)
        :param zones: Dictionary of ZoneROI objects or zone dictionaries with polygon vertices
        :param canvas_size: Output image resolution (width, height)
        :param margin: Border padding in pixels
        :return: BGR numpy image of the minimap
        """
        cw, ch = canvas_size
        canvas = np.full((ch, cw, 3), (15, 23, 42), dtype=np.uint8)
        gw = max(self.metric_width, 1.0)
        gh = max(self.metric_height, 1.0)
        scale_x = (cw - 2 * margin) / gw
        scale_y = (ch - 2 * margin) / gh

        def ground_to_canvas(gx: float, gy: float) -> tuple[int, int]:
            cx = int(margin + (gx * scale_x))
            cy = int(margin + (gy * scale_y))
            return max(0, min(cw - 1, cx)), max(0, min(ch - 1, cy))

        _draw_bev_grid(canvas, self.camera_id, gw, gh, margin, ground_to_canvas)
        if zones:
            _draw_bev_zones(canvas, zones, self.transform_polygon, ground_to_canvas)
        _draw_bev_tracks(canvas, tracks, self, ground_to_canvas)
        return canvas

    def to_dict(self) -> dict[str, Any]:
        """Serializes calibration data to dictionary."""
        return {
            "camera_id": self.camera_id,
            "metric_width": self.metric_width,
            "metric_height": self.metric_height,
            "src_points": self.src_points.tolist() if self.src_points is not None else [],
            "dst_points": self.dst_points.tolist() if self.dst_points is not None else [],
            "homography_matrix": self.H.tolist() if self.H is not None else [],
            "is_calibrated": self.is_calibrated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GroundPlaneHomography":
        """Instantiates GroundPlaneHomography from dictionary."""
        inst = cls(
            camera_id=data.get("camera_id", "cam_01"),
            metric_width=data.get("metric_width", 10.0),
            metric_height=data.get("metric_height", 10.0),
        )
        src, dst = data.get("src_points"), data.get("dst_points")
        if src and len(src) == 4:
            inst.set_calibration(src_points=src, dst_points=dst, metric_width=data.get("metric_width", 10.0), metric_height=data.get("metric_height", 10.0))
        return inst


def _draw_bev_grid(
    canvas: np.ndarray, camera_id: str, gw: float, gh: float, margin: int,
    ground_to_canvas: Callable[[float, float], tuple[int, int]],
) -> None:
    """Draw metric border, grid lines, ticks, and header title on BEV canvas."""
    ch, cw = canvas.shape[:2]
    cv2.rectangle(canvas, (margin, margin), (cw - margin, ch - margin), (51, 65, 85), 1)
    steps_x = max(2, int(gw / 2.0))
    for step in range(1, steps_x):
        gx = step * (gw / steps_x)
        pt1, pt2 = ground_to_canvas(gx, 0), ground_to_canvas(gx, gh)
        cv2.line(canvas, pt1, pt2, (30, 41, 59), 1)
        cv2.putText(canvas, f"{gx:.1f}m", (pt1[0] - 12, ch - margin + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (100, 116, 139), 1)

    steps_y = max(2, int(gh / 2.0))
    for step in range(1, steps_y):
        gy = step * (gh / steps_y)
        pt1, pt2 = ground_to_canvas(0, gy), ground_to_canvas(gw, gy)
        cv2.line(canvas, pt1, pt2, (30, 41, 59), 1)
        cv2.putText(canvas, f"{gy:.1f}m", (4, pt1[1] + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (100, 116, 139), 1)

    cv2.putText(canvas, f"BEV Minimap: {camera_id} ({gw:.1f}m x {gh:.1f}m)", (margin, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 220, 255), 1)


def _draw_bev_zones(
    canvas: np.ndarray, zones: dict[str, Any],
    transform_polygon: Callable[[list[tuple[float, float]]], list[tuple[float, float]]],
    ground_to_canvas: Callable[[float, float], tuple[int, int]],
) -> None:
    """Project and draw translucent polygonal zones and labels onto BEV canvas."""
    for z_name, zone in zones.items():
        poly_cam = zone.get("polygon") if isinstance(zone, dict) else getattr(zone, "polygon", None)
        if poly_cam is None:
            continue
        if hasattr(poly_cam, "tolist"):
            poly_cam = poly_cam.tolist()
        canvas_pts = [ground_to_canvas(gx, gy) for gx, gy in transform_polygon(poly_cam)]
        if len(canvas_pts) < 3:
            continue
        pts_arr = np.array(canvas_pts, dtype=np.int32).reshape((-1, 1, 2))
        z_overlay = canvas.copy()
        color = tuple(zone["color"]) if isinstance(zone, dict) and "color" in zone else getattr(zone, "color", (0, 200, 100))
        cv2.fillPoly(z_overlay, [pts_arr], color)
        cv2.addWeighted(z_overlay, 0.2, canvas, 0.8, 0, canvas)
        cv2.polylines(canvas, [pts_arr], True, color, 1)
        moments = cv2.moments(pts_arr)
        cx, cy = (int(moments["m10"] / moments["m00"]), int(moments["m01"] / moments["m00"])) if moments["m00"] != 0 else canvas_pts[0]
        cv2.putText(canvas, str(z_name), (cx - 20, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)


def _draw_single_bev_track(
    canvas: np.ndarray, tid: Any, trk: Any, homography: GroundPlaneHomography,
    ground_to_canvas: Callable[[float, float], tuple[int, int]],
) -> None:
    """Render one tracked object dot, velocity arrow, and label on BEV canvas."""
    bbox = trk.get("bbox") if isinstance(trk, dict) else getattr(trk, "bbox", None)
    if bbox is None:
        return
    gx, gy = homography.track_to_ground(bbox)
    cx, cy = ground_to_canvas(gx, gy)
    cat = trk.get("category", "person") if isinstance(trk, dict) else getattr(trk, "category", "person")
    dot_color = (0, 0, 255) if cat == "restricted" else ((0, 215, 255) if cat == "vip" else (0, 255, 0))
    cv2.circle(canvas, (cx, cy), 5, dot_color, -1)
    cv2.circle(canvas, (cx, cy), 7, (255, 255, 255), 1)

    vel = trk.get("velocity", (0.0, 0.0)) if isinstance(trk, dict) else getattr(trk, "velocity", (0.0, 0.0))
    vx, vy = float(vel[0]), float(vel[1])
    if np.hypot(vx, vy) > 0.5:
        tgx, tgy = homography.camera_to_ground((bbox[0] + bbox[2] / 2.0 + vx * 2.0, bbox[1] + bbox[3] + vy * 2.0))
        cv2.arrowedLine(canvas, (cx, cy), ground_to_canvas(tgx, tgy), (255, 255, 0), 1, tipLength=0.3)

    name = (trk.get("entity_name") if isinstance(trk, dict) else getattr(trk, "entity_name", None)) or f"#{tid}"
    cv2.putText(canvas, f"{name} ({gx:.1f}m, {gy:.1f}m)", (cx + 8, cy + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (226, 232, 240), 1)


def _draw_bev_tracks(
    canvas: np.ndarray, tracks: dict[int, Any], homography: GroundPlaneHomography,
    ground_to_canvas: Callable[[float, float], tuple[int, int]],
) -> None:
    """Render all tracked entities onto the BEV canvas."""
    for tid, trk in tracks.items():
        _draw_single_bev_track(canvas, tid, trk, homography, ground_to_canvas)
