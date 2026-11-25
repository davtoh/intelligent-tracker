"""Milestone 3+ Node VM frontend tests for Step 2: ActiveSourceContext, SourceRef routing, Analytics & Studio freeze."""

import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_DIR = ROOT / "dashboard" / "static" / "js"

_VM_PREAMBLE = """
const fs = require('fs');
const vm = require('vm');
const byId = new Map();
function makeEl(id, tag = 'div') {
  const listeners = {}, cls = new Set(), attrs = {};
  const el = {
    id, tagName: tag.toUpperCase(), value: '', textContent: '', innerHTML: '', href: '', src: '',
    disabled: false, hidden: false, style: {}, dataset: {}, options: [], children: [],
    parentElement: { appendChild: (c) => { byId.set(c.id, c); return c; } },
    classList: {
      add: (c) => cls.add(c), remove: (c) => cls.delete(c), contains: (c) => cls.has(c),
      toggle: (c, f) => (f === undefined ? (cls.has(c) ? cls.delete(c) : cls.add(c)) : (f ? cls.add(c) : cls.delete(c))),
    },
    getAttribute: (k) => (k === 'data-tab' ? id : (attrs[k] ?? null)),
    setAttribute: (k, v) => { attrs[k] = String(v); },
    removeAttribute: (k) => { delete attrs[k]; if (k === 'src') el.src = ''; },
    insertAdjacentElement: (_pos, c) => { byId.set(c.id, c); },
    addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
    dispatchEvent: (ev) => { (listeners[ev.type || ev] || []).forEach((fn) => fn(ev)); },
    click: () => { (listeners.click || []).forEach((fn) => fn({ preventDefault() {}, stopPropagation() {} })); },
    querySelector: (sel) => (sel === '.media-empty-state-title' ? (el._titleEl || (el._titleEl = makeEl(id + '-t'))) : sel === '.media-empty-state-sub' ? (el._subEl || (el._subEl = makeEl(id + '-s'))) : null),
    querySelectorAll: () => [],
    appendChild: (c) => { el.children.push(c); if (c.tagName === 'OPTGROUP') el.options.push(...c.options); else if (c.tagName === 'OPTION') el.options.push(c); return c; },
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 640, height: 480 }),
    getContext: () => ({ clearRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {}, fill() {}, arc() {}, closePath() {}, save() {}, restore() {}, fillText() {}, fillRect() {}, strokeRect() {}, drawImage() {} }),
  };
  return el;
}
const store = new Map(), winListeners = {}, docListeners = {}, events = [];
const sandbox = {
  console, Math, Date, Number, String, Boolean, Array, Object, Set, Map, JSON, URLSearchParams,
  encodeURIComponent, decodeURIComponent, Promise, setTimeout, clearTimeout, byId, makeEl, store, events,
  winListeners, docListeners, process,
  Event: function (t) { this.type = t; },
  CustomEvent: function (t, init) { this.type = t; this.detail = init?.detail; },
  localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) },
  history: { pushState: (_s, _t, u) => { sandbox.location.hash = u; } },
  location: { hash: '' },
  fetch: async () => ({ ok: true, json: async () => ([]) }),
  document: {
    readyState: 'complete',
    getElementById: (id) => byId.get(id) || null,
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: (tag) => makeEl('tmp_' + Math.random().toString(36).slice(2, 7), tag),
    addEventListener: (ev, fn) => { (docListeners[ev] = docListeners[ev] || []).push(fn); },
  },
  addEventListener: (ev, fn) => { (winListeners[ev] = winListeners[ev] || []).push(fn); },
  dispatchEvent: (ev) => { events.push(ev); (winListeners[ev.type] || []).forEach((fn) => fn(ev)); },
};
sandbox.window = sandbox; sandbox.globalThis = sandbox; sandbox.sandbox = sandbox;
const ctx = vm.createContext(sandbox);
"""


