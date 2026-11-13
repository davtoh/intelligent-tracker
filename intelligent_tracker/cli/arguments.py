# -*- coding: utf-8 -*-
"""
Intelligent Tracker CLI - Argument Parsing & Configuration Loading.
"""

import os
import json
import argparse
from typing import Dict, Any, Optional, Tuple

try:
    import yaml
except ImportError:
    yaml = None


def build_argument_parser() -> argparse.ArgumentParser:
    """Construct and configure the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Intelligent Tracker - Edge AI Retail & Security Analytics",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    _add_model_args(parser)
    _add_pipeline_args(parser)
    _add_runtime_args(parser)
    return parser


def _add_model_args(parser: argparse.ArgumentParser) -> None:
    """Register detector, tracker, and re-identification arguments."""
    _add_detector_args(parser)
    _add_reid_args(parser)


def _add_detector_args(parser: argparse.ArgumentParser) -> None:
    """Register detector and tracker configuration arguments."""
    parser.add_argument(
        "--config",
        default=None,
        help="Path to YAML/JSON configuration file (e.g. configs/demo.yaml, configs/retail.yaml)",
    )
    parser.add_argument(
        "--detector",
        default=None,
        choices=["haar", "yolov8", "yolo11", "mock", "face", "eye", "color"],
        help="Detection architecture to use (default: yolov8 or config value)",
    )
    parser.add_argument(
        "--tracker",
        default=None,
        choices=["centroid", "sort"],
        help="Multi-object tracking algorithm (default: centroid or config value)",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=None,
        help="Confidence threshold for AI detectors (0.0 to 1.0)",
    )
    parser.add_argument(
        "--classes",
        nargs="*",
        default=None,
        help="Filter detected classes (e.g. 'person' or class IDs like 0)",
    )


def _add_reid_args(parser: argparse.ArgumentParser) -> None:
    """Register Re-ID and matching parameters."""
    parser.add_argument(
        "--reid",
        default=None,
        choices=["color", "onnx", "mock", "none", "dual", "dual_model"],
        help="Visual Re-ID feature extractor for cross-session identification (default: color or config value)",
    )
    parser.add_argument(
        "--reid-thresh",
        type=float,
        default=None,
        help="Cosine similarity threshold for Re-ID gallery matching (0.0 to 1.0)",
    )


def _add_pipeline_args(parser: argparse.ArgumentParser) -> None:
    """Register video source, geometry, database, and recording arguments."""
    parser.add_argument(
        "--source",
        default=None,
        help="Video source: camera index (0, 1), 'real'/'auto' (first physical webcam with data), 'synthetic', video file, or RTSP URL",
    )
    parser.add_argument(
        "--resolution",
        default=None,
        help="Input resolution formatted as WIDTHxHEIGHT (e.g. 640x480, 1280x720)",
    )
    parser.add_argument(
        "--framerate",
        type=int,
        default=None,
        help="Target processing frame rate (default: 30)",
    )
    parser.add_argument(
        "--heatmap",
        action="store_true",
        help="Enable real-time occupancy heatmap visualization",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional path to output annotated video file (e.g. output.mp4)",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Path to SQLite database file for Re-ID gallery and sighting audit trail (default: data/tracker.db)",
    )


def _add_runtime_args(parser: argparse.ArgumentParser) -> None:
    """Register GUI mode and execution limits."""
    parser.add_argument(
        "--gui",
        default="opencv",
        choices=["opencv", "forms"],
        help="GUI backend: 'opencv' (high-speed HUD with mouse selection) or 'forms' (Matplotlib toolbar)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without GUI window (ideal for CI, servers, and benchmarks)",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=60,
        help="Maximum frames to process in headless mode before exiting (0 = run indefinitely)",
    )
    parser.add_argument(
        "--governance",
        action="store_true",
        help="Enable RSAC, active learning, and universal enrollment governance subsystems",
    )


def parse_args(args: Optional[list] = None) -> argparse.Namespace:
    """Parse CLI arguments with default help formatter."""
    parser = build_argument_parser()
    return parser.parse_args(args)


def load_config(config_path: Optional[str]) -> Dict[str, Any]:
    """Load configuration from YAML or JSON file."""
    if not config_path or not os.path.exists(config_path):
        return {}

    with open(config_path, "r", encoding="utf-8") as f:
        if config_path.endswith((".yaml", ".yml")):
            if yaml is None:
                raise RuntimeError("PyYAML is required to parse YAML configs. Run `pip install pyyaml`.")
            return yaml.safe_load(f) or {}
        elif config_path.endswith(".json"):
            return json.load(f) or {}
    return {}


def parse_resolution(res_str: Optional[str], default: Tuple[int, int] = (640, 480)) -> Tuple[int, int]:
    """Parse resolution string formatted as WIDTHxHEIGHT."""
    if not res_str:
        return default
    try:
        parts = str(res_str).lower().split("x")
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return default
