# -*- coding: utf-8 -*-
"""
Intelligent Tracker CLI - Pipeline Builder & Subsystem Assembly.
"""

import os
import sys
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple

import cv2

from intelligent_tracker.detectors import DetectorFactory
from intelligent_tracker.video import VideoSource, resolve_camera_source
from intelligent_tracker.tracker import TrackerFactory
from intelligent_tracker.geometry import Tripwire, ZoneROI
from intelligent_tracker.analytics import AnalyticsEngine
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.reid import ReIDExtractorFactory
from intelligent_tracker.matcher import GalleryMatcher
from intelligent_tracker.cli.arguments import parse_resolution


@dataclass
class PipelineContext:
    """Holds active execution pipeline components and runtime parameters."""
    video_source: VideoSource
    detector: Any
    tracker: Any
    analytics: AnalyticsEngine
    db: Optional[TrackerDB]
    reid_extractor: Any
    gallery_matcher: Optional[GalleryMatcher]
    event_pipeline: Optional[Dict[str, Any]]
    event_bus: Any
    writer: Optional[cv2.VideoWriter]
    params: Dict[str, Any]


def resolve_pipeline_params(args, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve CLI options against config file defaults."""
    video_cfg = cfg.get("video", {})
    detector_cfg = cfg.get("detector", {})
    tracker_cfg = cfg.get("tracker", {})
    vis_cfg = cfg.get("visualization", {})
    reid_cfg = cfg.get("reid", {})
    db_cfg = cfg.get("database", {})

    res_w, res_h = _resolve_resolution(args, video_cfg)
    raw_source = args.source or video_cfg.get("source", "0")
    source = "synthetic" if str(raw_source).lower() in ("synthetic", "mock") else resolve_camera_source(raw_source)

    reid_name = _resolve_reid_model(args, reid_cfg, db_cfg)
    db_path = args.db or db_cfg.get("path", "data/tracker.db" if reid_name else None)

    return {
        "res_w": res_w,
        "res_h": res_h,
        "source": source,
        "detector_name": args.detector or detector_cfg.get("model", "haar"),
        "conf_thresh": args.conf if args.conf is not None else float(detector_cfg.get("confidence", 0.25)),
        "classes_filter": args.classes if args.classes is not None else detector_cfg.get("classes", None),
        "tracker_name": args.tracker or tracker_cfg.get("type", "centroid"),
        "max_disappeared": int(tracker_cfg.get("max_disappeared", 30)),
        "min_hits": int(tracker_cfg.get("min_hits", 2)),
        "iou_thresh": float(tracker_cfg.get("iou_threshold", 0.2)),
        "framerate": args.framerate or int(video_cfg.get("framerate", 30)),
        "show_heatmap": args.heatmap or vis_cfg.get("draw_heatmap", False),
        "reid_name": reid_name,
        "db_path": db_path,
        "reid_threshold": args.reid_thresh if args.reid_thresh is not None else float(reid_cfg.get("threshold", 0.65)),
        "video_cfg": video_cfg,
        "analytics_cfg": cfg.get("analytics", {}),
        "vis_cfg": vis_cfg,
        "output": args.output,
        "headless": args.headless,
        "gui": args.gui,
        "frames": args.frames, "config": args.config,
    }


def _resolve_resolution(args, video_cfg: Dict[str, Any]) -> Tuple[int, int]:
    """Determine width and height from args or video configuration."""
    if args.resolution:
        return parse_resolution(args.resolution)
    if "resolution" in video_cfg:
        res_cfg = video_cfg["resolution"]
        if isinstance(res_cfg, (list, tuple)) and len(res_cfg) == 2:
            return int(res_cfg[0]), int(res_cfg[1])
        return parse_resolution(str(res_cfg))
    return 640, 480


def _resolve_reid_model(args, reid_cfg: Dict[str, Any], db_cfg: Dict[str, Any]) -> Optional[str]:
    """Probe existing database schema or args to pick reid model."""
    reid_name = args.reid or reid_cfg.get("model")
    db_path = args.db or db_cfg.get("path", "data/tracker.db")

    if reid_name is None and db_path and os.path.exists(db_path):
        try:
            probe_db = TrackerDB(db_path)
            probe_sigs = probe_db.get_signatures()
            if probe_sigs and hasattr(probe_sigs[0].get("embedding"), "shape"):
                dim = probe_sigs[0]["embedding"].shape[0]
                reid_name = "dual" if dim == 2560 else ("onnx" if dim == 512 else None)
        except Exception:
            pass

    if reid_name is None:
        reid_name = reid_cfg.get("model", "color")
    if reid_name and str(reid_name).lower() == "none":
        return None
    return reid_name


def build_pipeline(args, cfg: Dict[str, Any]) -> PipelineContext:
    """Instantiate and wire all pipeline components into a PipelineContext."""
    p = resolve_pipeline_params(args, cfg)
    _print_banner(p)

    video_source = VideoSource(
        source=p["source"],
        buffer_size=int(p["video_cfg"].get("buffer_size", 1)),
        auto_reconnect=bool(p["video_cfg"].get("auto_reconnect", True)),
        reconnect_delay=float(p["video_cfg"].get("reconnect_delay", 1.0)),
        fps_limit=float(p["framerate"]),
        width=p["res_w"],
        height=p["res_h"],
    )

    detector = _build_detector(p)
    tracker = _build_tracker(p)
    analytics = _build_analytics(p)
    db, reid_extractor, gallery_matcher = _build_reid(p)
    event_pipeline, event_bus = _build_alerting(cfg, analytics)
    writer = _build_writer(p)

    return PipelineContext(
        video_source=video_source,
        detector=detector,
        tracker=tracker,
        analytics=analytics,
        db=db,
        reid_extractor=reid_extractor,
        gallery_matcher=gallery_matcher,
        event_pipeline=event_pipeline,
        event_bus=event_bus,
        writer=writer,
        params=p,
    )


def _print_banner(p: Dict[str, Any]) -> None:
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


def _build_detector(p: Dict[str, Any]):
    """Instantiate detector backend."""
    det_kwargs = {}
    if p["detector_name"] in ("yolov8", "yolo11", "onnx"):
        det_kwargs["conf_threshold"] = p["conf_thresh"]
        if p["classes_filter"]:
            det_kwargs["classes"] = p["classes_filter"]
    try:
        det = DetectorFactory.create(p["detector_name"], **det_kwargs)
        print(f"[INFO] Initialized detector backend: {det.__class__.__name__}")
        return det
    except Exception as e:
        print(f"[ERROR] Failed to initialize detector '{p['detector_name']}': {e}")
        sys.exit(1)


def _build_tracker(p: Dict[str, Any]):
    """Instantiate tracking engine."""
    try:
        trk = TrackerFactory.create(
            p["tracker_name"],
            max_disappeared=p["max_disappeared"],
            min_hits=p["min_hits"],
            iou_threshold=p["iou_thresh"],
        )
        print(f"[INFO] Initialized multi-object tracker: {trk.__class__.__name__}")
        return trk
    except Exception as e:
        print(f"[ERROR] Failed to initialize tracker '{p['tracker_name']}': {e}")
        sys.exit(1)


def _build_analytics(p: Dict[str, Any]) -> AnalyticsEngine:
    """Build spatial analytics engine with configured tripwires and zones."""
    acfg = p["analytics_cfg"]
    hm_cfg = acfg.get("heatmap", {})
    analytics = AnalyticsEngine(
        resolution=(p["res_w"], p["res_h"]),
        heatmap_enabled=bool(hm_cfg.get("enabled", True)),
        heatmap_decay=float(hm_cfg.get("decay", 0.998)) if hm_cfg.get("decay") is not None else None,
    )
    for tw in acfg.get("tripwires", []):
        line = tw.get("line")
        if line and len(line) >= 2:
            analytics.add_tripwire(Tripwire(
                line_segment=line,
                name=tw.get("name", "tripwire"),
                bidirectional=bool(tw.get("bidirectional", True)),
                color=tuple(tw.get("color", [0, 255, 255])),
            ))
            print(f"[INFO] Registered Tripwire: '{tw.get('name', 'tripwire')}' {line}")
    for z in acfg.get("zones", []):
        poly = z.get("polygon")
        if poly and len(poly) >= 3:
            cap = z.get("capacity_limit", z.get("max_occupancy"))
            analytics.add_zone(ZoneROI(
                polygon=poly,
                name=z.get("name", "zone"),
                dwell_threshold=float(z.get("dwell_threshold", 5.0)),
                color=tuple(z.get("color", [0, 200, 100])),
                capacity_limit=cap,
            ))
            cap_str = f" (capacity: {cap})" if cap else ""
            print(f"[INFO] Registered Zone ROI: '{z.get('name', 'zone')}' ({len(poly)} vertices){cap_str}")
    return analytics


def _build_reid(p: Dict[str, Any]) -> Tuple[Optional[TrackerDB], Any, Optional[GalleryMatcher]]:
    """Configure optional Re-ID database, extractor, and gallery matcher."""
    if not p["reid_name"]:
        return None, None, None
    try:
        db = TrackerDB(p["db_path"])
        extractor = ReIDExtractorFactory.create(p["reid_name"])
        matcher = GalleryMatcher(db=db, extractor=extractor, reid_threshold=p["reid_threshold"])
        print(f"[INFO] Initialized Re-ID Engine: {extractor.__class__.__name__} (gallery: {matcher.gallery_size} signatures) -> {p['db_path']}")
        return db, extractor, matcher
    except Exception as e:
        print(f"[WARN] Failed to initialize Re-ID engine: {e}")
        return None, None, None


def _build_alerting(cfg: Dict[str, Any], analytics: AnalyticsEngine) -> Tuple[Optional[Dict[str, Any]], Any]:
    """Configure alerting pipeline (webhooks, Telegram, MQTT, rules)."""
    alert_cfg = cfg.get("alerting", cfg.get("events"))
    if not alert_cfg:
        return None, None
    try:
        from intelligent_tracker.events import setup_event_pipeline
        pipeline = setup_event_pipeline(cfg)
        bus = pipeline.get("event_bus")
        analytics.event_bus = bus
        print("[INFO] Initialized Event Dispatching & Alerting Pipeline:")
        if pipeline.get("webhooks"):
            print(f"  - Webhooks   : {len(pipeline['webhooks'])} active endpoint(s)")
        if pipeline.get("telegram"):
            print(f"  - Telegram   : enabled (mock={pipeline['telegram'].mock})")
        if pipeline.get("mqtt"):
            mqtt_client = pipeline["mqtt"]
            state = "connected" if mqtt_client.is_connected else "offline"
            print(f"  - MQTT       : {state} (broker: {mqtt_client.broker}:{mqtt_client.port})")
        if pipeline.get("rule_engine"):
            print(f"  - Alert Rules: {len(pipeline['rule_engine'].rules)} active rule(s)")
        return pipeline, bus
    except Exception as e:
        print(f"[WARN] Failed to initialize event alerting pipeline: {e}")
        return None, None


def _build_writer(p: Dict[str, Any]) -> Optional[cv2.VideoWriter]:
    """Initialize output video recorder if requested."""
    if not p["output"]:
        return None
    os.makedirs(os.path.dirname(os.path.abspath(p["output"])) or ".", exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(p["output"], fourcc, float(p["framerate"]), (p["res_w"], p["res_h"]))
    print(f"[INFO] Video recording enabled -> {p['output']}")
    return writer
