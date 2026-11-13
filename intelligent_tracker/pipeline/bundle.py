"""PipelineBundle container, deterministic teardown, and subsystem builders."""

from dataclasses import dataclass
import logging
import os
from typing import Any

import cv2

from intelligent_tracker.active_learning import ActiveLearningManager
from intelligent_tracker.analytics import AnalyticsEngine
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.detectors import DetectorFactory
from intelligent_tracker.enrollment import UniversalEnrollmentManager
from intelligent_tracker.events import EventBus, setup_event_pipeline
from intelligent_tracker.geometry import Tripwire, ZoneROI
from intelligent_tracker.matcher import GalleryMatcher
from intelligent_tracker.memory import ConfidenceEngine
from intelligent_tracker.pipeline._world_setup import register_world_children
from intelligent_tracker.pipeline.config import PipelineConfig
from intelligent_tracker.reid import ReIDExtractorFactory
from intelligent_tracker.rsac import RSACManager
from intelligent_tracker.tracker import TrackerFactory
from intelligent_tracker.video import VideoSource
from intelligent_tracker.world import (
    CameraNode,
    WorldEntityBridge,
    WorldGraph,
    WorldRuleEngine,
)

logger = logging.getLogger("intelligent_tracker.pipeline.bundle")


def _safe_call(obj: Any, method: str, *args: Any) -> None:
    """Invoke a cleanup method on an optional subsystem without propagating errors."""
    if obj is None or not hasattr(obj, method):
        return
    try:
        getattr(obj, method)(*args)
    except Exception as exc:
        logger.debug("Cleanup %s.%s() raised: %s", type(obj).__name__, method, exc)


@dataclass
class PipelineBundle:
    """Encapsulates all initialized CV, Re-ID, analytics, and event subsystems."""

    config: PipelineConfig
    db: TrackerDB | None = None
    video_source: VideoSource | None = None
    detector: Any = None
    tracker: Any = None
    analytics: AnalyticsEngine | None = None
    reid_extractor: Any = None
    gallery_matcher: GalleryMatcher | None = None
    rsac_manager: RSACManager | None = None
    active_learning: ActiveLearningManager | None = None
    enrollment_manager: UniversalEnrollmentManager | None = None
    event_bus: EventBus | None = None
    event_pipeline: dict[str, Any] | None = None
    confidence_engine: ConfidenceEngine | None = None
    world_graph: WorldGraph | None = None
    world_bridge: WorldEntityBridge | None = None
    world_rule_engine: WorldRuleEngine | None = None
    writer: Any = None
    _closed: bool = False

    def close(self) -> None:
        """Deterministically release all owned resources and background workers."""
        if self._closed:
            return
        self._closed = True

        _safe_call(self.writer, "release")
        _safe_call(self.video_source, "stop")
        _safe_call(self.video_source, "release")
        _safe_call(self.world_rule_engine, "stop")

        if isinstance(self.event_pipeline, dict):
            _safe_call(self.event_pipeline.get("rule_engine"), "stop")
            _safe_call(self.event_pipeline.get("mqtt"), "disconnect")
            for webhook in self.event_pipeline.get("webhooks") or []:
                _safe_call(webhook, "close")
            bus = self.event_pipeline.get("event_bus")
            if bus is not None and bus is not self.event_bus:
                _safe_call(bus, "stop")

        _safe_call(self.event_bus, "stop")
        _safe_call(self.db, "close")


def build_database(db_path: str | None) -> TrackerDB | None:
    """Initialize TrackerDB when a database path is configured."""
    if not db_path:
        return None
    try:
        return TrackerDB(db_path)
    except Exception as exc:
        logger.error("Database initialization failed (%s): %s", db_path, exc)
        return None


def build_video_source(config: PipelineConfig) -> VideoSource:
    """Construct a VideoSource instance from normalized PipelineConfig."""
    res_w, res_h = config.resolution
    return VideoSource(
        source=config.source,
        buffer_size=config.buffer_size,
        auto_reconnect=config.auto_reconnect,
        reconnect_delay=config.reconnect_delay,
        fps_limit=float(config.framerate),
        width=res_w,
        height=res_h,
        loop_video=config.loop_video,
    )


