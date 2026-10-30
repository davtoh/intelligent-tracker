#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Stream & Pipeline Manager.

Coordinates video ingestion, detection, multi-object tracking, spatial analytics,
Re-ID gallery matching, and event dispatching in a background worker thread.
Provides thread-safe MJPEG streaming and real-time telemetry push for WebSocket clients.
"""

import os
import sys
import time
import io
import json
import uuid
import base64
import logging
import threading
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import asdict

import cv2
import numpy as np

try:
    import yaml
except ImportError:
    yaml = None

from dashboard.services.stream_subscribers import StreamSubscriberRegistry
from dashboard.services.frame_overlay import FrameOverlayRenderer
from dashboard.services.entity_tagger import EntityTaggerService

from intelligent_tracker.video import VideoSource, resolve_camera_source
from intelligent_tracker.detectors import DetectorFactory
from intelligent_tracker.tracker import TrackerFactory
from intelligent_tracker.geometry import Tripwire, ZoneROI
from intelligent_tracker.analytics import AnalyticsEngine
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.reid import ReIDExtractorFactory
from intelligent_tracker.matcher import GalleryMatcher
from intelligent_tracker.events import setup_event_pipeline, EventBus, frame_to_base64, crop_to_base64
from intelligent_tracker.homography import GroundPlaneHomography
from intelligent_tracker.topology import CrossCameraTopology
from intelligent_tracker.rsac import RSACManager
from intelligent_tracker.active_learning import ActiveLearningManager
from intelligent_tracker.enrollment import UniversalEnrollmentManager

logger = logging.getLogger("intelligent_tracker.dashboard")


class StreamManager:
    """
    Manages live camera feeds, AI inference pipelines, MJPEG frame encoding,
    and real-time telemetry distribution for the web dashboard.
    """

    def __init__(
        self,
        config_path: Optional[str] = None,
        db_path: Optional[str] = None,
        camera_id: str = "cam_01",
        name: Optional[str] = None,
        source_override: Optional[Any] = None,
        custom_cfg: Optional[Dict[str, Any]] = None,
    ):
        self.camera_id = camera_id
        self.name = name or f"Camera {camera_id.upper()}"
        self.source_override = source_override
        self.config_path = config_path or os.environ.get("TRACKER_CONFIG", "configs/alert_demo.yaml")
        if not os.path.exists(self.config_path) and os.path.exists("configs/demo.yaml"):
            self.config_path = "configs/demo.yaml"

        self.db_path = db_path or os.environ.get("TRACKER_DB", "data/tracker.db")
        loaded_cfg = self._load_config(self.config_path)
        if custom_cfg:
            self.cfg = {**loaded_cfg, **custom_cfg}
        else:
            self.cfg = loaded_cfg

        # Core Components
        self.db: Optional[TrackerDB] = None
        self.video_source: Optional[VideoSource] = None
        self.detector = None
        self.tracker = None
        self.analytics: Optional[AnalyticsEngine] = None
        self.reid_extractor = None
        self.gallery_matcher: Optional[GalleryMatcher] = None
        self.rsac_manager: Optional[RSACManager] = None
        self.active_learning: Optional[ActiveLearningManager] = None
        self.enrollment_manager: Optional[UniversalEnrollmentManager] = None
        self.event_bus: Optional[EventBus] = None
        self.event_pipeline = None

        # Threading & Stream State
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._latest_jpeg: Optional[bytes] = None
        self._latest_raw_frame: Optional[np.ndarray] = None
        self._latest_telemetry: Dict[str, Any] = {
            "camera_id": self.camera_id,
            "status": "initializing",
            "fps": 0.0,
            "frame_count": 0,
            "active_tracks": [],
            "zones": [],
            "tripwires": [],
            "recent_alerts": [],
        }
        self.draw_heatmap = False
        self.start_time = time.time()

        # Milestone 8 & 9: Homography, Topology, RSAC & Overlay Controls
        self.homography = GroundPlaneHomography(camera_id=self.camera_id)
        self.topology: Optional[CrossCameraTopology] = None
        self.overlays: Dict[str, bool] = {
            "bboxes": True,
            "track_ids": True,
            "dwell_timers": True,
            "velocity": True,
            "zones": True,
            "tripwires": True,
            "heatmap": False,
            "bev_minimap": False,
            "hud_bar": True,
            "clutter": True,
        }

        # WebSocket Subscribers & Active Subscribers Tracking (Self-Healing Leased Registry)
        self._subscriber_registry = StreamSubscriberRegistry(
            resume_callback=self._resume_video_source,
            lease_ttl=3.0,
        )
        self._overlay_renderer = FrameOverlayRenderer()
        # Aliases for backward compatibility
        self._subscribers = self._subscriber_registry._subscribers
        self._ws_subscribers = self._subscriber_registry._ws_subscribers
        self._subscriber_lock = self._subscriber_registry._lock

        # Initialize Subsystems
        self._init_subsystems()

    def _resume_video_source(self) -> None:
        """Callback to resume video capture when subscribers reconnect."""
        if self.video_source and hasattr(self.video_source, "resume"):
            self.video_source.resume()

    def add_subscriber(self, sub_id: Optional[str] = None) -> str:
        """Register an active client subscriber (MJPEG stream or WebSocket) with a leased token."""
        return self._subscriber_registry.add_subscriber(sub_id)

    def heartbeat_subscriber(self, sub_id: str) -> None:
        """Update last-seen timestamp for an active leased subscriber."""
        self._subscriber_registry.heartbeat_subscriber(sub_id)

    def remove_subscriber(self, sub_id: Optional[str] = None) -> int:
        """Unregister an active client subscriber by token or pop one."""
        return self._subscriber_registry.remove_subscriber(sub_id)

    def _active_subscriber_count_unlocked(self) -> int:
        """Internal helper to prune expired subscriber leases and count active viewers."""
        return self._subscriber_registry._active_subscriber_count_unlocked()

    @property
    def subscriber_count(self) -> int:
        """Current number of active, non-expired subscribers."""
        return self._subscriber_registry.subscriber_count

    @property
    def is_hibernating(self) -> bool:
        """Returns True if the stream is currently hibernating due to zero subscribers."""
        return self._subscriber_registry.is_hibernating

    @is_hibernating.setter
    def is_hibernating(self, val: bool) -> None:
        self._subscriber_registry.is_hibernating = val

    @property
    def _is_hibernating(self) -> bool:
        """Alias for backward compatibility."""
        return self._subscriber_registry.is_hibernating

    @_is_hibernating.setter
    def _is_hibernating(self, val: bool) -> None:
        self._subscriber_registry.is_hibernating = val

    @property
    def is_running(self) -> bool:
        """Returns True if the background worker thread is active."""
        return self._running

    def _load_config(self, path: Optional[str]) -> Dict[str, Any]:
        if not path or not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                if yaml is not None and path.endswith((".yaml", ".yml")):
                    return yaml.safe_load(f) or {}
                return json.load(f) or {}
        except Exception as e:
            logger.warning("Failed to load config %s: %s", path, e)
            return {}

    def _init_subsystems(self):
        """Instantiate database, video source, detector, tracker, analytics and Re-ID."""
        # 1. Database
        try:
            self.db = TrackerDB(self.db_path)
        except Exception as e:
            logger.error("Database initialization failed: %s", e)
            self.db = None

        # 2. Config sections
        video_cfg = self.cfg.get("video", {})
        detector_cfg = self.cfg.get("detector", {})
        tracker_cfg = self.cfg.get("tracker", {})
        analytics_cfg = self.cfg.get("analytics", {})
        reid_cfg = self.cfg.get("reid", {})

        # Resolution
        res = video_cfg.get("resolution", [640, 480])
        res_w, res_h = (int(res[0]), int(res[1])) if isinstance(res, (list, tuple)) else (640, 480)

        # Source
        raw_source = self.source_override if self.source_override is not None else video_cfg.get("source", "synthetic")
        if str(raw_source).lower() in ("synthetic", "mock"):
            source = "synthetic"
        else:
            source = resolve_camera_source(raw_source)

        # VideoSource
        fps_target = float(video_cfg.get("framerate", 30))
        is_file_source = False
        if isinstance(source, str) and (os.path.exists(source) or source.lower().endswith((".mp4", ".avi", ".mkv", ".mov"))):
            is_file_source = True

        self.video_source = VideoSource(
            source=source,
            buffer_size=int(video_cfg.get("buffer_size", 1)),
            auto_reconnect=bool(video_cfg.get("auto_reconnect", True)),
            fps_limit=fps_target,
            width=res_w,
            height=res_h,
            loop_video=is_file_source or bool(video_cfg.get("loop", True)),
        )

        # Detector
        det_name = detector_cfg.get("model", "mock")
        det_conf = float(detector_cfg.get("confidence", 0.25))
        det_kwargs = {"conf_threshold": det_conf} if det_name in ("yolov8", "yolo11", "onnx") else {}
        try:
            self.detector = DetectorFactory.create(det_name, **det_kwargs)
        except Exception as e:
            logger.warning("Preferred detector '%s' failed (%s), falling back to mock detector", det_name, e)
            self.detector = DetectorFactory.create("mock")

        # Tracker
        trk_name = tracker_cfg.get("type", "centroid")
        self.tracker = TrackerFactory.create(
            trk_name,
            max_disappeared=int(tracker_cfg.get("max_disappeared", 30)),
            min_hits=int(tracker_cfg.get("min_hits", 2)),
            iou_threshold=float(tracker_cfg.get("iou_threshold", 0.2)),
        )

        # Analytics Engine
        heatmap_cfg = analytics_cfg.get("heatmap", {})
        active_w = getattr(self.video_source, "width", res_w)
        active_h = getattr(self.video_source, "height", res_h)
        self.analytics = AnalyticsEngine(
            resolution=(active_w, active_h),
            heatmap_enabled=bool(heatmap_cfg.get("enabled", True)),
            heatmap_decay=float(heatmap_cfg.get("decay", 0.998)) if heatmap_cfg.get("decay") else None,
            camera_id=self.camera_id,
        )

        # Add Zones & Tripwires from config
        for tw_data in analytics_cfg.get("tripwires", []):
            tw_line = tw_data.get("line")
            if tw_line and len(tw_line) >= 2:
                tw = Tripwire(
                    line_segment=tw_line,
                    name=tw_data.get("name", "tripwire"),
                    bidirectional=bool(tw_data.get("bidirectional", True)),
                    color=tuple(tw_data.get("color", [0, 255, 255])),
                )
                self.analytics.add_tripwire(tw)

        for z_data in analytics_cfg.get("zones", []):
            z_poly = z_data.get("polygon")
            if z_poly and len(z_poly) >= 3:
                zone = ZoneROI(
                    polygon=z_poly,
                    name=z_data.get("name", "zone"),
                    dwell_threshold=float(z_data.get("dwell_threshold", 5.0)),
                    color=tuple(z_data.get("color", [0, 200, 100])),
                    capacity_limit=z_data.get("capacity_limit", z_data.get("max_occupancy")),
                )
                self.analytics.add_zone(zone)

        # Re-ID & Gallery Matcher
        reid_name = reid_cfg.get("model", "color")
        if reid_name and self.db:
            try:
                self.reid_extractor = ReIDExtractorFactory.create(reid_name)
                self.gallery_matcher = GalleryMatcher(
                    db=self.db,
                    extractor=self.reid_extractor,
                    reid_threshold=float(reid_cfg.get("threshold", 0.65)),
                )
            except Exception as e:
                logger.warning("Re-ID initialization warning: %s", e)

        # Event Dispatcher & Alerting Pipeline
        alert_cfg = self.cfg.get("alerting", self.cfg.get("events"))
        if alert_cfg:
            try:
                self.event_pipeline = setup_event_pipeline(self.cfg)
                self.event_bus = self.event_pipeline.get("event_bus")
                self.analytics.event_bus = self.event_bus
            except Exception as e:
                logger.warning("Event pipeline setup warning: %s", e)
        if self.event_bus is None:
            self.event_bus = EventBus(capacity=500)
            self.analytics.event_bus = self.event_bus

        # RSAC Manager & Analytics integration (Milestone 9)
        if self.db:
            try:
                self.rsac_manager = RSACManager(db=self.db)
                if self.analytics:
                    self.analytics.rsac_manager = self.rsac_manager
            except Exception as e:
                logger.warning("RSACManager initialization warning: %s", e)

        # Active Learning & Universal Enrollment (Milestone 9)
        if self.db:
            try:
                self.active_learning = ActiveLearningManager(
                    db=self.db,
                    matcher=self.gallery_matcher,
                    event_bus=self.event_bus,
                )
                if self.gallery_matcher:
                    self.gallery_matcher.active_learning = self.active_learning

                self.enrollment_manager = UniversalEnrollmentManager(
                    db=self.db,
                    extractor=self.reid_extractor,
                    matcher=self.gallery_matcher,
                )
            except Exception as e:
                logger.warning("ActiveLearning / Enrollment initialization warning: %s", e)

        # Default synthetic placeholder image
        self._latest_jpeg = self._create_placeholder_jpeg("Camera Initializing...")

    def _create_placeholder_jpeg(self, text: str) -> bytes:
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        img[:] = (20, 24, 33)  # Slate dark
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

    def start(self):
        """Start background processing loop."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._worker_loop, name="StreamManagerWorker", daemon=True)
            self._thread.start()
            logger.info("StreamManager background worker started for %s", self.camera_id)

    def stop(self):
        """Stop background worker cleanly."""
        with self._lock:
            self._running = False
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=2.0)
            if self.video_source:
                self.video_source.release()
            if self.event_pipeline and "rule_engine" in self.event_pipeline:
                if hasattr(self.event_pipeline["rule_engine"], "stop"):
                    self.event_pipeline["rule_engine"].stop()
            logger.info("StreamManager stopped for %s", self.camera_id)

    def _worker_loop(self):
        """Continuous pipeline loop executing detection, tracking, analytics, and frame drawing."""
        if not self.video_source:
            return

        frame_count = 0
        fps_samples = []
        last_t = time.time()

        with self.video_source as vs:
            while self._running:
                # Smart Hibernation: if no active viewers are connected and we have processed
                # at least one frame (to initialize telemetry & preview), sleep to conserve CPU.
                if self.subscriber_count <= 0 and frame_count > 0:
                    if not self._is_hibernating:
                        self._is_hibernating = True
                        if hasattr(vs, "pause"):
                            vs.pause()
                        with self._lock:
                            if self._latest_telemetry:
                                self._latest_telemetry["fps"] = 0.0
                                self._latest_telemetry["status"] = "hibernating"
                    time.sleep(0.2)
                    continue

                if self._is_hibernating:
                    self._is_hibernating = False
                    if hasattr(vs, "resume"):
                        vs.resume()
                    with self._lock:
                        if self._latest_telemetry:
                            self._latest_telemetry["status"] = "online"

                ret, frame = vs.read(timeout=1.0)
                if not ret or frame is None:
                    time.sleep(0.02)
                    continue

                # Protect downstream pipelines, browser rendering, and network from oversized frames
                max_dim = 1280
                h, w = frame.shape[:2]
                if w > max_dim or h > max_dim:
                    scale = max_dim / float(max(w, h))
                    frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

                frame_count += 1
                curr_t = time.time()
                dt = curr_t - last_t
                last_t = curr_t
                if dt > 0:
                    fps_samples.append(1.0 / dt)
                    if len(fps_samples) > 30:
                        fps_samples.pop(0)
                measured_fps = float(np.mean(fps_samples)) if fps_samples else 30.0

                with self._lock:
                    self._latest_raw_frame = frame.copy()

                # 1. Detection
                detections = []
                if self.detector:
                    try:
                        detections = self.detector.detect(frame)
                    except Exception as e:
                        logger.debug("Detector error: %s", e)

                # 2. Tracking
                tracks = {}
                if self.tracker:
                    try:
                        tracks = self.tracker.update(detections, frame=frame)
                    except Exception as e:
                        logger.debug("Tracker error: %s", e)

                # 3. Spatial Analytics
                if self.analytics:
                    try:
                        analytics_res = self.analytics.update(tracks, frame_time=curr_t, current_frame=frame)
                        # Milestone 8: Trigger Cross-Camera Topology Predictive Priors on Zone Exit
                        if self.topology and analytics_res and "new_events" in analytics_res:
                            for ev_d in analytics_res.get("new_events", []):
                                if ev_d.get("event_type") == "zone" and ev_d.get("action") == "exit":
                                    z_name = ev_d.get("zone_id")
                                    tid = ev_d.get("track_id")
                                    t_obj = tracks.get(tid)
                                    ent_id = getattr(t_obj, "entity_id", None) if t_obj else None
                                    ent_name = getattr(t_obj, "entity_name", getattr(t_obj, "identity_label", f"Track #{tid}")) if t_obj else f"Track #{tid}"
                                    self.topology.record_zone_exit(
                                        camera_id=self.camera_id,
                                        zone_name=z_name,
                                        entity_name=ent_name,
                                        entity_id=ent_id,
                                        timestamp=curr_t,
                                    )
                    except Exception as e:
                        logger.debug("Analytics error: %s", e)

                # 4. Re-ID Gallery Matching (with Cross-Camera Topology Priors)
                if self.gallery_matcher and tracks:
                    try:
                        if self.topology and self.gallery_matcher.topology is None:
                            self.gallery_matcher.topology = self.topology
                        identified = self.gallery_matcher.match_tracks(tracks, frame)
                        for ev in identified:
                            if self.event_bus:
                                self.event_bus.publish(ev)
                    except Exception as e:
                        logger.debug("Re-ID matching error: %s", e)

                # 5. Render Annotated Frame with Customizable Overlay Flags via FrameOverlayRenderer
                annotated = self._overlay_renderer.render(
                    frame=frame,
                    tracks=tracks,
                    overlays=self.overlays,
                    analytics=self.analytics,
                    draw_heatmap=self.draw_heatmap,
                    rsac_manager=self.rsac_manager,
                    homography=self.homography,
                    camera_id=self.camera_id,
                    measured_fps=measured_fps,
                    start_time=self.start_time,
                )

                # Compress to JPEG
                ret, buf = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if ret:
                    jpeg_bytes = buf.tobytes()
                    with self._lock:
                        self._latest_jpeg = jpeg_bytes

                # Build Telemetry with Ground Coordinates
                recent_alerts = []
                if self.event_bus:
                    for ev in self.event_bus.get_recent_events(limit=8):
                        if hasattr(ev, "to_dict"):
                            recent_alerts.append(ev.to_dict())
                        elif hasattr(ev, "__dataclass_fields__"):
                            recent_alerts.append(asdict(ev))
                        else:
                            recent_alerts.append({"event_type": getattr(ev, "event_type", "event")})

                # Compute ground coordinates for active tracks
                active_tracks_telemetry = []
                for tid, trk in tracks.items():
                    gx, gy = self.homography.track_to_ground(trk.bbox)
                    active_tracks_telemetry.append({
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

                telemetry = {
                    "camera_id": self.camera_id,
                    "status": "online",
                    "timestamp": curr_t,
                    "fps": round(measured_fps, 1),
                    "resolution": f"{frame.shape[1]}x{frame.shape[0]}",
                    "frame_count": frame_count,
                    "homography_calibrated": self.homography.is_calibrated,
                    "overlays": dict(self.overlays),
                    "active_tracks": active_tracks_telemetry,
                    "zones": [
                        {
                            "name": z.name,
                            "occupancy": z.occupancy,
                            "capacity_limit": getattr(z, "capacity_limit", None),
                            "dwell_threshold": z.dwell_threshold,
                            "is_breached": getattr(z, "_threshold_breached", False),
                            "polygon": z.polygon.tolist() if hasattr(z.polygon, "tolist") else list(z.polygon),
                        }
                        for z in (list(self.analytics.zones.values()) if self.analytics else [])
                    ],
                    "tripwires": [
                        {
                            "name": tw.name,
                            "in_count": tw.in_count,
                            "out_count": tw.out_count,
                            "line": list(tw.line_segment),
                        }
                        for tw in (list(self.analytics.tripwires.values()) if self.analytics else [])
                    ],
                    "recent_alerts": recent_alerts,
                }

                with self._lock:
                    self._latest_telemetry = telemetry

                # Push to active WebSocket subscribers
                self._broadcast_telemetry(telemetry)

                # Target framerate pace
                time.sleep(0.01)

    def _broadcast_telemetry(self, telemetry: Dict[str, Any]):
        """Distribute telemetry to registered async queues."""
        self._subscriber_registry.broadcast_telemetry(telemetry)

    def register_ws_subscriber(self, sub: Any):
        self._subscriber_registry.register_ws_subscriber(sub)

    def unregister_ws_subscriber(self, sub: Any):
        self._subscriber_registry.unregister_ws_subscriber(sub)

    def get_latest_frame_jpeg(self, camera_id: Optional[str] = None) -> bytes:
        with self._lock:
            if self._latest_jpeg is not None:
                return self._latest_jpeg
            return self._create_placeholder_jpeg("Waiting for stream...")

    def get_latest_telemetry(self, camera_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            return dict(self._latest_telemetry)

    def get_heatmap_jpeg(self) -> bytes:
        """Render accumulated spatial occupancy heatmap as JPEG."""
        if not self.analytics or not self.analytics.heatmap:
            return self._create_placeholder_jpeg("Heatmap Not Initialized")
        hm_colored = self.analytics.heatmap.get_colored_map()
        ret, buf = cv2.imencode(".jpg", hm_colored, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        return buf.tobytes() if ret else b""

    def toggle_heatmap(self, enabled: Optional[bool] = None) -> bool:
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
        """
        Interactive click-to-tag bounding box capability.
        Delegates to EntityTaggerService for Re-ID visual registration.
        """
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
