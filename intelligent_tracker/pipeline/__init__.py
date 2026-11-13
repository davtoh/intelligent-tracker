"""Unified CV pipeline configuration, assembly, and lifecycle management."""

from intelligent_tracker.pipeline.bundle import PipelineBundle
from intelligent_tracker.pipeline.config import (
    PipelineConfig,
    load_pipeline_config,
    parse_classes,
    parse_resolution,
)
from intelligent_tracker.pipeline.engine import PipelineEngine
from intelligent_tracker.pipeline.frame_processor import FrameProcessor, FrameStepResult

__all__ = [
    "FrameProcessor",
    "FrameStepResult",
    "PipelineBundle",
    "PipelineConfig",
    "PipelineEngine",
    "load_pipeline_config",
    "parse_classes",
    "parse_resolution",
]

