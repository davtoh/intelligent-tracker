"""Node VM unit tests for CameraGrid teardown, pagination, and 4-socket MJPEG budget."""

import json
from pathlib import Path
import shutil
import subprocess
import unittest

STATIC_JS = Path(__file__).resolve().parents[1] / "dashboard" / "static" / "js"
GRID_PAGINATION_JS = STATIC_JS / "grid_pagination.js"
CAMERA_GRID_JS = STATIC_JS / "camera_grid.js"


def _run_node(script: str) -> dict:
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(proc.stdout)


def _grid_vm_harness() -> str:
    return (
        "const fs = require('fs'), vm = require('vm');\n"
        f"const gpCode = fs.readFileSync({json.dumps(str(GRID_PAGINATION_JS))}, 'utf8');\n"
        f"const cgCode = fs.readFileSync({json.dumps(str(CAMERA_GRID_JS))}, 'utf8');\n"
        "const events = [];\n"
        "let gridHtml = '';\n"
        "const multiGrid = {\n"
        "  style: {}, className: '',\n"
        "  get innerHTML() { return gridHtml; },\n"
        "  set innerHTML(v) { events.push('innerHTML:' + (v ? 'set' : 'clear')); gridHtml = v; },\n"
        "  querySelectorAll: (sel) => (sel === 'img' && gridHtml.includes('<img') ? [{ src: '/stream/x' }] : []),\n"
        "};\n"
        "const liveImg = { src: '/stream/cam_01?annotated=false' };\n"
        "const bar = { hidden: true };\n"
        "const indicator = { textContent: '' };\n"
        "const prevBtn = { disabled: false, dataset: {}, addEventListener: () => {} };\n"
        "const nextBtn = { disabled: false, dataset: {}, addEventListener: () => {} };\n"
        "const elems = {\n"
        "  'multi-grid-container': multiGrid, 'video-wrapper': { style: {} },\n"
        "  'live-stream-img': liveImg, 'grid-pagination-bar': bar,\n"
        "  'grid-page-indicator': indicator, 'btn-grid-prev': prevBtn, 'btn-grid-next': nextBtn,\n"
        "};\n"
        "const doc = { getElementById: (id) => elems[id] || null, querySelectorAll: () => [] };\n"
        "const win = {\n"
        "  dispatchEvent: () => {},\n"
        "  LivePlayer: {\n"
        "    detachGridStreams: () => events.push('detachGridStreams'),\n"
        "    detachLiveStream: () => events.push('detachLiveStream'),\n"
        "    attachLiveStream: () => events.push('attachLiveStream'),\n"
        "  },\n"
        "  MjpegReconnect: { attach: () => {}, detachAll: () => events.push('detachAll') },\n"
        "};\n"
        "const sb = { window: win, document: doc, Event: function(t){ this.type = t; }, encodeURIComponent, Math, Number, String, Array, Object, console };\n"
        "vm.runInNewContext(gpCode, sb);\n"
        "vm.runInNewContext(cgCode, sb);\n"
    )


@unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
class TestCameraGridTeardownAndBudget(unittest.TestCase):
    """Verify detachGridStreams precedes innerHTML clear and MJPEG budget is capped at 4."""

    def test_detach_grid_streams_runs_before_innerhtml_teardown(self) -> None:
        script = _grid_vm_harness() + (
            "const cams = [{ id: 'c1', name: 'A', status: 'online' }, { id: 'c2', name: 'B', status: 'online' }];\n"
            "win.CameraGrid.setGridMode('2x2', cams, 'c1', () => {});\n"
            "win.CameraGrid.setGridMode('1x1', cams, 'c1', () => {});\n"
            "process.stdout.write(JSON.stringify({ events }));\n"
        )
        out = _run_node(script)
        ev = out["events"]
        clear_idx = len(ev) - 1 - ev[::-1].index("innerHTML:clear")
        detach_idx = len(ev) - 1 - ev[::-1].index("detachGridStreams")
        self.assertLess(detach_idx, clear_idx)

    def test_3x3_caps_mjpeg_to_4_and_renders_standby_posters(self) -> None:
        script = _grid_vm_harness() + (
            "const cams = Array.from({ length: 6 }, (_, i) => ({ id: 'c' + i, name: 'Cam ' + i, status: 'online' }));\n"
            "win.CameraGrid.setGridMode('3x3', cams, 'c0', () => {});\n"
            "const imgCount = (gridHtml.match(/<img /g) || []).length;\n"
            "const standbyCount = (gridHtml.match(/tile-standby-poster/g) || []).length;\n"
            "const viewBtnCount = (gridHtml.match(/btn-tile-view/g) || []).length;\n"
            "process.stdout.write(JSON.stringify({ imgCount, standbyCount, viewBtnCount, indicator: indicator.textContent, barHidden: bar.hidden }));\n"
        )
        out = _run_node(script)
        self.assertEqual(out["imgCount"], 4)
        self.assertEqual(out["standbyCount"], 2)
        self.assertEqual(out["viewBtnCount"], 2)
        self.assertEqual(out["indicator"], "Page 1 of 1")
        self.assertFalse(out["barHidden"])

    def test_4x4_layout_class_and_2x2_pagination(self) -> None:
        script = _grid_vm_harness() + (
            "const cams = Array.from({ length: 6 }, (_, i) => ({ id: 'c' + i, name: 'Cam ' + i, status: 'online' }));\n"
            "win.CameraGrid.setGridMode('4x4', cams, 'c0', () => {});\n"
            "const cls4 = multiGrid.className;\n"
            "win.CameraGrid.setGridMode('2x2', cams, 'c0', () => {});\n"
            "const p1Tiles = (gridHtml.match(/camera-grid-tile/g) || []).length;\n"
            "process.stdout.write(JSON.stringify({ cls4, p1Tiles, indicator: indicator.textContent }));\n"
        )
        out = _run_node(script)
        self.assertIn("grid-4x4", out["cls4"])
        self.assertEqual(out["p1Tiles"], 4)
        self.assertEqual(out["indicator"], "Page 1 of 2")
