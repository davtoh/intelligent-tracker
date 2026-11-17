#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit/VM tests for Step 2 Milestone 2: UnifiedCanvasOverlay client engine."""

import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINE_PATH = REPO_ROOT / "dashboard" / "static" / "js" / "unified_canvas_overlay.js"
INDEX_HTML_PATH = REPO_ROOT / "dashboard" / "static" / "index.html"


_NODE_CTX_PREAMBLE = """
function makeMockCtx() {
  const calls = [];
  const noop = (name) => (...a) => calls.push([name, ...a]);
  return {
    calls,
    canvas: { width: 800, height: 600 },
    save: noop('save'), restore: noop('restore'), clearRect: noop('clearRect'),
    fillRect: noop('fillRect'), strokeRect: noop('strokeRect'), fillText: noop('fillText'),
    setTransform: noop('setTransform'), beginPath: noop('beginPath'), closePath: noop('closePath'),
    moveTo: noop('moveTo'), lineTo: noop('lineTo'), stroke: noop('stroke'), fill: noop('fill'),
    setLineDash: noop('setLineDash'),
    measureText: (t) => ({ width: String(t).length * 6 }),
  };
}
"""


def _make_node_runner(body: str) -> dict:
    """Execute a JS snippet with unified_canvas_overlay.js loaded in a Node VM."""
    script = (
        "const fs = require('fs'), vm = require('vm');\n"
        f"const code = fs.readFileSync({json.dumps(str(ENGINE_PATH))}, 'utf8');\n"
        "const windowObj = { devicePixelRatio: 2 };\n"
        "const sandbox = { window: windowObj, Math, Number, Array, Object, String, Boolean, JSON, console };\n"
        "sandbox.globalThis = sandbox;\n"
        "vm.runInNewContext(code, sandbox);\n"
        "const U = windowObj.UnifiedCanvasOverlay;\n"
        + _NODE_CTX_PREAMBLE
        + f"\nconst result = (function() {{\n{body}\n}})();\n"
        + "process.stdout.write(JSON.stringify(result));\n"
    )
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, env=dict(os.environ), timeout=15)
    if proc.returncode != 0:
        raise AssertionError(f"Node VM failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}")
    return json.loads(proc.stdout)


