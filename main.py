#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Edge AI Retail & Security Analytics Platform.

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
- Dual GUI Modes: High-speed OpenCV HUD (`--gui opencv`) or Classical Matplotlib Toolbar (`--gui forms`).

Controls (Interactive OpenCV GUI):
  'X' button  - Close window and quit cleanly
  'q' / ESC   - Quit application
  Spacebar    - Pause / Resume video playback
  Mouse Click - Click any tracked bounding box to inspect/select entity
  'd'         - Clear / reset active tracks
  'h'         - Toggle occupancy heatmap overlay
  's'         - Save instantaneous snapshot image and analytics summary report
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
from intelligent_tracker.video import VideoSource, resolve_camera_source
from intelligent_tracker.tracker import TrackerFactory
from intelligent_tracker.geometry import Tripwire, ZoneROI
from intelligent_tracker.analytics import OccupancyHeatmap, AnalyticsEngine
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.reid import ReIDExtractorFactory
from intelligent_tracker.matcher import GalleryMatcher


def parse_args():
    parser = argparse.ArgumentParser(
        description="Intelligent Tracker - Edge AI Retail & Security Analytics",
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
        "--db",
        default=None,
        help="Path to SQLite database file for Re-ID gallery and sighting audit trail (default: data/tracker.db)",
    )
    parser.add_argument(
        "--reid",
        default=None,
        choices=["color", "onnx", "mock", "none"],
        help="Visual Re-ID feature extractor for cross-session identification (default: none or config value)",
    )
    parser.add_argument(
        "--reid-thresh",
        type=float,
        default=None,
        help="Cosine similarity threshold for Re-ID gallery matching (0.0 to 1.0)",
    )
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


