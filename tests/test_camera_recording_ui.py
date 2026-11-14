#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit, FastAPI partial, and Node vm mock-DOM tests for Dashboard Live MP4 Recording UI."""

import json
import os
import pathlib
import re
import shutil
import subprocess
import unittest
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.services.camera_pool_queries import build_camera_status_row

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR / "dashboard" / "static"
TEMPLATES_DIR = ROOT_DIR / "dashboard" / "templates"
JS_DIR = STATIC_DIR / "js"
CSS_DIR = STATIC_DIR / "css"

_NODE_VM_PRELUDE = r"""
const fs = require('fs'), vm = require('vm'), path = require('path'), jsDir = process.env.JS_DIR;
const byId = new Map(), docListeners = new Map(), winListeners = new Map();
const fetchCalls = [], toasts = [], switchedTabs = [], videoListCalls = [], selectEvents = [], rootContainers = [];
function matchSingle(el, sel) {
  let rem = sel.trim();
  const attrM = rem.match(/\[([a-zA-Z0-9_-]+)="([^"]*)"\]/);
  if (attrM) { if (el.getAttribute(attrM[1]) !== attrM[2]) return false; rem = rem.replace(attrM[0], ''); }
  for (const c of (rem.match(/\.[a-zA-Z0-9_-]+/g) || [])) if (!el.classList.contains(c.slice(1))) return false;
  rem = rem.replace(/\.[a-zA-Z0-9_-]+/g, '').trim();
  return !rem || el.tagName.toLowerCase() === rem.toLowerCase();
}
function collectDesc(node, out = []) { for (const ch of (node._children || [])) { out.push(ch); collectDesc(ch, out); } return out; }
function makeEl(tag = 'div', id = '') {
  const attrs = new Map(), listeners = new Map(), classes = new Set();
  const el = {
    tagName: tag.toUpperCase(), id, style: {}, hidden: false, disabled: false, checked: true, value: '', textContent: '', title: '', _html: '', _children: [], options: [],
    classList: {
      add: (...c) => c.forEach(x => classes.add(x)), remove: (...c) => c.forEach(x => classes.delete(x)),
      toggle: (c, f) => (f === undefined ? (classes.has(c) ? (classes.delete(c), false) : (classes.add(c), true)) : (f ? (classes.add(c), true) : (classes.delete(c), false))),
      contains: (c) => classes.has(c),
    },
    setAttribute: (k, v) => { attrs.set(k, String(v)); if (k === 'class') { classes.clear(); String(v).split(/\s+/).filter(Boolean).forEach(c => classes.add(c)); } },
    getAttribute: (k) => (attrs.has(k) ? attrs.get(k) : null),
    addEventListener: (t, fn) => { if (!listeners.has(t)) listeners.set(t, []); listeners.get(t).push(fn); },
    dispatchEvent: (ev) => { ev.currentTarget = el; ev.target = ev.target || el; ev.stopPropagation = ev.stopPropagation || (() => {}); return Promise.all((listeners.get(ev.type) || []).map(fn => fn(ev))); },
    click: () => el.dispatchEvent({ type: 'click', stopPropagation: () => {} }),
    querySelectorAll: (sel) => { const parts = sel.split(',').map(s => s.trim()).filter(Boolean); return collectDesc(el).filter(c => parts.some(p => matchSingle(c, p))); },
    querySelector: (sel) => el.querySelectorAll(sel)[0] || null,
  };
  Object.defineProperty(el, 'className', { get: () => Array.from(classes).join(' '), set: (v) => { classes.clear(); String(v).split(/\s+/).filter(Boolean).forEach(c => classes.add(c)); } });
  Object.defineProperty(el, 'innerHTML', {
    get: () => el._html,
    set: (html) => {
      el._html = String(html); el._children = [];
      const stack = [el], tagRe = /<\/([a-zA-Z0-9-]+)>|<([a-zA-Z0-9-]+)([^>]*)>/g;
      for (let m; (m = tagRe.exec(el._html)) !== null;) {
        if (m[1]) { if (stack.length > 1) stack.pop(); continue; }
        const child = makeEl(m[2]);
        for (let am, aRe = /([a-zA-Z0-9_-]+)="([^"]*)"/g; (am = aRe.exec(m[3])) !== null;) child.setAttribute(am[1], am[2]);
        if (/\bhidden\b/.test(m[3])) child.hidden = true;
        stack[stack.length - 1]._children.push(child);
        if (!/\/\s*>$/.test(m[0]) && !/^(img|input|br|hr)$/i.test(m[2])) stack.push(child);
      }
    },
  });
  return el;
}
['camera-recording-bar', 'rec-status-pill', 'rec-status-dot', 'rec-status-text', 'rec-camera-badge', 'rec-elapsed-val', 'rec-frames-val', 'rec-bytes-val', 'rec-filename-val', 'btn-record-start', 'btn-record-stop', 'btn-record-options-toggle', 'btn-record-open-studio', 'rec-options-panel', 'rec-filename-input', 'rec-fps-input', 'rec-max-duration-input', 'rec-max-frames-input', 'rec-annotated-toggle', 'active-camera-select', 'multi-grid-container', 'video-wrapper', 'live-stream-img', 'video-stream-title', 'header-fps-val', 'drawer-fps-val', 'stream-res-badge', 'kpi-active-tracks', 'kpi-total-crossed'].forEach(id => {
  const el = makeEl(id.includes('select') ? 'select' : (id.startsWith('btn-') ? 'button' : 'div'), id);
  if (id === 'rec-options-panel') el.hidden = true;
  if (id === 'rec-annotated-toggle') el.checked = true;
  if (id === 'camera-recording-bar') el.setAttribute('data-camera-id', 'cam_01');
  if (id === 'active-camera-select') { el.value = 'cam_01'; el.options = [{ value: 'cam_01' }, { value: 'cam_02' }]; }
  byId.set(id, el); rootContainers.push(el);
});
const navLiveTab = makeEl('button', 'tab-btn-live');
navLiveTab.setAttribute('class', 'nav-tab'); navLiveTab.setAttribute('data-tab', 'tab-live'); rootContainers.push(navLiveTab);
let activeCam = 'cam_01';
const routes = new Map();
const doc = {
  readyState: 'complete', hidden: false, getElementById: (id) => byId.get(id) || null,
  querySelectorAll: (sel) => { const parts = sel.split(',').map(s => s.trim()).filter(Boolean), pool = [...rootContainers]; rootContainers.forEach(r => collectDesc(r, pool)); return pool.filter(c => parts.some(p => matchSingle(c, p))); },
  querySelector: (sel) => doc.querySelectorAll(sel)[0] || null,
  addEventListener: (t, fn) => { if (!docListeners.has(t)) docListeners.set(t, []); docListeners.get(t).push(fn); },
};
function CustomEvent(type, init = {}) { this.type = type; this.detail = init.detail; }
function Event(type) { this.type = type; }
const sandbox = {
  console, Math, Number, String, Array, Object, Map, Set, JSON, Promise, Infinity, isNaN, parseFloat, parseInt, encodeURIComponent,
  CustomEvent, Event, document: doc, setInterval: () => 1, clearInterval: () => {},
  App: { getActiveCameraId: () => activeCam, switchCamera: (c) => { activeCam = c; } },
  VideoScrubber: { loadVideosList: async () => { videoListCalls.push(true); } },
  switchTab: (tab) => switchedTabs.push(tab),
  showToast: (title, msg, type, actionText, onAction) => toasts.push({ title, msg, type, actionText, hasAction: typeof onAction === 'function' }),
  fetch: async (url, opts = {}) => {
    fetchCalls.push({ url, method: opts.method || 'GET', body: opts.body ? JSON.parse(opts.body) : null });
    const handler = routes.get(`${opts.method || 'GET'} ${url}`);
    return handler ? handler(opts) : { ok: true, json: async () => ({ camera_id: activeCam, is_recording: false, status: 'idle', frames_written: 0, elapsed_s: 0, size_bytes: 0, filename: '' }) };
  },
};
sandbox.window = sandbox;
sandbox.addEventListener = (t, fn) => { if (!winListeners.has(t)) winListeners.set(t, []); winListeners.get(t).push(fn); };
sandbox.dispatchEvent = (ev) => { if (ev.type === 'video-select-request') selectEvents.push(ev.detail); return Promise.all((winListeners.get(ev.type) || []).map(fn => fn(ev))); };
vm.createContext(sandbox);
"""

