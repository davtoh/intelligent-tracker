# -*- coding: utf-8 -*-
"""
Intelligent Tracker CLI - Interactive Display & UI Controller.
"""

import time
from typing import Dict, Any, Optional

import cv2


class CliUiController:
    """Manages OpenCV HUD rendering, window events, and user interactions."""

    def __init__(self, params: Dict[str, Any], analytics: Any, tracker: Any, db: Any = None, extractor: Any = None, matcher: Any = None):
        self.p = params
        self.analytics = analytics
        self.tracker = tracker
        self.db = db
        self.extractor = extractor
        self.matcher = matcher
        self.window_name = "Intelligent Tracker - Analytics"
        self.selected_track_id: Optional[int] = None
        self.paused = False
        self.current_tracks: Dict[int, Any] = {}
        self.show_heatmap = self.p.get("show_heatmap", False)

    def setup(self) -> None:
        """Create named OpenCV window and attach mouse callback."""
        if self.p.get("headless"):
            return
        cv2.namedWindow(self.window_name, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(self.window_name, self._on_mouse_click)
        print("[INFO] Interactive Window Controls:")
        print("  - Click '[X]' button or press 'q' / ESC to quit")
        print("  - Press Spacebar to Pause / Resume playback")
        print("  - Click on any tracked bounding box to inspect/select")
        print("  - Press 'e' to enroll selected entity into Re-ID database")
        print("  - Press 'd' to clear tracks, 'h' to toggle heatmap, 's' to save snapshot")

    def _on_mouse_click(self, event, x, y, flags, param) -> None:
        """Handle mouse click selection for track inspection."""
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        clicked = None
        for tid, trk in self.current_tracks.items():
            bx, by, bw, bh = trk.bbox
            if bx <= x <= bx + bw and by <= y <= by + bh:
                clicked = tid
                break
        self.selected_track_id = clicked
        if clicked is not None:
            trk = self.current_tracks[clicked]
            disp = trk.entity_name or trk.identity_label or f"Track #{clicked}"
            state = f" [{trk.state.upper()}]" if trk.state != "confirmed" else ""
            print(f"[INSPECT] Selected {disp}{state}: {trk.label} (conf: {trk.confidence:.2f}, dwell: {trk.dwell_time:.1f}s, vel: {trk.velocity})")
        else:
            print("[INSPECT] Deselected track.")

    def is_window_closed(self) -> bool:
        """Check if OpenCV window was closed via OS close button."""
        if self.p.get("headless"):
            return False
        try:
            return cv2.getWindowProperty(self.window_name, cv2.WND_PROP_VISIBLE) < 1
        except Exception:
            return True

    def handle_paused_loop(self) -> bool:
        """Wait while paused; returns True to keep waiting, False to exit or resume."""
        if not self.paused or self.p.get("headless"):
            return False
        key = cv2.waitKey(30) & 0xFF
        if key in (ord("q"), 27) or self.is_window_closed():
            return False
        if key == ord(" "):
            self.paused = False
            print("[INFO] Playback resumed.")
        return True

    def render_overlay(self, frame, tracks: Dict[int, Any], measured_fps: float):
        """Render annotations, zones, tripwires, heatmap, and inspection boxes."""
        self.current_tracks = tracks
        vis_cfg = self.p.get("vis_cfg", {})
        annotated = self.analytics.draw(
            frame=frame,
            draw_zones=vis_cfg.get("draw_zones", True),
            draw_tripwires=vis_cfg.get("draw_tripwires", True),
            draw_heatmap=self.show_heatmap,
            draw_tracks=vis_cfg.get("draw_tracks", True),
            tracks=tracks,
            draw_hud=vis_cfg.get("draw_hud", True),
            fps=measured_fps,
        )
        if self.selected_track_id and self.selected_track_id in tracks:
            sel_trk = tracks[self.selected_track_id]
            sx, sy, sw, sh = sel_trk.bbox
            cv2.rectangle(annotated, (sx - 3, sy - 3), (sx + sw + 3, sy + sh + 3), (255, 255, 0), 2)
            disp = sel_trk.entity_name or sel_trk.identity_label or f"#{self.selected_track_id}"
            sel_label = f"INSPECTING: {disp} [Dwell: {sel_trk.dwell_time:.1f}s]"
            cv2.putText(annotated, sel_label, (sx, max(15, sy - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 2)
        return annotated

    def process_key_event(self, annotated, frame) -> bool:
        """Display annotated frame and dispatch keyboard interactions. Returns False to quit."""
        if self.p.get("headless"):
            return True

        cv2.imshow(self.window_name, annotated)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27) or self.is_window_closed():
            print("[INFO] Quit requested by user.")
            return False

        if key == ord(" "):
            self.paused = not self.paused
            print(f"[INFO] Playback {'paused' if self.paused else 'resumed'}")
        elif key == ord("e"):
            self._enroll_selected(frame)
        elif key == ord("d"):
            self.tracker.reset()
            self.selected_track_id = None
            print("[INFO] Tracks cleared.")
        elif key == ord("h"):
            self.show_heatmap = not self.show_heatmap
            print(f"[INFO] Heatmap display toggled: {self.show_heatmap}")
        elif key == ord("s"):
            self._save_snapshot(annotated)
        return True

    def _enroll_selected(self, frame) -> None:
        """Interactive entity gallery enrollment prompt."""
        if not (self.selected_track_id and self.selected_track_id in self.current_tracks and self.db is not None):
            print("[INFO] Click on a tracked bounding box before pressing 'e' to enroll.")
            return
        sel_trk = self.current_tracks[self.selected_track_id]
        print(f"\n{'=' * 50}\n>>> ENROLL ENTITY IN GALLERY (Track #{sel_trk.track_id}) <<<")
        try:
            ent_name = input("Enter Entity Name (e.g. 'Alice', 'Forklift #02'): ").strip()
            if ent_name:
                ent_cat = input("Enter Category ['person', 'staff', 'vip', 'vehicle'] [person]: ").strip() or "person"
                enrolled = self.db.enroll_entity(
                    name=ent_name, category=ent_cat, frame=frame,
                    bbox=sel_trk.bbox, extractor=self.extractor,
                )
                if self.matcher is not None:
                    self.matcher.reload_gallery()
                    self.matcher.reassign_track(sel_trk, enrolled["id"])
                print(f"[SUCCESS] Enrolled '{ent_name}' (ID #{enrolled['id']}) into Gallery!")
        except Exception as ex:
            print(f"[WARN] Enrollment error: {ex}")

    def _save_snapshot(self, annotated) -> None:
        """Export snapshot image and analytics summary JSON."""
        ts = int(time.time())
        img_name = f"snapshot_{ts}.png"
        rep_name = f"analytics_report_{ts}.json"
        cv2.imwrite(img_name, annotated)
        self.analytics.export_summary(rep_name)
        print(f"[INFO] Saved snapshot '{img_name}' and report '{rep_name}'")

    def cleanup(self) -> None:
        """Destroy OpenCV display windows."""
        if not self.p.get("headless"):
            cv2.destroyAllWindows()
            for _ in range(5):
                cv2.waitKey(1)

