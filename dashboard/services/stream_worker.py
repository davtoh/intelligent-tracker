#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Stream Worker Service.
Executes the continuous frame ingestion, computer vision inference,
spatial analytics, Re-ID matching, and telemetry distribution loop.
"""

import os
import time
import logging
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np

from dashboard.services.camera_diagnostics import CameraHealthManager

logger = logging.getLogger("intelligent_tracker.dashboard.worker")


def _diagnose_source_error(vs: Any) -> Tuple[str, str]:
    """Diagnose source failure root cause for health manager reporting."""
    if getattr(vs, "is_file", False) and not os.path.exists(str(vs.source)):
        return "FILE_NOT_FOUND", f"Video file not found: {vs.source}"
    if getattr(vs, "is_webcam", False) and not getattr(vs, "_is_connected", False):
        return "DEVICE_LOCKED", f"Camera device #{vs.source} is locked or unavailable"
    if getattr(vs, "is_rtsp", False) and not getattr(vs, "_is_connected", False):
        return "RTSP_TIMEOUT", f"RTSP connection timed out: {vs.source}"
    return "NO_FRAMES_DECODED", "No video frames could be decoded from source"


def _resize_frame_if_needed(frame: np.ndarray, max_dim: int = 1280) -> np.ndarray:
    """Clamp oversized video frames to protect browser rendering and bandwidth."""
    h, w = frame.shape[:2]
    if w > max_dim or h > max_dim:
        scale = max_dim / float(max(w, h))
        return cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return frame


def _measure_fps(curr_t: float, last_t: float, fps_samples: List[float]) -> Tuple[float, float]:
    """Compute rolling FPS average from frame timestamps."""
    dt = curr_t - last_t
    if dt > 0:
        fps_samples.append(1.0 / dt)
        if len(fps_samples) > 30:
            fps_samples.pop(0)
    measured_fps = float(np.mean(fps_samples)) if fps_samples else 30.0
    return measured_fps, curr_t


def _extract_recent_alerts(event_bus: Optional[Any]) -> List[Dict[str, Any]]:
    """Extract serialized dictionary list from event bus."""
    alerts = []
    if event_bus:
        for ev in event_bus.get_recent_events(limit=8):
            if hasattr(ev, "to_dict"):
                alerts.append(ev.to_dict())
            elif hasattr(ev, "__dataclass_fields__"):
                alerts.append(asdict(ev))
            else:
                alerts.append({"event_type": getattr(ev, "event_type", "event")})
    return alerts


def _extract_track_telemetry(tracks: Dict[int, Any], homography: Any) -> List[Dict[str, Any]]:
    """Map active vision tracks into telemetry dictionaries with homography coordinates."""
    telemetry_tracks = []
    for tid, trk in tracks.items():
        gx, gy = homography.track_to_ground(trk.bbox)
        telemetry_tracks.append({
            "id": tid,
            "bbox": [int(x) for x in trk.bbox],
            "centroid": [float(trk.centroid[0]), float(trk.centroid[1])],
            "ground_pos": [round(gx, 2), round(gy, 2)],
            "velocity": [round(float(trk.velocity[0]), 2), round(float(trk.velocity[1]), 2)],
            "label": trk.label,
            "confidence": round(float(trk.confidence), 2),
            "dwell_time": round(float(trk.dwell_time), 1),
            "entity_name": trk.entity_name,
            "category": getattr(trk, "category", "person"),
            "is_cluttered": bool(getattr(trk, "is_cluttered", False)),
            "clutter_partner_id": getattr(trk, "clutter_partner_id", None),
            "state": trk.state,
        })
    return telemetry_tracks


def _build_zones_data(analytics: Optional[Any]) -> List[Dict[str, Any]]:
    """Serialize zones from analytics engine."""
    if not analytics:
        return []
    return [
        {
            "name": z.name,
            "occupancy": z.occupancy,
            "capacity_limit": getattr(z, "capacity_limit", None),
            "dwell_threshold": z.dwell_threshold,
            "is_breached": getattr(z, "_threshold_breached", False),
            "polygon": z.polygon.tolist() if hasattr(z.polygon, "tolist") else list(z.polygon),
        }
        for z in list(analytics.zones.values())
    ]


def _build_tripwires_data(analytics: Optional[Any]) -> List[Dict[str, Any]]:
    """Serialize tripwires from analytics engine."""
    if not analytics:
        return []
    return [
        {
            "name": tw.name,
            "in_count": tw.in_count,
            "out_count": tw.out_count,
            "line": list(tw.line_segment),
        }
        for tw in list(analytics.tripwires.values())
    ]


class StreamWorker:
    """Collaborator executing continuous background video pipeline loop."""

    def __init__(self, manager: Any) -> None:
        self.manager = manager

    def run(self) -> None:
        """Continuous pipeline loop executing detection, tracking, analytics, and frame drawing."""
        if not self.manager.video_source:
            return

        frame_count = 0
        consecutive_empty = 0
        fps_samples: List[float] = []
        last_t = time.time()

        with self.manager.video_source as vs:
            while self.manager._running and not self.manager._stop_event.is_set():
                if self._handle_hibernation(vs, frame_count):
                    continue

                ret, frame = vs.read(timeout=1.0)
                if not ret or frame is None:
                    consecutive_empty, should_skip = self._handle_empty_frame(vs, consecutive_empty)
                    if should_skip:
                        continue

                frame_count += 1
                consecutive_empty = 0
                frame = _resize_frame_if_needed(frame)
                curr_t = time.time()
                measured_fps, last_t = _measure_fps(curr_t, last_t, fps_samples)
                if frame_count % 30 == 1:
                    CameraHealthManager().set_online(self.manager.camera_id, fps=measured_fps)

                self._process_single_frame(frame, curr_t, measured_fps, frame_count)

    def _process_single_frame(
        self,
        frame: np.ndarray,
        curr_t: float,
        measured_fps: float,
        frame_count: int,
    ) -> None:
        """Process one frame through detection, tracking, overlays, and telemetry."""
        with self.manager._lock:
            self.manager._latest_raw_frame = frame.copy()

        tracks = self._process_vision_pipeline(frame, curr_t)
        self._encode_annotated_frame(frame, tracks, measured_fps)

        telemetry = self._build_telemetry(tracks, curr_t, measured_fps, frame.shape, frame_count)
        with self.manager._lock:
            self.manager._latest_telemetry = telemetry

        self.manager._broadcast_telemetry(telemetry)
        self.manager._stop_event.wait(timeout=0.01)

    def _handle_hibernation(self, vs: Any, frame_count: int) -> bool:
        """Pause video capture if zero viewers are connected to conserve compute."""
        if self.manager.subscriber_count <= 0 and frame_count > 0:
            if not self.manager._is_hibernating:
                self.manager._is_hibernating = True
                if hasattr(vs, "pause"):
                    vs.pause()
                with self.manager._lock:
                    if self.manager._latest_telemetry:
                        self.manager._latest_telemetry["fps"] = 0.0
                        self.manager._latest_telemetry["status"] = "hibernating"
            self.manager._stop_event.wait(timeout=0.2)
            return True

        if self.manager._is_hibernating:
            self.manager._is_hibernating = False
            if hasattr(vs, "resume"):
                vs.resume()
            with self.manager._lock:
                if self.manager._latest_telemetry:
                    self.manager._latest_telemetry["status"] = "online"
        return False

    def _handle_empty_frame(self, vs: Any, consecutive_empty: int) -> Tuple[int, bool]:
        """Handle missing frames, report diagnostics errors, and generate placeholders."""
        consecutive_empty += 1
        if consecutive_empty >= 4:
            err_code, err_msg = _diagnose_source_error(vs)
            CameraHealthManager().set_error(self.manager.camera_id, err_msg, error_code=err_code)
            with self.manager._lock:
                if self.manager._latest_jpeg is None or (
                    self.manager._latest_telemetry and self.manager._latest_telemetry.get("status") != "error"
                ):
                    self.manager._latest_jpeg = CameraHealthManager().create_error_placeholder_jpeg(
                        self.manager.camera_id, name=self.manager.name, width=self.manager.width, height=self.manager.height
                    )
                if self.manager._latest_telemetry:
                    self.manager._latest_telemetry["status"] = "error"
                    self.manager._latest_telemetry["fps"] = 0.0
                    self.manager._latest_telemetry["error_code"] = err_code
                    self.manager._latest_telemetry["error_msg"] = err_msg
            self.manager._stop_event.wait(timeout=0.5)
            return consecutive_empty, True

        self.manager._stop_event.wait(timeout=0.04)
        return consecutive_empty, True

    def _process_vision_pipeline(self, frame: np.ndarray, curr_t: float) -> Dict[int, Any]:
        """Execute detection, tracking, spatial analytics, and Re-ID matching."""
        detections = []
        if self.manager.detector:
            try:
                detections = self.manager.detector.detect(frame)
            except Exception as e:
                logger.debug("Detector error: %s", e)

        tracks = {}
        if self.manager.tracker:
            try:
                tracks = self.manager.tracker.update(detections, frame=frame)
            except Exception as e:
                logger.debug("Tracker error: %s", e)

        if self.manager.analytics:
            try:
                analytics_res = self.manager.analytics.update(tracks, timestamp=curr_t, current_frame=frame)
                self._handle_zone_exits(analytics_res, tracks, curr_t)
            except Exception as e:
                logger.warning("Analytics error: %s", e, exc_info=True)

        self._process_reid(tracks, frame)
        return tracks

    def _handle_zone_exits(
        self,
        analytics_res: Optional[Dict[str, Any]],
        tracks: Dict[int, Any],
        curr_t: float,
    ) -> None:
        """Trigger cross-camera topology predictive priors on zone exit events."""
        if not (self.manager.topology and analytics_res and "new_events" in analytics_res):
            return
        for ev_d in analytics_res.get("new_events", []):
            action = ev_d.get("action") or ev_d.get("event_type")
            if action in ("exit", "zone_exit"):
                z_name = ev_d.get("zone_id")
                tid = ev_d.get("track_id")
                t_obj = tracks.get(tid)
                ent_id = getattr(t_obj, "entity_id", None) if t_obj else None
                ent_name = (
                    getattr(t_obj, "entity_name", getattr(t_obj, "identity_label", f"Track #{tid}"))
                    if t_obj
                    else f"Track #{tid}"
                )
                self.manager.topology.record_zone_exit(
                    camera_id=self.manager.camera_id,
                    zone_name=z_name,
                    entity_name=ent_name,
                    entity_id=ent_id,
                    timestamp=curr_t,
                )

    def _process_reid(self, tracks: Dict[int, Any], frame: np.ndarray) -> None:
        """Perform Re-ID gallery matching with cross-camera topology priors."""
        if not (self.manager.gallery_matcher and tracks):
            return
        try:
            if self.manager.topology and self.manager.gallery_matcher.topology is None:
                self.manager.gallery_matcher.topology = self.manager.topology
            identified = self.manager.gallery_matcher.match_tracks(tracks, frame)
            for ev in identified:
                if self.manager.event_bus:
                    self.manager.event_bus.publish(ev)
        except Exception as e:
            logger.debug("Re-ID matching error: %s", e)

    def _encode_annotated_frame(self, frame: np.ndarray, tracks: Dict[int, Any], measured_fps: float) -> None:
        """Render floating overlays and compress annotated frame to JPEG."""
        annotated = self.manager._overlay_renderer.render(
            frame=frame,
            tracks=tracks,
            overlays=self.manager.overlays,
            camera_id=self.manager.camera_id,
            measured_fps=measured_fps,
            start_time=self.manager.start_time,
            analytics=self.manager.analytics,
            rsac_manager=self.manager.rsac_manager,
            homography=self.manager.homography,
            draw_heatmap=self.manager.draw_heatmap,
        )
        ret, buf = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if ret:
            with self.manager._lock:
                self.manager._latest_jpeg = buf.tobytes()

    def _build_telemetry(
        self,
        tracks: Dict[int, Any],
        curr_t: float,
        measured_fps: float,
        shape: Tuple[int, ...],
        frame_count: int,
    ) -> Dict[str, Any]:
        """Construct comprehensive telemetry payload with ground plane projections."""
        return {
            "camera_id": self.manager.camera_id,
            "status": "online",
            "timestamp": curr_t,
            "fps": round(measured_fps, 1),
            "resolution": f"{shape[1]}x{shape[0]}",
            "frame_count": frame_count,
            "homography_calibrated": self.manager.homography.is_calibrated,
            "overlays": dict(self.manager.overlays),
            "active_tracks": _extract_track_telemetry(tracks, self.manager.homography),
            "zones": _build_zones_data(self.manager.analytics),
            "tripwires": _build_tripwires_data(self.manager.analytics),
            "recent_alerts": _extract_recent_alerts(self.manager.event_bus),
        }
