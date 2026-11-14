"""Global 2D world coordinate projection fusing per-camera homography and rigid world pose."""

from copy import deepcopy
from dataclasses import dataclass
import json
import math
import threading
from typing import Any

import cv2
import numpy as np

from intelligent_tracker.homography import GroundPlaneHomography
from intelligent_tracker.world.nodes import CameraNode


@dataclass
class CameraWorldPose:
    """
    2D rigid world pose anchoring a camera's local ground plane in global world meters.

    Mathematical Formulation:
    -------------------------
    Given local metric ground coordinates (X_local, Y_local), scale s > 0, yaw angle
    theta = radians(yaw_deg), and world origin (X_0, Y_0):

        [X_global]   [cos(theta)  -sin(theta)] [s * X_local]   [X_0]
        [Y_global] = [sin(theta)   cos(theta)] [s * Y_local] + [Y_0]
    """

    camera_id: str
    origin_x: float = 0.0
    origin_y: float = 0.0
    yaw_deg: float = 0.0
    scale: float = 1.0

    def __post_init__(self) -> None:
        self.origin_x = float(self.origin_x)
        self.origin_y = float(self.origin_y)
        self.yaw_deg = float(self.yaw_deg)
        self.scale = float(self.scale)
        if self.scale <= 0.0:
            raise ValueError(f"CameraWorldPose.scale must be > 0, got {self.scale}")

    def to_global(self, local_xy: tuple[float, float]) -> tuple[float, float]:
        """Transform local metric ground (X_local, Y_local) into global (X_global, Y_global)."""
        lx = float(local_xy[0]) * self.scale
        ly = float(local_xy[1]) * self.scale
        theta = math.radians(self.yaw_deg)
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        return ((cos_t * lx - sin_t * ly) + self.origin_x, (sin_t * lx + cos_t * ly) + self.origin_y)

    def to_local(self, global_xy: tuple[float, float]) -> tuple[float, float]:
        """Inverse rigid transform from global world (X_global, Y_global) to local metric (X_local, Y_local)."""
        dx = float(global_xy[0]) - self.origin_x
        dy = float(global_xy[1]) - self.origin_y
        theta = math.radians(self.yaw_deg)
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        return ((cos_t * dx + sin_t * dy) / self.scale, (-sin_t * dx + cos_t * dy) / self.scale)


def homography_from_matrix(matrix: list[list[float]], camera_id: str = "cam_01") -> GroundPlaneHomography:
    """Construct a GroundPlaneHomography directly from a 3x3 perspective matrix."""
    H = np.asarray(matrix, dtype=np.float64)
    if H.shape != (3, 3):
        raise ValueError(f"Expected 3x3 homography matrix, got {H.shape}")
    ret, H_inv = cv2.invert(H)
    if not ret:
        H_inv = np.linalg.pinv(H)
    homo = GroundPlaneHomography(camera_id=camera_id)
    homo.H = H
    homo.H_inv = H_inv
    return homo


def project_bbox_from_camera_node(
    camera_node: CameraNode,
    bbox: tuple[float, ...] | list[float],
) -> tuple[float, float] | None:
    """Project a bounding box bottom-center using CameraNode homography and world_pose."""
    if len(bbox) < 4:
        return None
    profile = camera_node.extra.get("homography_profile") if isinstance(camera_node.extra, dict) else None
    homo: GroundPlaneHomography | None = None
    if isinstance(profile, dict) and profile.get("src_points"):
        homo = GroundPlaneHomography.from_dict(profile)
    elif camera_node.homography is not None:
        homo = homography_from_matrix(camera_node.homography, camera_id=camera_node.camera_id)

    has_pose = tuple(camera_node.world_pose) != (0.0, 0.0, 0.0)
    if homo is None and not has_pose:
        return None

    x, y, w, h = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
    local_xy = homo.track_to_ground((x, y, w, h)) if homo is not None else (x + w / 2.0, y + h)
    pose = CameraWorldPose(
        camera_id=camera_node.camera_id,
        origin_x=camera_node.world_pose[0],
        origin_y=camera_node.world_pose[1],
        yaw_deg=camera_node.world_pose[2],
    )
    return pose.to_global(local_xy)


