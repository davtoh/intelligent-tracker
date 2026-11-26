"""Milestone 3 UI tests: Studio BEV quad overlay, UnifiedCanvasOverlay reuse, and minimap zoom/pan/BEV toggle."""

import json
import pathlib
import re
import shutil
import subprocess
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "dashboard" / "static"
JS_DIR = STATIC_DIR / "js"

_VM_PRELUDE = """
const fs = require('fs'), vm = require('vm');
const byId = new Map(), ctxCalls = [], winListeners = {}, docListeners = {};
function makeEl(id, tag = 'div', extra = {}) {
  const attrs = new Map(), listeners = {}, classes = new Set();
  const el = Object.assign({
    id, tagName: tag.toUpperCase(), style: {}, dataset: {}, value: '', textContent: '', innerHTML: '',
    disabled: false, hidden: false, width: 640, height: 480, options: [], selectedOptions: [], children: [],
    classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c), contains: (c) => classes.has(c), toggle: (c, v) => (v ? classes.add(c) : classes.delete(c)) },
    setAttribute: (k, v) => attrs.set(k, String(v)),
    getAttribute: (k) => (attrs.has(k) ? attrs.get(k) : null),
    removeAttribute: (k) => attrs.delete(k),
    addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
    dispatchEvent: (ev) => { (listeners[ev.type] || []).forEach((fn) => fn(ev)); },
    click: () => { (listeners.click || []).forEach((fn) => fn({ target: byId.get(id) })); },
    querySelectorAll: () => [],
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 640, height: 480 }),
    getContext: () => new Proxy({}, {
      get: (_t, prop) => (...args) => {
        ctxCalls.push([String(prop), ...args]);
        if (prop === 'measureText') return { width: String(args[0] || '').length * 6 };
        return undefined;
      },
    }),
    _listeners: listeners,
  }, extra);
  el.appendChild = (c) => { el.children.push(c); if (c.tagName === 'OPTGROUP') el.options.push(...c.children); else if (c.tagName === 'OPTION') el.options.push(c); return c; };
  return el;
}
const sb = {
  console, Math, Date, Number, Object, Array, Set, Map, JSON, encodeURIComponent,
  Event: function (t) { this.type = t; },
  setTimeout, clearTimeout, setInterval: () => 1, clearInterval: () => {},
  document: {
    getElementById: (id) => byId.get(id) || null,
    querySelectorAll: () => [],
    createElement: (tag) => makeEl('', tag),
    addEventListener: (ev, fn) => { (docListeners[ev] = docListeners[ev] || []).push(fn); },
  },
  addEventListener: (ev, fn) => { (winListeners[ev] = winListeners[ev] || []).push(fn); },
  fetch: async () => ({ ok: true, json: async () => ({}) }),
};
sb.window = sb;
vm.createContext(sb);
"""


