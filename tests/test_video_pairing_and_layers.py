#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit & Integration Tests for Video Pairing, Idempotent Transcoding,
Container PTS Timing, Resolution-Aware Reports, and Overlay Scaling.
"""

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.dependencies import VIDEOS_DIR
from intelligent_tracker.batch import VideoIndexer
from intelligent_tracker.video import PipelineVideoWriter

JS_DIR = pathlib.Path(__file__).resolve().parent.parent / "dashboard" / "static" / "js"


def create_test_clip(
    path: str,
    num_frames: int = 8,
    fps: float = 12.5,
    width: int = 320,
    height: int = 240,
) -> str:
    """Create a tiny synthetic MP4 clip with a moving green target."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with PipelineVideoWriter(path, fps=fps, resolution=(width, height)) as writer:
        for i in range(num_frames):
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            x = int(20 + (i * 10) % max(40, width - 60))
            cv2.rectangle(frame, (x, 40), (x + 40, 100), (0, 255, 0), -1)
            writer.write(frame)
    return path


class TestVideoPairingAndIdempotencyAPI(unittest.TestCase):
    """Verify SC-01 pairing metadata in /api/videos and SC-02 idempotent /transcode."""

    @classmethod
    def setUpClass(cls):
        os.makedirs(VIDEOS_DIR, exist_ok=True)
        cls.client = TestClient(app)
        cls.created_files = []

        cls.paired_src = "pair_unit_clip.mp4"
        cls.paired_h264 = "pair_unit_clip_h264.mp4"
        cls.unpaired_src = "unpaired_unit_clip.mp4"
        cls.zero_byte_src = "zerobyte_unit_clip.mp4"
        cls.zero_byte_h264 = "zerobyte_unit_clip_h264.mp4"

        for name in (cls.paired_src, cls.paired_h264, cls.unpaired_src, cls.zero_byte_src):
            full = os.path.join(VIDEOS_DIR, name)
            create_test_clip(full, num_frames=6, fps=10.0)
            cls.created_files.append(full)

        zero_path = os.path.join(VIDEOS_DIR, cls.zero_byte_h264)
        with open(zero_path, "wb") as f:
            f.write(b"")
        cls.created_files.append(zero_path)

    @classmethod
    def tearDownClass(cls):
        for full in cls.created_files:
            if os.path.exists(full):
                try:
                    os.remove(full)
                except OSError:
                    pass

    def test_list_videos_pairing_flags(self):
        """SC-01: Non-web-compatible recording with valid _h264 copy sets has_converted_h264=True."""
        resp = self.client.get("/api/videos")
        self.assertEqual(resp.status_code, 200)
        by_name = {item["filename"]: item for item in resp.json()}

        paired_item = by_name.get(self.paired_src)
        self.assertIsNotNone(paired_item)
        self.assertFalse(paired_item["web_compatible"])
        self.assertTrue(paired_item["has_converted_h264"])
        self.assertEqual(paired_item["converted_filename"], self.paired_h264)

        child_item = by_name.get(self.paired_h264)
        self.assertIsNotNone(child_item)
        self.assertFalse(child_item["has_converted_h264"])
        self.assertIsNone(child_item["converted_filename"])

        unpaired_item = by_name.get(self.unpaired_src)
        self.assertIsNotNone(unpaired_item)
        self.assertFalse(unpaired_item["has_converted_h264"])
        self.assertIsNone(unpaired_item["converted_filename"])

        zero_item = by_name.get(self.zero_byte_src)
        self.assertIsNotNone(zero_item)
        self.assertFalse(zero_item["has_converted_h264"])

    def test_transcode_idempotent_skips_ffmpeg_when_output_exists(self):
        """SC-02: POST /transcode without force returns HTTP 200 already_exists without spawning ffmpeg."""
        with patch(
            "dashboard.services.video_transcoder.VideoTranscodeService.transcode_to_h264_async"
        ) as mock_async, patch(
            "dashboard.services.video_transcoder.VideoTranscodeService.transcode_to_h264"
        ) as mock_sync:
            resp = self.client.post(f"/api/videos/{self.paired_src}/transcode?async_mode=true")
            self.assertEqual(resp.status_code, 200)
            payload = resp.json()
            self.assertEqual(payload["status"], "success")
            self.assertTrue(payload["already_exists"])
            self.assertEqual(payload["output_filename"], self.paired_h264)
            self.assertEqual(payload["video_url"], f"/videos/{self.paired_h264}")
            mock_async.assert_not_called()
            mock_sync.assert_not_called()

    def test_transcode_force_true_bypasses_guard(self):
        """POST /transcode?force=true executes transcoder even when _h264 copy exists."""
        with patch(
            "dashboard.services.video_transcoder.VideoTranscodeService.transcode_to_h264",
            return_value=True,
        ) as mock_sync:
            resp = self.client.post(
                f"/api/videos/{self.paired_src}/transcode?async_mode=false&force=true"
            )
            self.assertEqual(resp.status_code, 200)
            payload = resp.json()
            self.assertEqual(payload["status"], "success")
            self.assertNotIn("already_exists", payload)
            mock_sync.assert_called_once()


