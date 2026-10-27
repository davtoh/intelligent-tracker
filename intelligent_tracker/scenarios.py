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
- Realization of Scene, Area, and Line from intelligent_tracker.high_objects.
"""

import os
import json
import logging
from typing import Dict, List, Optional, Tuple, Any, Union

try:
    import yaml
except ImportError:
    yaml = None

import cv2
import numpy as np

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.geometry import ZoneROI, Tripwire
from intelligent_tracker.high_objects import Scene, Area, Line
from intelligent_tracker.homography import GroundPlaneHomography
from intelligent_tracker.topology import CrossCameraTopology, SpatialTransitionLink

logger = logging.getLogger("intelligent_tracker.scenarios")

DEFAULT_SCENARIOS_PATH = "configs/scenarios.yaml"


class ScenarioManager:
    """
    Coordinates spatial scenario configurations across all camera channels,
    bridging interactive web studio actions with live computer vision pipelines,
    YAML configuration files, and SQLite database storage.
    """

    def __init__(
        self,
        config_path: str = DEFAULT_SCENARIOS_PATH,
        db: Optional[TrackerDB] = None,
        db_path: str = "data/tracker.db",
    ):
        self.config_path = config_path
        self.db = db or TrackerDB(db_path)
        self.topology = CrossCameraTopology()

        # camera_id -> Dict of zones, tripwires, homography
        # {
        #   "cam_01": {
        #       "zones": {name: ZoneROI},
        #       "tripwires": {name: Tripwire},
        #       "homography": GroundPlaneHomography,
        #   }
        # }
        self.cameras: Dict[str, Dict[str, Any]] = {}

        # Load initial scenarios
        self.load_scenarios()

    def _ensure_camera_entry(self, camera_id: str) -> Dict[str, Any]:
        if camera_id not in self.cameras:
            self.cameras[camera_id] = {
                "zones": {},
                "tripwires": {},
                "homography": GroundPlaneHomography(camera_id=camera_id),
            }
        return self.cameras[camera_id]

    def load_scenarios(self):
        """Loads scenarios from SQLite TrackerDB, falling back to YAML file if DB is empty."""
        loaded_from_db = False

        if self.db:
            try:
                db_zones = self.db.get_zones()
                for zd in db_zones:
                    cam_id = zd["camera_id"]
                    cam_entry = self._ensure_camera_entry(cam_id)
                    z = ZoneROI(
                        polygon=zd["polygon"],
                        name=zd["name"],
                        dwell_threshold=zd.get("dwell_threshold", 5.0),
                        capacity_limit=zd.get("capacity_limit"),
                        color=tuple(zd.get("color", (0, 200, 100))),
                    )
                    z.category_filter = zd.get("category_filter", "")
                    cam_entry["zones"][zd["name"]] = z
                    loaded_from_db = True

                db_tw = self.db.get_tripwires()
                for td in db_tw:
                    cam_id = td["camera_id"]
                    cam_entry = self._ensure_camera_entry(cam_id)
                    tw = Tripwire(
                        line_segment=td["line_segment"],
                        name=td["name"],
                        bidirectional=td.get("bidirectional", True),
                        color=tuple(td.get("color", (0, 255, 255))),
                    )
                    cam_entry["tripwires"][td["name"]] = tw
                    loaded_from_db = True

                db_trans = self.db.get_spatial_transitions()
                for tr in db_trans:
                    link = SpatialTransitionLink.from_dict(tr)
                    self.topology.add_link(link)
                    loaded_from_db = True

                # Load homographies
                for cam_id in list(self.cameras.keys()) + ["cam_01", "cam_02"]:
                    h_data = self.db.get_homography_calibration(cam_id)
                    if h_data:
                        cam_entry = self._ensure_camera_entry(cam_id)
                        cam_entry["homography"] = GroundPlaneHomography.from_dict(h_data)
                        loaded_from_db = True

            except Exception as e:
                logger.warning("Failed loading scenarios from database: %s", e)

        # Fallback to YAML file if nothing loaded from DB
        if not loaded_from_db and os.path.exists(self.config_path):
            self.load_from_yaml(self.config_path)

    def load_from_yaml(self, path: str):
        """Parse scenarios from a YAML file."""
        if not os.path.exists(path) or yaml is None:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            cams_data = data.get("cameras", {})
            for cam_id, c_data in cams_data.items():
                cam_entry = self._ensure_camera_entry(cam_id)

                # Zones
                for zd in c_data.get("zones", []):
                    z = ZoneROI(
                        polygon=zd["polygon"],
                        name=zd["name"],
                        dwell_threshold=zd.get("dwell_threshold", 5.0),
                        capacity_limit=zd.get("capacity_limit"),
                        color=tuple(zd.get("color", (0, 200, 100))),
                    )
                    z.category_filter = zd.get("category_filter", "")
                    cam_entry["zones"][zd["name"]] = z
                    if self.db:
                        self.db.save_zone(
                            camera_id=cam_id,
                            name=zd["name"],
                            polygon=zd["polygon"],
                            category_filter=z.category_filter,
                            dwell_threshold=z.dwell_threshold,
                            capacity_limit=z.capacity_limit,
                            color=z.color,
                        )

                # Tripwires
                for td in c_data.get("tripwires", []):
                    tw = Tripwire(
                        line_segment=td["line_segment"],
                        name=td["name"],
                        bidirectional=td.get("bidirectional", True),
                        color=tuple(td.get("color", (0, 255, 255))),
                    )
                    cam_entry["tripwires"][td["name"]] = tw
                    if self.db:
                        self.db.save_tripwire(
                            camera_id=cam_id,
                            name=td["name"],
                            line_segment=td["line_segment"],
                            bidirectional=tw.bidirectional,
                            color=tw.color,
                        )

                # Homography
                h_cfg = c_data.get("homography")
                if h_cfg and "src_points" in h_cfg:
                    homo = GroundPlaneHomography.from_dict({**h_cfg, "camera_id": cam_id})
                    cam_entry["homography"] = homo
                    if self.db and homo.is_calibrated:
                        self.db.save_homography_calibration(
                            camera_id=cam_id,
                            src_points=homo.src_points.tolist(),
                            dst_points=homo.dst_points.tolist(),
                            matrix=homo.H.tolist(),
                            metric_width=homo.metric_width,
                            metric_height=homo.metric_height,
                        )

            # Topology Links
            top_links = data.get("spatial_transitions", [])
            for ld in top_links:
                link = SpatialTransitionLink.from_dict(ld)
                self.topology.add_link(link)
                if self.db:
                    self.db.save_spatial_transition(
                        link_id=link.link_id,
                        source_camera=link.source_camera,
                        source_zone=link.source_zone,
                        target_camera=link.target_camera,
                        target_zone=link.target_zone,
                        t_min=link.t_min,
                        t_max=link.t_max,
                        prior_boost=link.prior_boost,
                        bidirectional=link.bidirectional,
                        active=link.active,
                    )

            logger.info("Loaded scenarios from YAML file: %s", path)
        except Exception as e:
            logger.error("Error reading scenario YAML %s: %s", path, e)

    def save_to_yaml(self, path: Optional[str] = None):
        """Serialize current in-memory scenarios to YAML."""
        target_path = path or self.config_path
        if yaml is None:
            return

        export_data = {
            "version": "1.0",
            "cameras": {},
            "spatial_transitions": [l.to_dict() for l in self.topology.list_links() if not l.link_id.endswith("_rev")],
        }

        for cam_id, c_entry in self.cameras.items():
            cam_data = {"zones": [], "tripwires": [], "homography": {}}

            # Zones
            for z in c_entry["zones"].values():
                cam_data["zones"].append({
                    "name": z.name,
                    "polygon": z.polygon.tolist() if hasattr(z.polygon, "tolist") else list(z.polygon),
                    "dwell_threshold": z.dwell_threshold,
                    "capacity_limit": getattr(z, "capacity_limit", None),
                    "category_filter": getattr(z, "category_filter", ""),
                    "color": list(z.color),
                })

            # Tripwires
            for tw in c_entry["tripwires"].values():
                p1, p2 = tw.line_segment
                cam_data["tripwires"].append({
                    "name": tw.name,
                    "line_segment": [list(p1), list(p2)],
                    "bidirectional": tw.bidirectional,
                    "color": list(tw.color),
                })

            # Homography
            if c_entry["homography"].is_calibrated:
                cam_data["homography"] = c_entry["homography"].to_dict()

            export_data["cameras"][cam_id] = cam_data

        os.makedirs(os.path.dirname(os.path.abspath(target_path)) or ".", exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            yaml.dump(export_data, f, default_flow_style=False, sort_keys=False)
        logger.info("Saved scenarios to YAML: %s", target_path)

    # -------------------------------------------------------------------------
    # High-level Zone & Tripwire Operations
    # -------------------------------------------------------------------------

    def save_zone(
        self,
        camera_id: str,
        name: str,
        polygon: List[Union[List[float], Tuple[float, float]]],
        category_filter: str = "",
        dwell_threshold: float = 5.0,
        capacity_limit: Optional[int] = None,
        color: Tuple[int, int, int] = (0, 200, 100),
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
        return deleted

    def save_tripwire(
        self,
        camera_id: str,
        name: str,
        line_segment: List[Union[List[float], Tuple[float, float]]],
        bidirectional: bool = True,
        color: Tuple[int, int, int] = (0, 255, 255),
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
        return deleted

    def save_homography(
        self,
        camera_id: str,
        src_points: List[Tuple[float, float]],
        dst_points: Optional[List[Tuple[float, float]]] = None,
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
        return homo

    def get_homography(self, camera_id: str) -> GroundPlaneHomography:
        """Get the GroundPlaneHomography object for a camera."""
        cam_entry = self._ensure_camera_entry(camera_id)
        return cam_entry["homography"]

    def apply_to_stream_manager(self, mgr: Any):
        """
        Dynamically applies configured zones, tripwires, and homography
        to an active StreamManager instance.
        """
        if not mgr:
            return

        cam_id = mgr.camera_id
        cam_entry = self._ensure_camera_entry(cam_id)

        # 1. Apply Homography
        mgr.homography = cam_entry["homography"]

        # 2. Apply Zones and Tripwires into AnalyticsEngine
        if mgr.analytics:
            # Clear old zones and reload from scenario
            mgr.analytics.zones.clear()
            for z_name, z in cam_entry["zones"].items():
                mgr.analytics.add_zone(z)

            mgr.analytics.tripwires.clear()
            for tw_name, tw in cam_entry["tripwires"].items():
                mgr.analytics.add_tripwire(tw)

        # 3. Attach topology
        mgr.topology = self.topology
        logger.info("Applied scenario for '%s': %d zones, %d tripwires, calibrated=%s",
                    cam_id, len(cam_entry["zones"]), len(cam_entry["tripwires"]), mgr.homography.is_calibrated)
