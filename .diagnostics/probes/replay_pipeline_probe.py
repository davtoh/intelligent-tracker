#!/usr/bin/env python3
"""Diagnostic Probe: replay_pipeline_probe.

Runs unmocked VideoSource -> FrameProcessor (>1280px) -> CentroidTracker ->
FrameOverlayRenderer -> AsyncInferenceWorker -> CachedReplayProvider -> EventBus.
"""

import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _write_hd_video(path: Path, width: int = 1920, height: int = 1080, frames: int = 6) -> None:
    """Create a real >1280px synthetic MP4 clip for pipeline testing."""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")  # type: ignore[attr-defined]
    writer = cv2.VideoWriter(str(path), fourcc, 10.0, (width, height))
    try:
        for i in range(frames):
            img = np.zeros((height, width, 3), dtype=np.uint8)
            x0 = 1350 + i * 10
            cv2.rectangle(img, (x0, 700), (x0 + 180, 950), (0, 255, 0), -1)
            writer.write(img)
    finally:
        writer.release()


def _check_track_and_fps(video_path: Path, failures: list[str], checks: dict[str, Any]) -> None:
    """Verify Track.to_dict() keys and VideoSource FPS attributes."""
    from intelligent_tracker.tracker.track import Track
    from intelligent_tracker.video.source import VideoSource

    trk = Track(track_id=1, bbox=[10, 10, 50, 50], label="person", entity_id=7, entity_category="person")
    td = trk.to_dict()
    has_eid = "entity_id" in td and "category" in td
    checks["track_to_dict_has_entity_id_and_category"] = has_eid
    if not has_eid:
        failures.append(f"Track.to_dict() missing entity_id/category keys: {sorted(td.keys())}")

    vs = VideoSource(str(video_path))
    try:
        checks["video_source_has_fps_attr"] = hasattr(vs, "fps")
        if not hasattr(vs, "source_fps"):
            failures.append("VideoSource missing source_fps")
    finally:
        vs.stop()


def _check_hd_scale_and_centroid(tmp: Path, failures: list[str], checks: dict[str, Any]) -> None:
    """Verify 1920x1080 max_dim=1280 rescale and multi-frame CentroidTracker persistence (P0-3)."""
    from intelligent_tracker.detectors import MockDetector
    from intelligent_tracker.pipeline.config import PipelineConfig
    from intelligent_tracker.pipeline.engine import PipelineEngine
    from intelligent_tracker.pipeline.frame_processor import FrameProcessor

    cfg = PipelineConfig(
        db_path=str(tmp / "p.db"), detector_model="mock", reid_model="color", tracker_type="centroid"
    )
    bundle = PipelineEngine.build(cfg)
    try:
        det = MockDetector(boxes=[(1350, 700, 180, 250)])
        bundle.detector = det
        proc = FrameProcessor(bundle)
        hd_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        track_ids: list[int] = []
        last_res = None
        for idx in range(5):
            det.preset_boxes = [(1350 + idx * 15, 700, 180, 250)]
            last_res = proc.step(hd_frame, timestamp=1700000000.0 + idx * 0.1, max_dim=1280)
            if last_res.tracks:
                track_ids.append(next(iter(last_res.tracks.keys())))
        if not last_res or not last_res.tracks:
            checks["hd_track_x1"] = None
            failures.append("FrameProcessor.step() returned empty res.tracks on 1920x1080 input")
            return
        bx = next(iter(last_res.tracks.values())).bbox[0]
        checks["hd_track_x1"] = bx
        checks["centroid_hd_track_ids"] = track_ids
        if bx < 1200:
            failures.append(f"FrameProcessor max_dim=1280 coordinate mismatch: x1={bx}")
        if len(track_ids) < 5 or len(set(track_ids)) != 1:
            failures.append(f"CentroidTracker P0-3 multi-frame persistence failed: ids={track_ids}")
    finally:
        bundle.close()


