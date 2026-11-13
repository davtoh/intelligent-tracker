"""Single Source of Truth (SSOT) configuration normalization for PipelineEngine."""

from dataclasses import dataclass, field
import json
import logging
import os
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.video import resolve_camera_source

logger = logging.getLogger("intelligent_tracker.pipeline.config")


def parse_resolution(
    value: Any,
    default: tuple[int, int] = (640, 480),
) -> tuple[int, int]:
    """Normalize resolution from ``'WIDTHxHEIGHT'`` string or 2-element sequence."""
    if value is None:
        return default
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            w, h = int(value[0]), int(value[1])
            return (w, h) if w > 0 and h > 0 else default
        except (TypeError, ValueError):
            return default
    if isinstance(value, str):
        parts = value.lower().strip().split("x")
        if len(parts) == 2:
            try:
                w, h = int(parts[0].strip()), int(parts[1].strip())
                return (w, h) if w > 0 and h > 0 else default
            except ValueError:
                return default
    return default


def parse_classes(value: Any) -> list[str] | None:
    """Normalize detector class filter from comma-separated string or sequence."""
    if value is None:
        return None
    if isinstance(value, str):
        items = [c.strip() for c in value.split(",") if c.strip()]
        return items or None
    if isinstance(value, (list, tuple, set)):
        items = [str(c).strip() for c in value if str(c).strip()]
        return items or None
    return None


def load_pipeline_config(path: str | os.PathLike[str] | None) -> dict[str, Any]:
    """Load pipeline configuration from a YAML or JSON file."""
    if not path:
        return {}
    path_str = os.fspath(path)
    if not os.path.exists(path_str):
        return {}
    try:
        with open(path_str, "r", encoding="utf-8") as handle:
            if path_str.lower().endswith((".yaml", ".yml")):
                if yaml is None:
                    raise RuntimeError("PyYAML is required to parse YAML configs.")
                return yaml.safe_load(handle) or {}
            return json.load(handle) or {}
    except RuntimeError:
        raise
    except Exception as exc:
        logger.warning("Failed to load config %s: %s", path_str, exc)
        return {}


def _resolve_source(raw_source: Any) -> Any:
    """Resolve synthetic/mock alias or delegate to camera source resolver."""
    if raw_source is None:
        return "synthetic"
    if str(raw_source).strip().lower() in ("synthetic", "mock"):
        return "synthetic"
    return resolve_camera_source(raw_source)


def _is_video_file(source: Any) -> bool:
    """Return True if source points to a local file or video extension."""
    if not isinstance(source, str):
        return False
    return os.path.exists(source) or source.lower().endswith((".mp4", ".avi", ".mkv", ".mov"))


def _probe_db_reid_model(db_path: str | None) -> str | None:
    """Infer Re-ID model from existing database embedding dimensions."""
    if not db_path or not os.path.exists(db_path):
        return None
    db: TrackerDB | None = None
    try:
        db = TrackerDB(db_path)
        sigs = db.get_signatures()
        if sigs and hasattr(sigs[0].get("embedding"), "shape"):
            dim = int(sigs[0]["embedding"].shape[0])
            if dim == 2560:
                return "dual"
            if dim == 512:
                return "onnx"
    except Exception:
        return None
    finally:
        if db is not None:
            db.close()
    return None


def _normalize_reid_name(raw_name: Any) -> str | None:
    """Normalize Re-ID model name, treating 'none' or empty as disabled."""
    if raw_name is None:
        return None
    text = str(raw_name).strip()
    if not text or text.lower() == "none":
        return None
    return text


