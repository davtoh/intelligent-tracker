#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit/VM tests for Step 2 Milestone 4: #videos ScrubberOverlay parity & modularity budgets."""

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
JS_DIR = REPO_ROOT / "dashboard" / "static" / "js"
UNIFIED_JS = JS_DIR / "unified_canvas_overlay.js"
RENDERER_JS = JS_DIR / "scrubber_overlay_renderer.js"
SCRUBBER_JS = JS_DIR / "scrubber_overlay.js"
LAYERS_JS = JS_DIR / "overlay_layers.js"
TOOLBAR_JS = JS_DIR / "overlay_layer_toolbar.js"


def _run_node(script_body: str) -> dict:
    """Execute a self-contained JS snippet in Node and return parsed JSON."""
    proc = subprocess.run(
        ["node", "-e", script_body],
        capture_output=True,
        text=True,
        env=dict(os.environ),
        timeout=15,
    )
    if proc.returncode != 0:
        raise AssertionError(f"Node VM failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}")
    return json.loads(proc.stdout)


def _vm_preamble(files: list[Path]) -> str:
    """Build a Node VM preamble that loads the requested JS files with DOM/canvas mocks."""
    loads = "\n".join(
        f"vm.runInNewContext(fs.readFileSync({json.dumps(str(p))}, 'utf8'), sb);" for p in files
    )
    return (
        "const fs = require('fs'), vm = require('vm');\n"
        "const calls = [];\n"
        "const noop = (n) => (...a) => calls.push([n, ...a]);\n"
        "const ctx = { canvas: { width: 0, height: 0 }, save: noop('save'), restore: noop('restore'),\n"
        "  clearRect: noop('clearRect'), fillRect: noop('fillRect'), strokeRect: noop('strokeRect'),\n"
        "  fillText: noop('fillText'), setTransform: noop('setTransform'), scale: noop('scale'),\n"
        "  beginPath: noop('beginPath'), closePath: noop('closePath'), moveTo: noop('moveTo'),\n"
        "  lineTo: noop('lineTo'), stroke: noop('stroke'), fill: noop('fill'), setLineDash: noop('setLineDash'),\n"
        "  measureText: (t) => ({ width: String(t).length * 6 }) };\n"
        "const viewport = { getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 450 }) };\n"
        "const canvas = { width: 0, height: 0, style: {}, parentElement: viewport, getContext: () => ctx };\n"
        "const video = { videoWidth: 1280, videoHeight: 720, currentTime: 1.0, paused: true,\n"
        "  getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 450 }) };\n"
        "const toolbarEl = { innerHTML: '', hidden: true, querySelectorAll: () => [], addEventListener: () => {} };\n"
        "const statusEl = { textContent: '' };\n"
        "const elems = { 'scrubber-video-player': video, 'scrubber-overlay-canvas': canvas,\n"
        "  'scrubber-overlay-layers': toolbarEl, 'scrubber-overlay-layers-status': statusEl };\n"
        "const doc = { readyState: 'complete', getElementById: (id) => elems[id] || null, querySelectorAll: () => [] };\n"
        "const win = { devicePixelRatio: 2, addEventListener: () => {} };\n"
        "function HTMLElement() {}\n"
        "const sb = { window: win, document: doc, HTMLElement, Math, Number, Array, Object, String, Boolean,\n"
        "  JSON, Map, Set, Infinity, encodeURIComponent, requestAnimationFrame: () => 1, cancelAnimationFrame: () => {},\n"
        "  getComputedStyle: () => ({ direction: 'ltr' }), console };\n"
        "sb.globalThis = sb;\n"
        f"{loads}\n"
    )


