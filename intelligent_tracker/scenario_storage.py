#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Scenario persistence, YAML/SQLite serialization, and WorldGraph sync helpers."""

import logging
import os
from collections.abc import Callable
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.geometry import Tripwire, ZoneROI
from intelligent_tracker.homography import GroundPlaneHomography
from intelligent_tracker.topology import CrossCameraTopology, SpatialTransitionLink
from intelligent_tracker.world import TripwireNode, WorldGraph, ZoneNode
from intelligent_tracker.world.coordinates import sync_loaded_homographies_to_world

logger = logging.getLogger("intelligent_tracker.scenarios")


def sync_zone_to_world(
    world_graph: WorldGraph | None, camera_id: str, name: str,
    polygon: list[list[float] | tuple[float, float]], capacity_limit: int | None,
) -> None:
    """Register or update a ZoneNode in an attached WorldGraph."""
    if world_graph is not None and len(polygon) >= 3:
        pts = [(float(pt[0]), float(pt[1])) for pt in polygon]
        world_graph.register_zone(ZoneNode(zone_id=name, camera_id=camera_id, name=name, points=pts, max_occupancy=capacity_limit))


def sync_tripwire_to_world(
    world_graph: WorldGraph | None, camera_id: str, name: str,
    line_segment: list[list[float] | tuple[float, float]], bidirectional: bool,
) -> None:
    """Register or update a TripwireNode in an attached WorldGraph."""
    if world_graph is not None and len(line_segment) >= 2:
        p1, p2 = line_segment[0], line_segment[1]
        world_graph.register_tripwire(
            TripwireNode(tripwire_id=name, camera_id=camera_id, name=name, pt1=(float(p1[0]), float(p1[1])), pt2=(float(p2[0]), float(p2[1])), direction="both" if bidirectional else "in")
        )


def remove_child_from_world(world_graph: WorldGraph | None, camera_id: str, child_kind: str, name: str) -> None:
    """Remove a zone or tripwire node from an attached WorldGraph if present."""
    if world_graph is not None:
        world_graph.remove_node(f"{camera_id}:{child_kind}:{name}")


def _build_zone(zd: dict[str, Any]) -> ZoneROI:
    z = ZoneROI(
        polygon=zd["polygon"], name=zd["name"], dwell_threshold=zd.get("dwell_threshold", 5.0),
        capacity_limit=zd.get("capacity_limit"), color=tuple(zd.get("color", (0, 200, 100))),
    )
    z.category_filter = zd.get("category_filter", "")
    return z


def _build_tripwire(td: dict[str, Any]) -> Tripwire:
    return Tripwire(
        line_segment=td["line_segment"], name=td["name"],
        bidirectional=td.get("bidirectional", True), color=tuple(td.get("color", (0, 255, 255))),
    )


def _load_db_zones_and_tripwires(db: TrackerDB, ensure_camera_entry: Callable[[str], dict[str, Any]]) -> bool:
    loaded = False
    for zd in db.get_zones():
        ensure_camera_entry(zd["camera_id"])["zones"][zd["name"]] = _build_zone(zd)
        loaded = True
    for td in db.get_tripwires():
        ensure_camera_entry(td["camera_id"])["tripwires"][td["name"]] = _build_tripwire(td)
        loaded = True
    return loaded


def _load_db_transitions_and_homographies(
    db: TrackerDB, ensure_camera_entry: Callable[[str], dict[str, Any]],
    cameras: dict[str, dict[str, Any]], topology: CrossCameraTopology,
) -> bool:
    loaded = False
    for tr in db.get_spatial_transitions():
        topology.add_link(SpatialTransitionLink.from_dict(tr))
        loaded = True
    for cam_id in list(cameras.keys()) + ["cam_01", "cam_02"]:
        h_data = db.get_homography_calibration(cam_id)
        if h_data:
            ensure_camera_entry(cam_id)["homography"] = GroundPlaneHomography.from_dict(h_data)
            loaded = True
    return loaded


def load_scenarios_from_db(
    db: TrackerDB | None, ensure_camera_entry: Callable[[str], dict[str, Any]],
    cameras: dict[str, dict[str, Any]], topology: CrossCameraTopology,
) -> bool:
    """Load zones, tripwires, transitions, and homographies from SQLite."""
    if not db:
        return False
    try:
        z_ok = _load_db_zones_and_tripwires(db, ensure_camera_entry)
        return _load_db_transitions_and_homographies(db, ensure_camera_entry, cameras, topology) or z_ok
    except Exception as exc:
        logger.warning("Failed loading scenarios from database: %s", exc)
        return False


def _parse_yaml_zones(cam_id: str, zones_data: list[dict[str, Any]], cam_entry: dict[str, Any], db: TrackerDB | None) -> None:
    for zd in zones_data:
        z = _build_zone(zd)
        cam_entry["zones"][zd["name"]] = z
        if db:
            db.save_zone(cam_id, zd["name"], zd["polygon"], z.category_filter, z.dwell_threshold, z.capacity_limit, z.color)


def _parse_yaml_tripwires(cam_id: str, tripwires_data: list[dict[str, Any]], cam_entry: dict[str, Any], db: TrackerDB | None) -> None:
    for td in tripwires_data:
        tw = _build_tripwire(td)
        cam_entry["tripwires"][td["name"]] = tw
        if db:
            db.save_tripwire(cam_id, td["name"], td["line_segment"], tw.bidirectional, tw.color)