def _run_vm(files: list[Path], body: str) -> dict:
    file_list = json.dumps([str(p.relative_to(ROOT)).replace("\\", "/") for p in files])
    script = (
        _VM_PREAMBLE
        + f"\nfor (const f of {file_list}) {{ vm.runInContext(fs.readFileSync(f, 'utf8'), ctx, {{ filename: f }}); }}\n"
        + f"vm.runInContext(`(async () => {{\n{body}\n}})().catch((e) => {{ console.error(e); process.exit(1); }});`, ctx);\n"
    )
    proc = subprocess.run(["node", "-e", script], cwd=str(ROOT), capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise AssertionError(f"Node VM failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


class TestStep2Milestone3Frontend(unittest.TestCase):
    """Node VM tests for ActiveSourceContext, full SourceRef routing, Analytics sync & Studio freeze."""

    def test_active_source_context_storage_and_hash_pin_override(self) -> None:
        body = """
        sandbox.ActiveSourceContext.set({ kind: 'camera', cameraId: 'cam_02' });
        const storedCam = JSON.parse(store.get('it_active_source_ref'));
        const legacyCam = store.get('it_focused_camera_id');
        sandbox.location.hash = '#analytics?video=clip.mp4&run_id=r9&offset_sec=4.5';
        const pinned = sandbox.ActiveSourceContext.get();
        const unpinned = sandbox.ActiveSourceContext.get({ ignoreHash: true });
        const selVal = sandbox.ActiveSourceContext.toSelectValue(pinned);
        console.log(JSON.stringify({ storedCam, legacyCam, pinned, unpinned, selVal }));
        """
        out = _run_vm([JS_DIR / "app_navigation.js", JS_DIR / "active_source_context.js"], body)
        self.assertEqual(out["storedCam"]["cameraId"], "cam_02")
        self.assertEqual(out["legacyCam"], "cam_02")
        self.assertTrue(out["pinned"]["pinned"])
        self.assertEqual(out["pinned"]["videoFilename"], "clip.mp4")
        self.assertEqual(out["pinned"]["runId"], "r9")
        self.assertEqual(out["unpinned"]["cameraId"], "cam_02")
        self.assertEqual(out["selVal"], "video:clip.mp4")

    def test_full_sourceref_hash_serialization_and_videos_routing(self) -> None:
        body = """
        ['scrubber-video-player'].forEach((id) => byId.set(id, makeEl(id, 'video')));
        sandbox.fetch = async (u) => ({ ok: true, json: async () => (u === '/api/videos' ? [{ filename: 'clip.mp4', video_url: '/videos/clip.mp4', web_compatible: true, codec: 'h264' }] : []) });
        const loaded = [], dets = [], seeks = [];
        winListeners['video-seek-request'] = [(e) => seeks.push(e.detail)];
        sandbox.switchTab = () => {};
        sandbox.VideoScrubber = { loadVideosList: async () => {}, loadVideoIntoPlayer: (...a) => loaded.push(a), loadDetections: (...a) => dets.push(a) };
        const ref = { kind: 'video', cameraId: 'cam_1', videoFilename: 'clip.mp4', runId: 'run_8', mediaOffsetSec: 7.25, ts: 1700, trackId: 4, entityId: 9, zoneId: 'dock', bbox: [1, 2, 30, 40] };
        const hash = sandbox.AppNavigation.buildHash('tab-videos', ref);
        const parsed = sandbox.AppNavigation.parseHash(hash);
        const roundtrip = sandbox.AppNavigation.paramsToSourceRef(parsed.params);
        await sandbox.AppNavigation.navigate('tab-videos', ref);
        console.log(JSON.stringify({ hash, roundtrip, loaded, dets, seeks }));
        """
        out = _run_vm([JS_DIR / "media_empty_state.js", JS_DIR / "active_source_context.js", JS_DIR / "app_navigation.js"], body)
        self.assertIn("run_id=run_8", out["hash"])
        self.assertIn("offset_sec=7.25", out["hash"])
        self.assertIn("track_id=4", out["hash"])
        self.assertEqual(out["roundtrip"]["bbox"], [1, 2, 30, 40])
        self.assertEqual(out["loaded"][0][1], "clip.mp4")
        self.assertEqual(out["dets"], [["clip.mp4", "run_8"]])
        self.assertEqual(out["seeks"], [{"filename": "clip.mp4", "offsetSec": 7.25}])

    def test_unavailable_source_media_empty_state_across_tabs(self) -> None:
        body = """
        ['live-stream-img', 'static-heatmap-img', 'studio-live-img'].forEach((id) => byId.set(id, makeEl(id, 'img')));
        byId.set('video-stream-title', makeEl('video-stream-title'));
        byId.set('analytics-source-select', makeEl('analytics-source-select', 'select'));
        byId.set('studio-camera-select', makeEl('studio-camera-select', 'select'));
        sandbox.fetch = async (u) => ({ ok: true, json: async () => (u === '/api/cameras' ? [{ id: 'cam_01' }] : []) });
        sandbox.switchTab = () => {}; sandbox.LivePlayer = { detachLiveStream() {} };
        sandbox.Studio = { loadStudioChannels: async () => {} }; sandbox.AnalyticsView = { initSourceSelect: async () => {} };
        await sandbox.AppNavigation.navigate('tab-live', { cameraId: 'missing_cam' });
        await sandbox.AppNavigation.navigate('tab-analytics', { cameraId: 'missing_cam' });
        await sandbox.AppNavigation.navigate('tab-studio', { videoFilename: 'missing.mp4' });
        const titles = ['live-stream-img', 'static-heatmap-img', 'studio-live-img'].map((id) => byId.get(id + '-empty-state').querySelector('.media-empty-state-title').textContent);
        console.log(JSON.stringify({ titles, liveTitle: byId.get('video-stream-title').textContent }));
        """
        out = _run_vm([JS_DIR / "media_empty_state.js", JS_DIR / "active_source_context.js", JS_DIR / "app_navigation.js"], body)
        self.assertEqual(out["titles"][:2], ["Camera Unavailable", "Camera Unavailable"])
        self.assertEqual(out["titles"][2], "Recorded Video Unavailable")
        self.assertIn("missing_cam", out["liveTitle"])

    def test_analytics_source_select_sync_and_drilldown_app_navigate(self) -> None:
        body = """
        const sel = makeEl('analytics-source-select', 'select');
        ['trafficChart', 'tab-analytics', 'heatmap-camera-badge', 'btn-download-heatmap', 'static-heatmap-img', 'heatmap-hotspot-canvas', 'heatmap-axis-x', 'heatmap-axis-y', 'heatmap-hotspot-tooltip'].forEach((id) => byId.set(id, makeEl(id)));
        byId.set('analytics-source-select', sel);
        sandbox.fetch = async (u) => ({ ok: true, json: async () => (u === '/api/cameras' ? [{ id: 'cam_a', name: 'Lobby' }] : u === '/api/videos' ? [{ filename: 'clip.mp4' }] : { camera_id: 'cam_a', grid_size: [32, 24], hotspots: [{ col: 16, row: 12, source_ref: { kind: 'video', video_filename: 'clip.mp4', run_id: 'r1', media_offset_sec: 5.0 } }] }) });
        const navCalls = []; sandbox.App = { navigate: (t, r) => navCalls.push({ t, r }), getActiveCameraId: () => 'cam_a' };
        await sandbox.AnalyticsView.initSourceSelect();
        sel.value = 'video:clip.mp4'; sel.dispatchEvent({ type: 'change' });
        const storedAfter = sandbox.ActiveSourceContext.get({ ignoreHash: true });
        sandbox.AnalyticsDrilldown.setFlowData({ camera_id: 'cam_a', bucket_sec: 60 });
        sandbox.AnalyticsDrilldown.drillDownToTimeWindow({ bucket_start: 100, media_refs: [{ source_ref: { kind: 'camera', camera_id: 'cam_a', run_id: 'r_flow' } }] }, 'tab-alerts');
        sandbox.AnalyticsDrilldown.setHeatmapData({ camera_id: 'cam_a', grid_size: [32, 24], hotspots: [{ col: 16, row: 12, source_ref: { kind: 'video', video_filename: 'clip.mp4', run_id: 'r1', media_offset_sec: 5.0 } }] });
        sandbox.AnalyticsDrilldown.handleHeatmapClick(byId.get('heatmap-hotspot-canvas'), 330, 250);
        console.log(JSON.stringify({ opts: sel.options.map((o) => o.value), storedAfter, navCalls }));
        """
        out = _run_vm([JS_DIR / "media_empty_state.js", JS_DIR / "active_source_context.js", JS_DIR / "analytics_drilldown.js", JS_DIR / "analytics_view.js"], body)
        self.assertIn("video:clip.mp4", out["opts"])
        self.assertEqual(out["storedAfter"]["videoFilename"], "clip.mp4")
        self.assertEqual(out["navCalls"][0]["t"], "tab-alerts")
        self.assertEqual(out["navCalls"][0]["r"]["runId"], "r_flow")
        self.assertEqual(out["navCalls"][1]["t"], "tab-timeline")
        self.assertEqual(out["navCalls"][1]["r"]["mediaOffsetSec"], 5.0)

    def test_studio_freeze_frame_toggle_and_select_zone_by_id(self) -> None:
        body = """
        const btn = makeEl('btn-studio-freeze-toggle', 'button'), img = makeEl('studio-live-img', 'img');
        ['studio-video-player', 'studio-drawing-canvas', 'studio-camera-select', 'studio-status-banner'].forEach((id) => byId.set(id, makeEl(id)));
        byId.set('btn-studio-freeze-toggle', btn); byId.set('studio-live-img', img);
        sandbox.fetch = async (u) => ({ ok: true, json: async () => (u.includes('/freeze_frame') ? { camera_id: 'cam_01', width: 640, height: 480, image_base64: 'data:image/jpeg;base64,FREEZE' } : {}) });
        const ctrl = sandbox.StudioCanvas.bindFreezeControl(() => 'cam_01');
        await ctrl.freeze();
        const frozenState = { text: btn.textContent, src: img.src, pressed: btn.getAttribute('aria-pressed'), frozen: ctrl.isFrozen() };
        ctrl.resume();
        const resumedState = { text: btn.textContent, src: img.src, pressed: btn.getAttribute('aria-pressed'), frozen: ctrl.isFrozen() };
        const state = { activeCamera: 'cam_01', mode: 'draw_zone', zones: [{ id: 'z_9', name: 'vault', polygon: [[0, 0], [10, 0], [10, 10]] }], tripwires: [] };
        sandbox.StudioShapeEditor.init(() => state, { drawOverlay() {} });
        const found = sandbox.StudioCanvas.selectZoneById('z_9', state, { updateStatus() {}, drawOverlay() {} });
        console.log(JSON.stringify({ frozenState, resumedState, found, selected: sandbox.StudioShapeEditor.getSelected(), mode: state.mode }));
        """
        out = _run_vm([JS_DIR / "media_empty_state.js", JS_DIR / "active_source_context.js", JS_DIR / "studio_shape_editor.js", JS_DIR / "studio_canvas.js"], body)
        self.assertTrue(out["frozenState"]["frozen"])
        self.assertEqual(out["frozenState"]["src"], "data:image/jpeg;base64,FREEZE")
        self.assertIn("Resume", out["frozenState"]["text"])
        self.assertFalse(out["resumedState"]["frozen"])
        self.assertIn("/stream/cam_01?t=", out["resumedState"]["src"])
        self.assertTrue(out["found"])
        self.assertEqual(out["selected"], {"type": "zone", "name": "vault"})
        self.assertEqual(out["mode"], "idle")
