"""Intelligent Tracker CLI - Interactive Runner & Execution Loop."""

import time
from typing import Any

from intelligent_tracker.cli.display import CliUiController
from intelligent_tracker.cli.pipeline_builder import PipelineContext
from intelligent_tracker.pipeline import (
    FrameProcessor,
    PipelineBundle,
    PipelineConfig,
)


def run_legacy_forms_gui(
    args: Any,
    res_w: int,
    res_h: int,
    source: Any,
    detector_name: str,
    conf_thresh: float,
    classes_filter: Any,
) -> None:
    """Fallback GUI using legacy Matplotlib forms with pan/zoom toolbar."""
    from intelligent_tracker.high_objects import World

    print("[INFO] Launching legacy Matplotlib GUI with interactive toolbar...")
    world = World(name="Intelligent Tracker")
    world.create_scene(
        [source],
        name="TrackerScene",
        framerate=args.framerate or 30,
        resolution=(res_w, res_h),
    )

    det_kwargs: dict[str, Any] = {}
    if detector_name in ("yolov8", "yolo11", "onnx"):
        det_kwargs["conf_threshold"] = conf_thresh
        if classes_filter:
            det_kwargs["classes"] = classes_filter

    world.create_detector(detector_name, **det_kwargs)
    world.show(throw=False)
    world.block(close=True)
    print("[INFO] Application closed.")


def _ensure_bundle(ctx: PipelineContext) -> PipelineBundle:
    """Return ctx.bundle or adapt a manually constructed PipelineContext."""
    if ctx.bundle is not None:
        return ctx.bundle
    return PipelineBundle(
        config=PipelineConfig(),
        db=ctx.db,
        video_source=ctx.video_source,
        detector=ctx.detector,
        tracker=ctx.tracker,
        analytics=ctx.analytics,
        reid_extractor=ctx.reid_extractor,
        gallery_matcher=ctx.gallery_matcher,
        event_bus=ctx.event_bus,
        event_pipeline=ctx.event_pipeline,
        writer=ctx.writer,
    )


class CliAppRunner:
    """Coordinates video ingestion, FrameProcessor stepping, and UI lifecycle."""

    def __init__(self, ctx: PipelineContext) -> None:
        self.ctx = ctx
        self.p = ctx.params
        self.bundle = _ensure_bundle(ctx)
        self.processor = FrameProcessor(self.bundle)
        self.frame_count = 0
        self.start_time = time.time()
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

    def _process_frame(self, vs: Any) -> bool:
        """Acquire, step FrameProcessor, annotate, and display a single frame."""
        ret, frame = vs.read(timeout=2.0)
        if not ret or frame is None:
            print("[WARN] Video source timeout or stream completed.")
            return False

        step_res = self.processor.step(
            frame,
            timestamp=time.time(),
            target_size=(self.p["res_w"], self.p["res_h"]),
        )
        self.frame_count = step_res.frame_count
        self.measured_fps = step_res.fps

        for ev in step_res.identifications:
            print(
                f"[RE-ID] Identified Track #{ev.track_id}: '{ev.name}' [{ev.category}] "
                f"(similarity: {float(ev.similarity) * 100:.1f}%)"
            )

        self._publish_mqtt(step_res.analytics, step_res.tracks, step_res.timestamp)

        annotated = self.ui.render_overlay(step_res.frame, step_res.tracks, self.measured_fps)
        if self.ctx.writer is not None:
            self.ctx.writer.write(annotated)

        self._log_events(step_res.analytics)

        if self.p["headless"] and 0 < self.p["frames"] <= self.frame_count:
            return False
        return self.ui.process_key_event(annotated, step_res.frame)

    def _publish_mqtt(
        self,
        telemetry: dict[str, Any],
        tracks: dict[int, Any],
        t0: float,
    ) -> None:
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

    def _log_events(self, telemetry: dict[str, Any]) -> None:
        """Log new tripwire or zone crossing events."""
        for ev in telemetry.get("new_events", []):
            if "direction" in ev:
                print(
                    f"[EVENT] Tripwire '{ev['tripwire_id']}' crossed by "
                    f"Track #{ev['track_id']} ({ev['direction']})"
                )
            else:
                print(
                    f"[EVENT] Zone '{ev['zone_id']}': Track #{ev['track_id']} -> "
                    f"{ev['event_type']} (dwell: {ev.get('dwell_time', 0.0):.1f}s)"
                )

    def _shutdown(self) -> None:
        """Release resources via PipelineBundle.close() and print final session metrics."""
        elapsed = time.time() - self.start_time
        final_fps = self.frame_count / elapsed if elapsed > 0 else 0.0

        self.bundle.close()
        self.ui.cleanup()

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


def run_cli(args: Any = None) -> None:
    """CLI entrypoint: parse args, build pipeline, and execute runner."""
    from intelligent_tracker.cli.arguments import load_config, parse_args

    if args is None:
        args = parse_args()
    cfg = load_config(args.config)

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
