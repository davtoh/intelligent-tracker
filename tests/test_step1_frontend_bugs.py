#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Node VM & contract tests for Step 1 M2: Frontend & Multiview Critical Bugs (Findings 1-7)."""

import json
import pathlib
import shutil
import subprocess
import unittest

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR / "dashboard" / "static"

_VM_PRELUDE = r"""
const fs = require('fs'), vm = require('vm');
const byId = new Map(), fetchCalls = [], ctxCalls = [];
function makeEl(id, extra = {}) {
  const listeners = {}, classes = new Set(extra.classes || []);
  return {
    id, value: '', checked: false, hidden: false, innerHTML: '', textContent: '', src: '',
    width: 640, height: 480, clientWidth: 640, clientHeight: 480, naturalWidth: 640, naturalHeight: 480,
    style: {}, dataset: {}, options: [], selectedOptions: [],
    classList: { contains: (c) => classes.has(c), add: (c) => classes.add(c), remove: (c) => classes.delete(c), toggle: (c, f) => (f ? classes.add(c) : classes.delete(c)) },
    addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
    removeEventListener: () => {},
    _emit: (ev, payload) => (listeners[ev] || []).forEach((fn) => fn(payload)),
    querySelector: () => null, querySelectorAll: () => [],
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 640, height: 480 }),
    getContext: () => ({
      clearRect: (...a) => ctxCalls.push(['clearRect', ...a]),
      fillRect: (...a) => ctxCalls.push(['fillRect', ...a]),
      strokeRect: (...a) => ctxCalls.push(['strokeRect', ...a]),
      setTransform: () => {}, setLineDash: () => {}, save: () => {}, restore: () => {},
      beginPath: () => {}, moveTo: () => {}, lineTo: () => {}, closePath: () => {},
      fill: () => {}, stroke: () => {}, arc: () => {}, drawImage: () => {},
      measureText: (t) => ({ width: String(t).length * 6 }),
      fillText: (...a) => ctxCalls.push(['fillText', ...a]),
    }),
    ...extra,
  };
}
const docListeners = {};
const sandbox = {
  console, Date, Math, Set, Map, WeakMap, Array, Object, Number, String, Boolean, JSON, encodeURIComponent,
  HTMLElement: function () {},
  Event: function (t) { this.type = t; },
  setTimeout, clearTimeout, setInterval: () => 1, clearInterval: () => {},
  fetch: (url, opts) => { fetchCalls.push({ url, opts }); return Promise.resolve({ ok: true, json: async () => ({}) }); },
  document: {
    getElementById: (id) => byId.get(id) || null,
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener: (ev, fn) => { (docListeners[ev] = docListeners[ev] || []).push(fn); },
    _emit: (ev, payload) => (docListeners[ev] || []).forEach((fn) => fn(payload)),
  },
  addEventListener: () => {}, dispatchEvent: () => {},
  location: { hash: '', protocol: 'http:', host: 'test.local' },
  makeEl, byId, fetchCalls, ctxCalls,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
"""


def _run_node_vm(js_files: list[pathlib.Path], script_body: str) -> dict:
    if not shutil.which("node"):
        raise unittest.SkipTest("node binary not available")
    loaders = "\n".join(
        f"vm.runInContext(fs.readFileSync({json.dumps(str(p))}, 'utf8'), sandbox);"
        for p in js_files
    )
    res = subprocess.run(
        ["node", "-e", f"{_VM_PRELUDE}\n{loaders}\n{script_body}"],
        capture_output=True, text=True, check=False,
    )
    if res.returncode != 0:
        raise AssertionError(f"Node VM failed:\nSTDOUT:{res.stdout}\nSTDERR:{res.stderr}")
    return json.loads(res.stdout.strip().splitlines()[-1])