def _check_async_clock(
    bundle: Any, frame: np.ndarray, failures: list[str], checks: dict[str, Any]
) -> dict[int, Any]:
    """Verify real-clock AsyncInferenceWorker epoch vs monotonic stamping (P0-1)."""
    from dashboard.services.async_inference_worker import AsyncInferenceWorker
    from intelligent_tracker.pipeline.frame_processor import FrameProcessor

    worker = AsyncInferenceWorker(FrameProcessor(bundle), max_dim=1280)
    worker.start()
    worker.submit(frame, timestamp=None, frame_seq=1)
    res = None
    for _ in range(40):
        res = worker.get_latest_result()
        if res is not None:
            break
        time.sleep(0.025)
    worker.stop()
    ts_val = float(getattr(res, "timestamp", 0.0)) if res is not None else 0.0
    checks["async_worker_step_timestamp"] = ts_val
    if res is None or ts_val < 1_000_000_000.0:
        failures.append(f"P0-1 clock-domain bug: AsyncInferenceWorker stamped monotonic timestamp={ts_val}")
    return res.tracks if res else {}


def _check_overlay_heatmap(
    bundle: Any, frame: np.ndarray, tracks: dict[int, Any], failures: list[str], checks: dict[str, Any]
) -> None:
    """Verify FrameOverlayRenderer heatmap overlay and 16:9 output shape (P0-4)."""
    from types import SimpleNamespace
    from dashboard.services.frame_overlay import FrameOverlayRenderer

    try:
        if getattr(bundle.analytics, "heatmap", None) is not None:
            bundle.analytics.heatmap.update([SimpleNamespace(centroid=(160.0, 180.0))])
        out = FrameOverlayRenderer.render(
            frame,
            tracks,
            {"heatmap": True},
            "cam_01",
            10.0,
            0.0,
            analytics=bundle.analytics,
            draw_heatmap=True,
        )
        checks["overlay_16_9_shape"] = list(out.shape)
        if out.shape != (720, 1280, 3):
            failures.append(f"FrameOverlayRenderer 16:9 shape mismatch: {out.shape}")
    except (AttributeError, RuntimeError, TypeError) as exc:
        checks["overlay_heatmap_error"] = f"{type(exc).__name__}: {exc}"
        failures.append(f"P0-4 FrameOverlayRenderer(draw_heatmap=True) raised {type(exc).__name__}: {exc}")


def _check_async_clock_and_overlay(tmp: Path, failures: list[str], checks: dict[str, Any]) -> None:
    """Run AsyncInferenceWorker clock check and FrameOverlayRenderer heatmap check."""
    from intelligent_tracker.detectors import MockDetector
    from intelligent_tracker.pipeline.config import PipelineConfig
    from intelligent_tracker.pipeline.engine import PipelineEngine

    cfg = PipelineConfig(
        db_path=str(tmp / "clk.db"), detector_model="mock", reid_model="color", tracker_type="centroid"
    )
    bundle = PipelineEngine.build(cfg)
    try:
        bundle.detector = MockDetector(boxes=[[100, 100, 220, 320, 0.9, "person"]])
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        tracks = _check_async_clock(bundle, frame, failures, checks)
        _check_overlay_heatmap(bundle, frame, tracks, failures, checks)
    finally:
        bundle.close()


def _check_capture_only_mjpeg(
    tmp: Path, video_path: Path, failures: list[str], checks: dict[str, Any]
) -> None:
    """Verify capture_only mode does not freeze annotated MJPEG /stream/{id} (P1-6)."""
    from dashboard.services.processing_mode_service import ProcessingModeService
    from dashboard.services.stream_worker import StreamWorker
    from dashboard.stream_manager import StreamManager
    from intelligent_tracker.pipeline.frame_processor import FrameStepResult

    mode_svc = ProcessingModeService(mode="capture_only")
    mgr = StreamManager(
        camera_id="cam_cap",
        source_override=str(video_path),
        db_path=str(tmp / "cap.db"),
        custom_cfg={"detector": {"model": "mock"}, "reid": {"model": "color"}},
        processing_mode_service=mode_svc,
    )
    try:
        worker = StreamWorker(mgr)
        f1 = np.full((240, 320, 3), 40, dtype=np.uint8)
        f2 = np.full((240, 320, 3), 200, dtype=np.uint8)
        worker._process_single_frame(
            FrameStepResult(frame=f1, detections=[], tracks={}, analytics={}, identifications=[])
        )
        j1 = mgr.get_latest_frame_jpeg(annotated=True)
        worker._process_single_frame(
            FrameStepResult(frame=f2, detections=[], tracks={}, analytics={}, identifications=[])
        )
        j2 = mgr.get_latest_frame_jpeg(annotated=True)
        changed = j1 != j2 and len(j2) > 0
        checks["capture_only_annotated_mjpeg_updates"] = changed
        if not changed:
            failures.append(
                "P1-6: capture_only mode froze get_latest_frame_jpeg(annotated=True) on static placeholder"
            )
    finally:
        mgr.stop()


