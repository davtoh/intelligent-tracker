"""Intelligent Tracker - Stream Pipeline Factory Service.

Delegates configuration normalization and subsystem assembly to the unified
``intelligent_tracker.pipeline`` engine while preserving ``StreamPipelineBundle``
and ``StreamPipelineFactory`` contracts for dashboard consumers.
"""

from dataclasses import dataclass
from typing import Any

from intelligent_tracker.active_learning import ActiveLearningManager
from intelligent_tracker.analytics import AnalyticsEngine
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.enrollment import UniversalEnrollmentManager
from intelligent_tracker.events import EventBus
from intelligent_tracker.matcher import GalleryMatcher
from intelligent_tracker.pipeline import (
    PipelineBundle,
    PipelineConfig,
    PipelineEngine,
    load_pipeline_config,
)
from intelligent_tracker.pipeline.bundle import (
    build_analytics,
    build_database,
    build_detector,
    build_events,
    build_governance,
    build_reid,
    build_tracker,
    build_video_source,
)
from intelligent_tracker.rsac import RSACManager
from intelligent_tracker.video import VideoSource


@dataclass
class StreamPipelineBundle:
    """Encapsulates all initialized AI and vision pipeline subsystems."""

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
    event_pipeline: Any = None
    pipeline_bundle: PipelineBundle | None = None


def load_stream_config(path: str | None) -> dict[str, Any]:
    """Load configuration from a YAML or JSON file."""
    return load_pipeline_config(path)


class StreamPipelineFactory:
    """Factory service creating and interconnecting all tracking subsystems."""

    @classmethod
    def build(
        cls,
        cfg: dict[str, Any],
        db_path: str,
        camera_id: str,
        source_override: Any = None,
    ) -> StreamPipelineBundle:
        """Instantiate and wire complete computer vision pipeline via PipelineEngine."""
        data = dict(cfg or {})
        config = PipelineConfig.from_dict(
            data,
            camera_id=camera_id,
            db_path=db_path,
            source_override=source_override,
            detector_fallback_mock=True,
            enable_governance=True,
            enable_event_bus_fallback=True,
        )
        if "loop" not in data.get("video", {}):
            config.loop_video = True

        bundle = PipelineEngine.build(config)
        return StreamPipelineBundle(
            db=bundle.db,
            video_source=bundle.video_source,
            detector=bundle.detector,
            tracker=bundle.tracker,
            analytics=bundle.analytics,
            reid_extractor=bundle.reid_extractor,
            gallery_matcher=bundle.gallery_matcher,
            rsac_manager=bundle.rsac_manager,
            active_learning=bundle.active_learning,
            enrollment_manager=bundle.enrollment_manager,
            event_bus=bundle.event_bus,
            event_pipeline=bundle.event_pipeline,
            pipeline_bundle=bundle,
        )

    @staticmethod
    def _init_database(db_path: str) -> TrackerDB | None:
        return build_database(db_path)

    @staticmethod
    def _init_video_source(
        video_cfg: dict[str, Any],
        source_override: Any,
    ) -> tuple[VideoSource, int, int]:
        config = PipelineConfig.from_dict(
            {"video": dict(video_cfg or {})},
            source_override=source_override,
        )
        if "loop" not in (video_cfg or {}):
            config.loop_video = True
        vs = build_video_source(config)
        res_w, res_h = config.resolution
        return vs, res_w, res_h

    @staticmethod
    def _init_detector(detector_cfg: dict[str, Any]) -> Any:
        """Instantiate detector model with fallback to mock detector."""
        config = PipelineConfig.from_dict(
            {"detector": dict(detector_cfg or {})},
            detector_fallback_mock=True,
        )
        return build_detector(config)

    @staticmethod
    def _init_tracker(tracker_cfg: dict[str, Any]) -> Any:
        """Instantiate tracking engine."""
        config = PipelineConfig.from_dict({"tracker": dict(tracker_cfg or {})})
        return build_tracker(config)

    @staticmethod
    def _init_analytics(
        analytics_cfg: dict[str, Any],
        camera_id: str,
        res_w: int,
        res_h: int,
        video_source: VideoSource | None,
    ) -> AnalyticsEngine:
        """Instantiate spatial analytics engine and register tripwires and zones."""
        config = PipelineConfig.from_dict(
            {
                "video": {"resolution": [res_w, res_h]},
                "analytics": dict(analytics_cfg or {}),
            },
            camera_id=camera_id,
        )
        return build_analytics(config, video_source)

    @staticmethod
    def _init_reid(
        reid_cfg: dict[str, Any],
        db: TrackerDB | None,
    ) -> tuple[Any, GalleryMatcher | None]:
        """Instantiate Re-ID feature extractor and database gallery matcher."""
        config = PipelineConfig.from_dict({"reid": dict(reid_cfg or {})})
        return build_reid(config, db)

    @staticmethod
    def _init_events(
        cfg: dict[str, Any],
        analytics: AnalyticsEngine | None,
    ) -> tuple[Any, EventBus]:
        """Set up event bus and alerting dispatchers."""
        config = PipelineConfig.from_dict(dict(cfg or {}), enable_event_bus_fallback=True)
        pipeline, bus = build_events(config, analytics)
        return pipeline, bus

    @staticmethod
    def _init_governance(
        db: TrackerDB | None,
        analytics: AnalyticsEngine | None,
        gallery_matcher: GalleryMatcher | None,
        reid_extractor: Any,
        event_bus: EventBus | None,
    ) -> tuple[RSACManager | None, ActiveLearningManager | None, UniversalEnrollmentManager | None]:
        """Set up RSAC access rules, active learning queue, and universal enrollment."""
        config = PipelineConfig(enable_governance=True)
        return build_governance(config, db, analytics, gallery_matcher, reid_extractor, event_bus)
