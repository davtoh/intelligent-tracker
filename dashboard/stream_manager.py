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

        # WebSocket Subscribers: list of async queues or callback callables
        self._ws_subscribers: List[Any] = []
        self._ws_lock = threading.Lock()

        # Active Subscribers Tracking & Smart Hibernation
        self._subscriber_count = 0
        self._subscriber_lock = threading.Lock()

        # Initialize Subsystems
        self._init_subsystems()

    def add_subscriber(self) -> int:
        """Register an active client subscriber (MJPEG stream or WebSocket)."""
        with self._subscriber_lock:
            self._subscriber_count += 1
            return self._subscriber_count

    def remove_subscriber(self) -> int:
        """Unregister an active client subscriber."""
        with self._subscriber_lock:
            self._subscriber_count = max(0, self._subscriber_count - 1)
            return self._subscriber_count

    @property
    def subscriber_count(self) -> int:
        """Current number of active subscribers."""
        with self._subscriber_lock:
            return self._subscriber_count

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
                    time.sleep(0.1)
                    continue

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

                # 5. Render Annotated Frame with Customizable Overlay Flags
                annotated = frame.copy()
                h, w = annotated.shape[:2]

                # Draw Heatmap if enabled
                if (self.draw_heatmap or self.overlays.get("heatmap", False)) and self.analytics:
                    try:
                        annotated = self.analytics.draw_heatmap_overlay(annotated, alpha=0.55)
                    except Exception:
                        pass

                # Draw Zones
                if self.overlays.get("zones", True) and self.analytics:
                    for zone in list(self.analytics.zones.values()):
                        pts = zone.polygon.reshape((-1, 1, 2)).astype(np.int32)
                        is_breached = getattr(zone, "_threshold_breached", False)
                        z_col = (0, 0, 255) if is_breached else zone.color
                        # Semi-transparent fill
                        overlay = annotated.copy()
                        cv2.fillPoly(overlay, [pts], z_col)
                        cv2.addWeighted(overlay, 0.25, annotated, 0.75, 0, annotated)
                        cv2.polylines(annotated, [pts], True, z_col, 2)
                        # Label
                        M = cv2.moments(pts)
                        if M["m00"] != 0:
                            cx = int(M["m10"] / M["m00"])
                            cy = int(M["m01"] / M["m00"])
                        else:
                            cx, cy = pts[0][0][0], pts[0][0][1]
                        cap_text = f"/{zone.capacity_limit}" if getattr(zone, "capacity_limit", None) else ""
                        tag = f"{zone.name} [{zone.occupancy}{cap_text}]"
                        cv2.putText(annotated, tag, (cx - 30, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

                # Draw Tripwires
                if self.overlays.get("tripwires", True) and self.analytics:
                    for tw in list(self.analytics.tripwires.values()):
                        p1, p2 = tw.line_segment
                        ip1 = (int(round(p1[0])), int(round(p1[1])))
                        ip2 = (int(round(p2[0])), int(round(p2[1])))
                        cv2.line(annotated, ip1, ip2, tw.color, 2)
                        mid = ((ip1[0] + ip2[0]) // 2, (ip1[1] + ip2[1]) // 2)
                        tw_tag = f"{tw.name}: IN={tw.in_count} OUT={tw.out_count}"
                        cv2.putText(annotated, tw_tag, (mid[0] + 5, mid[1] - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, tw.color, 1)

                # Draw Tracks (Bounding Boxes, Labels, Dwell Timers, Velocity Vectors)
                for tid, trk in list(tracks.items()):
                    bx, by, bw, bh = trk.bbox
                    color = (0, 255, 0)
                    cat_id = getattr(trk, "category", "person")
                    if self.rsac_manager:
                        cat_obj = self.rsac_manager.get_category(cat_id)
                        if cat_obj and cat_obj.color:
                            hex_c = cat_obj.color.lstrip("#")
                            if len(hex_c) == 6:
                                r, g, b = int(hex_c[0:2], 16), int(hex_c[2:4], 16), int(hex_c[4:6], 16)
                                color = (b, g, r)
                    if hasattr(trk, "category") and trk.category == "restricted":
                        color = (0, 0, 255)
                    elif hasattr(trk, "category") and trk.category == "vip":
                        color = (0, 215, 255)
                    elif trk.state == "predicting":
                        color = (255, 165, 0)

                    # Bounding Box
                    if self.overlays.get("bboxes", True):
                        cv2.rectangle(annotated, (bx, by), (bx + bw, by + bh), color, 2)

                    # Clutter / Interacting warning banner
                    if getattr(trk, "is_cluttered", False) and self.overlays.get("clutter", True):
                        partner_info = f" with #{trk.clutter_partner_id}" if getattr(trk, "clutter_partner_id", None) else ""
                        clutter_tag = f"[CLUTTER{partner_info}]"
                        cv2.putText(annotated, clutter_tag, (bx, by + bh + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 140, 255), 2)

                    # Track Label & Dwell Timer
                    if self.overlays.get("track_ids", True):
                        name_disp = trk.entity_name or trk.identity_label or f"#{tid}"
                        dwell_str = f" [{trk.dwell_time:.1f}s]" if self.overlays.get("dwell_timers", True) else ""
                        hud_text = f"{name_disp} ({trk.confidence:.2f}){dwell_str}"
                        cv2.putText(annotated, hud_text, (bx, max(15, by - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

                    # Velocity Vector
                    if self.overlays.get("velocity", True):
                        vx, vy = trk.velocity if hasattr(trk, "velocity") else (0.0, 0.0)
                        if np.hypot(vx, vy) > 0.5:
                            cx, cy = trk.centroid
                            cv2.arrowedLine(
                                annotated,
                                (int(cx), int(cy)),
                                (int(cx + vx * 3), int(cy + vy * 3)),
                                (255, 255, 0),
                                2,
                                tipLength=0.3,
                            )

                # Top Status HUD bar
                if self.overlays.get("hud_bar", True):
                    uptime = int(time.time() - self.start_time)
                    hud_summary = f"CAM: {self.camera_id} | FPS: {measured_fps:.1f} | TRACKS: {len(tracks)} | TIME: {uptime}s"
                    cv2.rectangle(annotated, (0, 0), (w, 24), (15, 23, 42), -1)
                    cv2.putText(annotated, hud_summary, (10, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 220, 255), 1)

                # BEV Minimap Picture-in-Picture (PiP) Overlay
                if self.overlays.get("bev_minimap", False) and self.homography:
                    try:
                        pip_size = (160, 160)
                        bev_small = self.homography.render_bev_minimap(
                            tracks,
                            zones=self.analytics.zones if self.analytics else None,
                            canvas_size=pip_size,
                            margin=16,
                        )
                        # Place in bottom-right corner
                        px, py = w - pip_size[0] - 12, h - pip_size[1] - 12
                        if px > 0 and py > 0:
                            annotated[py:py + pip_size[1], px:px + pip_size[0]] = bev_small
                            cv2.rectangle(annotated, (px, py), (px + pip_size[0], py + pip_size[1]), (0, 220, 255), 1)
                    except Exception as e:
                        logger.debug("BEV PiP overlay error: %s", e)

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
        with self._ws_lock:
            dead = []
            for sub in self._ws_subscribers:
                try:
                    if hasattr(sub, "put_nowait"):
                        sub.put_nowait(telemetry)
                    elif callable(sub):
                        sub(telemetry)
                except Exception:
                    dead.append(sub)
            for d in dead:
                self._ws_subscribers.remove(d)
                self.remove_subscriber()

    def register_ws_subscriber(self, sub: Any):
        with self._ws_lock:
            if sub not in self._ws_subscribers:
                self._ws_subscribers.append(sub)
                self.add_subscriber()

    def unregister_ws_subscriber(self, sub: Any):
        with self._ws_lock:
            if sub in self._ws_subscribers:
                self._ws_subscribers.remove(sub)
                self.remove_subscriber()

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
        Interactive click-to-tag bounding box capability:
        Extracts crop from current frame, generates Re-ID embedding, registers into SQLite database,
        and links live track identity.
        """
        if not self.db:
            raise RuntimeError("Database not available")

        with self._lock:
            raw_frame = None
            if self._latest_raw_frame is not None:
                raw_frame = self._latest_raw_frame.copy()

        if raw_frame is None:
            raise RuntimeError("No video frame available to extract visual signature")

        # Resolve bounding box
        target_bbox = None
        if bbox and len(bbox) == 4:
            target_bbox = bbox
        elif track_id is not None and self.tracker:
            for tid, trk in self.tracker.tracks.items():
                if tid == track_id:
                    target_bbox = list(trk.bbox)
                    break

        if not target_bbox:
            # Fallback center crop if bbox not provided
            h, w = raw_frame.shape[:2]
            target_bbox = [w // 4, h // 4, w // 2, h // 2]

        bx, by, bw, bh = [int(v) for v in target_bbox]
        h, w = raw_frame.shape[:2]
        x1 = max(0, min(w - 1, bx))
        y1 = max(0, min(h - 1, by))
        x2 = max(x1 + 1, min(w, bx + bw))
        y2 = max(y1 + 1, min(h, by + bh))
        crop = raw_frame[y1:y2, x1:x2]

        # Check or add entity
        existing = self.db.get_entity_by_name(entity_name)
        if existing:
            entity_id = existing["id"]
            if category:
                self.db.update_entity(entity_id, category=category, notes=notes)
        else:
            entity_id = self.db.add_entity(name=entity_name, category=category, notes=notes)

        # Generate Re-ID Embedding
        emb = None
        if self.reid_extractor and crop.size > 0:
            try:
                emb = self.reid_extractor.extract_crop(crop)
            except Exception as e:
                logger.warning("Failed to compute Re-ID embedding for tag: %s", e)

        if emb is None or not isinstance(emb, np.ndarray):
            # Synthetic 128-dim embedding fallback
            vec = np.random.randn(128).astype(np.float32)
            emb = vec / (np.linalg.norm(vec) + 1e-7)

        # Save thumbnail crop
        crop_rel_path = f"data/crops/{entity_name.lower().replace(' ', '_')}_{int(time.time())}.jpg"
        abs_crop_path = os.path.abspath(crop_rel_path)
        os.makedirs(os.path.dirname(abs_crop_path), exist_ok=True)
        cv2.imwrite(abs_crop_path, crop)

        sig_id = self.db.add_signature(entity_id=entity_id, embedding=emb, crop_path=crop_rel_path)

        # Record immediate sighting
        self.db.record_sighting(
            entity_id=entity_id,
            track_id=track_id or 0,
            source=self.camera_id,
            zone_id="manual_tag",
            bbox=f"{bx},{by},{bw},{bh}",
            confidence=1.0,
            snapshot_path=crop_rel_path,
        )

        # Update in-memory tracker track
        if track_id is not None and self.tracker:
            for tid, trk in self.tracker.tracks.items():
                if tid == track_id:
                    trk.entity_name = entity_name
                    trk.category = category
                    break

        # Refresh gallery
        if self.gallery_matcher:
            try:
                self.gallery_matcher.refresh_gallery()
            except Exception:
                pass

        logger.info("Successfully tagged entity '%s' (ID #%d, sig #%d)", entity_name, entity_id, sig_id)
        return {
            "entity_id": entity_id,
            "name": entity_name,
            "category": category,
            "signature_id": sig_id,
            "crop_path": crop_rel_path,
        }
