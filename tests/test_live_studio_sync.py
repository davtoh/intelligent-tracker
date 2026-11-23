#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit & Node VM tests for Step 1.5 Milestone 2: Live Monitor vs Video Studio Synchronization."""

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from dashboard.services.async_inference_worker import AsyncInferenceWorker, build_live_step_result
from dashboard.services.file_detection_replay import FileDetectionReplayProvider
from dashboard.services.stream_telemetry import build_stream_telemetry
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.pipeline import FrameStepResult

REPO_ROOT = Path(__file__).resolve().parent.parent
INTERACTIVE_JS = REPO_ROOT / "dashboard" / "static" / "js" / "interactive_canvas.js"
UNIFIED_JS = REPO_ROOT / "dashboard" / "static" / "js" / "unified_canvas_overlay.js"
LIVE_PLAYER_JS = REPO_ROOT / "dashboard" / "static" / "js" / "live_player.js"
FRAME_SURFACE_JS = REPO_ROOT / "dashboard" / "static" / "js" / "multiview" / "frame_surface.js"


def _run_node(script: str) -> dict:
    """Execute a Node.js VM snippet and parse its JSON stdout."""
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        env=dict(os.environ),
        timeout=15,
    )
    if proc.returncode != 0:
        raise AssertionError(f"Node VM failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}")
    return json.loads(proc.stdout.strip())


class _FakeProcessor:
    """Deterministic FrameProcessor stub for AsyncInferenceWorker tests."""

    def __init__(self, tracks: dict | None = None) -> None:
        self.tracks = tracks or {1: SimpleNamespace(bbox=(10, 20, 30, 40), centroid=(25.0, 40.0), velocity=(1.0, 0.0), label="person", confidence=0.95, dwell_time=1.2, state="confirmed")}
        self.calls: list[tuple[float, int | None]] = []

    def step(self, frame: np.ndarray, timestamp: float = 0.0, max_dim: int | None = None) -> FrameStepResult:
        self.calls.append((timestamp, max_dim))
        return FrameStepResult(frame=frame, tracks=dict(self.tracks), timestamp=timestamp, fps=24.0, frame_count=len(self.calls))


