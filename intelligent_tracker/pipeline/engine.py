"""Unified PipelineEngine orchestrating subsystem assembly for CLI and Dashboard."""

from typing import Any

from intelligent_tracker.pipeline.bundle import (
    PipelineBundle,
    build_analytics,
    build_database,
    build_detector,
    build_events,
    build_governance,
    build_reid,
    build_tracker,
    build_video_source,
    build_world,
    build_writer,
)
from intelligent_tracker.pipeline.config import PipelineConfig
from intelligent_tracker.world import WorldGraph


class PipelineEngine:
    """Canonical factory assembling a complete PipelineBundle from PipelineConfig."""

    @classmethod
    def build(
        cls,
        config: PipelineConfig,
        *,
        raise_on_detector_error: bool | None = None,
        world_graph: WorldGraph | None = None,
    ) -> PipelineBundle:
        """Instantiate and wire all pipeline subsystems without calling sys.exit()."""
        bundle = PipelineBundle(config=config)
        try:
            bundle.db = build_database(config.db_path)
            bundle.video_source = build_video_source(config)
            bundle.detector = build_detector(config, raise_on_error=raise_on_detector_error)
            bundle.tracker = build_tracker(config)
            bundle.analytics = build_analytics(config, bundle.video_source)
            bundle.reid_extractor, bundle.gallery_matcher = build_reid(config, bundle.db)
            bundle.event_pipeline, bundle.event_bus = build_events(config, bundle.analytics)
            (
                bundle.rsac_manager,
                bundle.active_learning,
                bundle.enrollment_manager,
            ) = build_governance(
                config,
                bundle.db,
                bundle.analytics,
                bundle.gallery_matcher,
                bundle.reid_extractor,
                bundle.event_bus,
            )
            (
                bundle.world_graph,
                bundle.world_bridge,
                bundle.world_rule_engine,
            ) = build_world(
                config,
                world_graph=world_graph,
                db=bundle.db,
                analytics=bundle.analytics,
                gallery_matcher=bundle.gallery_matcher,
                event_bus=bundle.event_bus,
            )
            bundle.writer = build_writer(config)
        except Exception:
            bundle.close()
            raise
        return bundle

    @classmethod
    def from_dict(
        cls,
        cfg: dict[str, Any] | None = None,
        *,
        raise_on_detector_error: bool | None = None,
        world_graph: WorldGraph | None = None,
        **config_kwargs: Any,
    ) -> PipelineBundle:
        """Normalize a config dictionary and build a PipelineBundle."""
        config = PipelineConfig.from_dict(cfg, **config_kwargs)
        return cls.build(
            config,
            raise_on_detector_error=raise_on_detector_error,
            world_graph=world_graph,
        )

    @classmethod
    def from_cli_args(
        cls,
        args: Any,
        cfg: dict[str, Any] | None = None,
        *,
        raise_on_detector_error: bool | None = None,
        world_graph: WorldGraph | None = None,
    ) -> PipelineBundle:
        """Normalize CLI arguments + config dict and build a PipelineBundle."""
        config = PipelineConfig.from_cli_args(args, cfg)
        return cls.build(
            config,
            raise_on_detector_error=raise_on_detector_error,
            world_graph=world_graph,
        )

