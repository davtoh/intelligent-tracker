"""Intelligent Tracker CLI - Pipeline Builder & Subsystem Assembly."""

from dataclasses import dataclass
from typing import Any

import cv2

from intelligent_tracker.analytics import AnalyticsEngine
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.matcher import GalleryMatcher
from intelligent_tracker.pipeline import (
    PipelineBundle,
    PipelineConfig,
    PipelineEngine,
    parse_resolution,
)
from intelligent_tracker.video import VideoSource


@dataclass
class PipelineContext:
    """Holds active execution pipeline components and runtime parameters."""

    video_source: VideoSource
    detector: Any
    tracker: Any
    analytics: AnalyticsEngine
    db: TrackerDB | None
    reid_extractor: Any
    gallery_matcher: GalleryMatcher | None
    event_pipeline: dict[str, Any] | None
    event_bus: Any
    writer: cv2.VideoWriter | None
    params: dict[str, Any]
    bundle: PipelineBundle | None = None


def _resolve_resolution(args: Any, video_cfg: dict[str, Any]) -> tuple[int, int]:
    """Determine width and height from CLI args or video configuration."""
    if getattr(args, "resolution", None):
        return parse_resolution(args.resolution)
    if "resolution" in video_cfg:
        return parse_resolution(video_cfg["resolution"])
    return (640, 480)


def _resolve_frames_limit(args: Any) -> int:
    """Resolve effective frame limit from explicit --frames or headless/benchmark defaults."""
    raw_frames = getattr(args, "frames", None)
    if raw_frames is not None:
        return max(0, int(raw_frames))
    if (
        getattr(args, "headless", False)
        or getattr(args, "benchmark", False)
        or getattr(args, "benchmark_output", None)
    ):
        return 60
    return 0


def _config_to_params(config: PipelineConfig, args: Any, cfg: dict[str, Any]) -> dict[str, Any]:
    """Convert normalized PipelineConfig into the legacy CLI params dictionary."""
    res_w, res_h = config.resolution
    benchmark_output = getattr(args, "benchmark_output", None)
    benchmark_enabled = bool(getattr(args, "benchmark", False) or benchmark_output)
    return {
        "res_w": res_w,
        "res_h": res_h,
        "source": config.source,
        "detector_name": config.detector_model,
        "conf_thresh": config.detector_confidence,
        "classes_filter": config.detector_classes,
        "tracker_name": config.tracker_type,
        "max_disappeared": config.max_disappeared,
        "min_hits": config.min_hits,
        "iou_thresh": config.iou_threshold,
        "framerate": config.framerate,
        "show_heatmap": config.show_heatmap,
        "reid_name": config.reid_model,
        "db_path": config.db_path,
        "reid_threshold": config.reid_threshold,
        "video_cfg": cfg.get("video", {}),
        "analytics_cfg": cfg.get("analytics", {}),
        "vis_cfg": cfg.get("visualization", {}),
        "output": getattr(args, "output", config.output_path),
        "headless": getattr(args, "headless", False),
        "gui": getattr(args, "gui", "opencv"),
        "frames": _resolve_frames_limit(args),
        "benchmark": benchmark_enabled,
        "benchmark_output": benchmark_output,
        "config": getattr(args, "config", config.config_path),
        "governance": config.enable_governance,
    }


def resolve_pipeline_params(args: Any, cfg: dict[str, Any], *, resolve_source: bool = False) -> dict[str, Any]:
    """Resolve CLI options against config file defaults via PipelineConfig SSOT."""
    config = PipelineConfig.from_cli_args(args, cfg, resolve_source=resolve_source)
    return _config_to_params(config, args, cfg)


def build_pipeline(args: Any, cfg: dict[str, Any]) -> PipelineContext:
    """Instantiate and wire all pipeline components via PipelineEngine."""
    config = PipelineConfig.from_cli_args(args, cfg)
    params = _config_to_params(config, args, cfg)
    _print_banner(params)

    bundle = PipelineEngine.build(config, raise_on_detector_error=True)
    _log_initialized_subsystems(bundle)

    return PipelineContext(
        video_source=bundle.video_source,
        detector=bundle.detector,
        tracker=bundle.tracker,
        analytics=bundle.analytics,
        db=bundle.db,
        reid_extractor=bundle.reid_extractor,
        gallery_matcher=bundle.gallery_matcher,
        event_pipeline=bundle.event_pipeline,
        event_bus=bundle.event_bus,
        writer=bundle.writer,
        params=params,
        bundle=bundle,
    )


def _log_initialized_subsystems(bundle: PipelineBundle) -> None:
    """Log concise initialization status for CLI user feedback."""
    if bundle.detector is not None:
        print(f"[INFO] Initialized detector backend: {bundle.detector.__class__.__name__}")
    if bundle.tracker is not None:
        print(f"[INFO] Initialized multi-object tracker: {bundle.tracker.__class__.__name__}")
    if bundle.gallery_matcher is not None:
        print(
            f"[INFO] Initialized Re-ID Engine: {bundle.reid_extractor.__class__.__name__} "
            f"(gallery: {bundle.gallery_matcher.gallery_size} signatures) -> {bundle.config.db_path}"
        )
    if bundle.event_pipeline:
        print("[INFO] Initialized Event Dispatching & Alerting Pipeline:")
        if bundle.event_pipeline.get("webhooks"):
            print(f"  - Webhooks   : {len(bundle.event_pipeline['webhooks'])} active endpoint(s)")
        if bundle.event_pipeline.get("telegram"):
            print(f"  - Telegram   : enabled (mock={bundle.event_pipeline['telegram'].mock})")
        if bundle.event_pipeline.get("mqtt"):
            mqtt_client = bundle.event_pipeline["mqtt"]
            state = "connected" if mqtt_client.is_connected else "offline"
            print(f"  - MQTT       : {state} (broker: {mqtt_client.broker}:{mqtt_client.port})")
        if bundle.event_pipeline.get("rule_engine"):
            print(f"  - Alert Rules: {len(bundle.event_pipeline['rule_engine'].rules)} active rule(s)")


def _print_banner(p: dict[str, Any]) -> None:
    """Print standard CLI banner."""
    print("=" * 65)
    print("Intelligent Tracker - Edge AI Retail & Security Analytics")
    print("=" * 65)
    print(f"  Config File : {p['config'] if p['config'] else '[None - defaults]'}")
    print(f"  Source      : {p['source']}")
    print(f"  Detector    : {p['detector_name']} (conf={p['conf_thresh']})")
    print(f"  Tracker     : {p['tracker_name']} (max_disappeared={p['max_disappeared']}, min_hits={p['min_hits']})")
    print(f"  Re-ID Engine: {p['reid_name'] or '[Disabled]'} (threshold={p['reid_threshold']:.2f})")
    if p["db_path"]:
        print(f"  Database    : {p['db_path']}")
    print(f"  Resolution  : {p['res_w']}x{p['res_h']}")
    print(f"  Target FPS  : {p['framerate']}")
    mode_str = "Headless" if p["headless"] else f"Interactive GUI ({p['gui']})"
    print(f"  Mode        : {mode_str}")
    if p["output"]:
        print(f"  Recording   : {p['output']}")
    print("=" * 65)
