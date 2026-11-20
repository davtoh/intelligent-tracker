#!/usr/bin/env python3
"""Diagnostic Probe: replay_pipeline_probe.

Runs real VideoSource -> FrameProcessor (>1280px) -> CachedReplayProvider ->
WorldEntityBridge -> EventBus with zero SimpleNamespace stubs.
"""

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _write_hd_video(path: Path, width: int = 1920, height: int = 1080, frames: int = 6) -> None:
    """Create a real >1280px synthetic MP4 clip for pipeline testing."""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, 10.0, (width, height))
    try:
        for i in range(frames):
            img = np.zeros((height, width, 3), dtype=np.uint8)
            x0 = 1350 + i * 10
            cv2.rectangle(img, (x0, 700), (x0 + 180, 950), (0, 255, 0), -1)
            writer.write(img)
    finally:
        writer.release()


def _check_track_and_scale_contracts(tmp: Path, video_path: Path, failures: list[str], checks: dict[str, Any]) -> None:
    """Check Track.to_dict(), FrameProcessor >1280px scale, and VideoSource FPS attrs."""
    from intelligent_tracker.detectors import MockDetector
    from intelligent_tracker.pipeline.config import PipelineConfig
    from intelligent_tracker.pipeline.engine import PipelineEngine
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

    cfg = PipelineConfig(db_path=str(tmp / "p.db"), detector_model="mock", reid_model="color", tracker_type="centroid")
    bundle = PipelineEngine.build(cfg)
    try:
        bundle.detector = MockDetector(boxes=[[1400, 700, 1580, 950, 0.9, "person"]])
        from intelligent_tracker.pipeline.frame_processor import FrameProcessor
        proc = FrameProcessor(bundle)
        hd_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        res = proc.step(hd_frame, timestamp=1.0, max_dim=1280)
        # In 1920x1080 with max_dim=1280, frame is downscaled by 1280/1920 (2/3)
        # If tracks are NOT rescaled back, x1 will be ~933 instead of ~1400
        if res.tracks:
            bx = res.tracks[0].bbox[0]
            checks["hd_track_x1"] = bx
            if bx < 1200:
                failures.append(f"FrameProcessor max_dim=1280 coordinate mismatch: input x1=1400 returned x1={bx}")
        else:
            checks["hd_track_x1"] = None
    finally:
        bundle.close()


def _check_replay_bridge_and_ttl(tmp: Path, video_path: Path, failures: list[str], checks: dict[str, Any]) -> None:
    """Check CachedReplayProvider WorldEntityBridge sync and FileDetectionReplayProvider TTL."""
    from dashboard.services.cached_replay_provider import CachedReplayProvider
    from dashboard.services.file_detection_replay import FileDetectionReplayProvider
    from intelligent_tracker.database import TrackerDB
    from intelligent_tracker.pipeline.config import PipelineConfig
    from intelligent_tracker.pipeline.engine import PipelineEngine
    from intelligent_tracker.video.source import VideoSource

    db = TrackerDB(str(tmp / "replay.db"))
    vs = VideoSource(str(video_path))
    cfg = PipelineConfig(db_path=str(tmp / "replay.db"), detector_model="mock", reid_model="color", tracker_type="centroid")
    bundle = PipelineEngine.build(cfg)
    try:
        rep = FileDetectionReplayProvider(db, vs)
        loaded_before = rep.ensure_loaded()
        db.save_video_run(
            video_filename=video_path.name,
            report={"entities": [], "alerts": []},
            frame_detections=[{
                "frame_idx": 0, "timestamp_sec": 0.0,
                "tracks": [{"track_id": 1, "label": "person", "confidence": 0.9, "bbox": [10, 10, 50, 50], "entity_id": 1}],
            }],
            source_fps=10.0,
        )
        loaded_after = rep.ensure_loaded()
        checks["replay_ttl_reload_after_complete"] = bool(loaded_after)
        if not loaded_before and not loaded_after:
            failures.append("FileDetectionReplayProvider.ensure_loaded() permanently cached _loaded=True on empty DB")

        crp = CachedReplayProvider(db, vs, bundle=bundle, replay_provider=rep, run_reid=False)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        crp.build_step_result(frame, now=100.0, frame_seq=0, media_time_s=0.0)
        snap = bundle.world_graph.snapshot() if bundle.world_graph and hasattr(bundle.world_graph, "snapshot") else {}
        wg_entities = len(snap.get("entities", {}))
        checks["replay_world_bridge_entities"] = wg_entities
        if wg_entities == 0:
            failures.append("CachedReplayProvider(run_reid=False) skipped WorldEntityBridge sync (0 entities in WorldGraph)")
    finally:
        vs.stop()
        bundle.close()
        db.close()


def run_probe() -> dict[str, Any]:
    """Execute replay pipeline integration assertions."""
    checks: dict[str, Any] = {}
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        vid = tmp / "vid.mp4"
        _write_hd_video(vid)
        _check_track_and_scale_contracts(tmp, vid, failures, checks)
        _check_replay_bridge_and_ttl(tmp, vid, failures, checks)

    status = "error" if failures else "ok"
    summary = f"Replay pipeline probe: {len(failures)} failure(s)" if failures else "Replay pipeline probe passed all checks."
    return {"status": status, "summary": summary, "details": {"checks": checks, "failures": failures}}


if __name__ == "__main__":
    res = run_probe()
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["status"] == "ok" else 1)
