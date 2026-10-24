#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker — Edge AI Retail & Security Analytics Platform.

Supports:
- Robust Video Ingestion: RTSP network streams, USB webcams, video files, synthetic feeds.
- Edge AI Detectors: YOLOv8, YOLO11 (ONNX Runtime), Haar Cascades, Mock detector.
- Multi-Object Tracking: CentroidTracker (IoU + Euclidean), SortTracker (Kalman).
- Retail & Security Analytics:
  - Polygonal Zone ROIs (occupancy counting, dwell times)
  - Virtual Tripwires (bidirectional entry/exit crossing detection)
  - Spatial Occupancy Heatmaps (Gaussian density accumulation, decay, false-color overlay)
- YAML Configuration: Template-driven setup via `--config configs/demo.yaml`.
- Output recording: Headless annotated video export via `--output result.mp4`.

Controls (Interactive GUI):
  'q' - Quit application
  'd' - Clear / reset active tracks
  'h' - Toggle occupancy heatmap overlay
  's' - Save snapshot image and analytics summary report
"""

from __future__ import division, print_function, absolute_import

import os
import sys
import time
import json
import argparse
from typing import Dict, Any, Optional

import cv2
import numpy as np

try:
    import yaml
except ImportError:
    yaml = None

from intelligent_tracker.detectors import DetectorFactory, COCO_CLASSES
from intelligent_tracker.video import VideoSource
from intelligent_tracker.tracker import TrackerFactory
from intelligent_tracker.geometry import Tripwire, ZoneROI
from intelligent_tracker.analytics import OccupancyHeatmap, AnalyticsEngine


def parse_args():
    parser = argparse.ArgumentParser(
        description="Intelligent Tracker — Edge AI Retail & Security Analytics",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
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
        "--source",
        default=None,
        help="Video source: camera index (0, 1), 'synthetic'/'mock', video file path, or RTSP URL",
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
    return parser.parse_args()


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


def parse_resolution(res_str: Optional[str], default=(640, 480)):
    if not res_str:
        return default
    try:
        parts = str(res_str).lower().split("x")
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return default


def main():
    args = parse_args()
    cfg = load_config(args.config)

    # 1. Resolve Parameters (CLI arguments take precedence over config file)
    video_cfg = cfg.get("video", {})
    detector_cfg = cfg.get("detector", {})
    tracker_cfg = cfg.get("tracker", {})
    analytics_cfg = cfg.get("analytics", {})
    vis_cfg = cfg.get("visualization", {})

    # Resolution
    if args.resolution:
        res_w, res_h = parse_resolution(args.resolution)
    elif "resolution" in video_cfg:
        res_cfg = video_cfg["resolution"]
        if isinstance(res_cfg, (list, tuple)) and len(res_cfg) == 2:
            res_w, res_h = int(res_cfg[0]), int(res_cfg[1])
        else:
            res_w, res_h = parse_resolution(str(res_cfg))
    else:
        res_w, res_h = 640, 480

    # Source
    raw_source = args.source or video_cfg.get("source", "0")
    if str(raw_source).isdigit():
        source = int(raw_source)
    elif str(raw_source).lower() in ("synthetic", "mock"):
        source = "synthetic"
    else:
        source = str(raw_source)

    # Detector
    detector_name = args.detector or detector_cfg.get("model", "haar")
    conf_thresh = args.conf if args.conf is not None else float(detector_cfg.get("confidence", 0.25))
    classes_filter = args.classes if args.classes is not None else detector_cfg.get("classes", None)

    # Tracker
    tracker_name = args.tracker or tracker_cfg.get("type", "centroid")
    max_disappeared = int(tracker_cfg.get("max_disappeared", 30))
    min_hits = int(tracker_cfg.get("min_hits", 2))
    iou_thresh = float(tracker_cfg.get("iou_threshold", 0.2))

    # Framerate & Headless
    framerate = args.framerate or int(video_cfg.get("framerate", 30))
    show_heatmap = args.heatmap or vis_cfg.get("draw_heatmap", False)

    print("=" * 65)
    print("Intelligent Tracker — Edge AI Retail & Security Analytics")
    print("=" * 65)
    print("  Config File : {}".format(args.config if args.config else "[None - defaults]"))
    print("  Source      : {}".format(source))
    print("  Detector    : {} (conf={})".format(detector_name, conf_thresh))
    print("  Tracker     : {} (max_disappeared={}, min_hits={})".format(tracker_name, max_disappeared, min_hits))
    print("  Resolution  : {}x{}".format(res_w, res_h))
    print("  Target FPS  : {}".format(framerate))
    print("  Mode        : {}".format("Headless" if args.headless else "Interactive GUI"))
    if args.output:
        print("  Recording   : {}".format(args.output))
    print("=" * 65)

    # 2. Initialize Video Source
    video_source = VideoSource(
        source=source,
        buffer_size=int(video_cfg.get("buffer_size", 1)),
        auto_reconnect=bool(video_cfg.get("auto_reconnect", True)),
        reconnect_delay=float(video_cfg.get("reconnect_delay", 1.0)),
        fps_limit=float(framerate),
        width=res_w,
        height=res_h,
    )

    # 3. Initialize Detector
    det_kwargs = {}
    if detector_name in ("yolov8", "yolo11", "onnx"):
        det_kwargs["conf_threshold"] = conf_thresh
        if classes_filter:
            det_kwargs["classes"] = classes_filter

    try:
        detector = DetectorFactory.create(detector_name, **det_kwargs)
        print("[INFO] Initialized detector backend: {}".format(detector.__class__.__name__))
    except Exception as e:
        print("[ERROR] Failed to initialize detector '{}': {}".format(detector_name, e))
        sys.exit(1)

    # 4. Initialize Multi-Object Tracker
    try:
        tracker = TrackerFactory.create(
            tracker_name,
            max_disappeared=max_disappeared,
            min_hits=min_hits,
            iou_threshold=iou_thresh,
        )
        print("[INFO] Initialized multi-object tracker: {}".format(tracker.__class__.__name__))
    except Exception as e:
        print("[ERROR] Failed to initialize tracker '{}': {}".format(tracker_name, e))
        sys.exit(1)

    # 5. Initialize Analytics Engine (Zones, Tripwires, Heatmap)
    heatmap_cfg = analytics_cfg.get("heatmap", {})
    heatmap_enabled = bool(heatmap_cfg.get("enabled", True))
    heatmap_decay = float(heatmap_cfg.get("decay", 0.998)) if heatmap_cfg.get("decay") is not None else None

    analytics = AnalyticsEngine(
        resolution=(res_w, res_h),
        heatmap_enabled=heatmap_enabled,
        heatmap_decay=heatmap_decay,
    )

    # Parse Tripwires from config
    for tw_data in analytics_cfg.get("tripwires", []):
        tw_name = tw_data.get("name", "tripwire")
        tw_line = tw_data.get("line")
        tw_bi = bool(tw_data.get("bidirectional", True))
        tw_col = tuple(tw_data.get("color", [0, 255, 255]))
        if tw_line and len(tw_line) >= 2:
            tripwire = Tripwire(line_segment=tw_line, name=tw_name, bidirectional=tw_bi, color=tw_col)
            analytics.add_tripwire(tripwire)
            print("[INFO] Registered Tripwire: '{}' {}".format(tw_name, tw_line))

    # Parse Zones from config
    for z_data in analytics_cfg.get("zones", []):
        z_name = z_data.get("name", "zone")
        z_poly = z_data.get("polygon")
        z_dwell = float(z_data.get("dwell_threshold", 5.0))
        z_col = tuple(z_data.get("color", [0, 200, 100]))
        if z_poly and len(z_poly) >= 3:
            zone = ZoneROI(polygon=z_poly, name=z_name, dwell_threshold=z_dwell, color=z_col)
            analytics.add_zone(zone)
            print("[INFO] Registered Zone ROI: '{}' ({} vertices)".format(z_name, len(z_poly)))

    # 6. Initialize Video Writer (if output specified)
    writer = None
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(args.output, fourcc, float(framerate), (res_w, res_h))
        print("[INFO] Video recording enabled -> {}".format(args.output))

    # 7. Main Tracking & Analytics Loop
    frame_count = 0
    start_time = time.time()
    measured_fps = 0.0
    fps_history = []

    print("[INFO] Starting pipeline execution...")
    with video_source as vs:
        try:
            while True:
                t0 = time.time()
                ret, frame = vs.read(timeout=2.0)
                if not ret or frame is None:
                    # Stream ended or timed out
                    print("[WARN] Video source timeout or stream completed.")
                    break

                # Ensure frame matches target resolution if resized
                if frame.shape[1] != res_w or frame.shape[0] != res_h:
                    frame = cv2.resize(frame, (res_w, res_h))

                # Step A: Object Detection
                detections = detector.detect(frame)

                # Step B: Multi-Object Tracking
                tracks = tracker.update(detections, timestamp=t0)

                # Step C: Analytics (Tripwires, Zones, Heatmap)
                analytics_telemetry = analytics.update(tracks, timestamp=t0)

                # Step D: Visual Overlay
                annotated = analytics.draw(
                    frame=frame,
                    draw_zones=vis_cfg.get("draw_zones", True),
                    draw_tripwires=vis_cfg.get("draw_tripwires", True),
                    draw_heatmap=show_heatmap,
                    draw_tracks=vis_cfg.get("draw_tracks", True),
                    tracks=tracks,
                    draw_hud=vis_cfg.get("draw_hud", True),
                    fps=measured_fps,
                )

                # Record frame if output writer active
                if writer is not None:
                    writer.write(annotated)

                frame_count += 1
                dt = time.time() - t0
                if dt > 0:
                    fps_history.append(1.0 / dt)
                    if len(fps_history) > 30:
                        fps_history.pop(0)
                    measured_fps = sum(fps_history) / len(fps_history)

                # Log periodic events
                if analytics_telemetry["new_events"]:
                    for ev in analytics_telemetry["new_events"]:
                        if "direction" in ev:
                            print("[EVENT] Tripwire '{}' crossed by Track #{} ({})".format(
                                ev["tripwire_id"], ev["track_id"], ev["direction"]
                            ))
                        else:
                            print("[EVENT] Zone '{}': Track #{} -> {} (dwell: {:.1f}s)".format(
                                ev["zone_id"], ev["track_id"], ev["event_type"], ev.get("dwell_time", 0.0)
                            ))

                # Step E: Display or Headless termination
                if args.headless:
                    if 0 < args.frames <= frame_count:
                        break
                else:
                    cv2.imshow("Intelligent Tracker — Analytics", annotated)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord("q"):
                        print("[INFO] Quit requested by user.")
                        break
                    elif key == ord("d"):
                        tracker.reset()
                        print("[INFO] Tracks cleared.")
                    elif key == ord("h"):
                        show_heatmap = not show_heatmap
                        print("[INFO] Heatmap display toggled: {}".format(show_heatmap))
                    elif key == ord("s"):
                        snap_img = "snapshot_{}.png".format(int(time.time()))
                        snap_rep = "analytics_report_{}.json".format(int(time.time()))
                        cv2.imwrite(snap_img, annotated)
                        analytics.export_summary(snap_rep)
                        print("[INFO] Saved snapshot '{}' and report '{}'".format(snap_img, snap_rep))

        except KeyboardInterrupt:
            print("\n[INFO] Stopped by user (KeyboardInterrupt).")

    # 8. Clean Shutdown & Summary
    elapsed = time.time() - start_time
    final_fps = frame_count / elapsed if elapsed > 0 else 0.0

    if writer is not None:
        writer.release()
        print("[INFO] Video recording finalized: {}".format(args.output))

    if not args.headless:
        cv2.destroyAllWindows()

    summary = analytics.export_summary()
    print("=" * 65)
    print("Pipeline Summary:")
    print("  Processed Frames : {}".format(frame_count))
    print("  Total Time       : {:.2f}s".format(elapsed))
    print("  Average Speed    : {:.1f} FPS".format(final_fps))
    print("  Connection Stats : {}".format(video_source.get_metrics()))
    print("  Zone Summary     : {}".format(summary["zones"]))
    print("  Tripwire Summary : {}".format(summary["tripwires"]))
    print("=" * 65)


if __name__ == "__main__":
    main()