@dataclass
class PipelineConfig:
    """Normalized configuration for assembling a unified CV pipeline."""

    camera_id: str = "default"
    source: Any = "synthetic"
    resolution: tuple[int, int] = (640, 480)
    framerate: int = 30
    buffer_size: int = 1
    auto_reconnect: bool = True
    reconnect_delay: float = 1.0
    loop_video: bool = False
    detector_model: str = "mock"
    detector_confidence: float = 0.25
    detector_classes: list[str] | None = None
    detector_fallback_mock: bool = False
    tracker_type: str = "centroid"
    max_disappeared: int = 30
    min_hits: int = 2
    iou_threshold: float = 0.2
    reid_model: str | None = "color"
    reid_threshold: float = 0.65
    db_path: str | None = None
    enable_governance: bool = False
    enable_event_bus_fallback: bool = False
    enable_memory_indexing: bool = True
    heatmap_enabled: bool = True
    heatmap_decay: float | None = 0.998
    show_heatmap: bool = False
    output_path: str | None = None
    tripwires: list[dict[str, Any]] = field(default_factory=list)
    zones: list[dict[str, Any]] = field(default_factory=list)
    raw_config: dict[str, Any] = field(default_factory=dict)
    config_path: str | None = None

    @classmethod
    def from_dict(
        cls,
        cfg: dict[str, Any] | None = None,
        *,
        camera_id: str = "default",
        db_path: str | None = None,
        source_override: Any = None,
        detector_fallback_mock: bool = True,
        enable_governance: bool = True,
        enable_event_bus_fallback: bool = True,
        enable_memory_indexing: bool = True,
        default_source: str = "synthetic",
        default_detector: str = "mock",
        probe_db_reid: bool = False,
        config_path: str | None = None,
    ) -> "PipelineConfig":
        """Build a normalized PipelineConfig from a nested config dictionary."""
        data = dict(cfg or {})
        video_cfg = data.get("video", {})
        det_cfg = data.get("detector", {})
        trk_cfg = data.get("tracker", {})
        reid_cfg = data.get("reid", {})
        db_cfg = data.get("database", {})
        ana_cfg = data.get("analytics", {})
        vis_cfg = data.get("visualization", {})
        mem_cfg = data.get("memory", {})
        hm_cfg = ana_cfg.get("heatmap", {})

        raw_source = source_override if source_override is not None else video_cfg.get("source", default_source)
        source = _resolve_source(raw_source)
        tracker_type = str(trk_cfg.get("type", "centroid")).strip().lower()
        default_iou = 0.3 if tracker_type == "sort" else 0.2
        resolved_db = db_path if db_path is not None else db_cfg.get("path")

        reid_raw = reid_cfg.get("model")
        if reid_raw is None and probe_db_reid:
            reid_raw = _probe_db_reid_model(resolved_db or "data/tracker.db")
        if reid_raw is None and "model" not in reid_cfg:
            reid_raw = "color"
        reid_model = _normalize_reid_name(reid_raw)
        if resolved_db is None and reid_model is not None:
            resolved_db = "data/tracker.db"

        decay_val = hm_cfg.get("decay", 0.998)
        return cls(
            camera_id=camera_id,
            source=source,
            resolution=parse_resolution(video_cfg.get("resolution")),
            framerate=int(video_cfg.get("framerate", 30)),
            buffer_size=int(video_cfg.get("buffer_size", 1)),
            auto_reconnect=bool(video_cfg.get("auto_reconnect", True)),
            reconnect_delay=float(video_cfg.get("reconnect_delay", 1.0)),
            loop_video=_is_video_file(source) or bool(video_cfg.get("loop", False)),
            detector_model=str(det_cfg.get("model", default_detector)).strip().lower(),
            detector_confidence=float(det_cfg.get("confidence", 0.25)),
            detector_classes=parse_classes(det_cfg.get("classes")),
            detector_fallback_mock=detector_fallback_mock,
            tracker_type=tracker_type,
            max_disappeared=int(trk_cfg.get("max_disappeared", trk_cfg.get("max_age", 30))),
            min_hits=int(trk_cfg.get("min_hits", 2)),
            iou_threshold=float(trk_cfg.get("iou_threshold", default_iou)),
            reid_model=reid_model,
            reid_threshold=float(reid_cfg.get("threshold", 0.65)),
            db_path=resolved_db,
            enable_governance=enable_governance,
            enable_event_bus_fallback=enable_event_bus_fallback,
            enable_memory_indexing=bool(mem_cfg.get("indexing", enable_memory_indexing)),
            heatmap_enabled=bool(hm_cfg.get("enabled", True)),
            heatmap_decay=float(decay_val) if decay_val is not None else None,
            show_heatmap=bool(vis_cfg.get("draw_heatmap", False)),
            tripwires=list(ana_cfg.get("tripwires", [])),
            zones=list(ana_cfg.get("zones", [])),
            raw_config=data,
            config_path=config_path,
        )

    @classmethod
    def from_cli_args(
        cls,
        args: Any,
        cfg: dict[str, Any] | None = None,
    ) -> "PipelineConfig":
        """Build PipelineConfig by layering CLI Namespace overrides onto a config dict."""
        data = dict(cfg or {})
        gov_cfg = data.get("governance", {})
        gov_enabled = bool(getattr(args, "governance", False) or gov_cfg.get("enabled", False))
        base = cls.from_dict(
            data,
            db_path=getattr(args, "db", None),
            source_override=getattr(args, "source", None),
            detector_fallback_mock=False,
            enable_governance=gov_enabled,
            enable_event_bus_fallback=False,
            default_source="0",
            default_detector="haar",
            probe_db_reid=True,
            config_path=getattr(args, "config", None),
        )
        if getattr(args, "resolution", None):
            base.resolution = parse_resolution(args.resolution, default=base.resolution)
        if getattr(args, "framerate", None):
            base.framerate = int(args.framerate)
        if getattr(args, "detector", None):
            base.detector_model = str(args.detector).strip().lower()
        if getattr(args, "conf", None) is not None:
            base.detector_confidence = float(args.conf)
        if getattr(args, "classes", None) is not None:
            base.detector_classes = parse_classes(args.classes)
        if getattr(args, "tracker", None):
            base.tracker_type = str(args.tracker).strip().lower()
        if getattr(args, "reid", None) is not None:
            base.reid_model = _normalize_reid_name(args.reid)
        if getattr(args, "reid_thresh", None) is not None:
            base.reid_threshold = float(args.reid_thresh)
        if getattr(args, "heatmap", False):
            base.show_heatmap = True
        if getattr(args, "output", None):
            base.output_path = args.output
        return base