_JS_RELOAD_SYNC = """
let calls = 0;
routes.set('GET /api/cameras/cam_01/record/status', () => {
  calls += 1;
  return { ok: true, json: async () => ({
    camera_id: 'cam_01', is_recording: true, status: 'recording', recording_id: 'rec1',
    filename: 'live_clip.mp4', frames_written: calls === 1 ? 45 : 90, elapsed_s: 2.5, size_bytes: calls === 1 ? 2048 : 4096,
  }) };
});
await sandbox.CameraRecording.syncStatus('cam_01');
const firstFrames = byId.get('rec-frames-val').textContent;
const firstBytes = byId.get('rec-bytes-val').textContent;
await navLiveTab.click();
await new Promise(r => setTimeout(r, 0));
console.log(JSON.stringify({
  firstFrames, firstBytes, statusText: byId.get('rec-status-text').textContent,
  elapsed: byId.get('rec-elapsed-val').textContent, secondFrames: byId.get('rec-frames-val').textContent,
  secondBytes: byId.get('rec-bytes-val').textContent, filename: byId.get('rec-filename-val').textContent,
  startDisabled: byId.get('btn-record-start').disabled, stopDisabled: byId.get('btn-record-stop').disabled,
}));
"""

_JS_START_STOP_STUDIO = """
byId.get('btn-record-options-toggle').click();
const panelOpenAfterToggle = !byId.get('rec-options-panel').hidden;
byId.get('rec-filename-input').value = 'front_door';
byId.get('rec-fps-input').value = '15';
byId.get('rec-max-duration-input').value = '30';
byId.get('rec-max-frames-input').value = '300';
byId.get('rec-annotated-toggle').checked = false;
routes.set('POST /api/cameras/cam_01/record/start', () => ({
  ok: true, json: async () => ({ camera_id: 'cam_01', is_recording: true, status: 'recording', recording_id: 'r2', filename: 'front_door.mp4', frames_written: 1, elapsed_s: 0.1, size_bytes: 512 })
}));
routes.set('POST /api/cameras/cam_01/record/stop', () => ({
  ok: true, json: async () => ({ camera_id: 'cam_01', is_recording: false, status: 'stopped', recording_id: 'r2', filename: 'front_door.mp4', frames_written: 60, elapsed_s: 4.0, size_bytes: 1048576 })
}));
await sandbox.CameraRecording.startRecording('cam_01');
await sandbox.CameraRecording.stopRecording('cam_01');
await byId.get('btn-record-open-studio').click();
await new Promise(r => setTimeout(r, 0));
sandbox.CameraRecording.stopPolling();
console.log(JSON.stringify({
  panelOpenAfterToggle, startCall: fetchCalls.find(c => c.url.endsWith('/record/start')),
  stopCall: fetchCalls.find(c => c.url.endsWith('/record/stop')), studioDisplay: byId.get('btn-record-open-studio').style.display,
  videoListCalls: videoListCalls.length, switchedTabs, selectEvents, lastToast: toasts[toasts.length - 1],
}));
"""

