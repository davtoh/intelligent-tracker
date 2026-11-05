#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Stream & Pipeline Manager.

Coordinates video ingestion, detection, multi-object tracking, spatial analytics,
Re-ID gallery matching, and event dispatching in a background worker thread.
Provides thread-safe MJPEG streaming and real-time telemetry push for WebSocket clients.
"""

import os
import time
import logging
import threading
from typing import Any, Dict, Optional

import numpy as np

from dashboard.services.stream_subscribers import StreamSubscriberRegistry, StreamSubscriberMixin
from dashboard.services.frame_overlay import FrameOverlayRenderer
from dashboard.services.stream_media import StreamMediaMixin
from dashboard.services.stream_worker import StreamWorker
from dashboard.services.pipeline_factory import StreamPipelineFactory, load_stream_config

from intelligent_tracker.video import VideoSource
from intelligent_tracker.analytics import AnalyticsEngine
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.matcher import GalleryMatcher
from intelligent_tracker.events import EventBus
from intelligent_tracker.homography import GroundPlaneHomography
from intelligent_tracker.topology import CrossCameraTopology
from intelligent_tracker.rsac import RSACManager
from intelligent_tracker.active_learning import ActiveLearningManager
from intelligent_tracker.enrollment import UniversalEnrollmentManager

logger = logging.getLogger("intelligent_tracker.dashboard")


def _default_telemetry(camera_id: str) -> Dict[str, Any]:
    """Default telemetry payload skeleton for initializing streams."""
    return {
        "camera_id": camera_id,
        "status": "initializing",
        "fps": 0.0,
        "frame_count": 0,
        "active_tracks": [],
        "zones": [],
        "tripwires": [],
        "recent_alerts": [],
    }


def _default_overlays() -> Dict[str, bool]:
    """Default visual overlay visibility flags."""
    return {
        "bboxes": True, "track_ids": True, "dwell_timers": True, "velocity": True,
        "zones": True, "tripwires": True, "heatmap": False, "bev_minimap": False,
        "hud_bar": True, "clutter": True,
    }


def _init_manager_config(
    manager: "StreamManager",
    config_path: Optional[str],
    db_path: Optional[str],
    custom_cfg: Optional[Dict[str, Any]],
) -> None:
    """Initialize stream configuration paths, database path, and empty component slots."""
    manager.config_path = config_path or os.environ.get("TRACKER_CONFIG", "configs/alert_demo.yaml")
    if not os.path.exists(manager.config_path) and os.path.exists("configs/demo.yaml"):
        manager.config_path = "configs/demo.yaml"

    manager.db_path = db_path or os.environ.get("TRACKER_DB", "data/tracker.db")
    loaded_cfg = load_stream_config(manager.config_path)
    manager.cfg = {**loaded_cfg, **custom_cfg} if custom_cfg else loaded_cfg

    manager.db = None
    manager.video_source = None
    manager.detector = None
    manager.tracker = None
    manager.analytics = None
    manager.reid_extractor = None
    manager.gallery_matcher = None
    manager.rsac_manager = None
    manager.active_learning = None
    manager.enrollment_manager = None
    manager.event_bus = None
    manager.event_pipeline = None


def _init_manager_runtime(manager: "StreamManager") -> None:
    """Initialize runtime threading locks, telemetry state, overlays, and collaborators."""
    manager._lock = threading.RLock()
    manager._thread = None
    manager._running = False
    manager._stop_event = threading.Event()
    manager._latest_jpeg = None
    manager._latest_raw_frame = None
    manager._latest_telemetry = _default_telemetry(manager.camera_id)
    manager.draw_heatmap = False
    manager.start_time = time.time()
    manager.homography = GroundPlaneHomography(camera_id=manager.camera_id)
    manager.topology = None
    manager.overlays = _default_overlays()
    manager._subscriber_registry = StreamSubscriberRegistry(
        resume_callback=manager._resume_video_source,
        lease_ttl=3.0,
    )
    manager._overlay_renderer = FrameOverlayRenderer()
    manager._subscribers = manager._subscriber_registry._subscribers
    manager._ws_subscribers = manager._subscriber_registry._ws_subscribers
    manager._subscriber_lock = manager._subscriber_registry._lock
    manager._worker = StreamWorker(manager)


class StreamManager(StreamSubscriberMixin, StreamMediaMixin):
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
    ) -> None:
        self.camera_id = camera_id
        self.name = name or f"Camera {camera_id.upper()}"
        self.source_override = source_override
        _init_manager_config(self, config_path, db_path, custom_cfg)
        _init_manager_runtime(self)
        self._init_subsystems()

    def _resume_video_source(self) -> None:
        """Callback to resume video capture when subscribers reconnect."""
        if self.video_source and hasattr(self.video_source, "resume"):
            self.video_source.resume()

    @property
    def is_running(self) -> bool:
        """Returns True if the background worker thread is active."""
        return self._running

    @property
    def width(self) -> int:
        """Stream frame width with fallback to video source or config."""
        if self.video_source and getattr(self.video_source, "width", None):
            return int(self.video_source.width)
        return int(self.cfg.get("video", {}).get("width", 640))

    @property
    def height(self) -> int:
        """Stream frame height with fallback to video source or config."""
        if self.video_source and getattr(self.video_source, "height", None):
            return int(self.video_source.height)
        return int(self.cfg.get("video", {}).get("height", 480))

    def _init_subsystems(self) -> None:
        """Instantiate database, video source, detector, tracker, analytics and Re-ID."""
        bundle = StreamPipelineFactory.build(
            cfg=self.cfg,
            db_path=self.db_path,
            camera_id=self.camera_id,
            source_override=self.source_override,
        )
        self.db = bundle.db
        self.video_source = bundle.video_source
        self.detector = bundle.detector
        self.tracker = bundle.tracker
        self.analytics = bundle.analytics
        self.reid_extractor = bundle.reid_extractor
        self.gallery_matcher = bundle.gallery_matcher
        self.rsac_manager = bundle.rsac_manager
        self.active_learning = bundle.active_learning
        self.enrollment_manager = bundle.enrollment_manager
        self.event_bus = bundle.event_bus
        self.event_pipeline = bundle.event_pipeline
        self._latest_jpeg = self._create_placeholder_jpeg("Camera Initializing...")

    def signal_stop(self) -> None:
        """Signal worker loop and video source to terminate immediately without waiting."""
        self._running = False
        self._stop_event.set()
        if self.video_source and hasattr(self.video_source, "signal_stop"):
            try:
                self.video_source.signal_stop()
            except Exception:
                pass

    def start(self) -> None:
        """Start background processing loop."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._worker_loop, name="StreamManagerWorker", daemon=True)
            self._thread.start()
            logger.info("StreamManager background worker started for %s", self.camera_id)

    def stop(self) -> None:
        """Stop background worker cleanly."""
        self.signal_stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.6)
        with self._lock:
            if self.video_source:
                self.video_source.release()
            if self.event_pipeline:
                if "rule_engine" in self.event_pipeline and hasattr(self.event_pipeline["rule_engine"], "stop"):
                    self.event_pipeline["rule_engine"].stop()
                if "event_bus" in self.event_pipeline and hasattr(self.event_pipeline["event_bus"], "stop"):
                    self.event_pipeline["event_bus"].stop()
            elif self.event_bus and hasattr(self.event_bus, "stop"):
                self.event_bus.stop()
            logger.info("StreamManager stopped for %s", self.camera_id)

    def _worker_loop(self) -> None:
        """Continuous pipeline loop executing detection, tracking, analytics, and frame drawing."""
        self._worker.run()
