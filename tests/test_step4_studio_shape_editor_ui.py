"""Milestone 2 UI tests: #studio interactive shape editor & video scenario re-eval."""

import json
import pathlib
import shutil
import subprocess
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "dashboard" / "static"
SHAPE_EDITOR_JS = STATIC_DIR / "js" / "studio_shape_editor.js"
STUDIO_OVERLAYS_JS = STATIC_DIR / "js" / "studio_overlays.js"
REPORTS_JS = STATIC_DIR / "js" / "video_batch_reports.js"


def _run_node_vm(script: str) -> dict:
    if not shutil.which("node"):
        raise unittest.SkipTest("Node.js not installed")
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise AssertionError(f"Node VM failed:\n{proc.stderr}\n{proc.stdout}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _shape_editor_prelude(fetch_js: str) -> str:
    return f"""
const fs = require('fs'), vm = require('vm');
const calls = [], renders = [], toasts = [], statuses = [];
const state = {{
  activeCamera: 'cam_01', mode: 'idle',
  zones: [{{ name: 'vault', polygon: [[10, 10], [100, 10], [100, 100], [10, 100]], color: [0, 255, 0], dwell_threshold: 2 }}],
  tripwires: [{{ name: 'gate', line_segment: [[200, 50], [300, 50]], color: [255, 255, 0], bidirectional: true }}],
}};
const winListeners = {{}};
const sb = {{
  console, Math, encodeURIComponent,
  fetch: {fetch_js},
  addEventListener: (ev, fn) => {{ (winListeners[ev] = winListeners[ev] || []).push(fn); }},
  StudioOverlays: {{ renderScenarioListUI: () => renders.push('list') }},
}};
sb.window = sb;
vm.createContext(sb);
vm.runInContext(fs.readFileSync({json.dumps(str(SHAPE_EDITOR_JS))}, 'utf8'), sb);
sb.window.StudioShapeEditor.init(() => state, {{
  drawOverlay: () => renders.push('draw'),
  updateStatus: (m) => statuses.push(m),
  showToast: (t, b, kind) => toasts.push({{ t, b, kind }}),
}});
"""


class TestStep4StudioShapeEditorUI(unittest.TestCase):
    """Verify Milestone 2 studio shape editor, re-eval UI, and file budgets."""

    def test_index_html_and_studio_module_budgets(self) -> None:
        budgets = {
            STATIC_DIR / "index.html": 179,
            SHAPE_EDITOR_JS: 300,
            STATIC_DIR / "js" / "studio_canvas.js": 260,
            STUDIO_OVERLAYS_JS: 250,
            STATIC_DIR / "studio.js": 349,
            REPORTS_JS: 348,
        }
        for path, cap in budgets.items():
            lines = len(path.read_text(encoding="utf-8").splitlines())
            self.assertLessEqual(lines, cap, f"{path.name} is {lines}L > {cap}L")
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn('partials/scripts_studio.html', html)
        self.assertLess(html.index('/static/app.js'), html.index('/static/js/nav_tabs_manager.js'))
        partial = (STATIC_DIR / "partials" / "scripts_studio.html").read_text(encoding="utf-8")
        self.assertLess(partial.index('studio_shape_editor.js'), partial.index('/static/studio.js'))

    def test_idle_hit_testing_and_vertex_drag_put(self) -> None:
        fetch_js = "async (url, opts) => { calls.push({ url, opts: JSON.parse(opts.body) }); return { ok: true, json: async () => ({}) }; }"
        script = _shape_editor_prelude(fetch_js) + """
(async () => {
  const ed = sb.window.StudioShapeEditor;
  const hitV = ed.hitTest({ x: 12, y: 12 });
  const hitS = ed.hitTest({ x: 50, y: 50 });
  const miss = ed.hitTest({ x: 400, y: 400 });
  ed.onMouseDown({ x: 10, y: 10 });
  ed.onMouseMove({ x: 25, y: 30 });
  await ed.onMouseUp({ x: 25, y: 30 });
  console.log(JSON.stringify({ hitV: hitV.kind, hitS: hitS.kind, miss, poly0: state.zones[0].polygon[0], calls }));
})();
"""
        out = _run_node_vm(script)
        self.assertEqual(out["hitV"], "vertex")
        self.assertEqual(out["hitS"], "shape")
        self.assertIsNone(out["miss"])
        self.assertEqual(out["poly0"], [25, 30])
        self.assertEqual(out["calls"][0]["url"], "/api/scenarios/zones/cam_01/vault")
        self.assertEqual(out["calls"][0]["opts"]["polygon"][0], [25, 30])

    def test_shape_move_put_and_escape_cancel(self) -> None:
        fetch_js = "async (url, opts) => { calls.push({ url, opts: JSON.parse(opts.body) }); return { ok: true, json: async () => ({}) }; }"
        script = _shape_editor_prelude(fetch_js) + """
(async () => {
  const ed = sb.window.StudioShapeEditor;
  ed.onMouseDown({ x: 50, y: 50 });
  ed.onMouseMove({ x: 70, y: 65 });
  (winListeners.keydown || []).forEach((fn) => fn({ key: 'Escape' }));
  const afterEsc = JSON.parse(JSON.stringify(state.zones[0].polygon));
  ed.onMouseDown({ x: 250, y: 50 });
  ed.onMouseMove({ x: 260, y: 70 });
  await ed.onMouseUp({ x: 260, y: 70 });
  console.log(JSON.stringify({ afterEsc, twSeg: state.tripwires[0].line_segment, calls }));
})();
"""
        out = _run_node_vm(script)
        self.assertEqual(out["afterEsc"], [[10, 10], [100, 10], [100, 100], [10, 100]])
        self.assertEqual(out["twSeg"], [[210, 70], [310, 70]])
        self.assertEqual(len(out["calls"]), 1)
        self.assertEqual(out["calls"][0]["url"], "/api/scenarios/tripwires/cam_01/gate")

    def test_rollback_on_failed_put_and_inline_rename(self) -> None:
        fetch_js = """async (url, opts) => {
          calls.push(url);
          if (url.includes('/zones/')) return { ok: false, status: 409, statusText: 'Conflict', json: async () => ({ detail: 'Name clash' }) };
          return { ok: true, json: async () => ({}) };
        }"""
        script = _shape_editor_prelude(fetch_js) + """
(async () => {
  const ed = sb.window.StudioShapeEditor;
  ed.onMouseDown({ x: 10, y: 10 });
  ed.onMouseMove({ x: 40, y: 40 });
  const dragOk = await ed.onMouseUp({ x: 40, y: 40 });
  const renameOk = await ed.renameShape('tripwire', 'cam_01', 'gate', 'gate_north');
  console.log(JSON.stringify({ dragOk, poly0: state.zones[0].polygon[0], renameOk, twName: state.tripwires[0].name, toasts }));
})();
"""
        out = _run_node_vm(script)
        self.assertFalse(out["dragOk"])
        self.assertEqual(out["poly0"], [10, 10])
        self.assertTrue(out["renameOk"])
        self.assertEqual(out["twName"], "gate_north")
        self.assertEqual(out["toasts"][0]["kind"], "error")

    def test_reeval_report_button_and_refresh(self) -> None:
        script = f"""
const fs = require('fs'), vm = require('vm');
const calls = [], synced = [];
const container = {{ innerHTML: '', style: {{}}, querySelector: () => null }};
const runs = [{{ run_id: 'r1', config: {{ detector: 'yolov8', sample_rate: 1, confidence: 0.4 }}, report: {{ frames_processed: 5 }} }}];
const sb = {{
  console, encodeURIComponent,
  localStorage: {{ getItem: () => null, setItem: () => {{}} }},
  OverlayLayers: {{ syncRuns: (fn, r, opts) => synced.push({{ fn, count: r.length, opts }}) }},
  document: {{ getElementById: (id) => id === 'video-batch-report-container' ? container : null }},
  fetch: async (url, opts) => {{
    calls.push({{ url, method: opts?.method || 'GET' }});
    return {{ ok: true, json: async () => (opts?.method === 'POST' ? {{ status: 'ok' }} : runs) }};
  }},
}};
sb.window = sb;
vm.createContext(sb);
vm.runInContext(fs.readFileSync({json.dumps(str(REPORTS_JS))}, 'utf8'), sb);
(async () => {{
  const html = sb.window.VideoBatchReports.renderReportCards(runs[0].report, 'clip.mp4', {{}}, runs, 'r1');
  const ok = await sb.window.VideoBatchReports.reevaluateReportRun('clip.mp4', 'r1');
  console.log(JSON.stringify({{ hasBtn: html.includes('id="btn-reeval-report-run"'), ok, calls, synced }}));
}})();
"""
        out = _run_node_vm(script)
        self.assertTrue(out["hasBtn"])
        self.assertTrue(out["ok"])
        self.assertEqual(out["calls"][0], {"url": "/api/videos/re-evaluate-scenarios", "method": "POST"})
        self.assertEqual(out["calls"][1]["url"], "/api/videos/clip.mp4/reports")
        self.assertEqual(out["synced"][0]["opts"], {"force": True})