def _parse_yaml_homography(cam_id: str, h_cfg: dict[str, Any] | None, cam_entry: dict[str, Any], db: TrackerDB | None) -> None:
    if not h_cfg or "src_points" not in h_cfg:
        return
    homo = GroundPlaneHomography.from_dict({**h_cfg, "camera_id": cam_id})
    cam_entry["homography"] = homo
    if db and homo.is_calibrated:
        db.save_homography_calibration(
            cam_id, homo.src_points.tolist(), homo.dst_points.tolist(),
            homo.H.tolist(), homo.metric_width, homo.metric_height,
        )


def _parse_yaml_transitions(top_links: list[dict[str, Any]], topology: CrossCameraTopology, db: TrackerDB | None) -> None:
    for ld in top_links:
        link = SpatialTransitionLink.from_dict(ld)
        topology.add_link(link)
        if db:
            db.save_spatial_transition(
                link.link_id, link.source_camera, link.source_zone, link.target_camera,
                link.target_zone, link.t_min, link.t_max, link.prior_boost, link.bidirectional, link.active,
            )


def load_scenarios_from_yaml(
    path: str, ensure_camera_entry: Callable[[str], dict[str, Any]],
    db: TrackerDB | None, topology: CrossCameraTopology,
) -> None:
    """Parse scenarios from a YAML file into memory and optional SQLite."""
    if not os.path.exists(path) or yaml is None:
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        for cam_id, c_data in data.get("cameras", {}).items():
            cam_entry = ensure_camera_entry(cam_id)
            _parse_yaml_zones(cam_id, c_data.get("zones", []), cam_entry, db)
            _parse_yaml_tripwires(cam_id, c_data.get("tripwires", []), cam_entry, db)
            _parse_yaml_homography(cam_id, c_data.get("homography"), cam_entry, db)
        _parse_yaml_transitions(data.get("spatial_transitions", []), topology, db)
        logger.info("Loaded scenarios from YAML file: %s", path)
    except Exception as exc:
        logger.error("Error reading scenario YAML %s: %s", path, exc)


def _serialize_camera_entry(c_entry: dict[str, Any]) -> dict[str, Any]:
    zones = [
        {
            "name": z.name, "dwell_threshold": z.dwell_threshold, "color": list(z.color),
            "polygon": z.polygon.tolist() if hasattr(z.polygon, "tolist") else list(z.polygon),
            "capacity_limit": getattr(z, "capacity_limit", None), "category_filter": getattr(z, "category_filter", ""),
        }
        for z in c_entry["zones"].values()
    ]
    tripwires = [
        {
            "name": tw.name, "bidirectional": tw.bidirectional, "color": list(tw.color),
            "line_segment": [list(tw.line_segment[0]), list(tw.line_segment[1])],
        }
        for tw in c_entry["tripwires"].values()
    ]
    homography = c_entry["homography"].to_dict() if c_entry["homography"].is_calibrated else {}
    return {"zones": zones, "tripwires": tripwires, "homography": homography}


def save_scenarios_to_yaml(target_path: str, cameras: dict[str, dict[str, Any]], topology: CrossCameraTopology) -> None:
    """Serialize current in-memory scenarios to a YAML file."""
    if yaml is None:
        return
    export_data = {
        "version": "1.0",
        "cameras": {cid: _serialize_camera_entry(ce) for cid, ce in cameras.items()},
        "spatial_transitions": [l.to_dict() for l in topology.list_links() if not l.link_id.endswith("_rev")],
    }
    os.makedirs(os.path.dirname(os.path.abspath(target_path)) or ".", exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as f:
        yaml.dump(export_data, f, default_flow_style=False, sort_keys=False)
    logger.info("Saved scenarios to YAML: %s", target_path)


class ScenarioStorageMixin:
    """Mixin delegating ScenarioManager storage lifecycle to ``scenario_storage`` helpers."""

    config_path: str
    db: TrackerDB | None
    topology: CrossCameraTopology
    cameras: dict[str, dict[str, Any]]

    def _ensure_camera_entry(self, camera_id: str) -> dict[str, Any]:
        if camera_id not in self.cameras:
            self.cameras[camera_id] = {"zones": {}, "tripwires": {}, "homography": GroundPlaneHomography(camera_id=camera_id)}
        return self.cameras[camera_id]

    def load_scenarios(self) -> None:
        """Load scenarios from SQLite TrackerDB, falling back to YAML if DB is empty."""
        if not load_scenarios_from_db(self.db, self._ensure_camera_entry, self.cameras, self.topology):
            if os.path.exists(self.config_path):
                self.load_from_yaml(self.config_path)
                return
        sync_loaded_homographies_to_world(getattr(self, "world_graph", None), getattr(self, "coordinate_mapper", None), self.cameras)

    def load_from_yaml(self, path: str) -> None:
        """Parse scenarios from a YAML file."""
        load_scenarios_from_yaml(path, self._ensure_camera_entry, self.db, self.topology)
        sync_loaded_homographies_to_world(getattr(self, "world_graph", None), getattr(self, "coordinate_mapper", None), self.cameras)

    def save_to_yaml(self, path: str | None = None) -> None:
        """Serialize current in-memory scenarios to YAML."""
        save_scenarios_to_yaml(path or self.config_path, self.cameras, self.topology)