def _check_replay_ttl(
    db: Any, vs: Any, video_path: Path, failures: list[str], checks: dict[str, Any]
) -> Any:
    """Verify FileDetectionReplayProvider reloads after DB save_video_run()."""
    from dashboard.services.file_detection_replay import FileDetectionReplayProvider

    rep = FileDetectionReplayProvider(db, vs)
    loaded_before = rep.ensure_loaded()
    tracks = [{"track_id": 1, "label": "person", "confidence": 0.9, "bbox": [10, 10, 50, 50], "entity_id": 1}]
    db.save_video_run(
        video_filename=video_path.name,
        report={"entities": [], "alerts": []},
        frame_detections=[{"frame_idx": 0, "timestamp_sec": 0.0, "tracks": tracks}],
        source_fps=10.0,
    )
    loaded_after = rep.ensure_loaded()
    checks["replay_ttl_reload_after_complete"] = bool(loaded_after)
    if not loaded_before and not loaded_after:
        failures.append("FileDetectionReplayProvider.ensure_loaded() cached _loaded=True on empty DB")
    return rep


def _check_eof_and_motion_pause(
    video_path: Path, failures: list[str], checks: dict[str, Any]
) -> None:
    """Verify loop_video=False EOF, pause() FPS reset, and MotionGate gap re-seed."""
    from intelligent_tracker.pipeline.motion_gate import MotionGate
    from intelligent_tracker.video.source import VideoSource

    vs = VideoSource(str(video_path), loop_video=False)
    try:
        frames = 0
        while frames < 20:
            ok, _ = vs.read(timeout=1.0)
            if not ok:
                break
            frames += 1
        ok_after, _ = vs.read(timeout=0.1)
        checks["non_loop_eof_stopped"] = (frames > 0) and (not ok_after) and (not vs._running)
        if not checks["non_loop_eof_stopped"]:
            failures.append(f"P1-9 non-loop EOF failed: frames={frames}, ok_after={ok_after}, running={vs._running}")
        vs.pause()
        checks["pause_clears_measured_fps"] = vs.measured_fps == 0.0 and vs._last_frame_time is None
        if not checks["pause_clears_measured_fps"]:
            failures.append("P1-7 pause() did not clear _measured_fps and _last_frame_time")
    finally:
        vs.stop()

    mg = MotionGate(hold_seconds=3.0)
    f0 = np.zeros((72, 128, 3), dtype=np.uint8)
    f1 = np.full((72, 128, 3), 200, dtype=np.uint8)
    mg.evaluate("cam_p3", f0, now=1.0)
    wake = mg.evaluate("cam_p3", f1, now=10.0)
    checks["motion_gate_gap_reseed"] = not wake.motion_active and not wake.first_trigger
    if wake.motion_active:
        failures.append("P3-1 MotionGate triggered false motion burst after hibernation gap")


def _check_replay_bridge_and_ttl(
    tmp: Path, video_path: Path, failures: list[str], checks: dict[str, Any]
) -> None:
    """Check CachedReplayProvider WorldEntityBridge sync and FileDetectionReplayProvider TTL."""
    from dashboard.services.cached_replay_provider import CachedReplayProvider
    from intelligent_tracker.database import TrackerDB
    from intelligent_tracker.pipeline.config import PipelineConfig
    from intelligent_tracker.pipeline.engine import PipelineEngine
    from intelligent_tracker.video.source import VideoSource

    db = TrackerDB(str(tmp / "replay.db"))
    vs = VideoSource(str(video_path))
    cfg = PipelineConfig(
        db_path=str(tmp / "replay.db"), detector_model="mock", reid_model="color", tracker_type="centroid"
    )
    bundle = PipelineEngine.build(cfg)
    try:
        rep = _check_replay_ttl(db, vs, video_path, failures, checks)
        crp = CachedReplayProvider(db, vs, bundle=bundle, replay_provider=rep, run_reid=False)
        crp.build_step_result(np.zeros((480, 640, 3), dtype=np.uint8), now=100.0, frame_seq=0, media_time_s=0.0)
        snap = bundle.world_graph.snapshot() if bundle.world_graph and hasattr(bundle.world_graph, "snapshot") else {}
        wg_entities = len(snap.get("entities", {}))
        checks["replay_world_bridge_entities"] = wg_entities
        if wg_entities == 0:
            failures.append("CachedReplayProvider(run_reid=False) skipped WorldEntityBridge sync (0 entities)")
    finally:
        vs.stop()
        bundle.close()
        db.close()


