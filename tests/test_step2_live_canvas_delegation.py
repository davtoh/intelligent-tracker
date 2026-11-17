#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit/VM tests for Step 2 Milestone 3: #live client-side canvas delegation & un-burned streaming."""

import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LIVE_HTML = REPO_ROOT / "dashboard" / "static" / "partials" / "tabs" / "live.html"
UNIFIED_JS = REPO_ROOT / "dashboard" / "static" / "js" / "unified_canvas_overlay.js"
INTERACTIVE_JS = REPO_ROOT / "dashboard" / "static" / "js" / "interactive_canvas.js"
CAMERA_GRID_JS = REPO_ROOT / "dashboard" / "static" / "js" / "camera_grid.js"
LIVE_PLAYER_JS = REPO_ROOT / "dashboard" / "static" / "js" / "live_player.js"
AI_CONFIG_JS = REPO_ROOT / "dashboard" / "static" / "js" / "camera_ai_config.js"


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


def _load_interactive_vm(toggle_states: dict | None = None) -> str:
    """Build Node VM preamble loading UnifiedCanvasOverlay + InteractiveCanvas."""
    toggles_json = json.dumps(toggle_states or {})
    return (
        "const fs = require('fs'), vm = require('vm');\n"
        f"const uCode = fs.readFileSync({json.dumps(str(UNIFIED_JS))}, 'utf8');\n"
        f"const iCode = fs.readFileSync({json.dumps(str(INTERACTIVE_JS))}, 'utf8');\n"
        f"const toggles = {toggles_json};\n"
        "const elements = {\n"
        "  'track-tooltip': { style: {} },\n"
        "  'tooltip-title': { textContent: '' },\n"
        "  'tooltip-body': { textContent: '' },\n"
        "};\n"
        "Object.keys(toggles).forEach(k => { elements['overlay-toggle-' + k] = { checked: toggles[k] }; });\n"
        "const doc = { getElementById: (id) => elements[id] || null, querySelectorAll: () => [] };\n"
        "const win = { devicePixelRatio: 2 };\n"
        "const sb = { window: win, document: doc, Math, Number, Array, Object, String, Boolean, JSON, parseFloat, parseInt, console };\n"
        "sb.globalThis = sb;\n"
        "vm.runInNewContext(uCode, sb);\n"
        "vm.runInNewContext(iCode, sb);\n"
    )


