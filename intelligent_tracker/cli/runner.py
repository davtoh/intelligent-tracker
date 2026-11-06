# -*- coding: utf-8 -*-
"""
Intelligent Tracker CLI - Interactive Runner & Execution Loop.
"""

import time
from typing import Dict, Any

import cv2

from intelligent_tracker.cli.pipeline_builder import PipelineContext
from intelligent_tracker.cli.display import CliUiController


def run_legacy_forms_gui(args, res_w: int, res_h: int, source: Any, detector_name: str, conf_thresh: float, classes_filter: Any) -> None:
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


class CliAppRunner:
    """Coordinates video ingestion, model inference, and analytics execution."""

    def __init__(self, ctx: PipelineContext):
        self.ctx = ctx
        self.p = ctx.params
        self.frame_count = 0
        self.start_time = time.time()
        self.fps_history = []
        self.measured_fps = 0.0
        self.ui = CliUiController(
            params=self.p,
            analytics=ctx.analytics,
            tracker=ctx.tracker,
            db=ctx.db,
            extractor=ctx.reid_extractor,
            matcher=ctx.gallery_matcher,
        )

    def run(self) -> None:
        """Main execution lifecycle."""
        self.ui.setup()
        print("[INFO] Starting pipeline execution...")
        with self.ctx.video_source as vs:
            try:
                while True:
                    if self.ui.paused and not self.ui.handle_paused_loop():
                        break
                    if not self._process_frame(vs):
                        break
            except KeyboardInterrupt:
                print("\n[INFO] Stopped by user (KeyboardInterrupt).")
        self._shutdown()

    def _process_frame(self, vs) -> bool:
        """Acquire, infer, annotate, and display a single frame."""
        t0 = time.time()
        ret, frame = vs.read(timeout=2.0)
        if not ret or frame is None:
            print("[WARN] Video source timeout or stream completed.")
            return False

        if frame.shape[1] != self.p["res_w"] or frame.shape[0] != self.p["res_h"]:
            frame = cv2.resize(frame, (self.p["res_w"], self.p["res_h"]))

        detections = self.ctx.detector.detect(frame)
        tracks = self.ctx.tracker.update(detections, timestamp=t0)

        self._process_reid(frame, tracks, t0)
        res = self.ctx.analytics.update(tracks, timestamp=t0)
        self._publish_mqtt(res, tracks, t0)

        annotated = self.ui.render_overlay(frame, tracks, self.measured_fps)
        if self.ctx.writer is not None:
            self.ctx.writer.write(annotated)

        self._update_fps(t0)
        self._log_events(res)

        if self.p["headless"] and 0 < self.p["frames"] <= self.frame_count:
            return False
        return self.ui.process_key_event(annotated, frame)

    def _process_reid(self, frame, tracks, t0: float) -> None:
        """Match tracks against Re-ID gallery and publish identification events."""
        if self.ctx.gallery_matcher is None:
            return
        id_events = self.ctx.gallery_matcher.match_tracks(
            tracks=tracks,
            frame=frame,
            source=str(self.p["source"]),
            timestamp=t0,
        )
        for ev in id_events:
            print(f"[RE-ID] Identified Track #{ev.track_id}: '{ev.name}' [{ev.category}] (similarity: {float(ev.similarity) * 100:.1f}%)")
            self._publish_id_alert(frame, tracks, ev, t0)

    def _publish_id_alert(self, frame, tracks, ev, t0: float) -> None:
        """Publish EntityIdentifiedEvent or RestrictedEntityAlert to event bus."""
        if self.ctx.event_bus is None:
            return
        try:
            from intelligent_tracker.events import EntityIdentifiedEvent, RestrictedEntityAlert, crop_to_base64
            trk = tracks.get(ev.track_id)
            snap_b64 = crop_to_base64(frame, trk.bbox) if trk else None
            self.ctx.event_bus.publish(EntityIdentifiedEvent(
                camera_id=self.ctx.analytics.camera_id,
                track_id=ev.track_id,
                entity_id=getattr(ev, "entity_id", 0),
                name=ev.name,
                category=ev.category,
                similarity=ev.similarity,
                snapshot_base64=snap_b64,
                timestamp=t0,
            ))
            if str(ev.category).lower() in ("restricted", "banned", "blacklisted"):
                self.ctx.event_bus.publish(RestrictedEntityAlert(
                    camera_id=self.ctx.analytics.camera_id,
                    track_id=ev.track_id,
                    entity_id=getattr(ev, "entity_id", 0),
                    name=ev.name,
                    category=ev.category,
                    severity="critical",
                    message=f"Restricted entity '{ev.name}' detected",
                    snapshot_base64=snap_b64,
                    timestamp=t0,
                ))
        except Exception:
            pass

    def _publish_mqtt(self, telemetry: Dict[str, Any], tracks: Dict[int, Any], t0: float) -> None:
        """Send live telemetry to MQTT broker if configured."""
        pipe = self.ctx.event_pipeline
        if pipe and pipe.get("mqtt"):
            try:
                pipe["mqtt"].publish_occupancy(
                    camera_id=self.ctx.analytics.camera_id,
                    zone_occupancy=telemetry.get("zone_occupancy", {}),
                    total_tracks=len(tracks),
                    timestamp=t0,
                )
            except Exception:
                pass

    def _update_fps(self, t0: float) -> None:
        """Update sliding average frame rate."""
        self.frame_count += 1
        dt = time.time() - t0
        if dt > 0:
            self.fps_history.append(1.0 / dt)
            if len(self.fps_history) > 30:
                self.fps_history.pop(0)
            self.measured_fps = sum(self.fps_history) / len(self.fps_history)

    def _log_events(self, telemetry: Dict[str, Any]) -> None:
        """Log new tripwire or zone crossing events."""
        for ev in telemetry.get("new_events", []):
            if "direction" in ev:
                print(f"[EVENT] Tripwire '{ev['tripwire_id']}' crossed by Track #{ev['track_id']} ({ev['direction']})")
            else:
                print(f"[EVENT] Zone '{ev['zone_id']}': Track #{ev['track_id']} -> {ev['event_type']} (dwell: {ev.get('dwell_time', 0.0):.1f}s)")

    def _shutdown(self) -> None:
        """Release resources and print final session metrics."""
        elapsed = time.time() - self.start_time
        final_fps = self.frame_count / elapsed if elapsed > 0 else 0.0

        if self.ctx.writer is not None:
            self.ctx.writer.release()
            print(f"[INFO] Video recording finalized: {self.p['output']}")
        if self.ctx.db is not None:
            self.ctx.db.close()
            print("[INFO] SQLite database closed.")

        self.ui.cleanup()

        pipe = self.ctx.event_pipeline
        if pipe:
            if pipe.get("mqtt"):
                pipe["mqtt"].disconnect()
            if pipe.get("event_bus"):
                pipe["event_bus"].stop(timeout=1.0)
            print("[INFO] Event alerting pipeline stopped cleanly.")

        summary = self.ctx.analytics.export_summary()
        print("=" * 65)
        print("Pipeline Summary:")
        print(f"  Processed Frames : {self.frame_count}")
        print(f"  Total Time       : {elapsed:.2f}s")
        print(f"  Average Speed    : {final_fps:.1f} FPS")
        print(f"  Connection Stats : {self.ctx.video_source.get_metrics()}")
        print(f"  Zone Summary     : {summary['zones']}")
        print(f"  Tripwire Summary : {summary['tripwires']}")
        print("=" * 65)


def run_cli(args=None) -> None:
    """CLI entrypoint: parse args, build pipeline, and execute runner."""
    from intelligent_tracker.cli.arguments import parse_args, load_config
    if args is None:
        args = parse_args()
    cfg = load_config(args.config)

    # Legacy Matplotlib GUI route
    if not args.headless and args.gui == "forms":
        video_cfg = cfg.get("video", {})
        det_cfg = cfg.get("detector", {})
        from intelligent_tracker.cli.pipeline_builder import _resolve_resolution
        res_w, res_h = _resolve_resolution(args, video_cfg)
        raw_source = args.source or video_cfg.get("source", "0")
        source = "synthetic" if str(raw_source).lower() in ("synthetic", "mock") else raw_source
        det_name = args.detector or det_cfg.get("model", "haar")
        conf = args.conf if args.conf is not None else float(det_cfg.get("confidence", 0.25))
        classes = args.classes if args.classes is not None else det_cfg.get("classes", None)
        run_legacy_forms_gui(args, res_w, res_h, source, det_name, conf, classes)
        return

    from intelligent_tracker.cli.pipeline_builder import build_pipeline
    ctx = build_pipeline(args, cfg)
    runner = CliAppRunner(ctx)
    runner.run()