def _check_auto_sighting_crop(tmp: Path, failures: list[str], checks: dict[str, Any]) -> None:
    """Verify periodic sighting crop persistence and _enrich_sighting URL."""
    from dashboard.routers.analytics import _enrich_sighting
    from intelligent_tracker.database import TrackerDB
    from intelligent_tracker.matching._gallery_signals import emit_periodic_sighting
    from intelligent_tracker.matching.gallery import GalleryMatcher
    from intelligent_tracker.tracker.track import Track

    db, crops = TrackerDB(str(tmp / "sighting.db")), tmp / "sighting_crops"
    crops.mkdir(parents=True, exist_ok=True)
    try:
        eid = db.add_entity("ProbeCarol", "person")
        db.add_signature(eid, np.ones(16, dtype=np.float32))
        matcher = GalleryMatcher(db=db, extractor=None, sighting_interval=5.0)
        matcher.crops_dir = str(crops)
        emitted = emit_periodic_sighting(matcher, entity_id=eid, name="ProbeCarol", category="person", track=Track(track_id=7, bbox=(10, 10, 50, 70), label="person"), confidence=0.9, source="cam_1", zone_id="", timestamp=100.0, frame=np.full((120, 160, 3), 90, dtype=np.uint8))
        rows = db.query_sightings(entity_id=eid, limit=5)
        enriched = _enrich_sighting(rows[0], db) if rows else {}
        ok = bool(emitted and rows and rows[0].get("snapshot_path") and Path(rows[0]["snapshot_path"]).exists() and str(enriched.get("snapshot_url", "")).startswith("/crops/sighting_"))
        checks["auto_sighting_crop_persisted"] = ok
        if not ok:
            failures.append("Automatic sighting crop persistence or /crops/sighting_* enrichment failed")
        from intelligent_tracker.pipeline.post_detection_governance import handle_zone_exits
        from intelligent_tracker.world.graph import WorldGraph
        from intelligent_tracker.world.handoff import MultiCameraHandoffCoordinator
        from intelligent_tracker.world.transitions import WorldTransitionRegistry
        wg = WorldGraph()
        reg = WorldTransitionRegistry(wg)
        coord = MultiCameraHandoffCoordinator(wg, transition_registry=reg)
        bridge = type("B", (), {"handoff_coordinator": coord})()
        bundle = type("P", (), {"analytics": type("A", (), {"camera_id": "cam_1"})(), "config": None, "gallery_matcher": None})()
        handle_zone_exits(bundle, {"new_events": [{"action": "exit", "track_id": 7, "zone_id": "z1"}]}, {7: Track(track_id=7, bbox=(10, 10, 40, 60), label="person")}, 100.0, topology=reg, world_bridge=bridge)
        checks["handoff_zone_exit_ok"] = True
    finally:
        db.close()


def run_probe() -> dict[str, Any]:
    """Execute replay pipeline integration assertions."""
    checks: dict[str, Any] = {}
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp, vid = Path(tmpdir), Path(tmpdir) / "vid.mp4"
        _write_hd_video(vid)
        _check_track_and_fps(vid, failures, checks)
        _check_hd_scale_and_centroid(tmp, failures, checks)
        _check_async_clock_and_overlay(tmp, failures, checks)
        _check_capture_only_mjpeg(tmp, vid, failures, checks)
        _check_replay_bridge_and_ttl(tmp, vid, failures, checks)
        _check_eof_and_motion_pause(vid, failures, checks)
        _check_auto_sighting_crop(tmp, failures, checks)
    status = "error" if failures else "ok"
    summary = f"Replay pipeline probe: {len(failures)} failure(s)" if failures else "Replay pipeline probe passed all checks."
    return {"status": status, "summary": summary, "details": {"checks": checks, "failures": failures}}


if __name__ == "__main__":
    res = run_probe()
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["status"] == "ok" else 1)