def _run_node_vm(files: list[pathlib.Path], body_js: str) -> dict:
    if not shutil.which("node"):
        raise unittest.SkipTest("Node.js not installed")
    loads = "\n".join(
        f"vm.runInContext(fs.readFileSync({json.dumps(str(p))}, 'utf8'), sb);"
        for p in files
    )
    script = f"{_VM_PRELUDE}\n{loads}\n(async () => {{\n{body_js}\n}})().catch((e) => {{ console.error(e); process.exit(1); }});"
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", check=False)
    if proc.returncode != 0:
        raise AssertionError(f"Node VM failed:\n{proc.stderr}\n{proc.stdout}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


class TestStep4StudioUxAndMinimap(unittest.TestCase):
    """Verify M3 file budgets, BEV quad overlays, UnifiedCanvasOverlay reuse, and minimap controls."""

    def test_file_budgets_html_wiring_and_no_empty_catch(self) -> None:
        budgets = {
            JS_DIR / "studio_media.js": 145,
            JS_DIR / "studio_canvas.js": 245,
            STATIC_DIR / "studio.js": 349,
            JS_DIR / "world_minimap.js": 345,
            JS_DIR / "world_minimap_interactions.js": 255,
            STATIC_DIR / "partials" / "tabs" / "studio.html": 220,
            STATIC_DIR / "css" / "topology.css": 300,
        }
        for path, cap in budgets.items():
            lines = len(path.read_text(encoding="utf-8").splitlines())
            self.assertLessEqual(lines, cap, f"{path.name} is {lines}L > {cap}L")

        scripts_html = (STATIC_DIR / "partials" / "scripts_studio.html").read_text(encoding="utf-8")
        self.assertLess(scripts_html.index("studio_media.js"), scripts_html.index("studio_canvas.js"))

        studio_html = (STATIC_DIR / "partials" / "tabs" / "studio.html").read_text(encoding="utf-8")
        for el_id in (
            "btn-minimap-zoom-in",
            "btn-minimap-zoom-out",
            "btn-minimap-fit",
            "btn-minimap-view-toggle",
            "btn-studio-bev-quad-toggle",
            "studio-overlay-control-bar",
        ):
            self.assertIn(f'id="{el_id}"', studio_html)

        self.assertNotIn("!important", (STATIC_DIR / "css" / "topology.css").read_text(encoding="utf-8"))
        canvas_src = (JS_DIR / "studio_canvas.js").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"catch\s*(?:\([^)]*\))?\s*\{\s*\}", canvas_src))

    def test_saved_bev_quad_modes_and_post_calibration_redraw(self) -> None:
        body = """
        const canvas = makeEl('studio-drawing-canvas', 'canvas', { width: 640, height: 480 });
        const quadBtn = makeEl('btn-studio-bev-quad-toggle', 'button');
        byId.set('studio-drawing-canvas', canvas); byId.set('btn-studio-bev-quad-toggle', quadBtn);
        const homography = { src_points: [[10, 10], [200, 10], [220, 180], [20, 180]], metric_width: 8, metric_height: 6 };
        const textsAfter = (mode, saved) => {
          ctxCalls.length = 0;
          sb.StudioCanvas.drawOverlay(canvas.getContext('2d'), canvas, mode, [], null, saved);
          return ctxCalls.filter((c) => c[0] === 'fillText').map((c) => c[1]);
        };
        const allTexts = textsAfter('idle', { homography, bevQuadMode: 'all' });
        const selIdleTexts = textsAfter('idle', { homography, bevQuadMode: 'selected' });
        const selCalTexts = textsAfter('calibrate_homography', { homography, bevQuadMode: 'selected' });
        const offTexts = textsAfter('idle', { homography, bevQuadMode: 'off' });
        sb.fetch = async (u) => ({ ok: true, json: async () => (u.includes('/homography') ? { homography } : []) });
        sb.Studio.init();
        ctxCalls.length = 0;
        await sb.Studio.saveHomographyCalibration({ camera_id: 'cam_01', metric_width: 8, metric_height: 6, src_points: homography.src_points });
        const postSaveTexts = ctxCalls.filter((c) => c[0] === 'fillText').map((c) => c[1]);
        quadBtn.click(); const afterClick1 = sb.Studio.getBevQuadMode();
        quadBtn.click(); const afterClick2 = sb.Studio.getBevQuadMode();
        console.log(JSON.stringify({ allTexts, selIdleTexts, selCalTexts, offTexts, postSaveTexts, afterClick1, afterClick2 }));
        """
        files = [JS_DIR / "unified_canvas_overlay.js", JS_DIR / "studio_media.js", JS_DIR / "studio_canvas.js", STATIC_DIR / "studio.js"]
        out = _run_node_vm(files, body)
        self.assertTrue(any("BEV 8m" in t for t in out["allTexts"]))
        self.assertEqual(out["selIdleTexts"], [])
        self.assertTrue(any("1: TL" in t for t in out["selCalTexts"]))
        self.assertEqual(out["offTexts"], [])
        self.assertTrue(any("BEV 8m" in t for t in out["postSaveTexts"]))
        self.assertEqual((out["afterClick1"], out["afterClick2"]), ("selected", "off"))

    def test_studio_unified_overlay_tracks_and_control_bar(self) -> None:
        body = """
        const canvas = makeEl('studio-drawing-canvas', 'canvas', { width: 640, height: 480 });
        const bar = makeEl('studio-overlay-control-bar', 'div');
        const sel = makeEl('studio-camera-select', 'select', { value: 'cam_01' });
        byId.set('studio-drawing-canvas', canvas); byId.set('studio-overlay-control-bar', bar); byId.set('studio-camera-select', sel);
        sb.latestTelemetry = { camera_id: 'cam_01', active_tracks: [{ id: 7, entity_name: 'Alice', bbox: [50, 60, 80, 140], confidence: 0.91 }] };
        sb.fetch = async (url) => ({
          ok: true,
          json: async () => (url === '/api/cameras' ? [{ id: 'cam_01', name: 'Lobby' }]
            : url.includes('/api/scenarios/') ? { zones: [{ name: 'Vault', polygon: [[0, 0], [50, 0], [50, 50]] }], tripwires: [] }
            : []),
        });
        sb.Studio.init();
        await new Promise((r) => setTimeout(r, 0));
        await new Promise((r) => setTimeout(r, 0));
        ctxCalls.length = 0;
        sb.Studio.drawOverlay();
        const texts = ctxCalls.filter((c) => c[0] === 'fillText').map((c) => c[1]);
        const strokeRects = ctxCalls.filter((c) => c[0] === 'strokeRect').length;
        console.log(JSON.stringify({ barHasPills: bar.innerHTML.includes('overlay-feature-pill'), texts, strokeRects }));
        """
        files = [JS_DIR / "overlay_control_bar.js", JS_DIR / "unified_canvas_overlay.js", JS_DIR / "studio_media.js", JS_DIR / "studio_canvas.js", STATIC_DIR / "studio.js"]
        out = _run_node_vm(files, body)
        self.assertTrue(out["barHasPills"])
        self.assertGreaterEqual(out["strokeRects"], 1)
        self.assertTrue(any("Alice" in t for t in out["texts"]))
        self.assertTrue(any("Vault" in t for t in out["texts"]))

    def test_world_minimap_zoom_pan_and_fit(self) -> None:
        body = """
        const canvas = makeEl('bev-minimap-canvas', 'canvas', { width: 320, height: 320, getBoundingClientRect: () => ({ left: 0, top: 0, width: 320, height: 320 }) });
        const zoomIn = makeEl('btn-minimap-zoom-in', 'button'), zoomOut = makeEl('btn-minimap-zoom-out', 'button'), fitBtn = makeEl('btn-minimap-fit', 'button');
        [['bev-minimap-canvas', canvas], ['btn-minimap-zoom-in', zoomIn], ['btn-minimap-zoom-out', zoomOut], ['btn-minimap-fit', fitBtn]].forEach(([k, v]) => byId.set(k, v));
        const worldData = { bounds: [0, 0, 20, 20], zones: [], transitions: [], entities: [], cameras: [{ camera_id: 'cam_01', calibrated: true, world_pose: { origin_x: 5, origin_y: 5, yaw_deg: 0, fov_deg: 60, range_m: 4 } }] };
        sb.fetch = async () => ({ ok: true, json: async () => worldData });
        const view = sb.WorldTacticalMinimapView;
        const baseXY = view.toCanvasXY(10, 10, [0, 0, 20, 20], 320, 320, 20);
        sb.WorldMinimapInteractions.bind(() => 'cam_01');
        await view.fetchAndRender(canvas, 'cam_01', null, []);
        const [wx0, wy0] = view.toWorldXY(220, 180, [0, 0, 20, 20], 320, 320, 20);
        canvas._listeners.wheel[0]({ clientX: 220, clientY: 180, deltaY: -100, preventDefault: () => {} });
        const afterWheelZoom = view.getViewport().zoom;
        const [wx1, wy1] = view.toWorldXY(220, 180, [0, 0, 20, 20], 320, 320, 20);
        canvas._listeners.mousedown[0]({ clientX: 300, clientY: 300 });
        canvas._listeners.mousemove[0]({ clientX: 260, clientY: 270 });
        canvas._listeners.mouseup[0]({});
        const afterPan = view.getViewport();
        zoomIn.click(); const afterBtnZoomIn = view.getViewport().zoom;
        zoomOut.click(); fitBtn.click();
        console.log(JSON.stringify({ baseXY, wx0, wy0, wx1, wy1, afterWheelZoom, afterPan, afterBtnZoomIn, afterFit: view.getViewport() }));
        """
        out = _run_node_vm([JS_DIR / "world_minimap.js", JS_DIR / "world_minimap_interactions.js"], body)
        self.assertEqual(out["baseXY"], [160, 160])
        self.assertGreater(out["afterWheelZoom"], 1.0)
        self.assertAlmostEqual(out["wx0"], out["wx1"], places=4)
        self.assertAlmostEqual(out["wy0"], out["wy1"], places=4)
        self.assertNotEqual(out["afterPan"]["panX"], 0)
        self.assertGreater(out["afterBtnZoomIn"], out["afterWheelZoom"])
        self.assertEqual((out["afterFit"]["zoom"], out["afterFit"]["panX"]), (1, 0))

    def test_world_minimap_camera_bev_view_toggle(self) -> None:
        body = """
        const canvas = makeEl('bev-minimap-canvas', 'canvas', { width: 320, height: 320 });
        const viewBtn = makeEl('btn-minimap-view-toggle', 'button');
        byId.set('bev-minimap-canvas', canvas); byId.set('btn-minimap-view-toggle', viewBtn);
        const bevCalls = [];
        sb.BEVMinimap = { render: (_c, h, _z, camId) => bevCalls.push({ camId, w: h?.metric_width || null }) };
        sb.fetch = async () => ({ ok: true, json: async () => ({ bounds: [0, 0, 20, 20], zones: [], transitions: [], entities: [], cameras: [{ camera_id: 'cam_01', calibrated: true, world_pose: { origin_x: 5, origin_y: 5 } }] }) });
        sb.WorldMinimapInteractions.bind(() => 'cam_01');
        await sb.WorldTacticalMinimapView.fetchAndRender(canvas, 'cam_01', { is_calibrated: true, metric_width: 12, metric_height: 8 }, []);
        viewBtn.click();
        const cameraMode = sb.WorldTacticalMinimapView.getViewport().viewMode;
        const cameraLabel = viewBtn.textContent;
        viewBtn.click();
        const worldMode = sb.WorldTacticalMinimapView.getViewport().viewMode;
        console.log(JSON.stringify({ cameraMode, cameraLabel, worldMode, bevCalls }));
        """
        out = _run_node_vm([JS_DIR / "world_minimap.js", JS_DIR / "world_minimap_interactions.js"], body)
        self.assertEqual(out["cameraMode"], "camera")
        self.assertIn("Camera BEV", out["cameraLabel"])
        self.assertEqual(out["worldMode"], "world")
        self.assertEqual(out["bevCalls"], [{"camId": "cam_01", "w": 12}])


if __name__ == "__main__":
    unittest.main()