class GlobalCoordinateMapper:
    """Thread-safe mapper fusing per-camera homography and world pose into global (X, Y) meters."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._homographies: dict[str, GroundPlaneHomography] = {}
        self._poses: dict[str, CameraWorldPose] = {}

    def register_camera(
        self,
        camera_id: str,
        homography: GroundPlaneHomography | None = None,
        pose: CameraWorldPose | None = None,
    ) -> None:
        """Register or update a camera's homography and/or global 2D world pose."""
        if not camera_id:
            raise ValueError("camera_id must be non-empty")
        with self._lock:
            if homography is not None:
                self._homographies[camera_id] = homography
            if pose is not None:
                if pose.camera_id and pose.camera_id != camera_id:
                    raise ValueError(f"Pose camera_id '{pose.camera_id}' does not match '{camera_id}'")
                stored_pose = deepcopy(pose)
                stored_pose.camera_id = camera_id
                self._poses[camera_id] = stored_pose
            elif camera_id not in self._poses:
                self._poses[camera_id] = CameraWorldPose(camera_id=camera_id)

    def set_pose(self, pose: CameraWorldPose) -> None:
        """Set or replace the CameraWorldPose for pose.camera_id."""
        if not pose.camera_id:
            raise ValueError("CameraWorldPose.camera_id must be non-empty")
        with self._lock:
            self._poses[pose.camera_id] = deepcopy(pose)

    def get_pose(self, camera_id: str) -> CameraWorldPose | None:
        """Return an isolated copy of the CameraWorldPose for camera_id, if registered."""
        with self._lock:
            pose = self._poses.get(camera_id)
            return deepcopy(pose) if pose is not None else None

    def get_homography(self, camera_id: str) -> GroundPlaneHomography | None:
        """Return the registered GroundPlaneHomography for camera_id, if present."""
        with self._lock:
            return self._homographies.get(camera_id)

    def has_camera(self, camera_id: str) -> bool:
        """Return True if camera_id has a registered homography or world pose."""
        with self._lock:
            return camera_id in self._homographies or camera_id in self._poses

    def camera_to_global(self, camera_id: str, point: tuple[float, float]) -> tuple[float, float]:
        """Project camera pixel (u, v) -> local metric ground -> global world (X, Y) meters."""
        with self._lock:
            homo = self._homographies.get(camera_id)
            pose = deepcopy(self._poses.get(camera_id))
        local_xy = homo.camera_to_ground(point) if homo is not None else (float(point[0]), float(point[1]))
        return pose.to_global(local_xy) if pose is not None else local_xy

    def global_to_camera(self, camera_id: str, point: tuple[float, float]) -> tuple[float, float]:
        """Inverse-project global world (X, Y) meters -> local metric -> camera pixel (u, v)."""
        with self._lock:
            homo = self._homographies.get(camera_id)
            pose = deepcopy(self._poses.get(camera_id))
        local_xy = pose.to_local(point) if pose is not None else (float(point[0]), float(point[1]))
        return homo.ground_to_camera(local_xy) if homo is not None else local_xy

    def project_track_bbox(
        self,
        camera_id: str,
        bbox: tuple[float, float, float, float] | list[float],
    ) -> tuple[float, float]:
        """Project bounding box (x, y, w, h) bottom-center contact point into global (X, Y) meters."""
        if len(bbox) < 4:
            raise ValueError(f"Expected 4-element bbox (x, y, w, h), got {bbox!r}")
        x, y, w, h = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
        return self.camera_to_global(camera_id, (x + (w / 2.0), y + h))

    def project_polygon(
        self,
        camera_id: str,
        polygon: list[tuple[float, float]],
    ) -> list[tuple[float, float]]:
        """Project a list of camera pixel polygon vertices into global world (X, Y) meters."""
        if not polygon:
            return []
        with self._lock:
            homo = self._homographies.get(camera_id)
            pose = deepcopy(self._poses.get(camera_id))
        local_pts = homo.transform_polygon(polygon) if homo is not None else [(float(p[0]), float(p[1])) for p in polygon]
        return [pose.to_global(pt) for pt in local_pts] if pose is not None else local_pts


def sync_homography_to_world(
    world_graph: Any,
    coordinate_mapper: GlobalCoordinateMapper | None,
    camera_id: str,
    homo: GroundPlaneHomography,
) -> None:
    """Register a calibrated homography on attached WorldGraph CameraNode and GlobalCoordinateMapper."""
    if not homo.is_calibrated:
        return
    if coordinate_mapper is not None:
        coordinate_mapper.register_camera(camera_id, homography=homo)
    if world_graph is not None:
        existing = world_graph.get_node(camera_id, node_type="camera")
        extra = dict(existing.extra) if isinstance(existing, CameraNode) else {}
        extra["homography_profile"] = homo.to_dict()
        cam = existing if isinstance(existing, CameraNode) else CameraNode(camera_id=camera_id, name=camera_id)
        cam.homography = homo.H.tolist() if homo.H is not None else None
        cam.extra = extra
        world_graph.register_camera(cam)
        graph_mapper = getattr(world_graph, "coordinate_mapper", None)
        if graph_mapper is not None and graph_mapper is not coordinate_mapper:
            graph_mapper.register_camera(camera_id, homography=homo)


def sync_loaded_homographies_to_world(
    world_graph: Any,
    coordinate_mapper: GlobalCoordinateMapper | None,
    cameras: dict[str, dict[str, Any]],
) -> None:
    """Sync all calibrated camera homographies into attached WorldGraph and GlobalCoordinateMapper."""
    if world_graph is None and coordinate_mapper is None:
        return
    for cam_id, entry in cameras.items():
        homo = entry.get("homography")
        if isinstance(homo, GroundPlaneHomography) and homo.is_calibrated:
            sync_homography_to_world(world_graph, coordinate_mapper, cam_id, homo)


def compute_hop_global_path(
    camera_id: str, sightings: list[dict[str, Any]], coordinate_mapper: Any = None, homographies: dict[str, Any] | None = None,
) -> list[tuple[float, float]]:
    """Project sighting bounding boxes to global (X, Y) meters when mapper or homography exists."""
    use_mapper = coordinate_mapper is not None and coordinate_mapper.has_camera(camera_id)
    homo = homographies.get(camera_id) if homographies else None
    if not use_mapper and (homo is None or not getattr(homo, "is_calibrated", False)):
        return []
    path: list[tuple[float, float]] = []
    for s in sightings:
        raw = s.get("bbox")
        if not raw:
            continue
        try:
            vals = [float(v) for v in (json.loads(raw) if isinstance(raw, str) else raw)]
        except Exception:
            continue
        if len(vals) >= 4:
            gx, gy = coordinate_mapper.project_track_bbox(camera_id, vals) if use_mapper else homo.track_to_ground(tuple(vals[:4]))
            path.append((round(float(gx), 4), round(float(gy), 4)))
    return path