_JS_MISMATCH_TILE = """
const cams = [
  { id: 'cam_01', name: 'Front', status: 'online', fps: 20, active_tracks_count: 1, recording: { camera_id: 'cam_01', is_recording: false, status: 'idle' } },
  { id: 'cam_02', name: 'Rear', status: 'online', fps: 18, active_tracks_count: 0, recording: { camera_id: 'cam_02', is_recording: false, status: 'idle' } },
];
sandbox.CameraGrid.setGridMode('2x2', cams, 'cam_01', (id) => sandbox.App.switchCamera(id));
routes.set('POST /api/cameras/cam_02/record/start', () => ({
  ok: true, json: async () => ({ camera_id: 'cam_02', is_recording: true, status: 'recording', recording_id: 'bg2', filename: 'cam2.mp4', frames_written: 5, elapsed_s: 0.3, size_bytes: 2048 })
}));
const tileBtn2 = byId.get('multi-grid-container').querySelector('.btn-tile-record[data-camera-id="cam_02"]');
await tileBtn2.click();
await new Promise(r => setTimeout(r, 0));
sandbox.TelemetryGateway.updateKpiDisplays({ camera_id: 'cam_02', fps: 18, resolution: '640x480', recording: { camera_id: 'cam_02', is_recording: true, status: 'recording', frames_written: 77, elapsed_s: 4.0, size_bytes: 8192, filename: 'cam2.mp4' } }, 0, 0);
sandbox.TelemetryGateway.updateKpiDisplays({ camera_id: 'cam_01', fps: 20, resolution: '640x480', recording: { camera_id: 'cam_02', is_recording: true, status: 'recording', frames_written: 99, elapsed_s: 5.0, size_bytes: 9999, filename: 'wrong.mp4' } }, 1, 0);
sandbox.CameraRecording.stopPolling();
const tileBadge2 = byId.get('multi-grid-container').querySelector('.tile-rec-badge[data-camera-id="cam_02"]');
console.log(JSON.stringify({
  activeCamAfterTileClick: activeCam, barCamId: byId.get('camera-recording-bar').getAttribute('data-camera-id'),
  barStatus: byId.get('rec-status-text').textContent, barFrames: byId.get('rec-frames-val').textContent,
  tileBtn2Text: tileBtn2.textContent, tileBadge2Hidden: tileBadge2.hidden, cam2CachedFrames: sandbox.CameraRecording.getCachedStatus('cam_02').frames_written,
}));
"""


