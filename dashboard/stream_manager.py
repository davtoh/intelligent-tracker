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

from dashboard.services.stream_subscribers import StreamSubscriberRegistry, StreamSubscriberMixin
from dashboard.services.frame_overlay import FrameOverlayRenderer
from dashboard.services.stream_media import StreamMediaMixin
from dashboard.services.stream_recording import StreamRecordingController, StreamRecordingMixin
from dashboard.services.stream_worker import StreamWorker
from dashboard.services.pipeline_factory import StreamPipelineFactory, load_stream_config
from dashboard.services.multiview.thumbnail_cache import ThumbnailCache

from intelligent_tracker.homography import GroundPlaneHomography
from intelligent_tracker.world import WorldGraph

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
        "recording": {"camera_id": camera_id, "is_recording": False, "status": "idle"},
    }


def _default_overlays() -> Dict[str, bool]:
    """Default visual overlay visibility flags."""
    return {
        "bboxes": True, "track_ids": True, "dwell_timers": True, "velocity": True,
        "zones": True, "tripwires": True, "heatmap": False, "bev_minimap": False,
        "hud_bar": True, "clutter": True,
    }


def _fallback_close_manager_resources(manager: "StreamManager") -> None:
    """Release StreamManager resources when no PipelineBundle is attached."""
    if getattr(manager, "video_source", None):
        manager.video_source.release()
    if getattr(manager, "world_rule_engine", None) is not None:
        manager.world_rule_engine.stop()
    pipe_bus = None
    if getattr(manager, "event_pipeline", None):
        rule_eng = manager.event_pipeline.get("rule_engine")
        if rule_eng is not None and hasattr(rule_eng, "stop"):
            rule_eng.stop()
        pipe_bus = manager.event_pipeline.get("event_bus")
        if pipe_bus and hasattr(pipe_bus, "stop"):
            pipe_bus.stop(timeout=0.2)
    if getattr(manager, "event_fts_index", None) is not None:
        manager.event_fts_index.detach()
    if getattr(manager, "event_bus", None) and manager.event_bus is not pipe_bus and hasattr(manager.event_bus, "stop"):
        manager.event_bus.stop(timeout=0.2)
    if getattr(manager, "db", None) and hasattr(manager.db, "close"):
        manager.db.close()


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
    manager.confidence_engine = None
    manager.world_bridge = None
    manager.world_rule_engine = None


def _init_manager_runtime(manager: "StreamManager") -> None:
    """Initialize runtime threading locks, telemetry state, overlays, and collaborators."""
    manager._lock = threading.RLock()
    manager._thread = None
    manager._running = False
    manager._stop_event = threading.Event()
    manager._latest_jpeg = None
    manager._latest_raw_jpeg = None
    manager._latest_raw_frame = None
    manager._frame_seq = 0
    manager._frame_waiters = []
    manager._frame_waiter_lock = threading.Lock()
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
    manager.thumbnail_cache = ThumbnailCache(manager.camera_id)
    rec_cfg = manager.cfg.get("recording", {}) if isinstance(manager.cfg, dict) else {}
    rec_dir = rec_cfg.get("output_dir") if isinstance(rec_cfg, dict) else None
    manager._recording_controller = StreamRecordingController(
        manager.camera_id,
        output_dir=rec_dir,
        db_getter=lambda: getattr(manager, "db", None),
        mode_service_getter=lambda: getattr(manager, "_processing_mode_service", None),
    )
    manager._subscribers = manager._subscriber_registry._subscribers
    manager._ws_subscribers = manager._subscriber_registry._ws_subscribers
    manager._subscriber_lock = manager._subscriber_registry._lock
    manager._worker = StreamWorker(manager)


class StreamManager(StreamSubscriberMixin, StreamMediaMixin, StreamRecordingMixin):
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
        world_graph: Optional[WorldGraph] = None,
        processing_mode_service: Optional[Any] = None,
        event_bus: Optional[Any] = None,
        confidence_engine: Optional[Any] = None,
        event_fts_index: Optional[Any] = None,
    ) -> None:
        self.camera_id = camera_id
        self.name = name or f"Camera {camera_id.upper()}"
        self.source_override = source_override
        self.world_graph = world_graph
        self._injected_event_bus = event_bus
        self._injected_confidence_engine = confidence_engine
        self._injected_event_fts_index = event_fts_index
        if processing_mode_service is None:
            from dashboard.services.processing_mode_service import get_processing_mode_service

            processing_mode_service = get_processing_mode_service()
        self._processing_mode_service = processing_mode_service
        self._in_camera_pool = False
        _init_manager_config(self, config_path, db_path, custom_cfg)
        _init_manager_runtime(self)
        self._init_subsystems()

    def _resume_video_source(self) -> None:
        """Callback to resume video capture when subscribers reconnect."""
        svc = getattr(self, "_processing_mode_service", None)
        if svc is not None and svc.should_hibernate_camera(
            self.camera_id,
            subscriber_count=getattr(self, "subscriber_count", 0),
            is_recording=bool(getattr(self, "is_recording", False)),
            in_camera_pool=bool(getattr(self, "_in_camera_pool", False)),
            is_armed=bool(getattr(self, "is_armed", False)),
        ):
            return
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
            camera_name=self.name,
            source_override=self.source_override,
            world_graph=self.world_graph,
            event_bus=self._injected_event_bus,
            confidence_engine=self._injected_confidence_engine,
            event_fts_index=self._injected_event_fts_index,
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
        self.confidence_engine = bundle.confidence_engine
        self.world_graph = bundle.world_graph
        self.world_bridge = bundle.world_bridge
        self.world_rule_engine = bundle.world_rule_engine
        self.event_fts_index = bundle.event_fts_index
        self._pipeline_bundle = bundle.pipeline_bundle
        self._latest_jpeg = self._create_placeholder_jpeg("Camera Initializing...")

    def set_armed(self, armed: bool) -> None:
        """Propagate dynamic armed status to manager and active AsyncInferenceWorker."""
        self.is_armed = bool(armed)
        async_worker = getattr(getattr(self, "_worker", None), "_async_worker", None)
        if async_worker is not None and hasattr(async_worker, "set_armed"):
            async_worker.set_armed(self.is_armed)

    def signal_stop(self) -> None:
        """Signal worker loop and video source to terminate immediately without waiting."""
        self._running = False
        self._stop_event.set()
        self.notify_frame_ready()
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
        """Stop background worker cleanly and release owned pipeline resources outside self._lock."""
        self.signal_stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.6)
        recorder = getattr(self, "_recording_controller", None)
        if recorder is not None:
            recorder.finalize_if_active()
        bundle = getattr(self, "_pipeline_bundle", None)
        if bundle is not None and hasattr(bundle, "close"):
            bundle.close()
        else:
            _fallback_close_manager_resources(self)
        logger.info("StreamManager stopped for %s", self.camera_id)

    def start_recording(self, **kwargs: Any) -> Dict[str, Any]:
        """Start MP4 recording, wake hibernating source, and sync processing state."""
        res = super().start_recording(**kwargs)
        if getattr(self, "_processing_mode_service", None) is not None:
            self._resume_video_source()
        return res

    def _worker_loop(self) -> None:
        """Continuous pipeline loop executing detection, tracking, analytics, and frame drawing."""
        self._worker.run()