class TestBatchPTSAndResolutionMetadata(unittest.TestCase):
    """Verify SYM-02 and SYM-03: container PTS timestamps and source_resolution capture."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_batch_pts_")
        self.db_path = os.path.join(self.temp_dir, "tracker.db")
        self.video_path = os.path.join(self.temp_dir, "pts_clip.mp4")
        create_test_clip(self.video_path, num_frames=8, fps=12.5, width=320, height=240)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_process_video_records_source_resolution_and_fps(self):
        """VideoIndexer stores source_resolution and source_fps in summary and detection frames."""
        indexer = VideoIndexer(
            db_path=self.db_path,
            detector_name="mock",
            sample_rate=1,
        )
        try:
            summary = indexer.process_video(self.video_path, verbose=False)
            self.assertEqual(summary["source_resolution"], [320, 240])
            self.assertAlmostEqual(summary["source_fps"], 12.5, delta=1.0)
            self.assertGreater(len(summary["frame_detections"]), 0)
            for pkt in summary["frame_detections"]:
                self.assertEqual(pkt["source_resolution"], [320, 240])
        finally:
            indexer.db.close()

    def test_process_video_uses_container_pts_and_falls_back_when_zero_or_negative(self):
        """Container PTS overrides frame division; <= 0.0 PTS falls back to (read_frames - 1) / fps."""
        fake_frame = np.zeros((1086, 1920, 3), dtype=np.uint8)
        cv2.rectangle(fake_frame, (100, 100), (200, 300), (0, 255, 0), -1)

        # Simulate 3 frames:
        # Frame 0: POS_MSEC=0.0 -> fallback 0.0s
        # Frame 1: POS_MSEC=45.0 -> PTS 0.045s (distinct from 1/30.0 = 0.033s!)
        # Frame 2: POS_MSEC=-1.0 -> fallback 2 / 25.0 = 0.08s
        pos_values = iter([0.0, 45.0, -1.0])
        read_count = {"n": 0}

        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True

        def _cap_get(prop):
            if prop == cv2.CAP_PROP_FRAME_COUNT:
                return 3
            if prop == cv2.CAP_PROP_FPS:
                return 25.0
            if prop == cv2.CAP_PROP_FRAME_WIDTH:
                return 0  # Also tests fallback to frame.shape width/height
            if prop == cv2.CAP_PROP_FRAME_HEIGHT:
                return 0
            if prop == cv2.CAP_PROP_POS_MSEC:
                return next(pos_values, -1.0)
            return 0.0

        def _cap_read():
            if read_count["n"] < 3:
                read_count["n"] += 1
                return True, fake_frame.copy()
            return False, None

        mock_cap.get.side_effect = _cap_get
        mock_cap.read.side_effect = _cap_read

        indexer = VideoIndexer(db_path=self.db_path, detector_name="mock", sample_rate=1)
        try:
            with patch("intelligent_tracker.batch.cv2.VideoCapture", return_value=mock_cap):
                summary = indexer.process_video(self.video_path, verbose=False)

            self.assertEqual(summary["source_resolution"], [1920, 1086])
            self.assertEqual(summary["source_fps"], 25.0)
            times = [pkt["time"] for pkt in summary["frame_detections"]]
            self.assertEqual(times, [0.0, 0.045, 0.08])
        finally:
            indexer.db.close()


class TestFrontendScalingCacheAndMultiLayer(unittest.TestCase):
    """Execute real JS overlay, batch cache, and library modules in Node.js VM."""

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS runtime verification")
    def _run_js(self, files: list[str], body: str) -> dict:
        prelude = """