class TestCameraRecordingUIPartialAndPool(unittest.TestCase):
    """Verify Jinja2 recording partial rendering, pool status wiring, and modularity budgets."""

    def test_index_renders_recording_partial_and_assets(self):
        """GET / renders #camera-recording-bar, all inputs/buttons, and dedicated CSS/JS assets."""
        resp = TestClient(app).get("/")
        self.assertEqual(resp.status_code, 200)
        for token in (
            'id="camera-recording-bar"', 'id="btn-record-start"', 'id="btn-record-stop"',
            'id="btn-record-options-toggle"', 'id="btn-record-open-studio"', 'id="rec-options-panel"',
            'id="rec-filename-input"', 'id="rec-fps-input"', 'id="rec-max-duration-input"',
            'id="rec-max-frames-input"', 'id="rec-annotated-toggle"',
            '/static/css/camera_recording.css', '/static/js/camera_recording.js',
        ):
            self.assertIn(token, resp.text)

    def test_camera_pool_status_row_includes_recording_dict(self):
        """build_camera_status_row exposes idle fallback and active telemetry recording status."""
        idle_row = build_camera_status_row("cam_01", {"name": "Cam 1"}, None)
        self.assertFalse(idle_row["recording"]["is_recording"])
        self.assertEqual(idle_row["recording"]["status"], "idle")

        mgr = MagicMock(is_running=True, video_source=None)
        mgr.get_latest_telemetry.return_value = {
            "fps": 20.0, "active_tracks": [],
            "recording": {"camera_id": "cam_01", "is_recording": True, "status": "recording", "frames_written": 12},
        }
        active_row = build_camera_status_row("cam_01", {"name": "Cam 1"}, mgr)
        self.assertTrue(active_row["recording"]["is_recording"])
        self.assertEqual(active_row["recording"]["frames_written"], 12)

    def test_css_and_js_modularity_budgets(self):
        """Dedicated recording CSS/JS/partial stay under 350 lines with zero !important rules."""
        css_text = (CSS_DIR / "camera_recording.css").read_text(encoding="utf-8")
        js_text = (JS_DIR / "camera_recording.js").read_text(encoding="utf-8")
        partial_text = (TEMPLATES_DIR / "partials" / "camera_recording_bar.html").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"!important\b", css_text, re.IGNORECASE)), 0)
        self.assertLess(len(css_text.splitlines()), 350)
        self.assertLess(len(js_text.splitlines()), 350)
        self.assertLess(len(partial_text.splitlines()), 100)


