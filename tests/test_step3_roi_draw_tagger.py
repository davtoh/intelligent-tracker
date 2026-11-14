#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit/VM tests for Step 3 Milestone 2: RoiDrawTagger unified canvas controller."""

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OVERLAY_JS = REPO_ROOT / "dashboard" / "static" / "js" / "unified_canvas_overlay.js"
TAGGER_JS = REPO_ROOT / "dashboard" / "static" / "js" / "roi_draw_tagger.js"
INDEX_HTML = REPO_ROOT / "dashboard" / "static" / "index.html"


_NODE_PREAMBLE = """
function makeMockCtx() {
  const calls = [];
  const noop = (name) => (...a) => calls.push([name, ...a]);
  return {
    calls,
    save: noop('save'), restore: noop('restore'), clearRect: noop('clearRect'),
    fillRect: noop('fillRect'), strokeRect: noop('strokeRect'),
    setLineDash: noop('setLineDash'),
  };
}
function makeMockCanvas(rect) {
  const listeners = {};
  const ctx = makeMockCtx();
  return {
    listeners, ctx,
    width: rect.width, height: rect.height,
    style: { width: `${rect.width}px`, height: `${rect.height}px` },
    getContext: () => ctx,
    getBoundingClientRect: () => rect,
    addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
    removeEventListener: (ev, fn) => {
      listeners[ev] = (listeners[ev] || []).filter((f) => f !== fn);
    },
    setPointerCapture: () => {},
    releasePointerCapture: () => {},
    emit: (ev, payload) => (listeners[ev] || []).slice().forEach((fn) => fn(payload)),
  };
}
"""


def _run_node(body: str) -> dict:
    """Execute a JS snippet with UnifiedCanvasOverlay and RoiDrawTagger in Node VM."""
    script = (
        "const fs = require('fs'), vm = require('vm');\n"
        f"const overlayCode = fs.readFileSync({json.dumps(str(OVERLAY_JS))}, 'utf8');\n"
        f"const taggerCode = fs.readFileSync({json.dumps(str(TAGGER_JS))}, 'utf8');\n"
        "const windowObj = { devicePixelRatio: 1 };\n"
        "const sandbox = { window: windowObj, Math, Number, Array, Object, String, Boolean, JSON, WeakMap, console };\n"
        "sandbox.globalThis = sandbox;\n"
        "vm.runInNewContext(overlayCode, sandbox);\n"
        "vm.runInNewContext(taggerCode, sandbox);\n"
        "const T = windowObj.RoiDrawTagger;\n"
        + _NODE_PREAMBLE
        + f"\nconst result = (function() {{\n{body}\n}})();\n"
        + "process.stdout.write(JSON.stringify(result));\n"
    )
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, env=dict(os.environ), timeout=15)
    if proc.returncode != 0:
        raise AssertionError(f"Node VM failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}")
    return json.loads(proc.stdout)


