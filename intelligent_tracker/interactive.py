#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Interactive Screen Selection, Entity Tagging & Visual Controls Module.

Provides:

- Interactive mouse click inspection on tracked bounding boxes in live/paused video.
- Real-time inspector overlay displaying Track ID, Re-ID entity match, trajectory,
  dwell duration, classification confidence, and velocity.
- On-screen Entity Enrollment dialog & prompt to assign name, category, and notes,
  automatically storing thumbnail crops and feature signatures into TrackerDB.
- Interactive ROI drawing: Click-and-draw virtual tripwires and polygonal zones
  directly on the video window.
- Dual GUI support: High-speed OpenCV HUD (``--gui opencv``) and Matplotlib (``--gui forms``).
- Standalone CLI execution (``python -m intelligent_tracker.interactive``).
"""

from __future__ import division, print_function, absolute_import

import os
import sys
import time
import argparse
from typing import Dict, List, Tuple, Optional, Any

import cv2
import numpy as np

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.reid import BaseFeatureExtractor, ReIDExtractorFactory
from intelligent_tracker.matcher import GalleryMatcher
from intelligent_tracker.tracker import Track, TrackerFactory
from intelligent_tracker.detectors import DetectorFactory
from intelligent_tracker.video import VideoSource, resolve_camera_source
from intelligent_tracker.geometry import Tripwire, ZoneROI
from intelligent_tracker.analytics import AnalyticsEngine


class InteractiveController(object):
    """
    Manages user interaction, mouse callbacks, track inspection, on-screen enrollment,
    and interactive ROI drawing on OpenCV display windows.
    """

    def __init__(
        self,
        window_name: str = "Intelligent Tracker - Interactive",
        db: Optional[TrackerDB] = None,
        extractor: Optional[BaseFeatureExtractor] = None,
        matcher: Optional[GalleryMatcher] = None,
        analytics: Optional[AnalyticsEngine] = None,
    ):
        self.window_name = window_name
        self.db = db
        self.extractor = extractor
        self.matcher = matcher
        self.analytics = analytics

        # State tracking
        self.selected_track_id: Optional[int] = None
        self.current_tracks: Dict[int, Track] = {}
        self.current_frame: Optional[np.ndarray] = None
        self.paused: bool = False

        # Drawing mode states: 'none', 'tripwire', 'zone'
        self.draw_mode: str = "none"
        self.drawing_points: List[Tuple[int, int]] = []
        self.mouse_cursor: Tuple[int, int] = (0, 0)

        # Status notification banner
        self.status_message: str = "Ready. Click any object to inspect. Space=Pause, 'e'=Enroll, 't'=Tripwire, 'z'=Zone"
        self.status_time: float = time.time()

    def set_status(self, message: str, duration: float = 4.0):
        """Display a temporary status banner on the HUD."""
        self.status_message = message
        self.status_time = time.time() + duration

    def on_mouse(self, event: int, x: int, y: int, flags: int, param: Any):
        """OpenCV mouse callback handler."""
        self.mouse_cursor = (x, y)

        if event == cv2.EVENT_LBUTTONDOWN:
            if self.draw_mode == "tripwire":
                self.drawing_points.append((x, y))
                if len(self.drawing_points) >= 2:
                    self._commit_tripwire()
                return

            elif self.draw_mode == "zone":
                self.drawing_points.append((x, y))
                self.set_status("Zone point #{} added. Press Enter or double-click to close.".format(len(self.drawing_points)))
                return

            # Default Mode: Inspect / Select Track
            clicked_tid = None
            for tid, trk in self.current_tracks.items():
                bx, by, bw, bh = trk.bbox
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    clicked_tid = tid
                    break

            self.selected_track_id = clicked_tid
            if clicked_tid is not None:
                trk = self.current_tracks[clicked_tid]
                name_str = getattr(trk, "entity_name", "Unidentified")
                sim_str = "{:.1f}%".format(getattr(trk, "reid_score", 0.0) * 100)
                self.set_status(
                    "Selected Track #{}: {} (Match: {}, Dwell: {:.1f}s) - Press 'e' to Enroll".format(
                        clicked_tid, name_str, sim_str, trk.dwell_time
                    ),
                    duration=6.0,
                )
                print("[INSPECT] Track #{}: {} ({}) | conf: {:.2f} | dwell: {:.1f}s | vel: {}".format(
                    clicked_tid, trk.label, name_str, trk.confidence, trk.dwell_time, trk.velocity
                ))
            else:
                self.set_status("Deselected track. Click an object to inspect.")

        elif event == cv2.EVENT_RBUTTONDOWN or event == cv2.EVENT_LBUTTONDBLCLK:
            if self.draw_mode == "zone" and len(self.drawing_points) >= 3:
                self._commit_zone()

    def _commit_tripwire(self):
        """Finalize and add interactive tripwire to analytics."""
        if len(self.drawing_points) >= 2 and self.analytics is not None:
            ptA, ptB = self.drawing_points[:2]
            name = "tripwire_{}".format(int(time.time()) % 1000)
            tw = Tripwire(line_segment=[list(ptA), list(ptB)], name=name, color=(0, 255, 255))
            self.analytics.add_tripwire(tw)
            self.set_status("Created Tripwire '{}': {} -> {}".format(name, ptA, ptB))
            print("[INTERACTIVE] Created Tripwire '{}': {} -> {}".format(name, ptA, ptB))
        self.draw_mode = "none"
        self.drawing_points = []

    def _commit_zone(self):
        """Finalize and add interactive zone to analytics."""
        if len(self.drawing_points) >= 3 and self.analytics is not None:
            name = "zone_{}".format(int(time.time()) % 1000)
            poly = [list(pt) for pt in self.drawing_points]
            zone = ZoneROI(polygon=poly, name=name, dwell_threshold=4.0, color=(0, 200, 100))
            self.analytics.add_zone(zone)
            self.set_status("Created Zone '{}' with {} vertices.".format(name, len(poly)))
            print("[INTERACTIVE] Created Zone '{}' with {} vertices.".format(name, len(poly)))
        self.draw_mode = "none"
        self.drawing_points = []

    def prompt_enroll_selected(self) -> Optional[Dict[str, Any]]:
        """
        Prompt the user to enroll the currently selected track into TrackerDB.
        """
        if self.selected_track_id is None or self.selected_track_id not in self.current_tracks:
            self.set_status("No track selected to enroll! Click on an object first.")
            return None

        if self.current_frame is None or self.db is None:
            self.set_status("Database or frame not available.")
            return None

        trk = self.current_tracks[self.selected_track_id]
        print("\n" + "=" * 55)
        print(">>> ENROLL ENTITY IN GALLERY (Track #{}) <<<".format(trk.track_id))
        print("  Current Bounding Box : {}".format(trk.bbox))
        print("  Detected Label       : {}".format(trk.label))
        print("=" * 55)

        # Simple terminal prompt
        try:
            name = input("Enter Entity Name (e.g. 'Alice', 'Forklift #02'): ").strip()
            if not name:
                print("[INFO] Enrollment cancelled (empty name).")
                self.set_status("Enrollment cancelled (empty name).")
                return None

            category = input("Enter Category ['person', 'staff', 'vip', 'vehicle', 'visitor'] [person]: ").strip()
            if not category:
                category = "person"

            notes = input("Enter Notes (optional): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[INFO] Enrollment cancelled.")
            return None

        # Enroll into SQLite TrackerDB
        result = self.db.enroll_entity(
            name=name,
            category=category,
            frame=self.current_frame,
            bbox=trk.bbox,
            notes=notes,
            extractor=self.extractor,
            save_crop_dir="data/crops",
        )

        # Update track and reload gallery
        if self.matcher is not None:
            self.matcher.reload_gallery()
            self.matcher.reassign_track(trk, result["id"])

        self.set_status("Enrolled '{}' (ID #{}) into Gallery!".format(name, result["id"]))
        print("[SUCCESS] Successfully enrolled '{}' (ID #{}) into Gallery!".format(name, result["id"]))
        return result

    def render_overlay(self, image: np.ndarray) -> np.ndarray:
        """Draw interactive HUD, inspector card, and active drawing guides."""
        out = image.copy()
        h, w = out.shape[:2]

        # 1. Render Inspector Card for Selected Track
        if self.selected_track_id is not None and self.selected_track_id in self.current_tracks:
            trk = self.current_tracks[self.selected_track_id]
            bx, by, bw, bh = trk.bbox

            # Highlight bounding box with cyan border
            cv2.rectangle(out, (bx - 3, by - 3), (bx + bw + 3, by + bh + 3), (255, 255, 0), 2)

            # Draw trajectory path
            if hasattr(trk, "history") and len(trk.history) > 1:
                pts = np.array([[int(p[0]), int(p[1])] for p in trk.history], dtype=np.int32)
                cv2.polylines(out, [pts], False, (0, 255, 255), 2)

            # Render Inspector HUD Box (Top Right)
            card_w, card_h = 280, 140
            cx1 = w - card_w - 10
            cy1 = 10
            cx2 = w - 10
            cy2 = cy1 + card_h

            # Semi-transparent dark card
            overlay = out.copy()
            cv2.rectangle(overlay, (cx1, cy1), (cx2, cy2), (20, 20, 20), -1)
            cv2.addWeighted(overlay, 0.75, out, 0.25, 0, out)
            cv2.rectangle(out, (cx1, cy1), (cx2, cy2), (255, 255, 0), 1)

            # Inspector details text
            name_str = getattr(trk, "entity_name", None) or getattr(trk, "identity_label", None) or "Unidentified"
            score_str = "{:.1f}%".format(getattr(trk, "reid_score", 0.0) * 100) if getattr(trk, "entity_name", None) else trk.state.upper()
            lines = [
                "INSPECTOR: Track #{}".format(trk.track_id),
                "Identity : {} ({})".format(name_str, score_str),
                "Category : {}".format(getattr(trk, "entity_category", trk.label)),
                "Dwell    : {:.1f}s | Hits: {}".format(trk.dwell_time, trk.hits),
                "Velocity : ({:.1f}, {:.1f}) px/s".format(trk.velocity[0], trk.velocity[1]),
                "Controls : Press 'e' to Enroll",
            ]
            for i, line in enumerate(lines):
                col = (0, 255, 255) if i == 0 else (255, 255, 255) if i != 5 else (100, 255, 100)
                cv2.putText(out, line, (cx1 + 10, cy1 + 22 + i * 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1)

        # 2. Render Drawing Guides
        if self.draw_mode == "tripwire":
            for pt in self.drawing_points:
                cv2.circle(out, pt, 5, (0, 255, 255), -1)
            if len(self.drawing_points) == 1:
                cv2.line(out, self.drawing_points[0], self.mouse_cursor, (0, 255, 255), 2)
            cv2.putText(out, "DRAWING TRIPWIRE: Click second endpoint", (15, h - 35), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

        elif self.draw_mode == "zone":
            if self.drawing_points:
                pts = np.array(self.drawing_points, dtype=np.int32)
                cv2.polylines(out, [pts], False, (0, 200, 100), 2)
                for pt in self.drawing_points:
                    cv2.circle(out, pt, 5, (0, 200, 100), -1)
                cv2.line(out, self.drawing_points[-1], self.mouse_cursor, (0, 200, 100), 1)
            cv2.putText(out, "DRAWING ZONE: Click vertices (Enter/Double-click to close)", (15, h - 35), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 100), 2)

        # 3. Status Notification Bar (Bottom)
        if time.time() < self.status_time:
            bar_overlay = out.copy()
            cv2.rectangle(bar_overlay, (0, h - 28), (w, h), (0, 0, 0), -1)
            cv2.addWeighted(bar_overlay, 0.7, out, 0.3, 0, out)
            cv2.putText(out, self.status_message, (12, h - 9), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

        return out


def run_interactive_app(
    source: str = "synthetic",
    db_path: str = "data/tracker.db",
    detector_name: str = "yolov8",
    reid_name: str = "color",
    resolution: Tuple[int, int] = (640, 480),
    framerate: int = 30,
):
    """
    Run standalone interactive screen selection, tagging, and Re-ID inspection studio.
    """
    res_w, res_h = resolution
    resolved_source = resolve_camera_source(source)

    # Initialize components
    db = TrackerDB(db_path)
    extractor = ReIDExtractorFactory.create(reid_name)
    matcher = GalleryMatcher(db=db, extractor=extractor)
    detector = DetectorFactory.create(detector_name)
    tracker = TrackerFactory.create("centroid")
    analytics = AnalyticsEngine(resolution=resolution)

    controller = InteractiveController(
        window_name="Intelligent Tracker - Tagging Studio",
        db=db,
        extractor=extractor,
        matcher=matcher,
        analytics=analytics,
    )

    cv2.namedWindow(controller.window_name, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(controller.window_name, controller.on_mouse)

    video_source = VideoSource(
        source=resolved_source,
        width=res_w,
        height=res_h,
        fps_limit=float(framerate),
    )

    print("=" * 65)
    print("Intelligent Tracker - Interactive Tagging & Re-ID Studio")
    print("=" * 65)
    print("  Source      : {}".format(resolved_source))
    print("  Database    : {} (Gallery size: {})".format(db_path, matcher.gallery_size))
    print("  Detector    : {}".format(detector.__class__.__name__))
    print("  Re-ID       : {}".format(extractor.__class__.__name__))
    print("  Controls    :")
    print("    - Left Click  : Inspect tracked object")
    print("    - 'e'         : Enroll selected object into database gallery")
    print("    - Spacebar    : Pause / Resume video")
    print("    - 't'         : Draw virtual Tripwire (click 2 points)")
    print("    - 'z'         : Draw virtual Zone (click vertices, Enter to close)")
    print("    - 'd'         : Clear tracks")
    print("    - 's'         : Save snapshot & analytics report")
    print("    - 'q' / ESC   : Quit")
    print("=" * 65)

    with video_source as vs:
        try:
            while True:
                if controller.paused:
                    key = cv2.waitKey(30) & 0xFF
                    if key in (ord("q"), 27):
                        break
                    if key == ord(" "):
                        controller.paused = False
                        controller.set_status("Playback resumed.")
                    elif key == ord("e"):
                        controller.prompt_enroll_selected()
                    elif key == ord("t"):
                        controller.draw_mode = "tripwire"
                        controller.drawing_points = []
                        controller.set_status("Tripwire Mode: Click point A, then point B.")
                    elif key == ord("z"):
                        controller.draw_mode = "zone"
                        controller.drawing_points = []
                        controller.set_status("Zone Mode: Click vertices, press Enter/Double-click to close.")
                    elif key in (13, 10):  # Enter key
                        if controller.draw_mode == "zone":
                            controller._commit_zone()
                    continue

                ret, frame = vs.read(timeout=2.0)
                if not ret or frame is None:
                    print("[INFO] Video stream ended.")
                    break

                if frame.shape[1] != res_w or frame.shape[0] != res_h:
                    frame = cv2.resize(frame, (res_w, res_h))

                controller.current_frame = frame

                # Step 1: Detect & Track
                detections = detector.detect(frame)
                tracks = tracker.update(detections)
                controller.current_tracks = tracks

                # Step 2: Gallery Re-ID Matching
                matcher.match_tracks(tracks, frame, source=str(resolved_source))

                # Step 3: Analytics update & drawing
                analytics.update(tracks)
                annotated = analytics.draw(frame=frame, tracks=tracks)

                # Step 4: Render Interactive HUD & Inspector
                display = controller.render_overlay(annotated)

                cv2.imshow(controller.window_name, display)
                key = cv2.waitKey(1) & 0xFF

                if key in (ord("q"), 27):
                    break
                elif key == ord(" "):
                    controller.paused = True
                    controller.set_status("Playback paused. Space=Resume, 'e'=Enroll.")
                elif key == ord("e"):
                    controller.prompt_enroll_selected()
                elif key == ord("t"):
                    controller.draw_mode = "tripwire"
                    controller.drawing_points = []
                    controller.set_status("Tripwire Mode: Click point A, then point B.")
                elif key == ord("z"):
                    controller.draw_mode = "zone"
                    controller.drawing_points = []
                    controller.set_status("Zone Mode: Click vertices, press Enter/Double-click to close.")
                elif key in (13, 10):  # Enter key
                    if controller.draw_mode == "zone":
                        controller._commit_zone()
                elif key == ord("d"):
                    tracker.reset()
                    controller.selected_track_id = None
                    controller.set_status("Tracks reset.")
                elif key == ord("s"):
                    snap = "snapshot_{}.png".format(int(time.time()))
                    cv2.imwrite(snap, display)
                    controller.set_status("Saved snapshot to '{}'".format(snap))

                # Check if window closed via [X] button
                try:
                    if cv2.getWindowProperty(controller.window_name, cv2.WND_PROP_VISIBLE) < 1:
                        break
                except Exception:
                    break

        except KeyboardInterrupt:
            pass

    cv2.destroyAllWindows()
    db.close()
    print("[INFO] Interactive tagging studio closed.")


def main():
    parser = argparse.ArgumentParser(description="Interactive Screen Selection, Tagging & Re-ID Studio")
    parser.add_argument("--source", default="synthetic", help="Video source (camera index, 'synthetic', or video file)")
    parser.add_argument("--db", default="data/tracker.db", help="Path to SQLite database file")
    parser.add_argument("--detector", default="yolov8", choices=["haar", "yolov8", "yolo11", "mock"], help="Detector backend")
    parser.add_argument("--reid", default="color", choices=["color", "onnx", "mock"], help="Re-ID feature extractor")
    parser.add_argument("--resolution", default="640x480", help="Resolution WIDTHxHEIGHT")
    parser.add_argument("--framerate", type=int, default=30, help="Target framerate")
    args = parser.parse_args()

    parts = args.resolution.split("x")
    res = (int(parts[0]), int(parts[1])) if len(parts) == 2 else (640, 480)

    run_interactive_app(
        source=args.source,
        db_path=args.db,
        detector_name=args.detector,
        reid_name=args.reid,
        resolution=res,
        framerate=args.framerate,
    )


if __name__ == "__main__":
    main()