class TestVideoScrubberParity(unittest.TestCase):
    """Verify #videos ScrubberOverlay parity with UnifiedCanvasOverlay and budget compliance."""

    def test_modularity_line_budgets_under_350(self) -> None:
        for path in (SCRUBBER_JS, LAYERS_JS, RENDERER_JS, TOOLBAR_JS):
            line_count = len(path.read_text(encoding="utf-8").splitlines())
            self.assertLess(line_count, 350, f"{path.name} has {line_count} lines (>= 350L)")

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_scrubber_delegates_palettes_and_dpr_to_unified_overlay(self) -> None:
        script = _vm_preamble([UNIFIED_JS, RENDERER_JS, SCRUBBER_JS, LAYERS_JS]) + (
            "win.ScrubberOverlay.setLayer('r1', { label: 'Run 1', color: win.UnifiedCanvasOverlay.PALETTES[0],\n"
            "  frameDetections: [{ time: 1.0, source_resolution: [1280, 720],\n"
            "    tracks: [{ track_id: 7, label: 'person', confidence: 0.9, dwell_time: 2.5, bbox: [100, 100, 80, 120] }] }] });\n"
            "process.stdout.write(JSON.stringify({\n"
            "  palettesMatch: win.ScrubberOverlayRenderer.PALETTES === win.UnifiedCanvasOverlay.PALETTES,\n"
            "  layersPalettesMatch: win.OverlayLayers.PALETTES === win.UnifiedCanvasOverlay.PALETTES,\n"
            "  canvasW: canvas.width, canvasH: canvas.height,\n"
            "  styleW: canvas.style.width, styleH: canvas.style.height,\n"
            "  setTransformCalled: calls.some(c => c[0] === 'setTransform' && c[1] === 2),\n"
            "  labelsDrawn: calls.filter(c => c[0] === 'fillText').map(c => c[1]),\n"
            "}));\n"
        )
        out = _run_node(script)
        self.assertTrue(out["palettesMatch"])
        self.assertTrue(out["layersPalettesMatch"])
        self.assertEqual(out["canvasW"], 1600)
        self.assertEqual(out["canvasH"], 900)
        self.assertEqual(out["styleW"], "800px")
        self.assertEqual(out["styleH"], "450px")
        self.assertTrue(out["setTransformCalled"])
        self.assertTrue(any("#7" in txt and "2.5s" in txt for txt in out["labelsDrawn"]))

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_feature_visibility_toggles_filter_scrubber_vectors(self) -> None:
        script = _vm_preamble([UNIFIED_JS, RENDERER_JS, SCRUBBER_JS]) + (
            "const frame = { time: 1.0, source_resolution: [1280, 720],\n"
            "  tracks: [{ track_id: 4, label: 'car', confidence: 0.85, dwell_time: 3.0,\n"
            "    bbox: [50, 60, 100, 80], velocity: [20, 0] }],\n"
            "  zones: [{ name: 'Entry', polygon: [[0, 0], [100, 0], [100, 100]], is_breached: true }],\n"
            "  tripwires: [{ name: 'Gate', line: [[10, 10], [200, 10]], in_count: 1, out_count: 0 }] };\n"
            "win.ScrubberOverlay.setLayer('r1', { label: 'Run 1', frameDetections: [frame] });\n"
            "const countAll = { strokes: calls.filter(c => c[0] === 'strokeRect').length,\n"
            "  texts: calls.filter(c => c[0] === 'fillText').map(c => c[1]),\n"
            "  lines: calls.filter(c => c[0] === 'lineTo').length };\n"
            "win.ScrubberOverlay.setFeatureVisibility('bboxes', false);\n"
            "win.ScrubberOverlay.setFeatureVisibility('track_ids', false);\n"
            "win.ScrubberOverlay.setFeatureVisibility('dwell_timers', false);\n"
            "win.ScrubberOverlay.setFeatureVisibility('zones', false);\n"
            "win.ScrubberOverlay.setFeatureVisibility('tripwires', false);\n"
            "calls.length = 0;\n"
            "win.ScrubberOverlay.setFeatureVisibility('velocity', true);\n"
            "const countFiltered = { strokes: calls.filter(c => c[0] === 'strokeRect').length,\n"
            "  texts: calls.filter(c => c[0] === 'fillText').map(c => c[1]),\n"
            "  lines: calls.filter(c => c[0] === 'lineTo').length,\n"
            "  vis: win.ScrubberOverlay.getFeatureVisibility() };\n"
            "process.stdout.write(JSON.stringify({ countAll, countFiltered }));\n"
        )
        out = _run_node(script)
        self.assertEqual(out["countAll"]["strokes"], 1)
        self.assertTrue(any("#4" in t and "3.0s" in t for t in out["countAll"]["texts"]))
        self.assertGreater(out["countAll"]["lines"], 0)
        self.assertEqual(out["countFiltered"]["strokes"], 0)
        self.assertEqual(out["countFiltered"]["texts"], [])
        self.assertGreater(out["countFiltered"]["lines"], 0)
        self.assertTrue(out["countFiltered"]["vis"]["velocity"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_toolbar_renders_all_six_feature_pills_and_toggles_state(self) -> None:
        script = _vm_preamble([UNIFIED_JS, RENDERER_JS, SCRUBBER_JS, TOOLBAR_JS]) + (
            "const toggled = [];\n"
            "win.OverlayLayerToolbar.renderToolbar({\n"
            "  descriptors: [{ runId: 'r1', runNum: 1, label: 'Run 1', title: 'R1', palette: win.UnifiedCanvasOverlay.PALETTES[0] }],\n"
            "  activeRunIds: new Set(['r1']), hasLiveJob: false,\n"
            "  onToggleFeature: (k, v) => toggled.push([k, v]),\n"
            "});\n"
            "process.stdout.write(JSON.stringify({\n"
            "  html: toolbarEl.innerHTML,\n"
            "  keys: win.OverlayLayerToolbar.FEATURE_TOGGLES.map(f => f.key),\n"
            "  labels: win.OverlayLayerToolbar.FEATURE_TOGGLES.map(f => f.label),\n"
            "}));\n"
        )
        out = _run_node(script)
        self.assertEqual(out["keys"], ["bboxes", "track_ids", "dwell_timers", "velocity", "zones", "tripwires"])
        self.assertEqual(out["labels"], ["BBoxes", "IDs", "Dwell", "Velocity", "Zones", "Tripwires"])
        for key in out["keys"]:
            self.assertIn(f'data-feature-key="{key}"', out["html"])


if __name__ == "__main__":
    unittest.main()