class TestRoiDrawTagger(unittest.TestCase):
    """Verify coordinate mapping, click-vs-drag branching, video pause-on-drag, and budgets."""

    def test_index_html_loads_roi_draw_tagger_after_unified_overlay(self) -> None:
        html = INDEX_HTML.read_text(encoding="utf-8")
        idx_overlay = html.find('/static/js/unified_canvas_overlay.js')
        idx_tagger = html.find('/static/js/roi_draw_tagger.js')
        idx_interactive = html.find('/static/js/interactive_canvas.js')
        self.assertGreater(idx_overlay, -1)
        self.assertGreater(idx_tagger, idx_overlay)
        self.assertGreater(idx_interactive, idx_tagger)

    def test_file_line_budget(self) -> None:
        lines = TAGGER_JS.read_text(encoding="utf-8").splitlines()
        self.assertLess(len(lines), 260, f"roi_draw_tagger.js has {len(lines)} lines (>= 260)")

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_map_client_to_source_point_pillarbox_and_clamp(self) -> None:
        out = _run_node("""
const container = { getBoundingClientRect: () => ({ left: 100, top: 50, width: 1000, height: 500 }) };
const media = {
  naturalWidth: 1000, naturalHeight: 500,
  getBoundingClientRect: () => ({ left: 100, top: 50, width: 1200, height: 500 }),
};
// Media aspect 2:1 inside 1200x500 -> renderH=500, renderW=1000, offsetX=100, offsetY=0
const center = T.mapClientToSourcePoint(700, 300, media, container, 1000, 500);
const clamped = T.mapClientToSourcePoint(50, 10, media, container, 1000, 500);
return { center, clamped };
""")
        self.assertAlmostEqual(out["center"]["x"], 500.0, places=2)
        self.assertAlmostEqual(out["center"]["y"], 250.0, places=2)
        self.assertTrue(out["center"]["inBounds"])
        self.assertEqual(out["clamped"]["x"], 0)
        self.assertEqual(out["clamped"]["y"], 0)
        self.assertFalse(out["clamped"]["inBounds"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_normalize_drag_rect_and_hit_test(self) -> None:
        out = _run_node("""
const rev = T.normalizeDragRect({ x: 320.4, y: 240.6 }, { x: 120.2, y: 80.1 });
const tiny = T.normalizeDragRect({ x: 10, y: 10 }, { x: 12, y: 20 });
const tracks = [
  { id: 1, bbox: [100, 100, 120, 140] },
  { id: 2, bbox: [150, 150, 80, 90] },
];
const hitOverlap = T.hitTestTrackAtPoint(160, 160, tracks);
const hitFirst = T.hitTestTrackAtPoint(110, 110, tracks);
const miss = T.hitTestTrackAtPoint(10, 10, tracks);
return { rev, tiny, hitOverlap: hitOverlap?.id, hitFirst: hitFirst?.id, miss };
""")
        self.assertEqual(out["rev"], [120, 80, 200, 161])
        self.assertIsNone(out["tiny"])
        self.assertEqual(out["hitOverlap"], 2)
        self.assertEqual(out["hitFirst"], 1)
        self.assertIsNone(out["miss"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_click_threshold_selects_track_without_pausing_video(self) -> None:
        out = _run_node("""
const container = { getBoundingClientRect: () => ({ left: 0, top: 0, width: 640, height: 480 }) };
let pauseCalls = 0;
const videoEl = {
  videoWidth: 640, videoHeight: 480, paused: false,
  pause: () => { pauseCalls += 1; videoEl.paused = true; },
  getBoundingClientRect: () => ({ left: 0, top: 0, width: 640, height: 480 }),
};
const canvas = makeMockCanvas({ left: 0, top: 0, width: 640, height: 480 });
const clicks = [], rois = [];
T.attach({
  canvas, mediaEl: videoEl, containerEl: container,
  getTracks: () => [{ id: 7, bbox: [100, 100, 80, 120] }],
  getSourceContext: () => ({ sourceType: 'video', videoFilename: 'clip.mp4', timestampSec: 12.5 }),
  onTrackClick: (ev) => clicks.push(ev),
  onRoiDrawn: (ev) => rois.push(ev),
});
canvas.emit('pointerdown', { button: 0, pointerId: 1, clientX: 120, clientY: 130 });
canvas.emit('pointermove', { pointerId: 1, clientX: 123, clientY: 133 });
canvas.emit('pointerup', { pointerId: 1, clientX: 123, clientY: 133 });
return { clicks, rois, pauseCalls };
""")
        self.assertEqual(len(out["clicks"]), 1)
        self.assertEqual(out["clicks"][0]["track"]["id"], 7)
        self.assertEqual(len(out["rois"]), 0)
        self.assertEqual(out["pauseCalls"], 0)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_drag_threshold_pauses_video_draws_overlay_and_detaches(self) -> None:
        out = _run_node("""
const container = { getBoundingClientRect: () => ({ left: 0, top: 0, width: 640, height: 480 }) };
let pauseCalls = 0;
const videoEl = {
  videoWidth: 640, videoHeight: 480, paused: false,
  pause: () => { pauseCalls += 1; videoEl.paused = true; },
  getBoundingClientRect: () => ({ left: 0, top: 0, width: 640, height: 480 }),
};
const canvas = makeMockCanvas({ left: 0, top: 0, width: 640, height: 480 });
const clicks = [], rois = [];
const detach = T.attach({
  canvas, mediaEl: videoEl, containerEl: container,
  getTracks: () => [{ id: 7, bbox: [100, 100, 80, 120] }],
  getSourceContext: () => ({ sourceType: 'video', videoFilename: 'clip.mp4', timestampSec: 12.5 }),
  onTrackClick: (ev) => clicks.push(ev),
  onRoiDrawn: (ev) => rois.push(ev),
});
canvas.emit('pointerdown', { button: 0, pointerId: 2, clientX: 200, clientY: 150 });
canvas.emit('pointermove', { pointerId: 2, clientX: 300, clientY: 260 });
const dashCount = canvas.ctx.calls.filter((c) => c[0] === 'setLineDash' && c[1].length === 2).length;
canvas.emit('pointerup', { pointerId: 2, clientX: 300, clientY: 260 });
detach();
return { clicks, rois, pauseCalls, dashCount, remaining: (canvas.listeners.pointerdown || []).length };
""")
        self.assertEqual(len(out["clicks"]), 0)
        self.assertEqual(out["pauseCalls"], 1)
        self.assertEqual(len(out["rois"]), 1)
        self.assertEqual(out["rois"][0]["bbox"], [200, 150, 100, 110])
        self.assertEqual(out["rois"][0]["sourceContext"]["videoFilename"], "clip.mp4")
        self.assertGreaterEqual(out["dashCount"], 1)
        self.assertEqual(out["remaining"], 0)


if __name__ == "__main__":
    unittest.main()