class TestCameraRecordingNodeVMRuntime(unittest.TestCase):
    """Execute camera_recording.js, telemetry.js, and camera_grid.js in Node.js VM."""

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS runtime verification")
    def _run_node_vm(self, files: list[str], body: str) -> dict:
        script = "\n".join([
            _NODE_VM_PRELUDE,
            "JSON.parse(process.env.JS_FILES).forEach(f => vm.runInContext(fs.readFileSync(path.join(jsDir, f), 'utf8'), sandbox, { filename: f }));",
            "(async () => {", body, "})().catch(err => { console.error(err); process.exit(1); });",
        ])
        env = dict(os.environ, JS_DIR=str(JS_DIR), JS_FILES=json.dumps(files))
        proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, env=env, timeout=15)
        self.assertEqual(proc.returncode, 0, f"Node VM error:\nSTDOUT:{proc.stdout}\nSTDERR:{proc.stderr}")
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_page_reload_and_tab_switch_sync_live_indicators(self):
        """Initial load and returning to Live Monitor tab sync status/frames/bytes/elapsed."""
        out = self._run_node_vm(["camera_recording.js"], _JS_RELOAD_SYNC)
        self.assertEqual(out["statusText"], "RECORDING")
        self.assertEqual(out["firstFrames"], "45 frames")
        self.assertEqual(out["firstBytes"], "2.0 KB")
        self.assertEqual(out["elapsed"], "00:02.5")
        self.assertEqual(out["secondFrames"], "90 frames")
        self.assertEqual(out["secondBytes"], "4.0 KB")
        self.assertEqual(out["filename"], "live_clip.mp4")
        self.assertTrue(out["startDisabled"])
        self.assertFalse(out["stopDisabled"])

    def test_start_options_stop_and_studio_handoff(self):
        """Options toggle, start payload serialization, stop, and Video Studio handoff work end-to-end."""
        out = self._run_node_vm(["camera_recording.js"], _JS_START_STOP_STUDIO)
        self.assertTrue(out["panelOpenAfterToggle"])
        self.assertEqual(
            out["startCall"]["body"],
            {"filename": "front_door", "fps": 15, "max_duration_s": 30, "max_frames": 300, "annotated": False},
        )
        self.assertIsNotNone(out["stopCall"])
        self.assertEqual(out["studioDisplay"], "inline-flex")
        self.assertGreaterEqual(out["videoListCalls"], 2)
        self.assertEqual(out["switchedTabs"], ["tab-videos"])
        self.assertEqual(out["selectEvents"], [{"filename": "front_door.mp4"}])
        self.assertTrue(out["lastToast"]["hasAction"])

    def test_camera_id_mismatch_guard_and_grid_tile_isolation(self):
        """Background camera recording updates do not overwrite focused cam_01 recording bar."""
        out = self._run_node_vm(["camera_grid.js", "telemetry.js", "camera_recording.js"], _JS_MISMATCH_TILE)
        self.assertEqual(out["activeCamAfterTileClick"], "cam_01")
        self.assertEqual(out["barCamId"], "cam_01")
        self.assertEqual(out["barStatus"], "IDLE")
        self.assertEqual(out["barFrames"], "0 frames")
        self.assertEqual(out["tileBtn2Text"], "⏹ Stop")
        self.assertFalse(out["tileBadge2Hidden"])
        self.assertEqual(out["cam2CachedFrames"], 77)


if __name__ == "__main__":
    unittest.main()
