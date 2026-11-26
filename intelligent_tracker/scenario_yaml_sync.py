"""Additive per-shape scenario YAML synchronization into memory and SQLite."""

import logging
import os
from typing import Any, Callable

try:
    import yaml
except ImportError:
    yaml = None

from intelligent_tracker.scenario_storage import (
    _parse_yaml_homography,
    _parse_yaml_transitions,
    _parse_yaml_tripwires,
    _parse_yaml_zones,
)

logger = logging.getLogger(__name__)


def _upsert_camera_shapes(cam_id: str, c_data: dict[str, Any], cam_entry: dict[str, Any], db: Any) -> int:
    """Upsert missing zones, tripwires, and homography for one camera."""
    added = 0
    existing_zones = set(cam_entry.get("zones", {}).keys())
    missing_zones = [z for z in (c_data.get("zones") or []) if z.get("name") not in existing_zones]
    if missing_zones:
        _parse_yaml_zones(cam_id, missing_zones, cam_entry, db)
        added += len(missing_zones)
    existing_tw = set(cam_entry.get("tripwires", {}).keys())
    missing_tw = [t for t in (c_data.get("tripwires") or []) if t.get("name") not in existing_tw]
    if missing_tw:
        _parse_yaml_tripwires(cam_id, missing_tw, cam_entry, db)
        added += len(missing_tw)
    homo = cam_entry.get("homography")
    if (homo is None or not getattr(homo, "is_calibrated", False)) and c_data.get("homography"):
        _parse_yaml_homography(cam_id, c_data.get("homography"), cam_entry, db)
        added += 1
    return added


def upsert_missing_scenarios_from_yaml(
    path: str,
    ensure_camera_entry: Callable[[str], dict[str, Any]],
    cameras: dict[str, dict[str, Any]],
    db: Any,
    topology: Any,
) -> int:
    """Add any YAML cameras/zones/tripwires/homographies/transitions absent from DB."""
    if not path or not os.path.exists(path) or yaml is None:
        return 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as exc:
        logger.warning("Failed reading scenario YAML %s for upsert: %s", path, exc)
        return 0
    added = sum(
        _upsert_camera_shapes(cam_id, c_data, ensure_camera_entry(cam_id), db)
        for cam_id, c_data in (data.get("cameras") or {}).items()
        if isinstance(c_data, dict)
    )
    existing_links = set(getattr(topology, "links", {}).keys()) if topology is not None else set()
    missing_links = [link for link in (data.get("spatial_transitions") or []) if link.get("link_id") not in existing_links]
    if missing_links and topology is not None:
        _parse_yaml_transitions(missing_links, topology, db)
        added += len(missing_links)
    return added
