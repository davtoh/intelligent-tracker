"""Multi-camera global world tactical minimap telemetry and BEV canvas renderer."""

import time
from typing import Any

import numpy as np

from intelligent_tracker.homography import GroundPlaneHomography
from intelligent_tracker.world._minimap_render import (
    compute_world_bounds,
    draw_world_cameras_and_entities,
    draw_world_grid,
    draw_world_zones_and_transitions,
)
from intelligent_tracker.world.coordinates import (
    CameraWorldPose,
    GlobalCoordinateMapper,
    homography_from_matrix,
)
from intelligent_tracker.world.graph import WorldGraph


def _pose_from_camera(cid: str, cam_snap: dict[str, Any], mapper: GlobalCoordinateMapper | None) -> CameraWorldPose:
    """Resolve CameraWorldPose from GlobalCoordinateMapper or CameraNode snapshot."""
    if mapper is not None:
        pose = mapper.get_pose(cid)
        if pose is not None:
            return pose
    raw_pose = cam_snap.get("world_pose") or (0.0, 0.0, 0.0)
    return CameraWorldPose(camera_id=cid, origin_x=raw_pose[0], origin_y=raw_pose[1], yaw_deg=raw_pose[2])


def _homography_from_camera(cid: str, cam_snap: dict[str, Any], mapper: GlobalCoordinateMapper | None) -> GroundPlaneHomography | None:
    """Resolve GroundPlaneHomography from GlobalCoordinateMapper or CameraNode snapshot."""
    if mapper is not None:
        homo = mapper.get_homography(cid)
        if homo is not None and homo.is_calibrated:
            return homo
    extra = cam_snap.get("extra") or {}
    profile = extra.get("homography_profile") if isinstance(extra, dict) else None
    if isinstance(profile, dict) and profile.get("src_points"):
        return GroundPlaneHomography.from_dict(profile)
    matrix = cam_snap.get("homography")
    return homography_from_matrix(matrix, camera_id=cid) if matrix is not None else None


def _polygon_centroid(pts: list[list[float]] | list[tuple[float, float]]) -> list[float] | None:
    """Compute arithmetic centroid [x, y] of a non-empty 2D point list."""
    if not pts:
        return None
    return [round(sum(p[0] for p in pts) / len(pts), 4), round(sum(p[1] for p in pts) / len(pts), 4)]


