"""Unified PipelineEngine orchestrating subsystem assembly for CLI and Dashboard."""

from typing import Any

from intelligent_tracker.pipeline.bundle import (
    PipelineBundle,
    build_analytics,
    build_confidence_engine,
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
    def _assemble_core(
        cls,
        bundle: PipelineBundle,
        config: PipelineConfig,
        raise_on_detector_error: bool | None,
    ) -> None:
        """Assemble core capture, detection, tracking, analytics, Re-ID, and events."""
        bundle.db = build_database(config.db_path)
        bundle.video_source = build_video_source(config)
        bundle.detector = build_detector(config, raise_on_error=raise_on_detector_error)
        bundle.tracker = build_tracker(config)
        bundle.analytics = build_analytics(config, bundle.video_source)
        bundle.reid_extractor, bundle.gallery_matcher = build_reid(config, bundle.db)
        bundle.event_pipeline, bundle.event_bus = build_events(config, bundle.analytics)
        bundle.confidence_engine = build_confidence_engine(bundle.db, bundle.event_bus)

    @classmethod
    def _assemble_governance_and_world(
        cls,
        bundle: PipelineBundle,
        config: PipelineConfig,
        world_graph: WorldGraph | None,
    ) -> None:
        """Assemble governance, world graph bridge, and optional video writer."""
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
            confidence_engine=bundle.confidence_engine,
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
            confidence_engine=bundle.confidence_engine,
        )
        bundle.writer = build_writer(config)

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
            cls._assemble_core(bundle, config, raise_on_detector_error)
            cls._assemble_governance_and_world(bundle, config, world_graph)
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

