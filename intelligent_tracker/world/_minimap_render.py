"""OpenCV BEV rendering and world-bounds helpers for WorldTacticalMinimap."""

import math
from typing import Any

import cv2
import numpy as np


def compute_world_bounds(
    cameras: list[dict[str, Any]],
    zones: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    default_bounds: tuple[float, float, float, float],
) -> dict[str, float]:
    """Compute padded global metric bounding box covering all world features."""
    xs, ys = [], []
    for cam in cameras:
        pose = cam["world_pose"]
        xs.append(pose["origin_x"]); ys.append(pose["origin_y"])
        for pt in cam.get("fov_corners_global", []):
            xs.append(pt[0]); ys.append(pt[1])
    for zone in zones:
        for pt in zone.get("global_polygon", []):
            xs.append(pt[0]); ys.append(pt[1])
    for ent in entities:
        if ent.get("global_xy") is not None:
            xs.append(ent["global_xy"][0]); ys.append(ent["global_xy"][1])
        for pt in ent.get("global_trajectory", []):
            xs.append(pt[0]); ys.append(pt[1])
    if not xs or not ys:
        min_x, min_y, max_x, max_y = default_bounds
    else:
        min_x, max_x = min(xs) - 1.5, max(xs) + 1.5
        min_y, max_y = min(ys) - 1.5, max(ys) + 1.5
        if (max_x - min_x) < 5.0:
            mid_x = 0.5 * (min_x + max_x)
            min_x, max_x = mid_x - 2.5, mid_x + 2.5
        if (max_y - min_y) < 5.0:
            mid_y = 0.5 * (min_y + max_y)
            min_y, max_y = mid_y - 2.5, mid_y + 2.5
    return {
        "min_x": round(min_x, 3), "max_x": round(max_x, 3),
        "min_y": round(min_y, 3), "max_y": round(max_y, 3),
        "width_m": round(max_x - min_x, 3), "height_m": round(max_y - min_y, 3),
    }


def draw_world_grid(canvas: np.ndarray, bounds: dict[str, float], margin: int, to_px: Any) -> None:
    """Render background metric grid and title header onto world minimap canvas."""
    ch, cw = canvas.shape[:2]
    cv2.rectangle(canvas, (margin, margin), (cw - margin, ch - margin), (51, 65, 85), 1)
    for i in range(1, 5):
        gx = bounds["min_x"] + (bounds["width_m"] * i / 5.0)
        gy = bounds["min_y"] + (bounds["height_m"] * i / 5.0)
        cv2.line(canvas, to_px(gx, bounds["min_y"]), to_px(gx, bounds["max_y"]), (30, 41, 59), 1)
        cv2.line(canvas, to_px(bounds["min_x"], gy), to_px(bounds["max_x"], gy), (30, 41, 59), 1)
    title = f"World Tactical Minimap ({bounds['width_m']:.1f}m x {bounds['height_m']:.1f}m)"
    cv2.putText(canvas, title, (margin, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (56, 189, 248), 1)


def draw_world_zones_and_transitions(
    canvas: np.ndarray, zones: list[dict[str, Any]], transitions: list[dict[str, Any]], to_px: Any,
) -> None:
    """Render projected global zone polygons and directed transition arrows."""
    for zone in zones:
        pts = [to_px(p[0], p[1]) for p in zone.get("global_polygon", [])]
        if len(pts) >= 3:
            arr = np.array(pts, dtype=np.int32).reshape((-1, 1, 2))
            color = (0, 80, 235) if zone.get("restricted") else (16, 185, 129)
            cv2.polylines(canvas, [arr], True, color, 1)
            cv2.putText(canvas, zone["name"], pts[0], cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1)
    for tr in transitions:
        if tr.get("source_xy") and tr.get("target_xy"):
            cv2.arrowedLine(canvas, to_px(*tr["source_xy"]), to_px(*tr["target_xy"]), (250, 204, 21), 1, tipLength=0.15)


def draw_world_cameras_and_entities(
    canvas: np.ndarray, cameras: list[dict[str, Any]], entities: list[dict[str, Any]], to_px: Any,
) -> None:
    """Render calibrated camera origins/FOVs and live entity positions + trails."""
    for cam in cameras:
        ox, oy = cam["world_pose"]["origin_x"], cam["world_pose"]["origin_y"]
        yaw = math.radians(cam["world_pose"]["yaw_deg"])
        px, py = to_px(ox, oy)
        cv2.drawMarker(canvas, (px, py), (56, 189, 248), cv2.MARKER_TRIANGLE_UP, 10, 1)
        cv2.arrowedLine(canvas, (px, py), to_px(ox + math.cos(yaw) * 1.5, oy + math.sin(yaw) * 1.5), (56, 189, 248), 1, tipLength=0.25)
        cv2.putText(canvas, cam["camera_id"], (px + 6, py - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (148, 163, 184), 1)
        fov = [to_px(p[0], p[1]) for p in cam.get("fov_corners_global", [])]
        if len(fov) >= 3:
            cv2.polylines(canvas, [np.array(fov, dtype=np.int32).reshape((-1, 1, 2))], True, (71, 85, 105), 1)
    for ent in entities:
        color = (0, 0, 255) if ent.get("restricted") else ((0, 215, 255) if ent.get("category") == "vip" else (34, 197, 94))
        trail = [to_px(pt[0], pt[1]) for pt in ent.get("global_trajectory", [])]
        if len(trail) >= 2:
            cv2.polylines(canvas, [np.array(trail, dtype=np.int32).reshape((-1, 1, 2))], False, color, 2)
        if ent.get("global_xy") is not None:
            ex, ey = to_px(ent["global_xy"][0], ent["global_xy"][1])
            cv2.circle(canvas, (ex, ey), 5, color, -1)
            cv2.circle(canvas, (ex, ey), 7, (255, 255, 255), 1)
            cv2.putText(canvas, ent.get("name") or ent["world_entity_id"], (ex + 8, ey + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (241, 245, 249), 1)

