#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Scenario Manager & Spatial Orchestration Module.

Provides:
- Serialization and synchronization of zones, tripwires, homography calibrations,
  and cross-camera topology into 'configs/scenarios.yaml' and SQLite TrackerDB.
- Real-time application of spatial scenarios into active StreamManager pipelines
  without restarting the server.
- High-level scenario CRUD methods for Scenario Studio REST APIs.
- Optional synchronization of zone and tripwire nodes into a scoped WorldGraph.
"""

import logging
from typing import Any

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.geometry import Tripwire, ZoneROI
from intelligent_tracker.homography import GroundPlaneHomography
from intelligent_tracker.scenario_storage import (
    ScenarioStorageMixin,
    remove_child_from_world,
    sync_tripwire_to_world,
    sync_zone_to_world,
)
from intelligent_tracker.topology import CrossCameraTopology
from intelligent_tracker.world import GlobalCoordinateMapper, WorldGraph, WorldTransitionRegistry
from intelligent_tracker.world.coordinates import sync_homography_to_world

logger = logging.getLogger("intelligent_tracker.scenarios")

DEFAULT_SCENARIOS_PATH = "configs/scenarios.yaml"


class ScenarioManager(ScenarioStorageMixin):
    """
    Coordinates spatial scenario configurations across all camera channels,
    bridging interactive web studio actions with live computer vision pipelines,
    YAML configuration files, and SQLite database storage.
    """

    def __init__(
        self,
        config_path: str = DEFAULT_SCENARIOS_PATH,
        db: TrackerDB | None = None,
        db_path: str = "data/tracker.db",
        world_graph: WorldGraph | None = None,
        coordinate_mapper: GlobalCoordinateMapper | None = None,
    ):
        self.config_path = config_path
        self.db = db or TrackerDB(db_path)
        self.world_graph = world_graph
        self.coordinate_mapper = coordinate_mapper or getattr(world_graph, "coordinate_mapper", None) or GlobalCoordinateMapper()
        if world_graph is not None and getattr(world_graph, "coordinate_mapper", None) is None:
            world_graph.coordinate_mapper = self.coordinate_mapper
        self.world_transitions = WorldTransitionRegistry(world_graph, coordinate_mapper=self.coordinate_mapper) if world_graph is not None else None
        self.topology = CrossCameraTopology(world_transitions=self.world_transitions)
        handoff = getattr(world_graph, "handoff_coordinator", None)
        if handoff is not None:
            handoff.topology, handoff.transition_registry = self.topology, self.world_transitions
        self.cameras: dict[str, dict[str, Any]] = {}
        self.load_scenarios()

    def save_zone(
        self,
        camera_id: str,
        name: str,
        polygon: list[list[float] | tuple[float, float]],
        category_filter: str = "",
        dwell_threshold: float = 5.0,
        capacity_limit: int | None = None,
        color: tuple[int, int, int] = (0, 200, 100),
    ) -> ZoneROI:
        """Create or update a zone in memory, DB, and YAML."""
        cam_entry = self._ensure_camera_entry(camera_id)
        z = ZoneROI(
            polygon=polygon,
            name=name,
            dwell_threshold=dwell_threshold,
            capacity_limit=capacity_limit,
            color=color,
        )
        z.category_filter = category_filter
        cam_entry["zones"][name] = z

        if self.db:
            self.db.save_zone(
                camera_id=camera_id,
                name=name,
                polygon=polygon,
                category_filter=category_filter,
                dwell_threshold=dwell_threshold,
                capacity_limit=capacity_limit,
                color=color,
            )

        self.save_to_yaml()
        sync_zone_to_world(self.world_graph, camera_id, name, polygon, capacity_limit)
        return z

    def delete_zone(self, camera_id: str, name: str) -> bool:
        """Remove a zone from memory, DB, and YAML."""
        cam_entry = self._ensure_camera_entry(camera_id)
        deleted = False
        if name in cam_entry["zones"]:
            del cam_entry["zones"][name]
            deleted = True

        if self.db:
            db_del = self.db.delete_zone(camera_id, name)
            deleted = deleted or db_del

        if deleted:
            self.save_to_yaml()
        remove_child_from_world(self.world_graph, camera_id, "zone", name)
        return deleted

    def save_tripwire(
        self,
        camera_id: str,
        name: str,
        line_segment: list[list[float] | tuple[float, float]],
        bidirectional: bool = True,
        color: tuple[int, int, int] = (0, 255, 255),
    ) -> Tripwire:
        """Create or update a tripwire in memory, DB, and YAML."""
        cam_entry = self._ensure_camera_entry(camera_id)
        tw = Tripwire(
            line_segment=line_segment,
            name=name,
            bidirectional=bidirectional,
            color=color,
        )
        cam_entry["tripwires"][name] = tw

        if self.db:
            self.db.save_tripwire(
                camera_id=camera_id,
                name=name,
                line_segment=line_segment,
                bidirectional=bidirectional,
                color=color,
            )

        self.save_to_yaml()
        sync_tripwire_to_world(self.world_graph, camera_id, name, line_segment, bidirectional)
        return tw

    def delete_tripwire(self, camera_id: str, name: str) -> bool:
        """Remove a tripwire from memory, DB, and YAML."""
        cam_entry = self._ensure_camera_entry(camera_id)
        deleted = False
        if name in cam_entry["tripwires"]:
            del cam_entry["tripwires"][name]
            deleted = True

        if self.db:
            db_del = self.db.delete_tripwire(camera_id, name)
            deleted = deleted or db_del

        if deleted:
            self.save_to_yaml()
        remove_child_from_world(self.world_graph, camera_id, "tripwire", name)
        return deleted

    def save_homography(
        self,
        camera_id: str,
        src_points: list[tuple[float, float]],
        dst_points: list[tuple[float, float]] | None = None,
        metric_width: float = 10.0,
        metric_height: float = 10.0,
    ) -> GroundPlaneHomography:
        """Calibrate and save 4-point ground plane homography."""
        cam_entry = self._ensure_camera_entry(camera_id)
        homo = GroundPlaneHomography(
            src_points=src_points,
            dst_points=dst_points,
            metric_width=metric_width,
            metric_height=metric_height,
            camera_id=camera_id,
        )
        cam_entry["homography"] = homo

        if self.db and homo.is_calibrated:
            self.db.save_homography_calibration(
                camera_id=camera_id,
                src_points=homo.src_points.tolist(),
                dst_points=homo.dst_points.tolist(),
                matrix=homo.H.tolist(),
                metric_width=metric_width,
                metric_height=metric_height,
            )

        self.save_to_yaml()
        sync_homography_to_world(self.world_graph, self.coordinate_mapper, camera_id, homo)
        return homo

    def get_homography(self, camera_id: str) -> GroundPlaneHomography:
        """Get the GroundPlaneHomography object for a camera."""
        return self._ensure_camera_entry(camera_id)["homography"]

    def apply_to_stream_manager(self, mgr: Any) -> None:
        """Apply configured zones, tripwires, and homography to a StreamManager."""
        if not mgr:
            return
        cam_id = mgr.camera_id
        cam_entry = self._ensure_camera_entry(cam_id)
        mgr.homography = cam_entry["homography"]
        if mgr.analytics:
            mgr.analytics.zones.clear()
            for z in cam_entry["zones"].values():
                mgr.analytics.add_zone(z)
            mgr.analytics.tripwires.clear()
            for tw in cam_entry["tripwires"].values():
                mgr.analytics.add_tripwire(tw)
        mgr.topology = self.topology
        sync_homography_to_world(self.world_graph, self.coordinate_mapper, cam_id, cam_entry["homography"])
        logger.info(
            "Applied scenario for '%s': %d zones, %d tripwires, calibrated=%s",
            cam_id,
            len(cam_entry["zones"]),
            len(cam_entry["tripwires"]),
            mgr.homography.is_calibrated,
        )