class WorldTacticalMinimap:
    """Produces unified multi-camera global world minimap telemetry and OpenCV BEV imagery."""

    def __init__(
        self,
        world_graph: WorldGraph,
        coordinate_mapper: GlobalCoordinateMapper | None = None,
        *,
        default_bounds: tuple[float, float, float, float] = (0.0, 0.0, 20.0, 20.0),
    ) -> None:
        self.world_graph = world_graph
        self.coordinate_mapper = coordinate_mapper or getattr(world_graph, "coordinate_mapper", None)
        self.default_bounds = default_bounds

    def _project_camera_polygon(
        self, camera_id: str, points: list[Any], cam_snap: dict[str, Any],
    ) -> list[list[float]]:
        """Project camera-space polygon points into global world (X, Y) meters."""
        if not points:
            return []
        pts = [(float(p[0]), float(p[1])) for p in points]
        if self.coordinate_mapper is not None and self.coordinate_mapper.has_camera(camera_id):
            return [[round(gx, 4), round(gy, 4)] for gx, gy in self.coordinate_mapper.project_polygon(camera_id, pts)]
        homo = _homography_from_camera(camera_id, cam_snap, self.coordinate_mapper)
        pose = _pose_from_camera(camera_id, cam_snap, self.coordinate_mapper)
        local_pts = homo.transform_polygon(pts) if homo is not None else pts
        return [[round(gx, 4), round(gy, 4)] for gx, gy in (pose.to_global(pt) for pt in local_pts)]

    def _build_cameras_telemetry(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        """Serialize calibrated cameras, rigid world poses, and projected FOV corners."""
        cameras: list[dict[str, Any]] = []
        for cid, cam_snap in sorted(snapshot.get("cameras", {}).items()):
            pose = _pose_from_camera(cid, cam_snap, self.coordinate_mapper)
            homo = _homography_from_camera(cid, cam_snap, self.coordinate_mapper)
            fov_src = homo.src_points.tolist() if homo is not None and homo.src_points is not None else []
            fov_global = self._project_camera_polygon(cid, fov_src, cam_snap) if fov_src else []
            cameras.append({
                "camera_id": cid, "name": cam_snap.get("name") or cid, "enabled": bool(cam_snap.get("enabled", True)),
                "calibrated": homo is not None and homo.is_calibrated,
                "world_pose": {"origin_x": pose.origin_x, "origin_y": pose.origin_y, "yaw_deg": pose.yaw_deg, "scale": pose.scale},
                "fov_corners_global": fov_global,
            })
        return cameras

    def _build_zones_telemetry(
        self, snapshot: dict[str, Any], raw_cameras: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[tuple[str, str], list[float]]]:
        """Serialize global-projected ZoneNodes and return centroid lookup by (camera_id, zone_id)."""
        zones: list[dict[str, Any]] = []
        centroids: dict[tuple[str, str], list[float]] = {}
        for zid, z_snap in sorted(snapshot.get("zones", {}).items()):
            cid = z_snap.get("camera_id", "")
            global_poly = self._project_camera_polygon(cid, z_snap.get("points", []), raw_cameras.get(cid, {}))
            centroid = _polygon_centroid(global_poly)
            if centroid is not None:
                centroids[(cid, z_snap.get("zone_id", zid))] = centroid
            zones.append({
                "node_id": z_snap.get("node_id", zid), "zone_id": z_snap.get("zone_id", zid),
                "camera_id": cid, "name": z_snap.get("name", zid), "restricted": bool(z_snap.get("restricted", False)),
                "active_entity_ids": list(z_snap.get("active_entity_ids", [])), "global_polygon": global_poly,
            })
        return zones, centroids

    def _build_transitions_telemetry(
        self, snapshot: dict[str, Any], zone_centroids: dict[tuple[str, str], list[float]], cam_map: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Serialize directed TransitionEdgeNodes anchored to zone centroids or camera origins."""
        transitions: list[dict[str, Any]] = []
        for tid, tr in sorted(snapshot.get("transitions", {}).items()):
            sc, sz = tr.get("source_camera", ""), tr.get("source_zone", "")
            tc, tz = tr.get("target_camera", ""), tr.get("target_zone", "")
            s_pose = cam_map.get(sc, {}).get("world_pose")
            t_pose = cam_map.get(tc, {}).get("world_pose")
            src_xy = zone_centroids.get((sc, sz)) or ([s_pose["origin_x"], s_pose["origin_y"]] if s_pose else None)
            dst_xy = zone_centroids.get((tc, tz)) or ([t_pose["origin_x"], t_pose["origin_y"]] if t_pose else None)
            transitions.append({
                "link_id": tr.get("link_id", tid), "source_camera": sc, "source_zone": sz,
                "target_camera": tc, "target_zone": tz, "source_xy": src_xy, "target_xy": dst_xy,
                "t_min": tr.get("t_min", 2.0), "t_max": tr.get("t_max", 15.0),
                "prior_boost": tr.get("prior_boost", 0.35), "active": bool(tr.get("active", True)),
            })
        return transitions

    def _build_entities_telemetry(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        """Serialize live WorldEntities with global coordinates and bounded trajectories."""
        entities: list[dict[str, Any]] = []
        for we_id, ent in sorted(snapshot.get("entities", {}).items()):
            gxy = ent.get("global_xy")
            entities.append({
                "world_entity_id": ent.get("world_entity_id", we_id), "entity_id": ent.get("entity_id"),
                "session_id": ent.get("session_id"), "name": ent.get("name", ""), "category": ent.get("category", "unknown"),
                "restricted": bool(ent.get("restricted", False)), "camera_tracks": dict(ent.get("camera_tracks", {})),
                "global_xy": [round(float(gxy[0]), 4), round(float(gxy[1]), 4)] if gxy is not None else None,
                "global_trajectory": [[round(float(p[0]), 4), round(float(p[1]), 4), float(p[2])] for p in ent.get("global_trajectory", [])],
                "active_zones": ent.get("active_zones", {}), "last_seen": ent.get("last_seen"),
            })
        return entities

    def build_world_minimap_telemetry(self) -> dict[str, Any]:
        """Build JSON-serializable global world minimap telemetry from WorldGraph snapshot."""
        snapshot = self.world_graph.snapshot()
        raw_cameras = snapshot.get("cameras", {})
        cameras = self._build_cameras_telemetry(snapshot)
        cam_map = {c["camera_id"]: c for c in cameras}
        zones, centroids = self._build_zones_telemetry(snapshot, raw_cameras)
        transitions = self._build_transitions_telemetry(snapshot, centroids, cam_map)
        entities = self._build_entities_telemetry(snapshot)
        bounds = compute_world_bounds(cameras, zones, entities, self.default_bounds)
        return {
            "timestamp": time.time(), "bounds": bounds, "cameras": cameras,
            "zones": zones, "transitions": transitions, "entities": entities,
            "counts": {"cameras": len(cameras), "zones": len(zones), "transitions": len(transitions), "entities": len(entities)},
        }

    def render_world_minimap(self, canvas_size: tuple[int, int] = (640, 480), margin: int = 40) -> np.ndarray:
        """Render a unified top-down OpenCV BEV canvas across cameras, zones, edges, and entities."""
        telemetry = self.build_world_minimap_telemetry()
        cw, ch = canvas_size
        canvas = np.full((ch, cw, 3), (15, 23, 42), dtype=np.uint8)
        b = telemetry["bounds"]
        sx = (cw - 2 * margin) / max(b["width_m"], 1e-3)
        sy = (ch - 2 * margin) / max(b["height_m"], 1e-3)

        def to_px(gx: float, gy: float) -> tuple[int, int]:
            return (
                max(0, min(cw - 1, int(margin + (gx - b["min_x"]) * sx))),
                max(0, min(ch - 1, int(margin + (gy - b["min_y"]) * sy))),
            )

        draw_world_grid(canvas, b, margin, to_px)
        draw_world_zones_and_transitions(canvas, telemetry["zones"], telemetry["transitions"], to_px)
        draw_world_cameras_and_entities(canvas, telemetry["cameras"], telemetry["entities"], to_px)
        return canvas
