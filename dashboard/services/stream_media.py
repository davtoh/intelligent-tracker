#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Stream Media & Overlay Mixin.
Handles JPEG placeholder creation, overlay toggling, BEV minimap generation,
heatmap encoding, telemetry reads, and interactive entity tagging.
"""

import logging
from typing import Any, Dict, List, Optional
import cv2
import numpy as np

from dashboard.services.entity_tagger import EntityTaggerService

logger = logging.getLogger("intelligent_tracker.dashboard.media")


class StreamMediaMixin:
    """Provides video frame rendering, overlay toggling, and media export methods."""

    def _create_placeholder_jpeg(self, text: str) -> bytes:
        """Generate a slate-dark JPEG placeholder with centered text."""
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        img[:] = (20, 24, 33)
        cv2.putText(img, text, (160, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 220, 255), 2)
        ret, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        return buf.tobytes() if ret else b""

    def set_overlays(self, options: Dict[str, Any]) -> Dict[str, bool]:
        """Update floating video overlay settings dynamically."""
        with self._lock:
            for k, v in options.items():
                if k in self.overlays:
                    self.overlays[k] = bool(v)
            if "heatmap" in options:
                self.draw_heatmap = bool(options["heatmap"])
            return dict(self.overlays)

    def get_overlays(self) -> Dict[str, bool]:
        """Get current overlay visibility flags."""
        with self._lock:
            return dict(self.overlays)

    def get_bev_minimap_jpeg(self) -> bytes:
        """Render and encode real-time 2D Bird's-Eye-View (BEV) minimap image."""
        with self._lock:
            tracks = self.tracker.tracks if self.tracker and hasattr(self.tracker, "tracks") else {}
            zones = self.analytics.zones if self.analytics else {}
            bev = self.homography.render_bev_minimap(tracks, zones=zones)
            ret, buf = cv2.imencode(".jpg", bev, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            return buf.tobytes() if ret else b""

    def get_latest_frame_jpeg(self, camera_id: Optional[str] = None) -> bytes:
        """Retrieve most recent encoded JPEG frame or placeholder."""
        with self._lock:
            if self._latest_jpeg is not None:
                return self._latest_jpeg
            return self._create_placeholder_jpeg("Waiting for stream...")

    def get_latest_telemetry(self, camera_id: Optional[str] = None) -> Dict[str, Any]:
        """Retrieve a snapshot copy of the most recent telemetry state."""
        with self._lock:
            payload = dict(self._latest_telemetry)
        recorder = getattr(self, "_recording_controller", None)
        if recorder is not None:
            payload["recording"] = recorder.status()
        return payload

    def get_heatmap_jpeg(self) -> bytes:
        """Render accumulated spatial occupancy heatmap as JPEG."""
        if not self.analytics or not self.analytics.heatmap:
            return self._create_placeholder_jpeg("Heatmap Not Initialized")
        hm_colored = self.analytics.heatmap.get_colored_map()
        ret, buf = cv2.imencode(".jpg", hm_colored, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        return buf.tobytes() if ret else b""

    def toggle_heatmap(self, enabled: Optional[bool] = None) -> bool:
        """Toggle or explicitly set spatial heatmap overlay state."""
        with self._lock:
            if enabled is not None:
                self.draw_heatmap = bool(enabled)
            else:
                self.draw_heatmap = not self.draw_heatmap
            return self.draw_heatmap

    def tag_entity(
        self,
        entity_name: str,
        category: str = "person",
        track_id: Optional[int] = None,
        bbox: Optional[List[int]] = None,
        notes: str = "",
    ) -> Dict[str, Any]:
        """Tag an entity bounding box and register into Re-ID gallery."""
        with self._lock:
            raw_frame = self._latest_raw_frame.copy() if self._latest_raw_frame is not None else None

        return EntityTaggerService.tag_entity(
            raw_frame=raw_frame,
            db=self.db,
            entity_name=entity_name,
            category=category,
            track_id=track_id,
            bbox=bbox,
            notes=notes,
            camera_id=self.camera_id,
            tracker=self.tracker,
            reid_extractor=self.reid_extractor,
            gallery_matcher=self.gallery_matcher,
        )