class TestLiveCanvasDelegation(unittest.TestCase):
    """Verify #live un-burned stream URLs and InteractiveCanvas -> UnifiedCanvasOverlay delegation."""

    def test_live_html_uses_unburned_primary_stream(self) -> None:
        html = LIVE_HTML.read_text(encoding="utf-8")
        match = re.search(r'<img[^>]*id="live-stream-img"[^>]*src="([^"]+)"', html)
        self.assertIsNotNone(match, "Missing #live-stream-img src in live.html")
        self.assertEqual(match.group(1), "/stream/cam_01?annotated=false")

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_camera_grid_focus_vs_multigrid_stream_urls(self) -> None:
        script = (
            "const fs = require('fs'), vm = require('vm');\n"
            f"const code = fs.readFileSync({json.dumps(str(CAMERA_GRID_JS))}, 'utf8');\n"
            "const liveImg = { src: '' };\n"
            "const multiGrid = { style: {}, innerHTML: '', className: '', querySelectorAll: () => [] };\n"
            "const singleWrap = { style: {} };\n"
            "const elems = { 'live-stream-img': liveImg, 'multi-grid-container': multiGrid, 'video-wrapper': singleWrap };\n"
            "const doc = { getElementById: (id) => elems[id] || null, querySelectorAll: () => [] };\n"
            "const win = { dispatchEvent: () => {} };\n"
            "const sb = { window: win, document: doc, Event: function(t){ this.type = t; }, encodeURIComponent, String, Array, console };\n"
            "vm.runInNewContext(code, sb);\n"
            "const cams = [{ id: 'cam_01', name: 'Gate', status: 'online', fps: 30 }, { id: 'cam_02', name: 'Dock', status: 'online', fps: 25 }];\n"
            "win.CameraGrid.setGridMode('2x2', cams, 'cam_01', () => {});\n"
            "const gridHtml = multiGrid.innerHTML;\n"
            "win.CameraGrid.focusCamera('cam_02', cams, () => {});\n"
            "process.stdout.write(JSON.stringify({ gridHtml, focusedSrc: liveImg.src }));\n"
        )
        out = _run_node(script)
        self.assertIn("/stream/cam_01?annotated=true", out["gridHtml"])
        self.assertIn("/stream/cam_02?annotated=true", out["gridHtml"])
        self.assertEqual(out["focusedSrc"], "/stream/cam_02?annotated=false")

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_live_player_and_ai_config_preserve_annotated_false(self) -> None:
        script = (
            "const fs = require('fs'), vm = require('vm');\n"
            f"const lpCode = fs.readFileSync({json.dumps(str(LIVE_PLAYER_JS))}, 'utf8');\n"
            f"const aiCode = fs.readFileSync({json.dumps(str(AI_CONFIG_JS))}, 'utf8');\n"
            "const img = { src: '/stream/cam_01?annotated=false', dataset: {} };\n"
            "const doc = { getElementById: (id) => (id === 'live-stream-img' ? img : null), querySelectorAll: () => [], addEventListener: () => {} };\n"
            "const win = {};\n"
            "const sb = { window: win, document: doc, Date, encodeURIComponent, String, Array, clearTimeout, setTimeout, console };\n"
            "vm.runInNewContext(lpCode, sb);\n"
            "vm.runInNewContext(aiCode, sb);\n"
            "win.LivePlayer.detachLiveStream(img);\n"
            "win.LivePlayer.attachLiveStream(img, 'cam_01', true);\n"
            "const reconnectedSrc = img.src;\n"
            "win.CameraAIConfig.resolveInitialCameraId([{ id: 'cam_07', name: 'Lobby', enabled: true }], 'cam_01');\n"
            "process.stdout.write(JSON.stringify({ reconnectedSrc, resolvedSrc: img.src }));\n"
        )
        out = _run_node(script)
        self.assertTrue(out["reconnectedSrc"].startswith("/stream/cam_01?annotated=false&t="))
        self.assertEqual(out["resolvedSrc"], "/stream/cam_07?annotated=false")

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_interactive_canvas_hidpi_sync_and_render_delegation(self) -> None:
        preamble = _load_interactive_vm({"bboxes": True, "track_ids": True, "velocity": True, "heatmap": True})
        body = (
            "const calls = [];\n"
            "const noop = (n) => (...a) => calls.push([n, ...a]);\n"
            "const ctx = { canvas: { width: 0, height: 0 }, save: noop('save'), restore: noop('restore'),\n"
            "  clearRect: noop('clearRect'), fillRect: noop('fillRect'), strokeRect: noop('strokeRect'),\n"
            "  fillText: noop('fillText'), setTransform: noop('setTransform'), beginPath: noop('beginPath'),\n"
            "  closePath: noop('closePath'), moveTo: noop('moveTo'), lineTo: noop('lineTo'),\n"
            "  stroke: noop('stroke'), fill: noop('fill'), setLineDash: noop('setLineDash'),\n"
            "  measureText: (t) => ({ width: String(t).length * 6 }) };\n"
            "const canvas = { width: 0, height: 0, style: {}, getContext: () => ctx };\n"
            "const videoImg = { clientWidth: 640, clientHeight: 480, naturalWidth: 1280, naturalHeight: 720, offsetLeft: 0, offsetTop: 0 };\n"
            "win.InteractiveCanvas.syncSize(videoImg, canvas);\n"
            "const tracks = [{ id: 5, bbox: [100, 100, 200, 200], confidence: 0.9, dwell_time: 2.0, velocity: [12, 0], state: 'active' }];\n"
            "win.InteractiveCanvas.drawOverlay(ctx, canvas, videoImg, tracks, tracks[0], {\n"
            "  zones: [{ name: 'Z1', polygon: [[0, 0], [100, 0], [100, 100]], is_breached: false }],\n"
            "  tripwires: [{ name: 'T1', line: [[10, 10], [200, 10]], in_count: 1, out_count: 0 }],\n"
            "  heatmap: { grid: [[5, 0], [0, 1]], max: 5 },\n"
            "});\n"
            "const hovered = win.InteractiveCanvas.findHoveredTrack(100, 100, canvas, videoImg, tracks);\n"
            "win.InteractiveCanvas.updateTooltip(hovered, canvas, videoImg);\n"
            "process.stdout.write(JSON.stringify({ w: canvas.width, h: canvas.height, sw: canvas.style.width, sh: canvas.style.height,\n"
            "  hoveredId: hovered ? hovered.id : null, tooltipLeft: elements['track-tooltip'].style.left,\n"
            "  strokeCount: calls.filter(c => c[0] === 'strokeRect').length, textCalls: calls.filter(c => c[0] === 'fillText').map(c => c[1]) }));\n"
        )
        out = _run_node(preamble + body)
        self.assertEqual(out["w"], 1280)
        self.assertEqual(out["h"], 720)
        self.assertEqual(out["sw"], "640px")
        self.assertEqual(out["sh"], "360px")
        self.assertEqual(out["hoveredId"], 5)
        self.assertGreaterEqual(out["strokeCount"], 1)
        self.assertIn("Z1", out["textCalls"])
        self.assertIn("T1 1/0", out["textCalls"])


if __name__ == "__main__":
    unittest.main()
