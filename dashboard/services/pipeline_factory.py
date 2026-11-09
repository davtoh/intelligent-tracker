#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Stream Pipeline Factory Service.
Initializes and wires video sources, detectors, trackers, analytics,
Re-ID extractors, gallery matchers, and event dispatchers.
"""

import os
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

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
from intelligent_tracker.events import setup_event_pipeline, EventBus
from intelligent_tracker.rsac import RSACManager
from intelligent_tracker.active_learning import ActiveLearningManager
from intelligent_tracker.enrollment import UniversalEnrollmentManager

logger = logging.getLogger("intelligent_tracker.dashboard.pipeline")


@dataclass
class StreamPipelineBundle:
    """Encapsulates all initialized AI and vision pipeline subsystems."""
    db: Optional[TrackerDB] = None
    video_source: Optional[VideoSource] = None
    detector: Any = None
    tracker: Any = None
    analytics: Optional[AnalyticsEngine] = None
    reid_extractor: Any = None
    gallery_matcher: Optional[GalleryMatcher] = None
    rsac_manager: Optional[RSACManager] = None
    active_learning: Optional[ActiveLearningManager] = None
    enrollment_manager: Optional[UniversalEnrollmentManager] = None
    event_bus: Optional[EventBus] = None
    event_pipeline: Any = None


def load_stream_config(path: Optional[str]) -> Dict[str, Any]:
    """Load configuration from a YAML or JSON file."""
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


def _add_tripwires(analytics: AnalyticsEngine, tripwires_cfg: List[Dict[str, Any]]) -> None:
    """Add configured tripwire lines to the analytics engine."""
    for tw in tripwires_cfg:
        line = tw.get("line")
        if line and len(line) >= 2:
            analytics.add_tripwire(Tripwire(
                line_segment=line,
                name=tw.get("name", "tripwire"),
                bidirectional=bool(tw.get("bidirectional", True)),
                color=tuple(tw.get("color", [0, 255, 255])),
            ))


def _add_zones(analytics: AnalyticsEngine, zones_cfg: List[Dict[str, Any]]) -> None:
    """Add configured polygon zones to the analytics engine."""
    for z in zones_cfg:
        poly = z.get("polygon")
        if poly and len(poly) >= 3:
            analytics.add_zone(ZoneROI(
                polygon=poly,
                name=z.get("name", "zone"),
                dwell_threshold=float(z.get("dwell_threshold", 5.0)),
                color=tuple(z.get("color", [0, 200, 100])),
                capacity_limit=z.get("capacity_limit", z.get("max_occupancy")),
            ))


class StreamPipelineFactory:
    """Factory service creating and interconnecting all tracking subsystems."""

    @classmethod
    def build(
        cls,
        cfg: Dict[str, Any],
        db_path: str,
        camera_id: str,
        source_override: Optional[Any] = None,
    ) -> StreamPipelineBundle:
        """Instantiate and wire complete computer vision pipeline."""
        bundle = StreamPipelineBundle()
        bundle.db = cls._init_database(db_path)
        bundle.video_source, res_w, res_h = cls._init_video_source(cfg.get("video", {}), source_override)
        bundle.detector = cls._init_detector(cfg.get("detector", {}))
        bundle.tracker = cls._init_tracker(cfg.get("tracker", {}))
        bundle.analytics = cls._init_analytics(
            cfg.get("analytics", {}), camera_id, res_w, res_h, bundle.video_source
        )
        bundle.reid_extractor, bundle.gallery_matcher = cls._init_reid(cfg.get("reid", {}), bundle.db)
        bundle.event_pipeline, bundle.event_bus = cls._init_events(cfg, bundle.analytics)
        bundle.rsac_manager, bundle.active_learning, bundle.enrollment_manager = cls._init_governance(
            bundle.db, bundle.analytics, bundle.gallery_matcher, bundle.reid_extractor, bundle.event_bus
        )
        return bundle

    @staticmethod
    def _init_database(db_path: str) -> Optional[TrackerDB]:
        try:
            return TrackerDB(db_path)
        except Exception as e:
            logger.error("Database initialization failed: %s", e)
            return None

    @staticmethod
    def _init_video_source(
        video_cfg: Dict[str, Any],
        source_override: Optional[Any],
    ) -> Tuple[VideoSource, int, int]:
        """Configure and instantiate VideoSource handle."""
        res = video_cfg.get("resolution", [640, 480])
        res_w, res_h = (int(res[0]), int(res[1])) if isinstance(res, (list, tuple)) else (640, 480)
        raw_source = source_override if source_override is not None else video_cfg.get("source", "synthetic")
        source = "synthetic" if str(raw_source).lower() in ("synthetic", "mock") else resolve_camera_source(raw_source)

        fps_target = float(video_cfg.get("framerate", 30))
        is_file = isinstance(source, str) and (
            os.path.exists(source) or source.lower().endswith((".mp4", ".avi", ".mkv", ".mov"))
        )
        vs = VideoSource(
            source=source,
            buffer_size=int(video_cfg.get("buffer_size", 1)),
            auto_reconnect=bool(video_cfg.get("auto_reconnect", True)),
            fps_limit=fps_target,
            width=res_w,
            height=res_h,
            loop_video=is_file or bool(video_cfg.get("loop", True)),
        )
        return vs, res_w, res_h

    @staticmethod
    def _init_detector(detector_cfg: Dict[str, Any]) -> Any:
        """Instantiate detector model with fallback to mock detector."""
        det_name = str(detector_cfg.get("model", "mock")).lower().strip()
        det_conf = float(detector_cfg.get("confidence", 0.25))
        raw_classes = detector_cfg.get("classes")
        if isinstance(raw_classes, str):
            classes = [c.strip() for c in raw_classes.split(",") if c.strip()]
        elif isinstance(raw_classes, (list, tuple, set)):
            classes = [str(c).strip() for c in raw_classes if str(c).strip()]
        else:
            classes = None

        det_kwargs: Dict[str, Any] = {}
        if det_name in ("yolov8", "yolov8n", "yolo11", "yolo11n", "onnx"):
            det_kwargs["conf_threshold"] = det_conf
            if classes:
                det_kwargs["classes"] = classes
        elif det_name in ("mock", "mockdetector"):
            det_kwargs["confidence"] = det_conf

        try:
            return DetectorFactory.create(det_name, **det_kwargs)
        except Exception as e:
            logger.warning("Preferred detector '%s' failed (%s), falling back to mock", det_name, e)
            return DetectorFactory.create("mock")

    @staticmethod
    def _init_tracker(tracker_cfg: Dict[str, Any]) -> Any:
        """Instantiate tracking engine."""
        return TrackerFactory.create(
            tracker_cfg.get("type", "centroid"),
            max_disappeared=int(tracker_cfg.get("max_disappeared", 30)),
            min_hits=int(tracker_cfg.get("min_hits", 2)),
            iou_threshold=float(tracker_cfg.get("iou_threshold", 0.2)),
        )

    @staticmethod
    def _init_analytics(
        analytics_cfg: Dict[str, Any],
        camera_id: str,
        res_w: int,
        res_h: int,
        video_source: Optional[VideoSource],
    ) -> AnalyticsEngine:
        """Instantiate spatial analytics engine and register tripwires and zones."""
        heatmap_cfg = analytics_cfg.get("heatmap", {})
        active_w = getattr(video_source, "width", res_w)
        active_h = getattr(video_source, "height", res_h)
        analytics = AnalyticsEngine(
            resolution=(active_w, active_h),
            heatmap_enabled=bool(heatmap_cfg.get("enabled", True)),
            heatmap_decay=float(heatmap_cfg.get("decay", 0.998)) if heatmap_cfg.get("decay") else None,
            camera_id=camera_id,
        )
        _add_tripwires(analytics, analytics_cfg.get("tripwires", []))
        _add_zones(analytics, analytics_cfg.get("zones", []))
        return analytics

    @staticmethod
    def _init_reid(
        reid_cfg: Dict[str, Any],
        db: Optional[TrackerDB],
    ) -> Tuple[Any, Optional[GalleryMatcher]]:
        """Instantiate Re-ID feature extractor and database gallery matcher."""
        reid_name = reid_cfg.get("model", "color")
        if not reid_name or not db:
            return None, None
        try:
            extractor = ReIDExtractorFactory.create(reid_name)
            matcher = GalleryMatcher(
                db=db,
                extractor=extractor,
                reid_threshold=float(reid_cfg.get("threshold", 0.65)),
            )
            return extractor, matcher
        except Exception as e:
            logger.warning("Re-ID initialization warning: %s", e)
            return None, None

    @staticmethod
    def _init_events(
        cfg: Dict[str, Any],
        analytics: Optional[AnalyticsEngine],
    ) -> Tuple[Any, EventBus]:
        """Set up event bus and alerting dispatchers."""
        event_pipeline = None
        event_bus = None
        alert_cfg = cfg.get("alerting", cfg.get("events"))
        if alert_cfg:
            try:
                event_pipeline = setup_event_pipeline(cfg)
                event_bus = event_pipeline.get("event_bus")
                if analytics and event_bus:
                    analytics.event_bus = event_bus
            except Exception as e:
                logger.warning("Event pipeline setup warning: %s", e)
        if event_bus is None:
            event_bus = EventBus(capacity=500)
            if analytics:
                analytics.event_bus = event_bus
        return event_pipeline, event_bus

    @staticmethod
    def _init_governance(
        db: Optional[TrackerDB],
        analytics: Optional[AnalyticsEngine],
        gallery_matcher: Optional[GalleryMatcher],
        reid_extractor: Any,
        event_bus: Optional[EventBus],
    ) -> Tuple[Optional[RSACManager], Optional[ActiveLearningManager], Optional[UniversalEnrollmentManager]]:
        """Set up RSAC access rules, active learning queue, and universal enrollment."""
        if not db:
            return None, None, None
        rsac_mgr = None
        al_mgr = None
        enr_mgr = None
        try:
            rsac_mgr = RSACManager(db=db)
            if analytics:
                analytics.rsac_manager = rsac_mgr
        except Exception as e:
            logger.warning("RSACManager initialization warning: %s", e)
        try:
            al_mgr = ActiveLearningManager(db=db, matcher=gallery_matcher, event_bus=event_bus)
            if gallery_matcher:
                gallery_matcher.active_learning = al_mgr
            enr_mgr = UniversalEnrollmentManager(db=db, extractor=reid_extractor, matcher=gallery_matcher)
        except Exception as e:
            logger.warning("ActiveLearning / Enrollment initialization warning: %s", e)
        return rsac_mgr, al_mgr, enr_mgr