class TestLiveStudioSync(unittest.TestCase):
    """Verify AsyncInferenceWorker provenance, FileDetectionReplayProvider, and frontend sync."""

    def test_async_inference_worker_tracks_seq_lag_and_clears_on_vision_off(self) -> None:
        """AsyncInferenceWorker stamps inference_frame_seq/lag and clears cache when run_vision=False."""
        proc = _FakeProcessor()
        worker = AsyncInferenceWorker(proc)
        worker.start()
        self.addCleanup(worker.stop)

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        worker.submit(frame, timestamp=100.0, frame_seq=7)
        deadline = time.time() + 2.0
        while worker.get_latest_result() is None and time.time() < deadline:
            time.sleep(0.01)

        res = build_live_step_result(worker, frame, now=100.25, frame_seq=10, run_vision=True)
        self.assertEqual(res.frame_count, 10)
        self.assertEqual(getattr(res, "inference_frame_seq", None), 7)
        self.assertAlmostEqual(getattr(res, "inference_lag_ms", 0.0), 250.0, places=1)
        self.assertEqual(len(res.tracks), 1)

        off_res = build_live_step_result(worker, frame, now=100.5, frame_seq=11, run_vision=False)
        self.assertEqual(off_res.tracks, {})
        self.assertIsNone(worker.get_latest_result())

    def test_stream_telemetry_emits_seq_lag_and_source_resolution(self) -> None:
        """build_stream_telemetry includes frame_seq, inference_frame_seq, inference_lag_ms, and source_resolution."""
        mgr = SimpleNamespace(
            camera_id="cam_sync",
            overlays={"bboxes": True},
            homography=SimpleNamespace(is_calibrated=False, track_to_ground=lambda b: (0.0, 0.0)),
            analytics=None,
            event_bus=None,
            detector=SimpleNamespace(name="yolov8"),
            cfg={"detector": {"model": "yolov8"}},
        )
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        step_res = FrameStepResult(frame=frame, tracks={}, timestamp=50.0, fps=30.0, frame_count=42)
        setattr(step_res, "inference_frame_seq", 39)
        setattr(step_res, "inference_lag_ms", 95.4)

        payload = build_stream_telemetry(mgr, {}, 50.0, 30.0, frame.shape, 42, step_res=step_res)
        self.assertEqual(payload["frame_seq"], 42)
        self.assertEqual(payload["inference_frame_seq"], 39)
        self.assertEqual(payload["inference_lag_ms"], 95.4)
        self.assertEqual(payload["source_resolution"], [1280, 720])

    def test_file_detection_replay_provider_replays_and_scales_cached_runs(self) -> None:
        """FileDetectionReplayProvider replays pre-indexed video_runs detections and falls back when absent."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = TrackerDB(os.path.join(tmp.name, "replay.db"))
        self.addCleanup(db.close)

        dets = [
            {"time": 0.0, "frame": 0, "source_resolution": [1280, 720], "tracks": [{"id": 3, "bbox": [100, 200, 50, 80], "label": "person", "confidence": 0.9}]},
            {"time": 0.1, "frame": 1, "source_resolution": [1280, 720], "tracks": [{"id": 3, "bbox": [120, 200, 50, 80], "label": "person", "confidence": 0.92}]},
        ]
        db.save_video_run("sample_clip.mp4", report={"frames_processed": 2}, frame_detections=dets, source_resolution=[1280, 720], source_fps=10.0)

        vs = SimpleNamespace(is_file=True, source="data/videos/sample_clip_h264.mp4", source_fps=10.0)
        provider = FileDetectionReplayProvider(db, vs)
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        proc = _FakeProcessor()
        worker = AsyncInferenceWorker(proc, replay_provider=provider)

        step_res = build_live_step_result(worker, frame, now=10.0, frame_seq=2, run_vision=True)
        self.assertEqual(len(proc.calls), 0)
        self.assertEqual(getattr(step_res, "inference_lag_ms", -1.0), 0.0)
        self.assertIn(3, step_res.tracks)
        self.assertEqual(step_res.tracks[3].bbox, (60, 100, 25, 40))

    def test_file_detection_replay_fallback_when_no_run_exists(self) -> None:
        """FileDetectionReplayProvider returns None when no TrackerDB run exists for the video file."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = TrackerDB(os.path.join(tmp.name, "empty.db"))
        self.addCleanup(db.close)

        vs = SimpleNamespace(is_file=True, source="data/videos/unindexed.mp4", source_fps=25.0)
        provider = FileDetectionReplayProvider(db, vs)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        self.assertIsNone(provider.build_step_result(frame, now=1.0, frame_seq=1))

    @unittest.skipUnless(shutil.which("node"), "Node.js required for JS VM tests")
    def test_interactive_canvas_binds_live_stream_img_and_scales_source_res(self) -> None:
        """initTagModal binds #live-stream-img and findHoveredTrack respects sceneExtras.sourceRes."""
        script = (
            "const fs = require('fs'), vm = require('vm');\n"
            f"const uCode = fs.readFileSync({json.dumps(str(UNIFIED_JS))}, 'utf8');\n"
            f"const iCode = fs.readFileSync({json.dumps(str(INTERACTIVE_JS))}, 'utf8');\n"
            "let attachedOpts = null;\n"
            "const liveImg = { id: 'live-stream-img', naturalWidth: 640, naturalHeight: 360, clientWidth: 640, clientHeight: 360 };\n"
            "const liveCanvas = { id: 'interactive-canvas', width: 640, height: 360, style: { width: '640px', height: '360px' }, parentElement: {} };\n"
            "const els = { 'live-stream-img': liveImg, 'interactive-canvas': liveCanvas };\n"
            "const doc = { getElementById: (id) => els[id] || null };\n"
            "const win = { devicePixelRatio: 1, RoiDrawTagger: { setRecognitionHandler: () => {}, attach: (o) => { attachedOpts = o; } } };\n"
            "const sb = { window: win, document: doc, Math, Number, Array, Object, String, Boolean, JSON, parseFloat, parseInt, console };\n"
            "vm.runInNewContext(uCode, sb); vm.runInNewContext(iCode, sb);\n"
            "win.InteractiveCanvas.initTagModal(() => 'cam_01');\n"
            "const ctx = { clearRect: () => {}, save: () => {}, restore: () => {}, fillRect: () => {}, strokeRect: () => {}, fillText: () => {}, measureText: () => ({ width: 20 }) };\n"
            "const tracks = [{ id: 9, bbox: [200, 100, 100, 100], confidence: 0.9 }];\n"
            "win.InteractiveCanvas.drawOverlay(ctx, liveCanvas, liveImg, tracks, null, { sourceRes: [1280, 720] });\n"
            "const hit = win.InteractiveCanvas.findHoveredTrack(110, 60, liveCanvas, liveImg, tracks);\n"
            "process.stdout.write(JSON.stringify({ mediaId: attachedOpts.mediaEl.id, srcCtx: attachedOpts.getSourceContext(), hitId: hit ? hit.id : null }));\n"
        )
        out = _run_node(script)
        self.assertEqual(out["mediaId"], "live-stream-img")
        self.assertEqual(out["srcCtx"]["sourceWidth"], 640)
        self.assertEqual(out["hitId"], 9)

    @unittest.skipUnless(shutil.which("node"), "Node.js required for JS VM tests")
    def test_live_player_annotation_toggle_and_frame_surface_seq(self) -> None:
        """LivePlayer defaults to annotated=false, toggles annotated=true, and FrameSurface stamps seq."""
        script = (
            "const fs = require('fs'), vm = require('vm');\n"
            f"const lpCode = fs.readFileSync({json.dumps(str(LIVE_PLAYER_JS))}, 'utf8');\n"
            f"const fsCode = fs.readFileSync({json.dumps(str(FRAME_SURFACE_JS))}, 'utf8');\n"
            "const store = {};\n"
            "const img = { src: '', dataset: {} };\n"
            "const lagBadge = { hidden: true, textContent: '', dataset: {} };\n"
            "const hud = { textContent: '' };\n"
            "const btn = { textContent: '', dataset: {}, classList: { toggle: () => {} }, addEventListener: () => {} };\n"
            "const els = { 'live-stream-img': img, 'stream-lag-badge': lagBadge, 'stream-telemetry-hud': hud, 'btn-live-annotation-mode': btn };\n"
            "const doc = { getElementById: (id) => els[id] || null, addEventListener: () => {} };\n"
            "const win = { localStorage: { getItem: (k) => store[k] || null, setItem: (k, v) => { store[k] = v; } }, dispatchEvent: () => {} };\n"
            "const sb = { window: win, document: doc, Event: function(t){ this.type = t; }, Date, Math, Number, String, Boolean, Array, Object, encodeURIComponent, setTimeout, clearTimeout, console };\n"
            "vm.runInNewContext(lpCode, sb); vm.runInNewContext(fsCode, sb);\n"
            "win.LivePlayer.attachLiveStream(img, 'cam_01', true);\n"
            "const defaultSrc = img.src;\n"
            "win.LivePlayer.updateInferenceLagHud({ camera_id: 'cam_01', resolution: '1280x720', fps: 25, frame_seq: 20, inference_frame_seq: 16, inference_lag_ms: 185 });\n"
            "const lagVisible = !lagBadge.hidden; const lagText = lagBadge.textContent;\n"
            "win.LivePlayer.setBurnedAnnotationMode(true, img, 'cam_01');\n"
            "const burnedSrc = img.src;\n"
            "const tileCanvas = { width: 320, height: 180, dataset: {}, getContext: () => ({ fillRect: () => {}, fillText: () => {}, drawImage: () => {} }) };\n"
            "const surf = new win.FrameSurface(tileCanvas, { decodeBitmap: async () => ({ width: 320, height: 180, close: () => {} }) });\n"
            "surf.pushFrame(new Uint8Array([1, 2]), 44, 98765).then(() => {\n"
            "  process.stdout.write(JSON.stringify({ defaultSrc, burnedSrc, stored: store.it_live_annotated_mode, lagVisible, lagText, seqAttr: tileCanvas.dataset.frameSeq }));\n"
            "});\n"
        )
        out = _run_node(script)
        self.assertIn("annotated=false", out["defaultSrc"])
        self.assertIn("annotated=true", out["burnedSrc"])
        self.assertEqual(out["stored"], "true")
        self.assertTrue(out["lagVisible"])
        self.assertEqual(out["lagText"], "AI Lag: 185ms")
        self.assertEqual(out["seqAttr"], "44")


if __name__ == "__main__":
    unittest.main()