def run_legacy_forms_gui(args, res_w, res_h, source, detector_name, conf_thresh, classes_filter):
    """Fallback GUI using legacy Matplotlib forms with pan/zoom toolbar."""
    from intelligent_tracker.high_objects import World
    print("[INFO] Launching legacy Matplotlib GUI with interactive toolbar...")
    world = World(name="Intelligent Tracker")
    world.create_scene([source], name="TrackerScene", framerate=args.framerate or 30, resolution=(res_w, res_h))

    det_kwargs = {}
    if detector_name in ("yolov8", "yolo11", "onnx"):
        det_kwargs["conf_threshold"] = conf_thresh
        if classes_filter:
            det_kwargs["classes"] = classes_filter

    world.create_detector(detector_name, **det_kwargs)
    world.show(throw=False)
    world.block(close=True)
    print("[INFO] Application closed.")


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
    if str(raw_source).lower() in ("synthetic", "mock"):
        source = "synthetic"
    else:
        source = resolve_camera_source(raw_source)

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

    # Re-ID & SQLite Database configuration
    db_cfg = cfg.get("database", {})
    reid_cfg = cfg.get("reid", {})
    reid_name = args.reid or reid_cfg.get("model", "color")
    if reid_name and str(reid_name).lower() == "none":
        reid_name = None

    db_path = args.db or db_cfg.get("path", "data/tracker.db" if reid_name else None)
    reid_threshold = args.reid_thresh if args.reid_thresh is not None else float(reid_cfg.get("threshold", 0.65))

    print("=" * 65)
    print("Intelligent Tracker - Edge AI Retail & Security Analytics")
    print("=" * 65)
    print("  Config File : {}".format(args.config if args.config else "[None - defaults]"))
    print("  Source      : {}".format(source))
    print("  Detector    : {} (conf={})".format(detector_name, conf_thresh))
    print("  Tracker     : {} (max_disappeared={}, min_hits={})".format(tracker_name, max_disappeared, min_hits))
    print("  Re-ID Engine: {} (threshold={:.2f})".format(reid_name or "[Disabled]", reid_threshold))
    if db_path:
        print("  Database    : {}".format(db_path))
    print("  Resolution  : {}x{}".format(res_w, res_h))
    print("  Target FPS  : {}".format(framerate))
    print("  Mode        : {}".format("Headless" if args.headless else f"Interactive GUI ({args.gui})"))
    if args.output:
        print("  Recording   : {}".format(args.output))
    print("=" * 65)

    # Legacy Matplotlib GUI route
    if not args.headless and args.gui == "forms":
        run_legacy_forms_gui(args, res_w, res_h, source, detector_name, conf_thresh, classes_filter)
        return

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

    # 5b. Initialize Re-ID Engine & Sighting Database (if enabled)
    db = None
    reid_extractor = None
    gallery_matcher = None
    if reid_name:
        try:
            db = TrackerDB(db_path)
            reid_extractor = ReIDExtractorFactory.create(reid_name)
            gallery_matcher = GalleryMatcher(
                db=db,
                extractor=reid_extractor,
                reid_threshold=reid_threshold,
            )
            print("[INFO] Initialized Re-ID Engine: {} (gallery: {} signatures) -> {}".format(
                reid_extractor.__class__.__name__, gallery_matcher.gallery_size, db_path
            ))
        except Exception as e:
            print("[WARN] Failed to initialize Re-ID engine: {}".format(e))
            gallery_matcher = None

    # 6. Initialize Video Writer (if output specified)
    writer = None
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(args.output, fourcc, float(framerate), (res_w, res_h))
        print("[INFO] Video recording enabled -> {}".format(args.output))

    # 7. Setup Interactive Window & Mouse Callbacks
    window_name = "Intelligent Tracker - Analytics"
    selected_track_id = None
    paused = False
    current_tracks = {}

    def on_mouse_click(event, x, y, flags, param):
        nonlocal selected_track_id
        if event == cv2.EVENT_LBUTTONDOWN:
            clicked_tid = None
            for tid, trk in current_tracks.items():
                bx, by, bw, bh = trk.bbox
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    clicked_tid = tid
                    break
            selected_track_id = clicked_tid
            if clicked_tid is not None:
                trk = current_tracks[clicked_tid]
                disp_name = trk.entity_name or trk.identity_label or "Track #{}".format(clicked_tid)
                state_tag = " [{}]".format(trk.state.upper()) if trk.state != "confirmed" else ""
                print("[INSPECT] Selected {}{}: {} (conf: {:.2f}, dwell: {:.1f}s, vel: {})".format(
                    disp_name, state_tag, trk.label, trk.confidence, trk.dwell_time, trk.velocity
                ))
            else:
                print("[INSPECT] Deselected track.")

    if not args.headless:
        cv2.namedWindow(window_name, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(window_name, on_mouse_click)
        print("[INFO] Interactive Window Controls:")
        print("  - Click '[X]' button or press 'q' / ESC to quit")
        print("  - Press Spacebar to Pause / Resume playback")
        print("  - Click on any tracked bounding box to inspect/select")
        print("  - Press 'e' to enroll selected entity into Re-ID database")
        print("  - Press 'd' to clear tracks, 'h' to toggle heatmap, 's' to save snapshot")

    # 8. Main Tracking & Analytics Loop
    frame_count = 0
    start_time = time.time()
    measured_fps = 0.0
    fps_history = []
    window_closed = False

    print("[INFO] Starting pipeline execution...")
    with video_source as vs:
        try:
            while not window_closed:
                # Handle paused state
                if paused and not args.headless:
                    key = cv2.waitKey(30) & 0xFF
                    if key in (ord("q"), 27):
                        print("[INFO] Quit requested by user.")
                        break
                    try:
                        if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                            print("[INFO] Window closed via [X] button.")
                            break
                    except Exception:
                        print("[INFO] Window closed via [X] button.")
                        break
                    if key == ord(" "):
                        paused = False
                        print("[INFO] Playback resumed.")
                    continue

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
                current_tracks = tracks

                # Step B.5: Visual Re-ID Gallery Matching
                if gallery_matcher is not None:
                    id_events = gallery_matcher.match_tracks(
                        tracks=tracks,
                        frame=frame,
                        source=str(source),
                        timestamp=t0,
                    )
                    for ev in id_events:
                        print("[RE-ID] Identified Track #{}: '{}' [{}] (similarity: {:.1f}%)".format(
                            ev.track_id, ev.name, ev.category, float(ev.similarity) * 100
                        ))

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

                # Highlight selected track if inspected
                if selected_track_id and selected_track_id in tracks:
                    sel_trk = tracks[selected_track_id]
                    sx, sy, sw, sh = sel_trk.bbox
                    cv2.rectangle(annotated, (sx - 3, sy - 3), (sx + sw + 3, sy + sh + 3), (255, 255, 0), 2)
                    disp_name = sel_trk.entity_name or sel_trk.identity_label or "#{}".format(selected_track_id)
                    sel_label = "INSPECTING: {} [Dwell: {:.1f}s]".format(disp_name, sel_trk.dwell_time)
                    cv2.putText(annotated, sel_label, (sx, max(15, sy - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 2)

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
                    cv2.imshow(window_name, annotated)

                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord("q"), 27):
                        print("[INFO] Quit requested by user.")
                        break

                    # Check if window was closed via the [X] close button immediately after waitKey
                    try:
                        if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                            print("[INFO] Window closed via [X] button.")
                            window_closed = True
                            break
                    except Exception:
                        print("[INFO] Window closed via [X] button.")
                        window_closed = True
                        break

                    if key == ord(" "):
                        paused = not paused
                        print("[INFO] Playback {}".format("paused" if paused else "resumed"))
                    elif key == ord("e"):
                        if selected_track_id and selected_track_id in current_tracks and db is not None:
                            sel_trk = current_tracks[selected_track_id]
                            print("\n" + "=" * 50)
                            print(">>> ENROLL ENTITY IN GALLERY (Track #{}) <<<".format(sel_trk.track_id))
                            try:
                                ent_name = input("Enter Entity Name (e.g. 'Alice', 'Forklift #02'): ").strip()
                                if ent_name:
                                    ent_cat = input("Enter Category ['person', 'staff', 'vip', 'vehicle'] [person]: ").strip() or "person"
                                    enrolled = db.enroll_entity(
                                        name=ent_name,
                                        category=ent_cat,
                                        frame=frame,
                                        bbox=sel_trk.bbox,
                                        extractor=reid_extractor,
                                    )
                                    if gallery_matcher is not None:
                                        gallery_matcher.reload_gallery()
                                        gallery_matcher.reassign_track(sel_trk, enrolled["id"])
                                    print("[SUCCESS] Enrolled '{}' (ID #{}) into Gallery!".format(ent_name, enrolled["id"]))
                            except Exception as ex:
                                print("[WARN] Enrollment error: {}".format(ex))
                        else:
                            print("[INFO] Click on a tracked bounding box before pressing 'e' to enroll.")
                    elif key == ord("d"):
                        tracker.reset()
                        selected_track_id = None
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

    # 9. Clean Shutdown & Summary
    elapsed = time.time() - start_time
    final_fps = frame_count / elapsed if elapsed > 0 else 0.0

    if writer is not None:
        writer.release()
        print("[INFO] Video recording finalized: {}".format(args.output))

    if db is not None:
        db.close()
        print("[INFO] SQLite database closed.")

    if not args.headless:
        cv2.destroyAllWindows()
        for _ in range(5):
            cv2.waitKey(1)

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