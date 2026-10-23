#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker — Main Entrypoint.

Supports modular Edge AI detection backends:
- ONNX Runtime: YOLOv8, YOLO11
- Classical: Haar Cascades (Face, Eye)
- Synthetic / CI: Mock Detector

Controls:
  'q' - Quit
  'd' - Clear tracked objects in scene
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import sys
import os
import time
import argparse

from intelligent_tracker.high_objects import World
from intelligent_tracker.detectors import DetectorFactory, COCO_CLASSES


def parse_args():
    parser = argparse.ArgumentParser(
        description="Intelligent Tracker — Edge AI Retail & Security Analytics",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--detector",
        default="haar",
        choices=["haar", "yolov8", "yolo11", "mock", "face", "eye", "color"],
        help="Detection architecture to use",
    )
    parser.add_argument(
        "--source",
        default="0",
        help="Video source: camera index (0, 1), 'synthetic'/'mock', video file path, or RTSP URL",
    )
    parser.add_argument(
        "--resolution",
        default="640x480",
        help="Input resolution formatted as WIDTHxHEIGHT",
    )
    parser.add_argument(
        "--framerate",
        type=int,
        default=30,
        help="Target processing frame rate",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=0.25,
        help="Confidence threshold for AI detectors (0.0 to 1.0)",
    )
    parser.add_argument(
        "--classes",
        nargs="*",
        default=None,
        help="Filter detected classes (e.g. 'person' or class IDs like 0)",
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


def parse_resolution(res_str):
    try:
        parts = res_str.lower().split("x")
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return 640, 480


def main():
    args = parse_args()
    res_w, res_h = parse_resolution(args.resolution)

    # Resolve camera source
    source = args.source
    if source.isdigit():
        source = int(source)
    elif source.lower() in ("synthetic", "mock"):
        source = "mock"

    print("=" * 60)
    print("Intelligent Tracker — Edge AI Analytics Platform")
    print("=" * 60)
    print("  Detector   : {}".format(args.detector))
    print("  Source     : {}".format(args.source))
    print("  Resolution : {}x{}".format(res_w, res_h))
    print("  Framerate  : {} FPS".format(args.framerate))
    print("  Mode       : {}".format("Headless" if args.headless else "Interactive GUI"))
    print("=" * 60)

    # Initialize World and Scene
    world = World(name="World")
    scene = world.create_scene([source], name="TrackerScene", framerate=args.framerate, resolution=(res_w, res_h))

    # Initialize Detector
    detector_kwargs = {}
    if args.detector in ("yolov8", "yolo11", "onnx"):
        detector_kwargs["conf_threshold"] = args.conf
        if args.classes:
            detector_kwargs["classes"] = args.classes

    try:
        detector = world.create_detector(args.detector, **detector_kwargs)
        print("[INFO] Successfully initialized detector: {}".format(detector.__class__.__name__))
    except Exception as e:
        print("[ERROR] Failed to initialize detector '{}': {}".format(args.detector, e))
        sys.exit(1)

    if args.headless:
        print("[INFO] Running in headless mode for {} frames...".format(args.frames if args.frames > 0 else "infinite"))
        start_time = time.time()
        frame_count = 0
        try:
            while True:
                scene.compute()
                frame_count += 1
                if 0 < args.frames <= frame_count:
                    break
        except KeyboardInterrupt:
            print("\n[INFO] Stopped by user.")
        elapsed = time.time() - start_time
        fps = frame_count / elapsed if elapsed > 0 else 0
        print("[SUMMARY] Processed {} frames in {:.2f}s ({:.1f} FPS)".format(frame_count, elapsed, fps))
        world.close()
    else:
        print("[INFO] Opening visualization window. Press 'q' in the window to quit, 'd' to clear objects.")
        world.show(throw=False)
        world.block(close=True)
        print("[INFO] Application closed.")


if __name__ == "__main__":
    main()