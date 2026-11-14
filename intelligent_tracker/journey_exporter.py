#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Journey Video Exporter Module.

Synthesizes animated MP4 trajectory playback clips from ``EntityJourney`` hops,
title cards, transit transitions, and HUD metadata overlays.
"""

import logging
import math
import os
import time
from datetime import datetime

import cv2
import numpy as np

from intelligent_tracker.journey_segmenter import EntityJourney, JourneyHop

logger = logging.getLogger("intelligent_tracker.journey")


class JourneyVideoExporter:
    """Exports sliced and concatenated journey video clips into a single MP4 file."""

    def __init__(self, output_dir: str = "data/videos"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def export_journey_video(
        self, journey: EntityJourney, output_filename: str | None = None,
        resolution: tuple[int, int] = (640, 480), fps: int = 25, seconds_per_hop: float = 3.0,
    ) -> str:
        """Generate an MP4 journey summary video for the provided EntityJourney."""
        if not output_filename:
            output_filename = f"journey_{journey.entity_name.replace(' ', '_').lower()}_{int(time.time())}.mp4"
        writer, output_path = self._open_video_writer(os.path.join(self.output_dir, output_filename), fps, resolution)
        try:
            intro_sub = f"Target: {journey.entity_name} ({journey.category.upper()})"
            intro_info = f"Total Hops: {journey.total_hops} | Duration: {journey.total_duration_seconds:.0f}s"
            self._write_title_segment(writer, "SECURITY INCIDENT RECONSTRUCTION", intro_sub, intro_info, resolution, 2.0, fps)
            for hop in journey.hops:
                self._write_transit_segment(writer, hop, resolution, fps)
                self._write_hop_clip_frames(writer, hop, resolution, fps, seconds_per_hop)
            outro_sub = f"Audit Verified: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            self._write_title_segment(writer, "JOURNEY TRAJECTORY COMPLETE", outro_sub, "Intelligent Tracker Autonomous Security Microservice", resolution, 2.0, fps)
        finally:
            writer.release()
        logger.info("Exported journey video for '%s' to %s", journey.entity_name, output_path)
        return output_path

    def _open_video_writer(
        self,
        output_path: str,
        fps: int,
        size: tuple[int, int],
    ) -> tuple[cv2.VideoWriter, str]:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(output_path, fourcc, fps, size)
        if not writer.isOpened():
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            output_path = output_path.replace(".mp4", ".avi")
            writer = cv2.VideoWriter(output_path, fourcc, fps, size)
        return writer, output_path

    def _write_title_segment(
        self,
        writer: cv2.VideoWriter,
        title: str,
        subtitle: str,
        info: str,
        size: tuple[int, int],
        duration_sec: float,
        fps: int,
    ) -> None:
        frame = self._render_title_card(title=title, subtitle=subtitle, info=info, size=size)
        for _ in range(int(duration_sec * fps)):
            writer.write(frame)

    def _write_transit_segment(
        self,
        writer: cv2.VideoWriter,
        hop: JourneyHop,
        size: tuple[int, int],
        fps: int,
    ) -> None:
        if not hop.transit_time_from_prev or hop.transit_time_from_prev <= 0:
            return
        t_frame = self._render_transit_card(hop, size=size)
        for _ in range(int(1.2 * fps)):
            writer.write(t_frame)

    def _write_hop_clip_frames(
        self,
        writer: cv2.VideoWriter,
        hop: JourneyHop,
        size: tuple[int, int],
        fps: int,
        seconds_per_hop: float,
    ) -> None:
        w, h = size
        hop_frames = int(seconds_per_hop * fps)
        snapshot_img = None
        if hop.snapshot_path and os.path.exists(hop.snapshot_path):
            snapshot_img = cv2.imread(hop.snapshot_path)
        if snapshot_img is None:
            snapshot_img = np.full((h, w, 3), (30, 41, 59), dtype=np.uint8)
            cv2.putText(snapshot_img, f"FEED: {hop.camera_name}", (w // 4, h // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 220, 255), 2)

        snapshot_resized = cv2.resize(snapshot_img, (w, h))
        for f_idx in range(hop_frames):
            frame = snapshot_resized.copy()
            scale = 1.0 + 0.05 * math.sin(math.pi * f_idx / hop_frames)
            if scale > 1.0:
                sw, sh = int(w * scale), int(h * scale)
                scaled = cv2.resize(frame, (sw, sh))
                ox, oy = (sw - w) // 2, (sh - h) // 2
                frame = scaled[oy:oy + h, ox:ox + w]
            self._draw_hop_hud(frame, hop, f_idx, hop_frames)
            writer.write(frame)

    def _render_title_card(
        self,
        title: str,
        subtitle: str,
        info: str,
        size: tuple[int, int],
    ) -> np.ndarray:
        w, h = size
        img = np.full((h, w, 3), (15, 23, 42), dtype=np.uint8)
        cv2.rectangle(img, (20, 20), (w - 20, h - 20), (0, 220, 255), 1)
        cv2.putText(img, title, (40, h // 2 - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 220, 255), 2)
        cv2.putText(img, subtitle, (40, h // 2 + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        cv2.putText(img, info, (40, h // 2 + 50), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (148, 163, 184), 1)
        return img

    def _render_transit_card(self, hop: JourneyHop, size: tuple[int, int]) -> np.ndarray:
        w, h = size
        img = np.full((h, w, 3), (10, 15, 30), dtype=np.uint8)
        cv2.line(img, (w // 4, h // 2), (3 * w // 4, h // 2), (255, 200, 0), 2)
        arrow_text = f"--> Transit to {hop.camera_name} ({hop.transit_time_from_prev:.1f}s) -->"
        cv2.putText(img, arrow_text, (w // 5, h // 2 - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 200, 0), 1)
        return img

    def _draw_hop_hud(
        self,
        frame: np.ndarray,
        hop: JourneyHop,
        frame_idx: int,
        total_frames: int,
    ) -> None:
        h, w = frame.shape[:2]
        cv2.rectangle(frame, (0, 0), (w, 36), (15, 23, 42), -1)
        st_str = datetime.fromtimestamp(hop.start_time).strftime("%H:%M:%S")
        hud_text = f"HOP #{hop.hop_index}: {hop.camera_name} | TIME: {st_str} | DWELL: {hop.duration_seconds:.0f}s"
        cv2.putText(frame, hud_text, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 220, 255), 1)

        cv2.rectangle(frame, (0, h - 28), (w, h), (15, 23, 42), -1)
        zone_str = f"ZONE: {hop.zone_id}" if hop.zone_id else "ZONE: General Area"
        bot_text = f"{zone_str} | Sightings: {hop.sightings_count} | Progress: {int((frame_idx / total_frames) * 100)}%"
        cv2.putText(frame, bot_text, (12, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (148, 163, 184), 1)
