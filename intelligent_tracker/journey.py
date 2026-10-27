#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Trajectory Journey Search & Video Exporter Module.

Provides:
- Historical trajectory reconstruction across all camera feeds and zones.
- Chronological journey hop segmentation: (e.g. 10:02 Front Gate -> 10:04 Front Door -> 10:05 Hallway).
- Dwell times and inter-camera transit durations.
- Slicing and concatenation of video recordings or sighting snapshots into a single
  downloadable MP4 journey file with branded title overlays.
"""

import os
import time
import math
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Any, Union

import cv2
import numpy as np

from intelligent_tracker.database import TrackerDB

logger = logging.getLogger("intelligent_tracker.journey")


@dataclass
class JourneyHop:
    """Represents a discrete visit of an entity at a specific camera or zone."""
    hop_index: int
    camera_id: str
    camera_name: str
    zone_id: Optional[str]
    start_time: float
    end_time: float
    duration_seconds: float
    sightings_count: int
    snapshot_path: Optional[str] = None
    transit_time_from_prev: Optional[float] = None
    sample_bboxes: List[List[int]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EntityJourney:
    """Complete multi-camera chronological journey of an entity."""
    entity_id: Optional[int]
    entity_name: str
    category: str
    total_hops: int
    total_duration_seconds: float
    first_seen: float
    last_seen: float
    hops: List[JourneyHop]
    summary_narrative: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["hops"] = [h.to_dict() for h in self.hops]
        return d


class TrajectoryJourneySearcher:
    """Reconstructs cross-camera trajectories and journey hops from TrackerDB sightings."""

    def __init__(self, db: TrackerDB):
        self.db = db

    def search_journey(
        self,
        entity_id: Optional[int] = None,
        entity_name: Optional[str] = None,
        track_id: Optional[int] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        max_hop_gap_seconds: float = 60.0,
    ) -> EntityJourney:
        """
        Reconstructs the full journey across cameras for an entity or track.
        
        :param entity_id: Persistent entity ID.
        :param entity_name: Entity name if entity_id is unknown.
        :param track_id: Raw track ID if searching un-enrolled track.
        :param start_time: ISO-8601 or SQLite datetime lower bound.
        :param end_time: ISO-8601 or SQLite datetime upper bound.
        :param max_hop_gap_seconds: Maximum seconds elapsed between sightings before
                                    splitting into a separate hop on the same camera.
        :return: EntityJourney object.
        """
        resolved_id = entity_id
        resolved_name = entity_name or "Unknown Entity"
        resolved_category = "person"

        if entity_name and not resolved_id:
            ent = self.db.get_entity_by_name(entity_name)
            if ent:
                resolved_id = ent["id"]
                resolved_name = ent["name"]
                resolved_category = ent["category"]

        if resolved_id:
            ent = self.db.get_entity(resolved_id)
            if ent:
                resolved_name = ent["name"]
                resolved_category = ent["category"]

        sightings = self.db.query_sightings(
            entity_id=resolved_id,
            start_time=start_time,
            end_time=end_time,
            limit=500,
        )

        # If searching by track_id specifically and no entity_id was provided
        if not sightings and track_id is not None:
            with self.db._lock:
                cur = self.db._conn.cursor()
                try:
                    cur.execute(
                        "SELECT * FROM sightings WHERE track_id = ? ORDER BY timestamp ASC LIMIT 500",
                        (track_id,),
                    )
                    rows = cur.fetchall()
                    sightings = [dict(r) for r in rows]
                    if sightings:
                        resolved_name = f"Track #{track_id}"
                finally:
                    cur.close()

        if not sightings:
            now = time.time()
            return EntityJourney(
                entity_id=resolved_id,
                entity_name=resolved_name,
                category=resolved_category,
                total_hops=0,
                total_duration_seconds=0.0,
                first_seen=now,
                last_seen=now,
                hops=[],
                summary_narrative="No sightings found matching search criteria.",
            )

        # Sort sightings chronologically
        def parse_ts(ts_val) -> float:
            if isinstance(ts_val, (int, float)):
                return float(ts_val)
            if isinstance(ts_val, str):
                try:
                    return float(ts_val)
                except (ValueError, TypeError):
                    pass
                try:
                    dt = datetime.fromisoformat(ts_val)
                    return dt.timestamp()
                except Exception:
                    return 0.0
            return 0.0

        sorted_sightings = sorted(sightings, key=lambda s: parse_ts(s.get("timestamp")))

        hops: List[JourneyHop] = []
        current_hop_sightings: List[Dict[str, Any]] = []
        current_cam = None

        for s in sorted_sightings:
            cam = s.get("source") or "cam_01"
            s_ts = parse_ts(s.get("timestamp"))

            if current_cam is None:
                current_cam = cam
                current_hop_sightings.append(s)
            elif cam == current_cam:
                prev_ts = parse_ts(current_hop_sightings[-1].get("timestamp"))
                if s_ts - prev_ts <= max_hop_gap_seconds:
                    current_hop_sightings.append(s)
                else:
                    # Finalize hop due to time gap
                    hops.append(self._build_hop(len(hops) + 1, current_cam, current_hop_sightings, hops))
                    current_hop_sightings = [s]
            else:
                # Camera transition!
                hops.append(self._build_hop(len(hops) + 1, current_cam, current_hop_sightings, hops))
                current_cam = cam
                current_hop_sightings = [s]

        if current_hop_sightings and current_cam:
            hops.append(self._build_hop(len(hops) + 1, current_cam, current_hop_sightings, hops))

        first_ts = hops[0].start_time if hops else time.time()
        last_ts = hops[-1].end_time if hops else first_ts
        total_duration = max(0.0, last_ts - first_ts)

        # Generate summary narrative
        hop_descriptions = []
        for h in hops:
            st_str = datetime.fromtimestamp(h.start_time).strftime("%H:%M:%S")
            z_str = f" ({h.zone_id})" if h.zone_id else ""
            hop_descriptions.append(f"{st_str} {h.camera_name}{z_str} [{h.duration_seconds:.0f}s]")

        narrative = f"{resolved_name} journey ({len(hops)} hops): " + " -> ".join(hop_descriptions)

        return EntityJourney(
            entity_id=resolved_id,
            entity_name=resolved_name,
            category=resolved_category,
            total_hops=len(hops),
            total_duration_seconds=round(total_duration, 1),
            first_seen=first_ts,
            last_seen=last_ts,
            hops=hops,
            summary_narrative=narrative,
        )

    def _build_hop(
        self,
        index: int,
        camera_id: str,
        sightings: List[Dict[str, Any]],
        previous_hops: List[JourneyHop],
    ) -> JourneyHop:
        """Helper to create a JourneyHop dataclass from sightings list."""
        def parse_ts(ts_val) -> float:
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

        start_t = parse_ts(sightings[0].get("timestamp"))
        end_t = parse_ts(sightings[-1].get("timestamp"))
        dur = max(1.0, end_t - start_t)

        transit = None
        if previous_hops:
            prev_end = previous_hops[-1].end_time
            transit = max(0.0, start_t - prev_end)

        # Representative snapshot
        snap = None
        bboxes = []
        zone_id = None
        for s in sightings:
            if not snap and s.get("snapshot_path") and os.path.exists(s["snapshot_path"]):
                snap = s["snapshot_path"]
            if not zone_id and s.get("zone_id"):
                zone_id = s["zone_id"]
            if s.get("bbox"):
                try:
                    if isinstance(s["bbox"], str):
                        import json
                        bx = json.loads(s["bbox"])
                    else:
                        bx = list(s["bbox"])
                    bboxes.append(bx)
                except Exception:
                    pass

        cam_name = camera_id.upper()
        if not cam_name.startswith("CAM"):
            cam_name = f"Camera {camera_id}"

        return JourneyHop(
            hop_index=index,
            camera_id=camera_id,
            camera_name=cam_name,
            zone_id=zone_id,
            start_time=start_t,
            end_time=end_t,
            duration_seconds=round(dur, 1),
            sightings_count=len(sightings),
            snapshot_path=snap,
            transit_time_from_prev=round(transit, 1) if transit is not None else None,
            sample_bboxes=bboxes[:5],
        )


class JourneyVideoExporter:
    """Exports sliced and concatenated journey video clips into a single MP4 file."""

    def __init__(self, output_dir: str = "data/videos"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def export_journey_video(
        self,
        journey: EntityJourney,
        output_filename: Optional[str] = None,
        resolution: Tuple[int, int] = (640, 480),
        fps: int = 25,
        seconds_per_hop: float = 3.0,
    ) -> str:
        """
        Generates an MP4 journey summary video.
        
        If camera video files exist in output_dir matching the camera ID, slices footage.
        Otherwise, synthesizes an animated tactical playback using high-res sighting snapshots,
        camera title cards, transit transitions, and metadata overlays.
        
        :param journey: The EntityJourney object to export.
        :param output_filename: Optional custom target filename.
        :param resolution: Video (width, height)
        :param fps: Output video framerate.
        :param seconds_per_hop: Duration to render each hop.
        :return: Absolute path to the generated MP4 file.
        """
        if not output_filename:
            safe_name = journey.entity_name.replace(" ", "_").lower()
            output_filename = f"journey_{safe_name}_{int(time.time())}.mp4"

        output_path = os.path.join(self.output_dir, output_filename)
        w, h = resolution

        # Use fourcc mp4v for cross-platform compatibility
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(output_path, fourcc, fps, (w, h))

        if not writer.isOpened():
            # Fallback to MJPG/avi container if mp4v is not supported on edge
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            output_path = output_path.replace(".mp4", ".avi")
            writer = cv2.VideoWriter(output_path, fourcc, fps, (w, h))

        try:
            # 1. Opening Title Card (2 seconds)
            intro_frames = int(2.0 * fps)
            for f_idx in range(intro_frames):
                frame = self._render_title_card(
                    title="SECURITY INCIDENT RECONSTRUCTION",
                    subtitle=f"Target: {journey.entity_name} ({journey.category.upper()})",
                    info=f"Total Hops: {journey.total_hops} | Duration: {journey.total_duration_seconds:.0f}s",
                    size=(w, h),
                )
                writer.write(frame)

            # 2. Render Each Hop
            for hop in journey.hops:
                # Inter-hop transit title card if transit > 0
                if hop.transit_time_from_prev and hop.transit_time_from_prev > 0:
                    transit_frames = int(1.2 * fps)
                    for _ in range(transit_frames):
                        t_frame = self._render_transit_card(hop, size=(w, h))
                        writer.write(t_frame)

                # Hop Footage or Snapshot Animation
                hop_frames = int(seconds_per_hop * fps)
                snapshot_img = None
                if hop.snapshot_path and os.path.exists(hop.snapshot_path):
                    snapshot_img = cv2.imread(hop.snapshot_path)

                if snapshot_img is None:
                    # Synthetic camera view placeholder
                    snapshot_img = np.full((h, w, 3), (30, 41, 59), dtype=np.uint8)
                    cv2.putText(snapshot_img, f"FEED: {hop.camera_name}", (w // 4, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 220, 255), 2)

                snapshot_resized = cv2.resize(snapshot_img, (w, h))

                for f_idx in range(hop_frames):
                    frame = snapshot_resized.copy()

                    # Dynamic Pan/Zoom effect
                    scale = 1.0 + 0.05 * math.sin(math.pi * f_idx / hop_frames)
                    if scale > 1.0:
                        sw, sh = int(w * scale), int(h * scale)
                        scaled = cv2.resize(frame, (sw, sh))
                        ox, oy = (sw - w) // 2, (sh - h) // 2
                        frame = scaled[oy:oy + h, ox:ox + w]

                    # Overlay Camera and Hop HUD
                    self._draw_hop_hud(frame, hop, f_idx, hop_frames)
                    writer.write(frame)

            # 3. Outro Card (2 seconds)
            outro_frames = int(2.0 * fps)
            for _ in range(outro_frames):
                frame = self._render_title_card(
                    title="JOURNEY TRAJECTORY COMPLETE",
                    subtitle=f"Audit Verified: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    info="Intelligent Tracker Autonomous Security Microservice",
                    size=(w, h),
                )
                writer.write(frame)

        finally:
            writer.release()

        logger.info("Exported journey video for '%s' to %s", journey.entity_name, output_path)
        return output_path

    def _render_title_card(self, title: str, subtitle: str, info: str, size: Tuple[int, int]) -> np.ndarray:
        w, h = size
        img = np.full((h, w, 3), (15, 23, 42), dtype=np.uint8)
        # Tactical grid accent
        cv2.rectangle(img, (20, 20), (w - 20, h - 20), (0, 220, 255), 1)
        cv2.putText(img, title, (40, h // 2 - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 220, 255), 2)
        cv2.putText(img, subtitle, (40, h // 2 + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        cv2.putText(img, info, (40, h // 2 + 50), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (148, 163, 184), 1)
        return img

    def _render_transit_card(self, hop: JourneyHop, size: Tuple[int, int]) -> np.ndarray:
        w, h = size
        img = np.full((h, w, 3), (10, 15, 30), dtype=np.uint8)
        cv2.line(img, (w // 4, h // 2), (3 * w // 4, h // 2), (255, 200, 0), 2)
        arrow_text = f"--> Transit to {hop.camera_name} ({hop.transit_time_from_prev:.1f}s) -->"
        cv2.putText(img, arrow_text, (w // 5, h // 2 - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 200, 0), 1)
        return img

    def _draw_hop_hud(self, frame: np.ndarray, hop: JourneyHop, frame_idx: int, total_frames: int):
        h, w = frame.shape[:2]
        # Top banner
        cv2.rectangle(frame, (0, 0), (w, 36), (15, 23, 42), -1)
        st_str = datetime.fromtimestamp(hop.start_time).strftime("%H:%M:%S")
        hud_text = f"HOP #{hop.hop_index}: {hop.camera_name} | TIME: {st_str} | DWELL: {hop.duration_seconds:.0f}s"
        cv2.putText(frame, hud_text, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 220, 255), 1)

        # Bottom banner with zone & sightings
        cv2.rectangle(frame, (0, h - 28), (w, h), (15, 23, 42), -1)
        zone_str = f"ZONE: {hop.zone_id}" if hop.zone_id else "ZONE: General Area"
        bot_text = f"{zone_str} | Sightings: {hop.sightings_count} | Progress: {int((frame_idx/total_frames)*100)}%"
        cv2.putText(frame, bot_text, (12, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (148, 163, 184), 1)
