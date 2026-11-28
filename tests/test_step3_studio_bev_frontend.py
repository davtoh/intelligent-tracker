"""Node VM frontend tests for Step 3 Milestone 2: #alerts Clip @ MM:SS deep-links & H.264 pairing."""

import json
from pathlib import Path
import subprocess
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_node(script: str) -> dict:
    proc = subprocess.run(
        ["node", "-e", script],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    if proc.returncode != 0:
        raise AssertionError(f"Node script failed ({proc.returncode}): {proc.stderr}")
    return json.loads(proc.stdout.strip())


class TestStep3AlertsClipDeepLinksFrontend(unittest.TestCase):
    """Node VM tests verifying Clip @ MM:SS rendering and _h264.mp4 pair resolution."""

    def test_clip_button_renders_mmss_and_resolves_paired_h264(self) -> None:
        """buildSeekInStudioButtonHtml renders '▶ Clip @ MM:SS' and resolves paired H.264 clips."""
        script = r"""
const fs = require('fs');
const vm = require('vm');
let switched = null;
let dispatched = null;
const pairs = { 'live_clip.mp4': { convertedFilename: 'live_clip_h264.mp4' } };
const sandbox = {
  window: {
    switchTab: (t) => { switched = t; },
    dispatchEvent: (ev) => { dispatched = ev; },
    VideoLibrary: { getPairedH264: (fn) => pairs[fn] || null },
  },
  CustomEvent: class { constructor(t, i) { this.type = t; this.detail = i?.detail; } },
  document: { getElementById: () => null },
};
vm.runInNewContext(fs.readFileSync('dashboard/static/js/video_timeline_links.js', 'utf8'), sandbox);
const html = sandbox.window.VideoTimelineLinks.buildSeekInStudioButtonHtml('live_clip.mp4', 75.4);
const ok = sandbox.window.VideoTimelineLinks.seekToVideoTimestamp('live_clip.mp4', 75.4);
const plainHtml = sandbox.window.VideoTimelineLinks.buildSeekInStudioButtonHtml('native.mp4', 5);
process.stdout.write(JSON.stringify({ html, plainHtml, ok, switched, detail: dispatched?.detail }));
"""
        res = _run_node(script)
        self.assertTrue(res["ok"])
        self.assertIn("▶ Clip @ 01:15", res["html"])
        self.assertIn('class="btn btn-xs btn-outline btn-seek-studio"', res["html"])
        self.assertIn('data-video-filename="live_clip_h264.mp4"', res["html"])
        self.assertIn('data-offset-sec="75.40"', res["html"])
        self.assertIn("▶ Clip @ 00:05", res["plainHtml"])
        self.assertEqual(res["switched"], "tab-videos")
        self.assertEqual(res["detail"], {"filename": "live_clip_h264.mp4", "offsetSec": 75.4})

    def test_alerts_view_renders_clip_jump_for_recorded_live_alert(self) -> None:
        """AlertsView renders '▶ Clip @ MM:SS' with paired H.264 resolution for recorded alerts."""
        script = r"""
const fs = require('fs');
const vm = require('vm');
const tbody = { innerHTML: '' };
const payload = {
  items: [
    { id: 1, timestamp: 1700000100, event_type: 'zone_enter', severity: 'warning', camera_id: 'cam_01',
      zone_id: 'vault', entity_name: 'Alice', message: 'Entered vault',
      video_filename: 'cam01_rec.mp4', media_offset_sec: 12.5, is_read: false, metadata: {} },
    { id: 2, timestamp: 1700000105, event_type: 'zone_exit', severity: 'info', camera_id: 'cam_01',
      zone_id: 'vault', entity_name: 'Bob', message: 'Exited vault', is_read: true, metadata: {} },
  ],
  total: 2, has_more: false, unread_alert_count: 1,
};
const sandbox = {
  window: { VideoLibrary: { getPairedH264: (fn) => (fn === 'cam01_rec.mp4' ? { convertedFilename: 'cam01_rec_h264.mp4' } : null) } },
  document: { getElementById: (id) => (id === 'alerts-table-body' ? tbody : null) },
  fetch: async () => ({ ok: true, json: async () => payload }),
  URLSearchParams, console,
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('dashboard/static/js/video_timeline_links.js', 'utf8'), sandbox);
vm.runInContext(fs.readFileSync('dashboard/static/js/alerts_view.js', 'utf8'), sandbox);
(async () => {
  await vm.runInContext('window.AlertsView.loadAlerts({ filters: {} })', sandbox);
  process.stdout.write(JSON.stringify({ html: tbody.innerHTML }));
})();
"""
        html = _run_node(script)["html"]
        self.assertIn("▶ Clip @ 00:12", html)
        self.assertIn('data-video-filename="cam01_rec_h264.mp4"', html)
        self.assertIn('data-offset-sec="12.50"', html)
        self.assertEqual(html.count("btn-seek-studio"), 1)


class TestStep3StudioModalsAndBevMinimapFrontend(unittest.TestCase):
    """Node VM tests for OBS-024/026/027 Studio edit modals, FOV polygons, and BEV Quad filtering."""

    def test_studio_edit_zone_and_tripwire_modals_submit_full_put_payloads(self) -> None:
        """Clicking edit opens #modal-studio-zone / #modal-studio-tripwire pre-filled and PUTs full metadata."""
        script = r"""
const fs = require('fs');
const vm = require('vm');
const els = {};
const mkEl = (id, val = '') => {
  const listeners = {};
  const el = {
    id, value: val, style: { display: 'none' }, textContent: '',
    addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
    dispatch: (ev, arg = {}) => (listeners[ev] || []).forEach((fn) => fn({ preventDefault() {}, ...arg })),
    querySelector: () => ({ textContent: '' }),
  };
  els[id] = el;
  return el;
};
['modal-studio-zone','studio-zone-form','modal-zone-close','modal-zone-cancel','btn-modal-zone-save',
 'modal-zone-name-input','modal-zone-category-select','modal-zone-dwell-input','modal-zone-capacity-input',
 'modal-studio-tripwire','studio-tripwire-form','modal-tripwire-close','modal-tripwire-cancel','btn-modal-tripwire-save',
 'modal-tripwire-name-input','modal-tripwire-bidir-select'].forEach((id) => mkEl(id));
const puts = [];
const state = {
  activeCamera: 'cam_01', mode: 'idle',
  zones: [{ name: 'lobby', polygon: [[0,0],[10,0],[10,10]], category_filter: 'vip', dwell_threshold: 8, capacity_limit: 5 }],
  tripwires: [{ name: 'gate', line_segment: [[0,0],[10,10]], bidirectional: true }],
};
const sandbox = {
  window: { StudioOverlays: { renderScenarioListUI: () => {} } },
  document: { getElementById: (id) => els[id] || null },
  fetch: async (url, opts) => { puts.push({ url, method: opts.method, body: JSON.parse(opts.body) }); return { ok: true, json: async () => ({}) }; },
  console,
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('dashboard/static/js/scenario_modals.js', 'utf8'), sandbox);
vm.runInContext(fs.readFileSync('dashboard/static/js/studio_shape_editor.js', 'utf8'), sandbox);
(async () => {
  sandbox.window.ScenarioModals.init({});
  sandbox.window.StudioShapeEditor.init(() => state, { drawOverlay: () => {}, updateStatus: () => {}, showToast: () => {} });
  await sandbox.window.StudioShapeEditor.renameShape('zone', 'cam_01', 'lobby');
  const zPre = [els['modal-studio-zone'].style.display, els['modal-zone-name-input'].value, els['modal-zone-category-select'].value, els['modal-zone-dwell-input'].value, els['modal-zone-capacity-input'].value];
  els['modal-zone-name-input'].value = 'lobby_2';
  els['modal-zone-category-select'].value = 'staff';
  els['modal-zone-dwell-input'].value = '12.5';
  els['modal-zone-capacity-input'].value = '10';
  els['studio-zone-form'].dispatch('submit');
  await new Promise((r) => setTimeout(r, 10));
  await sandbox.window.StudioShapeEditor.renameShape('tripwire', 'cam_01', 'gate');
  const twPre = [els['modal-studio-tripwire'].style.display, els['modal-tripwire-name-input'].value, els['modal-tripwire-bidir-select'].value];
  els['modal-tripwire-name-input'].value = 'gate_out';
  els['modal-tripwire-bidir-select'].value = '0';
  els['studio-tripwire-form'].dispatch('submit');
  await new Promise((r) => setTimeout(r, 10));
  process.stdout.write(JSON.stringify({ zPre, twPre, puts, zone: state.zones[0], tw: state.tripwires[0] }));
})();
"""
        res = _run_node(script)
        self.assertEqual(res["zPre"], ["flex", "lobby", "vip", "8", "5"])
        self.assertEqual(res["twPre"], ["flex", "gate", "1"])
        self.assertEqual(res["puts"][0]["url"], "/api/scenarios/zones/cam_01/lobby")
        self.assertEqual(res["puts"][0]["body"], {"name": "lobby_2", "category_filter": "staff", "dwell_threshold": 12.5, "capacity_limit": 10})
        self.assertEqual(res["puts"][1]["url"], "/api/scenarios/tripwires/cam_01/gate")
        self.assertEqual(res["puts"][1]["body"], {"name": "gate_out", "bidirectional": False})
        self.assertEqual(res["zone"]["name"], "lobby_2")
        self.assertFalse(res["tw"]["bidirectional"])

    def test_world_minimap_renders_fov_corners_global_and_filters_by_bev_quad_mode(self) -> None:
        """WorldMinimapFovHelper draws calibrated fov_corners_global polygons and obeys bevQuadMode."""
        script = r"""
const fs = require('fs');
const vm = require('vm');
const makeCtx = () => {
  const ops = [];
  return {
    ops,
    clearRect() {}, fillRect() {}, beginPath() {}, closePath() {}, save() {}, restore() {}, setLineDash() {},
    moveTo(x, y) { ops.push(['moveTo', x, y]); },
    lineTo(x, y) { ops.push(['lineTo', x, y]); },
    arc(x, y, r, s, e) { ops.push(['arc', r, Math.round((e - s) * 100)]); },
    fill() { ops.push(['fill']); },
    stroke() { ops.push(['stroke']); },
    fillText() {},
  };
};
const sandbox = { window: {}, document: { getElementById: () => null }, console };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('dashboard/static/js/world_minimap_fov_helper.js', 'utf8'), sandbox);
vm.runInContext(fs.readFileSync('dashboard/static/js/world_minimap.js', 'utf8'), sandbox);
const data = {
  bounds: { min_x: 0, min_y: 0, max_x: 20, max_y: 20 },
  cameras: [
    { camera_id: 'cam_cal', calibrated: true, world_pose: { origin_x: 5, origin_y: 8, yaw_deg: -90, fov_deg: 75, range_m: 10 },
      fov_corners_global: [[0, 0], [10, 0], [10, 8], [0, 8]] },
    { camera_id: 'cam_uncal', calibrated: false, world_pose: { origin_x: 16, origin_y: 0, yaw_deg: 0, fov_deg: 75, range_m: 10 },
      fov_corners_global: [] },
  ],
  zones: [], transitions: [], entities: [],
};
const runMode = (mode) => {
  const ctx = makeCtx();
  sandbox.window.WorldTacticalMinimapView.setBevQuadMode(mode);
  sandbox.window.WorldTacticalMinimapView.render({ width: 320, height: 320, getContext: () => ctx }, data, 'cam_cal');
  const polyLines = ctx.ops.filter((o) => o[0] === 'lineTo').length - 10; // minus 10 grid lines
  const coneArcs = ctx.ops.filter((o) => o[0] === 'arc' && o[2] < 600).length;
  return { polyLines, coneArcs };
};
process.stdout.write(JSON.stringify({ all: runMode('all'), selected: runMode('selected'), off: runMode('off') }));
"""
        res = _run_node(script)
        self.assertEqual(res["all"], {"polyLines": 3, "coneArcs": 1})
        self.assertEqual(res["selected"], {"polyLines": 3, "coneArcs": 0})
        self.assertEqual(res["off"], {"polyLines": 0, "coneArcs": 0})

    def test_studio_bev_quad_toggle_and_post_homography_minimap_force_refresh(self) -> None:
        """Studio.setBevQuadMode syncs WorldTacticalMinimapView and saveHomographyCalibration bypasses 750ms throttle."""
        script = r"""
const fs = require('fs');
const vm = require('vm');
let worldMapFetches = 0;
const btnQuad = { textContent: '', dataset: {}, setAttribute() {}, addEventListener() {} };
const bevCanvas = { width: 320, height: 320, getContext: () => ({ clearRect(){}, fillRect(){}, beginPath(){}, closePath(){}, moveTo(){}, lineTo(){}, arc(){}, fill(){}, stroke(){}, fillText(){}, save(){}, restore(){}, setLineDash(){} }) };
const els = { 'btn-studio-bev-quad-toggle': btnQuad, 'bev-minimap-canvas': bevCanvas, 'studio-status-banner': { textContent: '', style: {} } };
const sandbox = {
  window: { addEventListener() {}, StudioCanvas: { drawOverlay() {} }, showToast() {} },
  document: {
    getElementById: (id) => els[id] || null,
    querySelectorAll: () => [],
    addEventListener: () => {},
  },
  fetch: async (url) => {
    if (url === '/api/topology/world-map') {
      worldMapFetches += 1;
      return { ok: true, json: async () => ({ bounds: [0,0,20,20], cameras: [{ camera_id: 'cam_01', calibrated: true, world_pose: { origin_x: 5, origin_y: 8, yaw_deg: -90 } }], zones: [], transitions: [], entities: [] }) };
    }
    return { ok: true, json: async () => ({ status: 'success', homography: { is_calibrated: true } }) };
  },
  setInterval: () => 1, clearInterval() {}, Date, console,
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('dashboard/static/js/world_minimap_fov_helper.js', 'utf8'), sandbox);
vm.runInContext(fs.readFileSync('dashboard/static/js/world_minimap.js', 'utf8'), sandbox);
vm.runInContext(fs.readFileSync('dashboard/static/studio.js', 'utf8'), sandbox);
(async () => {
  await sandbox.window.WorldTacticalMinimapView.fetchAndRender(bevCanvas, 'cam_01', null, []);
  const afterFirst = worldMapFetches;
  sandbox.window.Studio.setBevQuadMode('selected');
  const quadMode = sandbox.window.WorldTacticalMinimapView.getBevQuadMode();
  await sandbox.window.Studio.saveHomographyCalibration({ camera_id: 'cam_01', src_points: [[0,0],[10,0],[10,10],[0,10]], metric_width: 10, metric_height: 8 });
  await new Promise((r) => setTimeout(r, 10));
  process.stdout.write(JSON.stringify({ afterFirst, afterSave: worldMapFetches, quadMode }));
})();
"""
        res = _run_node(script)
        self.assertEqual(res["quadMode"], "selected")
        self.assertEqual(res["afterFirst"], 1)
        self.assertGreaterEqual(res["afterSave"], 2)


if __name__ == "__main__":
    unittest.main()