def build_detector(
    config: PipelineConfig,
    *,
    raise_on_error: bool | None = None,
) -> Any:
    """Instantiate detector backend with optional MockDetector fallback."""
    should_raise = (not config.detector_fallback_mock) if raise_on_error is None else raise_on_error
    det_name = config.detector_model
    det_kwargs: dict[str, Any] = {}
    if det_name in ("yolov8", "yolov8n", "yolo11", "yolo11n", "onnx"):
        det_kwargs["conf_threshold"] = config.detector_confidence
        if config.detector_classes:
            det_kwargs["classes"] = config.detector_classes
    elif det_name in ("mock", "mockdetector"):
        det_kwargs["confidence"] = config.detector_confidence

    try:
        return DetectorFactory.create(det_name, **det_kwargs)
    except KeyError as exc:
        if should_raise:
            raise ValueError(str(exc)) from exc
        logger.warning("Preferred detector '%s' failed (%s), falling back to mock", det_name, exc)
        return DetectorFactory.create("mock")
    except Exception as exc:
        if should_raise:
            raise
        logger.warning("Preferred detector '%s' failed (%s), falling back to mock", det_name, exc)
        return DetectorFactory.create("mock")


def build_tracker(config: PipelineConfig) -> Any:
    """Instantiate multi-object tracker backend."""
    if config.tracker_type == "sort":
        return TrackerFactory.create(
            "sort",
            max_age=config.max_disappeared,
            min_hits=config.min_hits,
            iou_threshold=config.iou_threshold,
        )
    return TrackerFactory.create(
        config.tracker_type,
        max_disappeared=config.max_disappeared,
        min_hits=config.min_hits,
        iou_threshold=config.iou_threshold,
    )


def build_analytics(
    config: PipelineConfig,
    video_source: VideoSource | None = None,
) -> AnalyticsEngine:
    """Instantiate AnalyticsEngine and register configured tripwires and zones."""
    res_w, res_h = config.resolution
    active_w = getattr(video_source, "width", res_w)
    active_h = getattr(video_source, "height", res_h)
    analytics = AnalyticsEngine(
        resolution=(active_w, active_h),
        heatmap_enabled=config.heatmap_enabled,
        heatmap_decay=config.heatmap_decay,
        camera_id=config.camera_id,
    )
    for tw in config.tripwires:
        line = tw.get("line")
        if line and len(line) >= 2:
            analytics.add_tripwire(Tripwire(
                line_segment=line,
                name=tw.get("name", "tripwire"),
                bidirectional=bool(tw.get("bidirectional", True)),
                color=tuple(tw.get("color", [0, 255, 255])),
            ))
    for zone in config.zones:
        poly = zone.get("polygon")
        if poly and len(poly) >= 3:
            analytics.add_zone(ZoneROI(
                polygon=poly,
                name=zone.get("name", "zone"),
                dwell_threshold=float(zone.get("dwell_threshold", 5.0)),
                color=tuple(zone.get("color", [0, 200, 100])),
                capacity_limit=zone.get("capacity_limit", zone.get("max_occupancy")),
            ))
    return analytics


def build_reid(
    config: PipelineConfig,
    db: TrackerDB | None,
) -> tuple[Any, GalleryMatcher | None]:
    """Instantiate Re-ID feature extractor and GalleryMatcher."""
    if not config.reid_model or db is None:
        return None, None
    try:
        extractor = ReIDExtractorFactory.create(config.reid_model)
        matcher = GalleryMatcher(
            db=db,
            extractor=extractor,
            reid_threshold=config.reid_threshold,
            camera_id=config.camera_id,
        )
        return extractor, matcher
    except Exception as exc:
        logger.warning("Re-ID initialization warning: %s", exc)
        return None, None