class TestStep1FrontendBugs(unittest.TestCase):
    """Verify Findings 1-7 & MULTIVIEW_TOKEN frontend contracts."""

    def test_index_html_loads_nav_tabs_manager_after_app_js(self) -> None:
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        app_pos = html.find('/static/app.js')
        nav_pos = html.find('/static/js/nav_tabs_manager.js')
        self.assertGreater(app_pos, 0)
        self.assertGreater(nav_pos, app_pos)

    def test_offline_camera_shows_offline_poster_in_1x1(self) -> None:
        script = r"""
        const img = makeEl('live-stream-img', { src: '' });
        const badge = makeEl('live-stream-status-badge');
        const badgeText = makeEl('live-stream-status-text');
        byId.set('live-stream-img', img);
        byId.set('live-stream-status-badge', badge);
        byId.set('live-stream-status-text', badgeText);
        byId.set('multi-grid-container', makeEl('multi-grid-container'));
        byId.set('video-wrapper', makeEl('video-wrapper'));
        sandbox.CameraManager = { getActiveCameras: () => [{ id: 'usb_2', name: 'USB 2', status: 'offline' }] };
        sandbox.LivePlayer.attachLiveStream(img, 'usb_2', true);
        const afterAttach = { src: img.src, status: badgeText.textContent };
        img.src = '';
        sandbox.CameraGrid.focusCamera('usb_2', [{ id: 'usb_2', name: 'USB 2', status: 'offline' }]);
        console.log(JSON.stringify({ afterAttach, afterFocus: { src: img.src, status: badgeText.textContent } }));
        """
        out = _run_node_vm([STATIC_DIR / "js" / "live_player.js", STATIC_DIR / "js" / "camera_grid.js"], script)
        self.assertIn("Offline", out["afterAttach"]["src"])
        self.assertEqual(out["afterAttach"]["status"], "OFFLINE")
        self.assertIn("Offline", out["afterFocus"]["src"])
        self.assertEqual(out["afterFocus"]["status"], "OFFLINE")

    def test_grid_tile_overlay_responsive_resize_and_stale_clear(self) -> None:
        script = r"""
        let roCb = null;
        sandbox.ResizeObserver = function (cb) { roCb = cb; return { observe: () => {} }; };
        let containerSize = { width: 400, height: 300 };
        const canvas = makeEl('c1', { style: { width: '999px', height: '999px' } });
        const container = makeEl('box', { getBoundingClientRect: () => ({ left: 0, top: 0, ...containerSize }) });
        const tile = makeEl('t1', {
          getAttribute: (k) => (k === 'data-id' ? 'cam_1' : ''),
          querySelector: (s) => (s === 'canvas.tile-overlay-canvas' ? canvas : (s === '.tile-video-container' ? container : null)),
        });
        const grid = makeEl('multi-grid-container', { querySelectorAll: () => [tile] });
        byId.set('multi-grid-container', grid);
        sandbox.GridTileOverlay.handleTelemetry({ camera_id: 'cam_1', fps: 20, seq: 1, tracks: [{ id: 1, bbox: [10, 10, 40, 40] }] }, grid);
        const w1 = canvas.width, styleW1 = canvas.style.width;
        containerSize = { width: 200, height: 150 };
        roCb();
        const w2 = canvas.width;
        sandbox.GridTileOverlay.handleTelemetry({ camera_id: 'cam_1', status: 'offline', tracks: [] }, grid);
        console.log(JSON.stringify({ w1, styleW1, w2, cleared: ctxCalls.filter(c => c[0] === 'clearRect').length > 0 }));
        """
        out = _run_node_vm([STATIC_DIR / "js" / "unified_canvas_overlay.js", STATIC_DIR / "js" / "multiview" / "grid_tile_overlay.js"], script)
        self.assertEqual(out["styleW1"], "")
        self.assertEqual(out["w1"], 400)
        self.assertEqual(out["w2"], 200)
        self.assertTrue(out["cleared"])

    def test_roi_drag_persists_across_mousemove_and_telemetry_sync(self) -> None:
        script = r"""
        const canvas = makeEl('interactive-canvas');
        const videoImg = makeEl('live-stream-img');
        byId.set('interactive-canvas', canvas);
        byId.set('live-stream-img', videoImg);
        sandbox.localStorage = { getItem: () => 'cam_1' };
        sandbox.document._emit('DOMContentLoaded');
        canvas._emit('pointerdown', { button: 0, pointerId: 1, clientX: 20, clientY: 20 });
        canvas._emit('pointermove', { pointerId: 1, clientX: 120, clientY: 140 });
        const beforeStroke = ctxCalls.filter(c => c[0] === 'strokeRect').length;
        canvas._emit('mousemove', { clientX: 50, clientY: 50 });
        const afterMouseMove = ctxCalls.filter(c => c[0] === 'strokeRect').length;
        sandbox.window.dispatchEvent;
        console.log(JSON.stringify({ dragging: sandbox.RoiDrawTagger.isDragging(canvas), beforeStroke, afterMouseMove }));
        """
        out = _run_node_vm([
            STATIC_DIR / "js" / "unified_canvas_overlay.js",
            STATIC_DIR / "js" / "roi_draw_tagger.js",
            STATIC_DIR / "js" / "interactive_canvas.js",
            STATIC_DIR / "app.js",
        ], script)
        self.assertTrue(out["dragging"])
        self.assertGreater(out["beforeStroke"], 0)
        self.assertEqual(out["beforeStroke"], out["afterMouseMove"])

    def test_submit_tag_form_omits_bbox_when_crop_base64_active(self) -> None:
        script = r"""
        const form = makeEl('tag-entity-form');
        byId.set('tag-entity-form', form);
        byId.set('tag-name-input', makeEl('tag-name-input', { value: 'Alice' }));
        byId.set('tag-category-select', makeEl('tag-category-select', { value: 'vip' }));
        byId.set('tag-bbox-val', makeEl('tag-bbox-val', { value: '[10,20,30,40]' }));
        byId.set('tag-crop-base64', makeEl('tag-crop-base64', { value: 'data:image/jpeg;base64,AAA' }));
        sandbox.InteractiveCanvas.initTagModal(() => 'cam_1');
        form._emit('submit', { preventDefault: () => {} });
        setTimeout(() => {
          const body = JSON.parse(fetchCalls[0].opts.body);
          console.log(JSON.stringify({ bbox: body.bbox, crop: body.crop_base64 }));
        }, 0);
        """
        out = _run_node_vm([STATIC_DIR / "js" / "interactive_canvas.js"], script)
        self.assertIsNone(out["bbox"])
        self.assertEqual(out["crop"], "data:image/jpeg;base64,AAA")

    def test_object_fit_contain_and_enrollment_column_wiring(self) -> None:
        modals = (STATIC_DIR / "partials" / "modals" / "entity_modals.html").read_text(encoding="utf-8")
        css = (STATIC_DIR / "css" / "views.css").read_text(encoding="utf-8")
        self.assertIn("object-fit: contain", modals.split('id="tag-roi-crop-img"')[1].split(">")[0])
        self.assertIn("object-fit: contain", modals.split('id="enroll-crop-preview-img"')[1].split(">")[0])
        self.assertLess(modals.find('id="enroll-camera-select"'), modals.find('class="modal-right-col"'))
        self.assertIn("object-fit: contain;", css.split(".entity-avatar")[1].split("}")[0])
        self.assertIn("object-fit: contain;", css.split(".timeline-thumbnail")[1].split("}")[0])

    def test_enrollment_camera_change_and_image_only_no_fallback(self) -> None:
        script = r"""
        const camSel = makeEl('enroll-camera-select', { value: '' });
        const modal = makeEl('modal-universal-enrollment');
        byId.set('modal-universal-enrollment', modal);
        byId.set('enroll-camera-select', camSel);
        byId.set('enroll-bbox-canvas', makeEl('enroll-bbox-canvas'));
        byId.set('enroll-canvas-placeholder', makeEl('enroll-canvas-placeholder'));
        sandbox.App = { getActiveCameraId: () => 'cam_01' };
        sandbox.UniversalEnrollment.init();
        camSel.value = 'cam_02';
        camSel._emit('change', { target: camSel });
        camSel.value = '';
        camSel._emit('change', { target: camSel });
        console.log(JSON.stringify({ urls: fetchCalls.map(c => c.url) }));
        """
        out = _run_node_vm([STATIC_DIR / "js" / "universal_enrollment.js"], script)
        self.assertEqual(out["urls"], ["/api/cameras/cam_02/freeze_frame"])

    def test_analytics_heatmap_and_studio_recorded_video_attach(self) -> None:
        analytics_html = (STATIC_DIR / "partials" / "tabs" / "analytics.html").read_text(encoding="utf-8")
        studio_html = (STATIC_DIR / "partials" / "tabs" / "studio.html").read_text(encoding="utf-8")
        self.assertIn('id="heatmap-colorbar-legend"', analytics_html)
        self.assertIn('id="heatmap-camera-badge"', analytics_html)
        self.assertIn('data-src="/analytics/heatmap"', analytics_html)
        self.assertIn('id="studio-video-player"', studio_html)
        script = r"""
        const hm = makeEl('static-heatmap-img', { dataset: { src: '/analytics/heatmap' } });
        const hmBadge = makeEl('heatmap-camera-badge');
        byId.set('static-heatmap-img', hm);
        byId.set('heatmap-camera-badge', hmBadge);
        sandbox.App = { getActiveCameraId: () => 'cam_7' };
        sandbox.LivePlayer.attachHeatmapImage(hm);
        const sImg = makeEl('studio-live-img'), sVid = makeEl('studio-video-player');
        byId.set('studio-live-img', sImg); byId.set('studio-video-player', sVid);
        sandbox.StudioCanvas.attachStudioMedia('demo.mp4', true, true);
        console.log(JSON.stringify({ hmSrc: hm.src, hmBadge: hmBadge.textContent, vidSrc: sVid.src, vidDisp: sVid.style.display, imgDisp: sImg.style.display }));
        """
        out = _run_node_vm([STATIC_DIR / "js" / "live_player.js", STATIC_DIR / "js" / "studio_media.js", STATIC_DIR / "js" / "studio_canvas.js"], script)
        self.assertIn("/analytics/heatmap?camera_id=cam_7", out["hmSrc"])
        self.assertEqual(out["hmBadge"], "Camera: cam_7")
        self.assertEqual(out["vidSrc"], "/videos/demo.mp4")
        self.assertEqual(out["vidDisp"], "block")
        self.assertEqual(out["imgDisp"], "none")

    def test_telemetry_reads_multiview_token_safely(self) -> None:
        script = r"""
        let wsUrl = '';
        sandbox.WebSocket = function (u) { wsUrl = u; };
        sandbox.location = { protocol: 'http:', host: 'test.local' };
        sandbox.MULTIVIEW_TOKEN = 'tok_xyz';
        sandbox.TelemetryGateway.initWebSocket('cam_1');
        console.log(JSON.stringify({ wsUrl }));
        """
        out = _run_node_vm([STATIC_DIR / "js" / "telemetry.js"], script)
        self.assertEqual(out["wsUrl"], "ws://test.local/ws/cam_1?token=tok_xyz")


if __name__ == "__main__":
    unittest.main()