const fs = require('fs'), vm = require('vm'), path = require('path'), jsDir = process.env.JS_DIR;
const byId = new Map(), docListeners = new Map(), winListeners = new Map(), storage = new Map(), draws = [];
const makeEl = (tag = 'div', id = '') => {
  const attrs = new Map(), listeners = new Map(), classes = new Set();
  const el = {
    tagName: tag.toUpperCase(), id, style: {}, hidden: false, disabled: false,
    textContent: '', value: '', title: '', tabIndex: 0, _html: '', _children: [],
    parentNode: null, parentElement: null,
    classList: {
      add: (...c) => c.forEach(x => classes.add(x)),
      remove: (...c) => c.forEach(x => classes.delete(x)),
      toggle: (c, f) => (f === undefined ? (classes.has(c) ? classes.delete(c) : classes.add(c)) : (f ? classes.add(c) : classes.delete(c))),
      contains: (c) => classes.has(c),
    },
    setAttribute: (k, v) => {
      attrs.set(k, String(v));
      if (k === 'class') String(v).split(/\\s+/).filter(Boolean).forEach(x => classes.add(x));
      if (k === 'id') { el.id = String(v); byId.set(el.id, el); }
    },
    getAttribute: (k) => (attrs.has(k) ? attrs.get(k) : null),
    removeAttribute: (k) => attrs.delete(k),
    addEventListener: (t, fn) => { if (!listeners.has(t)) listeners.set(t, []); listeners.get(t).push(fn); },
    dispatchEvent: (ev) => {
      ev.target = ev.target || el; ev.currentTarget = el;
      ev.stopPropagation = ev.stopPropagation || (() => {});
      ev.preventDefault = ev.preventDefault || (() => {});
      (listeners.get(ev.type) || []).forEach(fn => fn(ev));
    },
    click: () => el.dispatchEvent({ type: 'click', target: el }),
    focus: () => { doc.activeElement = el; },
    contains: (c) => el === c || el._children.includes(c),
    closest: (sel) => (sel.startsWith('.') && classes.has(sel.slice(1)) ? el : null),
    insertBefore: (n) => { n.parentNode = el; n.parentElement = el; if (n.id) byId.set(n.id, n); },
    querySelectorAll: (sel) => {
      const parts = sel.split(',').map(s => s.trim());
      return el._children.filter(c => parts.some(p => {
        if (p.startsWith('#')) return c.id === p.slice(1);
        if (p.startsWith('.')) {
          const m = p.match(/^\\.([^\\[]+)(\\[data-filename="([^"]+)"\\])?/);
          if (!m || !c.classList.contains(m[1])) return false;
          return m[3] ? c.getAttribute('data-filename') === m[3].replace(/\\\\/g, '') : true;
        }
        return c.tagName.toLowerCase() === p.toLowerCase();
      }));
    },
    querySelector: (sel) => el.querySelectorAll(sel)[0] || null,
    getBoundingClientRect: () => el._rect || { left: 0, top: 0, width: 960, height: 543 },
  };
  Object.defineProperty(el, 'innerHTML', {
    get: () => el._html,
    set: (html) => {
      el._html = String(html); el._children = [];
      const re = /<(button|select|div)\\b([^>]*)>/gi;
      for (let m; (m = re.exec(el._html)) !== null;) {
        const child = makeEl(m[1]);
        for (let am, attrRe = /([a-zA-Z0-9_-]+)="([^"]*)"/g; (am = attrRe.exec(m[2])) !== null;) child.setAttribute(am[1], am[2]);
        el._children.push(child);
      }
    },
  });
  return el;
};
const stage = makeEl('div', 'scrubber-stage');
const viewport = makeEl('div', 'scrubber-viewport');
viewport.parentNode = stage; viewport._rect = { left: 0, top: 0, width: 960, height: 543 };
const player = makeEl('video', 'scrubber-video-player');
player._rect = { left: 0, top: 0, width: 960, height: 543 };
player.videoWidth = 2688; player.videoHeight = 1520; player.currentTime = 1.0;
const canvas = makeEl('canvas', 'scrubber-overlay-canvas');
canvas.parentElement = viewport;
const ctx2d = {
  strokeStyle: '', fillStyle: '', lineWidth: 1, font: '', textBaseline: 'top',
  save: () => {}, restore: () => {}, scale: () => {}, clearRect: () => {}, fillRect: () => {},
  strokeRect: (x, y, w, h) => draws.push({ op: 'strokeRect', x, y, w, h, stroke: ctx2d.strokeStyle }),
  measureText: (txt) => ({ width: txt.length * 6 }),
  fillText: (txt, x, y) => draws.push({ op: 'fillText', txt, x, y, fill: ctx2d.fillStyle }),
};
canvas.getContext = () => ctx2d;
const layersBar = makeEl('div', 'scrubber-overlay-layers'), layersStatus = makeEl('div', 'scrubber-overlay-layers-status');
const reportContainer = makeEl('div', 'video-batch-report-container'), analyzeBtn = makeEl('button', 'btn-video-analyze');
[player, canvas, layersBar, layersStatus, reportContainer, analyzeBtn].forEach(e => byId.set(e.id, e));
const doc = {
  readyState: 'complete', activeElement: null,
  getElementById: (id) => byId.get(id) || null, createElement: (tag) => makeEl(tag),
  querySelector: (sel) => (sel === '.scrubber-viewport' ? viewport : null), querySelectorAll: () => [],
  addEventListener: (t, fn) => { if (!docListeners.has(t)) docListeners.set(t, []); docListeners.get(t).push(fn); },
};
function CustomEvent(type, init = {}) { this.type = type; this.detail = init.detail; }
function HTMLElement() {}
const sandbox = {
  console, Math, Number, String, Array, Object, Map, Set, JSON, Promise, Infinity, isNaN, parseFloat, parseInt, encodeURIComponent,
  HTMLElement, CustomEvent, MediaError: { MEDIA_ERR_SRC_NOT_SUPPORTED: 4 },
  CSS: { escape: (s) => String(s).replace(/[^a-zA-Z0-9_-]/g, '\\\\$&') },
  localStorage: { getItem: (k) => (storage.has(k) ? storage.get(k) : null), setItem: (k, v) => storage.set(k, String(v)) },
  getComputedStyle: () => ({ direction: 'ltr' }), requestAnimationFrame: () => 1, cancelAnimationFrame: () => {},
  document: doc, fetch: async () => ({ ok: false, json: async () => ({}) }), devicePixelRatio: 1,
};
sandbox.window = sandbox;
sandbox.addEventListener = (t, fn) => { if (!winListeners.has(t)) winListeners.set(t, []); winListeners.get(t).push(fn); };
sandbox.dispatchEvent = (ev) => Promise.all((winListeners.get(ev.type) || []).map(fn => fn(ev)));
vm.createContext(sandbox);
JSON.parse(process.env.JS_FILES).forEach(f => vm.runInContext(fs.readFileSync(path.join(jsDir, f), 'utf8'), sandbox, { filename: f }));
(async () => {
"""
        epilogue = "\n})().catch(err => { console.error(err); process.exit(1); });"
        env = dict(os.environ, JS_DIR=str(JS_DIR), JS_FILES=json.dumps(files))
        proc = subprocess.run(["node", "-e", prelude + body + epilogue], capture_output=True, text=True, env=env, timeout=15)
        self.assertEqual(proc.returncode, 0, f"Node harness failed:\nSTDERR:\n{proc.stderr}\nSTDOUT:\n{proc.stdout}")
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_resolution_aware_coordinate_scaling_2688_vs_1920(self):
        """SC-04: 2688x1520 detections render at identical canvas coordinates on 2688x1520 and 1920x1086 players."""
        res = self._run_js(
            ["scrubber_overlay_renderer.js", "scrubber_overlay.js"],
            """
const detections = [{
  time: 1.0, frame: 30, source_resolution: [2688, 1520],
  tracks: [{ track_id: 7, label: 'person', confidence: 0.91, bbox: [1421, 175, 63, 132] }],
}];
sandbox.ScrubberOverlay.setDetections(detections, [2688, 1520], { runId: 'r1' });
const orig = draws.filter(d => d.op === 'strokeRect')[0];
draws.length = 0;
player.videoWidth = 1920; player.videoHeight = 1086;
sandbox.ScrubberOverlay.render();
const trans = draws.filter(d => d.op === 'strokeRect')[0];
const fallbackFactors = sandbox.ScrubberOverlay.resolveScaleFactors(960, 543, { time: 1.0, tracks: [] }, 1920, 1086);
console.log(JSON.stringify({ orig, trans, fallbackFactors }));
""",
        )
        for key in ("x", "y", "w", "h"):
            self.assertAlmostEqual(res["orig"][key], res["trans"][key], delta=0.25)
        self.assertAlmostEqual(res["fallbackFactors"]["scaleX"], 960 / 2688, places=6)
        self.assertAlmostEqual(res["fallbackFactors"]["scaleY"], 543 / 1520, places=6)

    def test_reactive_cache_invalidation_clears_stale_tags(self):
        """SC-05: job-finished purges stale parent/_h264 report cache so car replaces person without reload."""
        res = self._run_js(
            ["video_batch_reports.js", "video_batch.js"],
            """
let phase = 1; const fetchedUrls = [];
sandbox.fetch = async (url) => {
  fetchedUrls.push(url);
  if (phase === 1) return { ok: true, json: async () => [{ run_id: 'r1', config: { detector: 'yolov8', classes: ['person'] }, report: { frames_processed: 10, total_detections: 3 } }] };
  return { ok: true, json: async () => [
    { run_id: 'r2', config: { detector: 'yolov8', classes: ['car'] }, report: { frames_processed: 10, total_detections: 5 } },
    { run_id: 'r1', config: { detector: 'yolov8', classes: ['person'] }, report: { frames_processed: 10, total_detections: 3 } },
  ] };
};
await sandbox.VideoBatch.restoreReportForFile('cam_rec.mp4');
const firstHtml = reportContainer.innerHTML;
await sandbox.VideoBatch.restoreReportForFile('cam_rec.mp4');
const callsAfterCacheHit = fetchedUrls.length;
phase = 2;
await sandbox.dispatchEvent(new CustomEvent('video-job-event', {
  detail: { type: 'job-finished', data: { job_type: 'analytics', filename: 'cam_rec.mp4', status: 'completed', result: { run_id: 'r2' } } }
}));
const secondHtml = reportContainer.innerHTML;
sandbox.VideoBatch.setCurrentBatchFilename('other.mp4');
reportContainer.innerHTML = '<div>OTHER_VIDEO_VIEW</div>';
await sandbox.dispatchEvent(new CustomEvent('video-job-event', {
  detail: { type: 'job-finished', data: { job_type: 'analytics', filename: 'cam_rec_h264.mp4', status: 'completed', result: { run_id: 'r3' } } }
}));
console.log(JSON.stringify({ firstHtml, secondHtml, callsAfterCacheHit, totalCalls: fetchedUrls.length, otherHtml: reportContainer.innerHTML }));
""",
        )
        self.assertIn("person", res["firstHtml"])
        self.assertEqual(res["callsAfterCacheHit"], 1)
        self.assertEqual(res["totalCalls"], 2)
        self.assertIn("car", res["secondHtml"])
        self.assertIn("r2", res["secondHtml"])
        self.assertEqual(res["otherHtml"], "<div>OTHER_VIDEO_VIEW</div>")

    def test_multi_layer_compositing_and_live_stream_lifecycle(self):
        """SC-06/SC-07: Multiple toggled layers render concurrently in distinct palettes alongside live stream."""
        res = self._run_js(
            ["scrubber_overlay_renderer.js", "scrubber_overlay.js", "overlay_layer_toolbar.js", "overlay_layers.js"],
            """
const runStreams = {
  r1: { source_resolution: [1920, 1080], frame_detections: [{ time: 1.0, tracks: [{ track_id: 1, label: 'person', confidence: 0.9, bbox: [100, 100, 50, 100] }] }] },
  r2: { source_resolution: [1920, 1080], frame_detections: [{ time: 1.0, tracks: [{ track_id: 2, label: 'car', confidence: 0.85, bbox: [400, 200, 120, 80] }] }] },
};
sandbox.fetch = async (url) => {
  if (url.endsWith('/reports')) return { ok: true, json: async () => [{ run_id: 'r2', config: { detector: 'yolov8', classes: ['car'] } }, { run_id: 'r1', config: { detector: 'yolov8', classes: ['person'] } }] };
  const m = url.match(/reports\\/([^/]+)\\/detections/);
  return { ok: Boolean(m && runStreams[m[1]]), json: async () => runStreams[m[1]] };
};
await sandbox.ScrubberOverlay.loadDetections('cam_rec.mp4');
await new Promise(r => setTimeout(r, 10));
layersBar.querySelectorAll('.overlay-layer-chip').find(c => c.getAttribute('data-run-id') === 'r1').click();
await new Promise(r => setTimeout(r, 10));
draws.length = 0;
sandbox.ScrubberOverlay.render();
const dualStrokes = draws.filter(d => d.op === 'strokeRect').map(d => d.stroke);
const dualLabels = draws.filter(d => d.op === 'fillText').map(d => d.txt);
await sandbox.dispatchEvent(new CustomEvent('video-job-event', {
  detail: { type: 'job-started', data: { job_id: 'j99', job_type: 'analytics', filename: 'cam_rec.mp4', status: 'running' } }
}));
sandbox.ScrubberOverlay.appendDetections([{ time: 1.0, tracks: [{ track_id: 9, label: 'truck', confidence: 0.88, bbox: [700, 300, 90, 70] }] }], [1920, 1080], { layerId: 'live:j99' });
const liveLayerCount = sandbox.ScrubberOverlay.getActiveLayerIds().length;
await sandbox.dispatchEvent(new CustomEvent('video-job-event', {
  detail: { type: 'job-finished', data: { job_id: 'j99', job_type: 'analytics', filename: 'cam_rec.mp4', status: 'cancelled' } }
}));
const postCancelIds = sandbox.ScrubberOverlay.getActiveLayerIds();
layersBar.querySelectorAll('.overlay-layer-action-btn').find(b => b.getAttribute('data-layer-action') === 'none').click();
const clearedIds = sandbox.OverlayLayers.getActiveRunIds();
layersBar.querySelectorAll('.overlay-layer-action-btn').find(b => b.getAttribute('data-layer-action') === 'all').click();
await new Promise(r => setTimeout(r, 10));
await sandbox.OverlayLayers.ensureLoaded('cam_rec_h264.mp4');
console.log(JSON.stringify({ dualStrokes, dualLabels, liveLayerCount, postCancelIds, clearedIds, restoredAliasIds: sandbox.OverlayLayers.getActiveRunIds() }));
""",
        )
        self.assertEqual(set(res["dualStrokes"]), {"#06b6d4", "#f59e0b"})
        self.assertTrue(any(lbl.startswith("R1 · person") for lbl in res["dualLabels"]))
        self.assertTrue(any(lbl.startswith("R2 · car") for lbl in res["dualLabels"]))
        self.assertEqual(res["liveLayerCount"], 3)
        self.assertEqual(set(res["postCancelIds"]), {"r1", "r2"})
        self.assertEqual(res["clearedIds"], [])
        self.assertEqual(set(res["restoredAliasIds"]), {"r1", "r2"})

    def test_paired_h264_switch_ui_and_reconvert_action(self):
        """SC-03: Paired incompatible video renders Switch to H.264 & Re-convert instead of Convert."""
        res = self._run_js(
            ["video_library.js"],
            """
const switched = [];
sandbox.loadVideoIntoPlayer = (url, fn, web, codec) => switched.push({ url, fn, web, codec });
const files = [{ filename: 'hevc_cam.mp4', video_url: '/videos/hevc_cam.mp4', size_mb: 12.4, codec: 'hevc', web_compatible: false, has_converted_h264: true, converted_filename: 'hevc_cam_h264.mp4', resolution: '2688x1520' }];
sandbox.VideoLibrary.registerVideos(files);
const cardHost = doc.createElement('div');
cardHost.innerHTML = sandbox.VideoLibrary.renderVideoFileCard(files[0], 'hevc_cam.mp4');
sandbox.VideoLibrary.bindPairedActionControls(cardHost);
cardHost.querySelector('.btn-switch-h264').click();
sandbox.VideoLibrary.showCodecNotice('HEVC unsupported', 'hevc_cam.mp4');
console.log(JSON.stringify({ cardHtml: cardHost.innerHTML, noticeHtml: doc.getElementById('scrubber-codec-notice').innerHTML, switched }));
""",
        )
        self.assertIn("btn-switch-h264", res["cardHtml"])
        self.assertIn("btn-reconvert-video", res["cardHtml"])
        self.assertNotIn("btn-transcode-video", res["cardHtml"])
        self.assertIn("▶ Switch to H.264", res["noticeHtml"])
        self.assertEqual(res["switched"], [{"url": "/videos/hevc_cam_h264.mp4", "fn": "hevc_cam_h264.mp4", "web": True, "codec": "h264"}])


if __name__ == "__main__":
    unittest.main()