def build_events(
    config: PipelineConfig,
    analytics: AnalyticsEngine | None = None,
) -> tuple[dict[str, Any] | None, EventBus | None]:
    """Initialize event pipeline and EventBus, wiring them to analytics."""
    event_pipeline: dict[str, Any] | None = None
    event_bus: EventBus | None = None
    raw = config.raw_config
    alert_cfg = raw.get("alerting", raw.get("events"))
    if alert_cfg:
        try:
            event_pipeline = setup_event_pipeline(raw)
            event_bus = event_pipeline.get("event_bus")
        except Exception as exc:
            logger.warning("Event pipeline setup warning: %s", exc)

    if event_bus is None and config.enable_event_bus_fallback:
        event_bus = EventBus(capacity=500)
        event_bus.start()

    if analytics is not None and event_bus is not None:
        analytics.event_bus = event_bus
    return event_pipeline, event_bus


def build_confidence_engine(
    db: TrackerDB | None,
    event_bus: EventBus | None = None,
) -> ConfidenceEngine:
    """Instantiate ConfidenceEngine backed by TrackerDB when available."""
    return ConfidenceEngine(db=db, event_bus=event_bus)


def build_governance(
    config: PipelineConfig,
    db: TrackerDB | None,
    analytics: AnalyticsEngine | None,
    gallery_matcher: GalleryMatcher | None,
    reid_extractor: Any,
    event_bus: EventBus | None,
    confidence_engine: ConfidenceEngine | None = None,
) -> tuple[RSACManager | None, ActiveLearningManager | None, UniversalEnrollmentManager | None]:
    """Initialize RSAC, active learning, and universal enrollment managers."""
    if not config.enable_governance or db is None:
        return None, None, None
    rsac_mgr: RSACManager | None = None
    al_mgr: ActiveLearningManager | None = None
    enr_mgr: UniversalEnrollmentManager | None = None
    try:
        rsac_mgr = RSACManager(db=db)
        if analytics is not None:
            analytics.rsac_manager = rsac_mgr
    except Exception as exc:
        logger.warning("RSACManager initialization warning: %s", exc)
    try:
        al_mgr = ActiveLearningManager(
            db=db, matcher=gallery_matcher, event_bus=event_bus, confidence_engine=confidence_engine,
        )
        if gallery_matcher is not None:
            gallery_matcher.active_learning = al_mgr
        enr_mgr = UniversalEnrollmentManager(db=db, extractor=reid_extractor, matcher=gallery_matcher)
    except Exception as exc:
        logger.warning("ActiveLearning / Enrollment initialization warning: %s", exc)
    return rsac_mgr, al_mgr, enr_mgr


def build_writer(config: PipelineConfig) -> Any:
    """Initialize optional cv2.VideoWriter when output_path is configured."""
    if not config.output_path:
        return None
    os.makedirs(os.path.dirname(os.path.abspath(config.output_path)) or ".", exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    res_w, res_h = config.resolution
    return cv2.VideoWriter(config.output_path, fourcc, float(config.framerate), (res_w, res_h))


def build_world(
    config: PipelineConfig,
    *,
    world_graph: WorldGraph | None = None,
    db: TrackerDB | None = None,
    analytics: AnalyticsEngine | None = None,
    gallery_matcher: GalleryMatcher | None = None,
    event_bus: EventBus | None = None,
    confidence_engine: ConfidenceEngine | None = None,
) -> tuple[WorldGraph, WorldEntityBridge, WorldRuleEngine | None]:
    """Initialize scoped WorldGraph, WorldEntityBridge, and optional WorldRuleEngine."""
    graph = world_graph if world_graph is not None else WorldGraph(event_bus=event_bus)
    graph.register_camera(CameraNode(
        camera_id=config.camera_id,
        name=config.camera_id,
        source=str(config.source),
        enabled=True,
    ))
    register_world_children(graph, config, analytics)
    bridge = WorldEntityBridge(
        graph,
        db=db,
        coordinate_mapper=getattr(graph, "coordinate_mapper", None),
        handoff_coordinator=getattr(graph, "handoff_coordinator", None),
        confidence_engine=confidence_engine,
    )
    if gallery_matcher is not None:
        gallery_matcher.camera_id = config.camera_id
        gallery_matcher.world_bridge = bridge
    rule_engine: WorldRuleEngine | None = None
    if event_bus is not None:
        rule_engine = WorldRuleEngine(graph, event_bus)
        rule_engine.start()
    return graph, bridge, rule_engine