class TestUnifiedCanvasOverlayEngine(unittest.TestCase):
    """Verify UnifiedCanvasOverlay geometry, HiDPI DPR, and scene rendering."""

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_compute_contain_box_pillarbox_and_letterbox(self) -> None:
        out = _make_node_runner("""
const pillar = U.computeContainBox(
  { left: 10, top: 20, width: 1600, height: 600 },
  { left: 10, top: 20 },
  1280,
  720
);
const letter = U.computeContainBox(
  { left: 0, top: 0, width: 800, height: 800 },
  null,
  1280,
  720
);
return { pillar, letter };
""")
        pillar = out["pillar"]
        self.assertAlmostEqual(pillar["renderH"], 600.0, places=2)
        self.assertAlmostEqual(pillar["renderW"], 600.0 * (1280.0 / 720.0), places=2)
        self.assertGreater(pillar["offsetX"], 0.0)
        self.assertAlmostEqual(pillar["offsetY"], 0.0, places=2)

        letter = out["letter"]
        self.assertAlmostEqual(letter["renderW"], 800.0, places=2)
        self.assertAlmostEqual(letter["renderH"], 800.0 / (1280.0 / 720.0), places=2)
        self.assertAlmostEqual(letter["offsetX"], 0.0, places=2)
        self.assertGreater(letter["offsetY"], 0.0)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_sync_canvas_dpr_and_scale_factors(self) -> None:
        out = _make_node_runner("""
const ctx = makeMockCtx();
const canvas = { width: 0, height: 0, style: {} };
const usedDpr = U.syncCanvasDpr(canvas, ctx, 640, 360);
const scales = U.resolveScaleFactors(640, 360, [1280, 720], 640, 360);
return {
  usedDpr,
  width: canvas.width,
  height: canvas.height,
  styleWidth: canvas.style.width,
  styleHeight: canvas.style.height,
  transformCalls: ctx.calls.filter(c => c[0] === 'setTransform'),
  scales,
};
""")
        self.assertEqual(out["usedDpr"], 2)
        self.assertEqual(out["width"], 1280)
        self.assertEqual(out["height"], 720)
        self.assertEqual(out["styleWidth"], "640px")
        self.assertEqual(out["styleHeight"], "360px")
        self.assertEqual(out["transformCalls"], [["setTransform", 2, 0, 0, 2, 0, 0]])
        self.assertAlmostEqual(out["scales"]["scaleX"], 0.5, places=4)
        self.assertAlmostEqual(out["scales"]["scaleY"], 0.5, places=4)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_render_scene_draws_all_primitives(self) -> None:
        out = _make_node_runner("""
const ctx = makeMockCtx();
U.renderScene(ctx, {
  clearWidth: 800, clearHeight: 600,
  transform: { offsetX: 0, offsetY: 0, scaleX: 1, scaleY: 1, renderW: 800, renderH: 600 },
  visibility: { bboxes: true, track_ids: true, dwell_timers: true, velocity: true, zones: true, tripwires: true, heatmap: true },
  heatmap: { grid: [[0, 0.8], [0.5, 0]], max: 1.0 },
  zones: [{ name: 'Lobby', occupancy: 2, is_breached: true, polygon: [[10, 10], [100, 10], [100, 100]] }],
  tripwires: [{ name: 'Gate', in_count: 3, out_count: 1, line: [[20, 200], [300, 200]] }],
  tracks: [{ id: 7, bbox: [50, 60, 40, 80], velocity: [10, -5], confidence: 0.91, dwell_time: 4.2, entity_name: 'Alice' }],
  hoveredTrack: { id: 7 },
});
return {
  ops: ctx.calls.map(c => c[0]),
  texts: ctx.calls.filter(c => c[0] === 'fillText').map(c => c[1]),
};
""")
        for op in ("clearRect", "strokeRect", "fillRect", "setLineDash"):
            self.assertIn(op, out["ops"])
        self.assertTrue(any("Alice" in t and "#7" in t and "4.2s" in t for t in out["texts"]))
        self.assertTrue(any("Lobby (2)" in t for t in out["texts"]))
        self.assertTrue(any("Gate 3/1" in t for t in out["texts"]))

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_render_scene_respects_visibility_toggles(self) -> None:
        out = _make_node_runner("""
const ctx = makeMockCtx();
U.renderScene(ctx, {
  clearWidth: 800, clearHeight: 600,
  transform: { offsetX: 0, offsetY: 0, scaleX: 1, scaleY: 1, renderW: 800, renderH: 600 },
  visibility: { bboxes: false, track_ids: false, dwell_timers: false, velocity: false, zones: false, tripwires: false, heatmap: false },
  heatmap: { grid: [[0.9]], max: 1.0 },
  zones: [{ name: 'Lobby', polygon: [[10, 10], [100, 10], [100, 100]] }],
  tripwires: [{ name: 'Gate', line: [[20, 200], [300, 200]] }],
  tracks: [{ id: 7, bbox: [50, 60, 40, 80], velocity: [10, -5] }],
});
return { ops: ctx.calls.map(c => c[0]) };
""")
        self.assertEqual(out["ops"], ["clearRect"])

    def test_index_html_loads_unified_overlay_before_interactive_canvas(self) -> None:
        html = INDEX_HTML_PATH.read_text(encoding="utf-8")
        unified_pos = html.find('/static/js/unified_canvas_overlay.js')
        interactive_pos = html.find('/static/js/interactive_canvas.js')
        self.assertNotEqual(unified_pos, -1)
        self.assertNotEqual(interactive_pos, -1)
        self.assertLess(unified_pos, interactive_pos)

    def test_modularity_line_and_function_budgets(self) -> None:
        lines = ENGINE_PATH.read_text(encoding="utf-8").splitlines()
        self.assertLess(len(lines), 280, f"unified_canvas_overlay.js is {len(lines)} lines (>= 280)")

        fn_starts = [
            (i, m.group(1))
            for i, line in enumerate(lines, start=1)
            if (m := re.match(r"^\s*function\s+([A-Za-z0-9_]+)\s*\(", line))
        ]
        self.assertGreaterEqual(len(fn_starts), 8)
        for idx, (start_line, fn_name) in enumerate(fn_starts):
            end_line = fn_starts[idx + 1][0] - 1 if idx + 1 < len(fn_starts) else len(lines)
            span = end_line - start_line + 1
            self.assertLessEqual(span, 35, f"{fn_name} spans {span} lines (> 35)")


if __name__ == "__main__":
    unittest.main()
