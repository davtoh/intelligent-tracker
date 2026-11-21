#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Node VM & contract tests for Step 4 M4: OverlayControlBar, Live Channel & Studio/BEV."""

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
    width: 640, height: 480, style: {}, dataset: {}, options: [], selectedOptions: [],
    classList: { contains: (c) => classes.has(c), add: (c) => classes.add(c), remove: (c) => classes.delete(c), toggle: (c, f) => (f ? classes.add(c) : classes.delete(c)) },
    addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
    _emit: (ev, payload) => (listeners[ev] || []).forEach((fn) => fn(payload)),
    querySelectorAll: () => [],
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 600 }),
    getContext: () => ({
      clearRect: (...a) => ctxCalls.push(['clearRect', ...a]),
      fillRect: (...a) => ctxCalls.push(['fillRect', ...a]),
      strokeRect: (...a) => ctxCalls.push(['strokeRect', ...a]),
      beginPath: () => {}, moveTo: () => {}, lineTo: () => {}, closePath: () => {},
      fill: () => {}, stroke: () => {}, arc: () => {}, save: () => {}, restore: () => {},
      setLineDash: () => {}, measureText: (t) => ({ width: String(t).length * 6 }),
      fillText: (...a) => ctxCalls.push(['fillText', ...a]),
    }),
    ...extra,
  };
}
const sandbox = {
  console, Date, Math, Set, Map, Array, Object, Number, String, Boolean, JSON, encodeURIComponent,
  HTMLElement: function () {},
  getComputedStyle: () => ({ direction: 'ltr' }),
  setTimeout, clearTimeout, setInterval: () => 1, clearInterval: () => {},
  Event: function (t) { this.type = t; },
  fetch: (url, opts) => { fetchCalls.push({ url, opts }); return Promise.resolve({ ok: true, json: async () => ({}) }); },
  document: {
    getElementById: (id) => byId.get(id) || null,
    querySelectorAll: () => [],
    addEventListener: () => {},
  },
  addEventListener: () => {},
  dispatchEvent: () => {},
  makeEl, byId, fetchCalls, ctxCalls,
};
sandbox.window = sandbox;
vm.createContext(sandbox);
"""


def _run_vm(js_files: list[pathlib.Path], script: str) -> dict:
    if not shutil.which("node"):
        raise unittest.SkipTest("Node.js is required for JS VM verification")
    loaders = "\n".join(
        f"vm.runInContext(fs.readFileSync({json.dumps(str(p))}, 'utf8'), sandbox);"
        for p in js_files
    )
    proc = subprocess.run(
        ["node", "-e", _VM_PRELUDE + loaders + "\n" + script],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"Node VM failed:\n{proc.stderr}\n{proc.stdout}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


class TestStep4OverlayBarAndStudio(unittest.TestCase):
    """Verify OverlayControlBar, single fullscreen button, Studio/BEV coordinates, and LivePlayer."""

    def test_single_fullscreen_button_and_overlay_container_in_live_html(self) -> None:
        html = (STATIC_DIR / "partials" / "tabs" / "live.html").read_text(encoding="utf-8")
        self.assertNotIn('id="fullscreen-btn"', html)
        self.assertIn('id="btn-fullscreen-toggle"', html)
        self.assertIn('id="live-overlay-control-bar"', html)
        self.assertIn('id="live-bev-pip-canvas"', html)
        self.assertNotIn('overlay-toggle-toast_prompts', html)

    def test_overlay_control_bar_live_and_scrubber_variants(self) -> None:
        script = """
        const liveBar = makeEl('live-overlay-control-bar');
        const scrubBar = makeEl('scrubber-overlay-layers');
        byId.set('live-overlay-control-bar', liveBar);
        byId.set('scrubber-overlay-layers', scrubBar);
        const toggled = [];
        sandbox.OverlayControlBar.mount({ container: liveBar, variant: 'live', onToggle: (k, v) => toggled.push([k, v]) });
        sandbox.OverlayLayerToolbar.renderToolbar({
          descriptors: [{ runId: 'r1', runNum: 1, label: 'Run 1', title: 'R1', palette: { id: 'cyan' } }],
          activeRunIds: new Set(['r1']), hasLiveJob: false,
        });
        console.log(JSON.stringify({
          liveHasToastPrompts: liveBar.innerHTML.includes('toast_prompts'),
          liveHasClutter: liveBar.innerHTML.includes('overlay-toggle-clutter'),
          scrubHasChips: scrubBar.innerHTML.includes('overlay-layer-chip') && scrubBar.innerHTML.includes('overlay-feature-pill'),
          liveKeysCount: sandbox.OverlayControlBar.LIVE_TOGGLES.length,
        }));
        """
        out = _run_vm([STATIC_DIR / "js" / "overlay_control_bar.js", STATIC_DIR / "js" / "overlay_layer_toolbar.js"], script)
        self.assertFalse(out["liveHasToastPrompts"])
        self.assertTrue(out["liveHasClutter"])
        self.assertTrue(out["scrubHasChips"])
        self.assertEqual(out["liveKeysCount"], 10)

    def test_studio_overlays_targets_active_live_camera_and_toggles_pip(self) -> None:
        script = """
        const pip = makeEl('live-bev-pip-canvas', { hidden: true });
        byId.set('live-bev-pip-canvas', pip);
        const state = { activeCamera: 'studio_cam', overlays: { bev_minimap: false }, zones: [], homography: null };
        sandbox.App = { getActiveCameraId: () => 'live_cam_02' };
        sandbox.StudioOverlays.init(() => state);
        sandbox.StudioOverlays.updateOverlays({ bev_minimap: true });
        console.log(JSON.stringify({ url: fetchCalls[0]?.url || '', pipHidden: pip.hidden }));
        """
        out = _run_vm([STATIC_DIR / "js" / "bev_minimap.js", STATIC_DIR / "js" / "studio_overlays.js"], script)
        self.assertEqual(out["url"], "/api/cameras/live_cam_02/overlays")
        self.assertFalse(out["pipHidden"])

    def test_studio_canvas_uses_contain_box_and_renders_saved_zones(self) -> None:
        script = """
        const img = makeEl('studio-live-img', { naturalWidth: 1280, naturalHeight: 720, parentElement: { getBoundingClientRect: () => ({ left: 0, top: 0 }) } });
        const canvas = makeEl('studio-drawing-canvas');
        byId.set('studio-live-img', img);
        byId.set('studio-drawing-canvas', canvas);
        sandbox.StudioCanvas.drawOverlay(canvas.getContext('2d'), canvas, 'idle', [], null, {
          zones: [{ name: 'Lobby', polygon: [[10, 10], [100, 10], [100, 100]] }],
          tripwires: [{ name: 'Gate', line_segment: [[0, 50], [200, 50]] }],
        });
        console.log(JSON.stringify({
          w: canvas.width, h: canvas.height, styleTop: canvas.style.top, styleH: canvas.style.height,
          texts: ctxCalls.filter(c => c[0] === 'fillText').map(c => c[1]),
        }));
        """
        out = _run_vm([STATIC_DIR / "js" / "unified_canvas_overlay.js", STATIC_DIR / "js" / "studio_canvas.js"], script)
        self.assertEqual(out["w"], 1280)
        self.assertEqual(out["h"], 720)
        self.assertEqual(out["styleTop"], "75px")
        self.assertEqual(out["styleH"], "450px")
        self.assertTrue(any("Lobby" in t for t in out["texts"]))
        self.assertTrue(any("Gate" in t for t in out["texts"]))

    def test_bev_minimap_gates_homography_and_updates_scale_badge(self) -> None:
        script = """
        const badge = makeEl('bev-metric-scale');
        const canvas = makeEl('bev-minimap-canvas', { width: 320, height: 320 });
        byId.set('bev-metric-scale', badge);
        sandbox.latestTelemetry = { active_tracks: [{ id: 1, bbox: [100, 100, 40, 80], ground_pos: [320, 240] }] };
        sandbox.BEVMinimap.render(canvas, { is_calibrated: false, metric_width: 10, metric_height: 10 }, [], 'cam_01');
        const uncalText = badge.textContent;
        sandbox.BEVMinimap.render(canvas, { is_calibrated: true, metric_width: 12, metric_height: 8, homography_matrix: [[1,0,0],[0,1,0],[0,0,1]] }, [], 'cam_01');
        console.log(JSON.stringify({ uncalText, calText: badge.textContent }));
        """
        out = _run_vm([STATIC_DIR / "js" / "bev_minimap.js"], script)
        self.assertEqual(out["uncalText"], "Pixel Est.")
        self.assertEqual(out["calText"], "Calibrated")

    def test_live_player_skips_stream_attach_for_recorded_video_in_studio(self) -> None:
        script = """
        const studioImg = makeEl('studio-live-img', { src: '' });
        const sel = makeEl('studio-camera-select', {
          value: 'clip.mp4',
          selectedOptions: [{ value: 'clip.mp4', parentElement: { label: 'Recorded Videos' } }],
        });
        byId.set('studio-live-img', studioImg);
        byId.set('studio-camera-select', sel);
        sandbox.LivePlayer.syncTabStreams('tab-live', 'tab-studio');
        console.log(JSON.stringify({ isPoster: studioImg.src.startsWith('data:image/svg+xml') }));
        """
        out = _run_vm([STATIC_DIR / "js" / "live_player.js"], script)
        self.assertTrue(out["isPoster"])

    def test_zero_cls_hud_css_and_title_containment(self) -> None:
        css = (STATIC_DIR / "css" / "player.css").read_text(encoding="utf-8")
        self.assertNotIn("!important", css)
        self.assertIn("gap: 8px;", css)
        self.assertIn("font-variant-numeric: tabular-nums;", css)
        self.assertIn("max-width: clamp(", css)
        self.assertIn(".stream-lag-badge[hidden]", css)
        self.assertIn("visibility: hidden;", css)

    def test_live_player_lag_hysteresis_and_p1_replay_suppression(self) -> None:
        script = """
        const hud = makeEl('stream-telemetry-hud'), lag = makeEl('stream-lag-badge', { hidden: true });
        byId.set('stream-telemetry-hud', hud); byId.set('stream-lag-badge', lag);
        const LP = sandbox.LivePlayer;
        LP.updateInferenceLagHud({ camera_id: 'cam_01', priority_tier: 'P0', fps: 24, inference_lag_ms: 220 });
        const h1 = lag.hidden;
        LP.updateInferenceLagHud({ camera_id: 'cam_01', priority_tier: 'P0', fps: 24, inference_lag_ms: 220 });
        const h2 = lag.hidden;
        LP.updateInferenceLagHud({ camera_id: 'cam_01', priority_tier: 'P0', fps: 24, inference_lag_ms: 220 });
        const h3 = lag.hidden, txt3 = lag.textContent;
        LP.updateInferenceLagHud({ camera_id: 'cam_01', priority_tier: 'P1', target_fps: 1, motion_active: false, inference_lag_ms: 500 });
        const hP1 = lag.hidden;
        LP.updateInferenceLagHud({ camera_id: 'cam_01', priority_tier: 'P0', fps: 24, inference_lag_ms: 250 });
        LP.updateInferenceLagHud({ camera_id: 'cam_01', priority_tier: 'P0', fps: 24, inference_lag_ms: 250 });
        LP.updateInferenceLagHud({ camera_id: 'cam_01', priority_tier: 'P0', fps: 24, inference_lag_ms: 250 });
        LP.updateInferenceLagHud({ camera_id: 'cam_01', priority_tier: 'REPLAY', replay_active: true, inference_lag_ms: 400 });
        console.log(JSON.stringify({ h1, h2, h3, txt3, hP1, hReplay: lag.hidden }));
        """
        out = _run_vm([STATIC_DIR / "js" / "live_player.js"], script)
        self.assertTrue(out["h1"] and out["h2"] and not out["h3"])
        self.assertTrue(out["txt3"].startswith("AI Lag:"))
        self.assertTrue(out["hP1"] and out["hReplay"])

    def test_multiview_tile_telemetry_boxes_armed_toggle_and_pool_alerts(self) -> None:
        script = """
        const fpsEl = makeEl('fps'), tracksEl = makeEl('tr'), armBtn = makeEl('arm', { dataset: { armed: 'false' } });
        const canvas = makeEl('ov', { clientWidth: 320, clientHeight: 180 });
        const tile = makeEl('tile', { attributes: { 'data-id': 'cam_02' }, querySelector: (s) => ({ '.tile-fps': fpsEl, '.tile-tracks': tracksEl, '.btn-tile-arm': armBtn, 'canvas.tile-overlay-canvas': canvas }[s] || null) });
        tile.getAttribute = (k) => k === 'data-id' ? 'cam_02' : null;
        const grid = makeEl('multi-grid-container', { querySelectorAll: () => [tile] });
        byId.set('multi-grid-container', grid);
        let renderedAlerts = null;
        sandbox.TelemetryGateway = { renderMiniAlerts: (a) => { renderedAlerts = a; } };
        sandbox.fetch = (url, opts) => { fetchCalls.push({ url, opts }); return Promise.resolve({ ok: true, json: async () => ({ events: [{ event_type: 'intrusion' }] }) }); };
        sandbox.GridTileOverlay.handleTelemetry({ camera_id: 'cam_02', fps: 18.5, priority_tier: 'P0', armed: true, ai_active: true, source_resolution: [640, 480], tracks: [{ id: 7, bbox: [10, 20, 50, 80] }] }, grid);
        const armedAfterTelemetry = armBtn.textContent;
        (async () => {
          await sandbox.GridTileOverlay.toggleCameraArmed('cam_02', armBtn, [{ id: 'cam_02', armed: true }]);
          await sandbox.GridTileOverlay.refreshPoolAlerts();
          console.log(JSON.stringify({ fps: fpsEl.textContent, tracks: tracksEl.textContent, armedAfterTelemetry, armedAfterToggle: armBtn.textContent, ctxCount: ctxCalls.length, urls: fetchCalls.map(c => c.url), alertsLen: renderedAlerts?.length || 0 }));
        })();
        """
        out = _run_vm([STATIC_DIR / "js" / "unified_canvas_overlay.js", STATIC_DIR / "js" / "multiview" / "grid_tile_overlay.js"], script)
        self.assertEqual(out["fps"], "18.5 FPS")
        self.assertEqual(out["tracks"], "1 tracks")
        self.assertEqual(out["armedAfterTelemetry"], "🛡 AI ON")
        self.assertEqual(out["armedAfterToggle"], "🛡 AI OFF")
        self.assertGreater(out["ctxCount"], 0)
        self.assertIn("/api/cameras/cam_02", out["urls"])
        self.assertEqual(out["alertsLen"], 1)

    def test_cameras_router_supports_patch_and_put(self) -> None:
        src = (ROOT_DIR / "dashboard" / "routers" / "cameras.py").read_text(encoding="utf-8")
        self.assertIn('@router.patch("/api/cameras/{camera_id}")', src)
        self.assertIn('@router.put("/api/cameras/{camera_id}")', src)


if __name__ == "__main__":
    unittest.main()
