#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Pure dataclasses and hop segmentation helpers extracted from ``journey.py``."""

import json
import os
from datetime import datetime
from typing import Any

from intelligent_tracker.journey_models import EntityJourney, JourneyHop
from intelligent_tracker.source_ref import build_source_ref, snapshot_path_to_url
from intelligent_tracker.world.coordinates import compute_hop_global_path

__all__ = [
    "EntityJourney", "JourneyHop", "parse_sighting_timestamp",
    "build_journey_hop", "segment_sightings_into_hops", "build_journey_narrative",
]


def parse_sighting_timestamp(ts_val: Any) -> float:
    """Parse numeric or ISO-8601 timestamp value into epoch seconds."""
    if isinstance(ts_val, (int, float)):
        return float(ts_val)
    if isinstance(ts_val, str):
        try:
            return float(ts_val)
        except (ValueError, TypeError):
            pass
        try:
            return datetime.fromisoformat(ts_val).timestamp()
        except Exception:
            return 0.0
    return 0.0


def _extract_sighting_summary(
    sightings: list[dict[str, Any]],
) -> tuple[str | None, str | None, list[list[int]]]:
    snap: str | None = None
    zone_id: str | None = None
    bboxes: list[list[int]] = []
    for s in sightings:
        if not snap and s.get("snapshot_path") and os.path.exists(s["snapshot_path"]):
            snap = s["snapshot_path"]
        if not zone_id and s.get("zone_id"):
            zone_id = s["zone_id"]
        if s.get("bbox"):
            try:
                bx = json.loads(s["bbox"]) if isinstance(s["bbox"], str) else list(s["bbox"])
                bboxes.append(bx)
            except Exception:
                pass
    return snap, zone_id, bboxes[:5]


def _extract_media_ref(sightings: list[dict[str, Any]]) -> tuple[str, float]:
    for s in sightings:
        vfile = str(s.get("video_filename") or "").strip()
        if vfile:
            try:
                offset = max(0.0, float(s.get("media_offset_sec") or 0.0))
            except (TypeError, ValueError):
                offset = 0.0
            return vfile, offset
    return "", 0.0


def _extract_hop_provenance(sightings: list[dict[str, Any]]) -> tuple[int | None, int | None, str, str, str]:
    tid = next((int(s["track_id"]) for s in sightings if s.get("track_id") not in (None, "")), None)
    eid = next((int(s["entity_id"]) for s in sightings if s.get("entity_id") not in (None, "")), None)
    rid = next((str(s["run_id"]).strip() for s in sightings if s.get("run_id")), "")
    cam = next((str(s["camera_id"]).strip() for s in sightings if s.get("camera_id")), "")
    snap = next((str(s["snapshot_path"]).strip() for s in sightings if s.get("snapshot_path")), "")
    return tid, eid, rid, cam, snap


def build_journey_hop(
    index: int, camera_id: str, sightings: list[dict[str, Any]], previous_hops: list[JourneyHop],
    coordinate_mapper: Any = None, homographies: dict[str, Any] | None = None,
) -> JourneyHop:
    """Build a JourneyHop dataclass from a contiguous camera sightings slice."""
    start_t = parse_sighting_timestamp(sightings[0].get("timestamp"))
    end_t = parse_sighting_timestamp(sightings[-1].get("timestamp"))
    dur = max(1.0, end_t - start_t)
    transit = max(0.0, start_t - previous_hops[-1].end_time) if previous_hops else None

    snap, zone_id, sample_bboxes = _extract_sighting_summary(sightings)
    video_filename, media_offset_sec = _extract_media_ref(sightings)
    track_id, entity_id, run_id, explicit_cam, raw_snap = _extract_hop_provenance(sightings)
    snapshot_url = snapshot_path_to_url(snap or raw_snap)
    ref_cam = explicit_cam or ("" if (video_filename and camera_id == video_filename) else camera_id)
    source_ref = build_source_ref(
        camera_id=ref_cam, video_filename=video_filename, run_id=run_id,
        media_offset_sec=media_offset_sec if (video_filename or media_offset_sec) else None,
        ts=start_t, track_id=track_id, entity_id=entity_id, zone_id=zone_id or "",
        bbox=sample_bboxes[0] if sample_bboxes else None, snapshot_url=snapshot_url,
    )
    global_path = compute_hop_global_path(camera_id, sightings, coordinate_mapper=coordinate_mapper, homographies=homographies)
    cam_name = camera_id.upper()
    if not cam_name.startswith("CAM"):
        cam_name = f"Camera {camera_id}"

    return JourneyHop(
        hop_index=index, camera_id=camera_id, camera_name=cam_name, zone_id=zone_id,
        start_time=start_t, end_time=end_t, duration_seconds=round(dur, 1),
        sightings_count=len(sightings), snapshot_path=snap,
        transit_time_from_prev=round(transit, 1) if transit is not None else None,
        sample_bboxes=sample_bboxes,
        global_start_xy=global_path[0] if global_path else None,
        global_end_xy=global_path[-1] if global_path else None,
        global_path=global_path, video_filename=video_filename, media_offset_sec=media_offset_sec,
        track_id=track_id, run_id=run_id, snapshot_url=snapshot_url, source_ref=source_ref,
    )


def segment_sightings_into_hops(
    sightings: list[dict[str, Any]], max_hop_gap_seconds: float = 60.0,
    coordinate_mapper: Any = None, homographies: dict[str, Any] | None = None,
) -> list[JourneyHop]:
    """Sort sightings chronologically and split into per-camera JourneyHop instances."""
    sorted_sightings = sorted(sightings, key=lambda s: parse_sighting_timestamp(s.get("timestamp")))
    hops: list[JourneyHop] = []
    current_hop: list[dict[str, Any]] = []
    current_cam: str | None = None

    for s in sorted_sightings:
        cam = str(s.get("camera_id") or "").strip() or str(s.get("source") or "").strip() or "cam_01"
        s_ts = parse_sighting_timestamp(s.get("timestamp"))
        if current_cam is None:
            current_cam = cam
            current_hop.append(s)
        elif cam == current_cam and s_ts - parse_sighting_timestamp(current_hop[-1].get("timestamp")) <= max_hop_gap_seconds:
            current_hop.append(s)
        else:
            hops.append(build_journey_hop(len(hops) + 1, current_cam, current_hop, hops, coordinate_mapper, homographies))
            current_cam = cam
            current_hop = [s]

    if current_hop and current_cam:
        hops.append(build_journey_hop(len(hops) + 1, current_cam, current_hop, hops, coordinate_mapper, homographies))
    return hops


def build_journey_narrative(entity_name: str, hops: list[JourneyHop]) -> str:
    """Format a human-readable summary narrative across chronological journey hops."""
    descriptions = []
    for h in hops:
        st_str = datetime.fromtimestamp(h.start_time).strftime("%H:%M:%S")
        z_str = f" ({h.zone_id})" if h.zone_id else ""
        descriptions.append(f"{st_str} {h.camera_name}{z_str} [{h.duration_seconds:.0f}s]")
    return f"{entity_name} journey ({len(hops)} hops): " + " -> ".join(descriptions)
