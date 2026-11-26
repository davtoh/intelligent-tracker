"""Node VM & contract tests for Step 1 Milestone 2 frontend P0/P1 seams."""

import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "dashboard" / "static"


_VM_PREAMBLE = """
const fs = require('fs');
const vm = require('vm');
const byId = new Map();
function makeEl(id, tag = 'div') {
  const listeners = {};
  const cls = new Set();
  return {
    id, tagName: tag.toUpperCase(), value: '', textContent: '', innerHTML: '', title: '', src: '',
    width: 640, height: 480, checked: false, disabled: false, hidden: false, style: {}, dataset: {}, options: [], children: [],
    classList: { add: (c) => cls.add(c), remove: (c) => cls.delete(c), toggle: (c, f) => (f === undefined ? (cls.has(c) ? cls.delete(c) : cls.add(c)) : (f ? cls.add(c) : cls.delete(c))), contains: (c) => cls.has(c) },
    getAttribute: (k) => (k === 'data-tab' ? id : null),
    setAttribute: () => {},
    removeAttribute: () => {},
    addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
    dispatchEvent: (ev) => { (listeners[ev.type || ev] || []).forEach((fn) => fn(ev)); },
    click: () => { (listeners.click || []).forEach((fn) => fn({ preventDefault() {}, stopPropagation() {} })); },
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 640, height: 480 }),
    getContext: () => ({ clearRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {}, fill() {}, arc() {}, closePath() {}, save() {}, restore() {}, fillText() {}, fillRect() {}, strokeRect() {}, drawImage() {} }),
    toDataURL: () => 'data:image/jpeg;base64,AAA',
    querySelector: () => null,
    querySelectorAll: () => [],
    appendChild: (c) => c,
    focus: () => {},
  };
}
const winListeners = {};
const docListeners = {};
const sandbox = {
  console, Math, Date, Number, String, Boolean, Array, Object, Set, Map, JSON, URLSearchParams, encodeURIComponent, decodeURIComponent,
  parseFloat, isNaN, Promise, setTimeout, clearTimeout, setInterval: () => 1, clearInterval: () => {},
  byId, makeEl, winListeners, docListeners, process,
  Event: function (type) { this.type = type; },
  localStorage: { getItem: () => null, setItem: () => {} },
  history: { pushState: (_s, _t, url) => { sandbox.location.hash = url; } },
  location: { hash: '', protocol: 'http:', host: 'localhost:8000' },
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  document: {
    readyState: 'complete',
    getElementById: (id) => byId.get(id) || null,
    querySelector: () => null,
    querySelectorAll: (sel) => (sel === '.nav-tab' ? [makeEl('tab-live'), makeEl('tab-studio'), makeEl('tab-timeline')] : sel === '.tab-pane' ? [makeEl('tab-live'), makeEl('tab-studio'), makeEl('tab-timeline')] : []),
    createElement: (tag) => makeEl('tmp', tag),
    addEventListener: (ev, fn) => { (docListeners[ev] = docListeners[ev] || []).push(fn); },
  },
  addEventListener: (ev, fn) => { (winListeners[ev] = winListeners[ev] || []).push(fn); },
  removeEventListener: () => {},
  scrollTo: () => {},
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.sandbox = sandbox;
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


class TestStep1SeamsFrontend(unittest.TestCase):
    """Verify Milestone 2 frontend P0/P1 seams in Node VM and HTML/CSS contracts."""

    def test_app_navigate_hash_routing_and_switch_camera_sync(self) -> None:
        body = """
        ['live-stream-img','interactive-canvas','connection-status-pill','connection-status-text','header-alert-badge','active-camera-select','video-stream-title','studio-camera-select','tab-live','tab-studio','tab-timeline'].forEach((id) => byId.set(id, makeEl(id)));
        const focused = [], wsCams = [];
        sandbox.CameraManager = { focusCamera: (id) => focused.push(id) };
        sandbox.TelemetryGateway = { initWebSocket: (c) => wsCams.push(c), closeWebSocket() {}, updateKpiDisplays() {}, updateConnectionStatus() {} };
        sandbox.LivePlayer = { attachLiveStream(img, cam) { img.src = '/stream/' + cam; }, detachLiveStream() {}, isPaused: () => false, bindHudButtons() {} };
        sandbox.Studio = { loadStudioChannels: async () => { byId.get('studio-camera-select').options = [{ value: 'cam_02' }]; }, renderBEV() {} };
        docListeners.DOMContentLoaded.forEach((fn) => fn());
        await sandbox.App.navigate('tab-live', { cameraId: 'cam_02' });
        const liveHash = sandbox.location.hash;
        const liveImgSrc = byId.get('live-stream-img').src;
        const selVal = byId.get('active-camera-select').value;
        const titleVal = byId.get('video-stream-title').textContent;
        await sandbox.App.navigate('tab-studio', { cameraId: 'cam_02', zoneId: 'vault' });
        const studioHash = sandbox.location.hash;
        const studioCam = byId.get('studio-camera-select').value;
        console.log(JSON.stringify({ liveHash, liveImgSrc, selVal, titleVal, focused, wsCams, studioHash, studioCam }));
        """
        res = _run_vm([STATIC_DIR / "js" / "app_navigation.js", STATIC_DIR / "app.js"], body)
        self.assertEqual(res["liveHash"], "#live?camera=cam_02")
        self.assertEqual(res["liveImgSrc"], "/stream/cam_02")
        self.assertEqual(res["selVal"], "cam_02")
        self.assertIn("cam_02", res["titleVal"])
        self.assertEqual(res["focused"], ["cam_02"])
        self.assertEqual(res["studioHash"], "#studio?camera=cam_02&zone=vault")
        self.assertEqual(res["studioCam"], "cam_02")

    def test_timeline_filters_awaited_and_time_range_wired(self) -> None:
        body = """
        ['timeline-entity-select','timeline-zone-select','timeline-source-select','timeline-limit-select','sightings-timeline-list','timeline-prev-btn','timeline-next-btn','timeline-page-info'].forEach((id) => byId.set(id, makeEl(id)));
        byId.get('timeline-limit-select').value = '50';
        const urls = [];
        sandbox.fetch = async (url) => {
          urls.push(url);
          if (url === '/entities') return { ok: true, json: async () => ([{ id: 1, name: 'Alice', category: 'person' }]) };
          if (url === '/zones') return { ok: true, json: async () => ([{ name: 'vault' }]) };
          if (url === '/sightings/sources') return { ok: true, json: async () => (['cam_a']) };
          return { ok: true, json: async () => ({ items: [], total: 0, has_more: false }) };
        };
        await sandbox.AppNavigation.navigate('tab-timeline', { source: 'cam_a', from: 100, to: 200 });
        console.log(JSON.stringify({ urls, srcVal: byId.get('timeline-source-select').value }));
        """
        res = _run_vm([STATIC_DIR / "js" / "app_navigation.js", STATIC_DIR / "js" / "gallery_timeline.js"], body)
        sighting_urls = [u for u in res["urls"] if u.startswith("/sightings?")]
        self.assertTrue(sighting_urls)
        self.assertIn("start_time=100", sighting_urls[-1])
        self.assertIn("end_time=200", sighting_urls[-1])
        self.assertIn("source=cam_a", sighting_urls[-1])

    def test_studio_points_changed_vertical_drag_and_window_release(self) -> None:
        body = """
        const canvas = makeEl('studio-drawing-canvas', 'canvas');
        byId.set('studio-drawing-canvas', canvas);
        let putBody = null;
        sandbox.fetch = async (_u, opts) => { putBody = JSON.parse(opts.body); return { ok: true, json: async () => ({}) }; };
        const state = { activeCamera: 'cam_1', mode: 'idle', zones: [{ name: 'z1', polygon: [[10, 10], [50, 10], [50, 50], [10, 50]] }], tripwires: [] };
        sandbox.StudioShapeEditor.init(() => state, { drawOverlay() {}, updateStatus() {}, showToast() {} });
        sandbox.StudioCanvas.setupListeners(canvas, {
          onMouseDown: (pt) => sandbox.StudioShapeEditor.onMouseDown(pt),
          onMouseMove: (pt) => sandbox.StudioShapeEditor.onMouseMove(pt),
          onMouseUp: (pt) => sandbox.StudioShapeEditor.onMouseUp(pt),
        });
        canvas.dispatchEvent({ type: 'pointerdown', clientX: 50, clientY: 50, pointerId: 1 });
        canvas.dispatchEvent({ type: 'pointermove', clientX: 50, clientY: 95 });
        winListeners.pointerup.forEach((fn) => fn({ type: 'pointerup', clientX: 50, clientY: 95, currentTarget: sandbox }));
        await new Promise((r) => setTimeout(r, 0));
        console.log(JSON.stringify({ putBody }));
        """
        res = _run_vm([STATIC_DIR / "js" / "studio_shape_editor.js", STATIC_DIR / "js" / "studio_canvas.js"], body)
        self.assertIsNotNone(res["putBody"])
        self.assertEqual(res["putBody"]["polygon"][2], [50, 95])

    def test_live_player_poster_percent_encoded_and_resume_reattach(self) -> None:
        body = """
        const img = makeEl('live-stream-img', 'img');
        byId.set('live-stream-img', img);
        byId.set('btn-stream-pause-play', makeEl('btn-stream-pause-play'));
        byId.set('btn-stream-reconnect', makeEl('btn-stream-reconnect'));
        sandbox.LivePlayer.bindHudButtons(img, () => 'cam_1');
        byId.get('btn-stream-pause-play').click();
        const pausedSrc = img.src;
        sandbox.LivePlayer.attachLiveStream(img, 'cam_1', true);
        const resumedSrc = img.src;
        console.log(JSON.stringify({ standby: sandbox.LivePlayer.STANDBY_POSTER_SVG, pausedSrc, resumedSrc }));
        """
        res = _run_vm([STATIC_DIR / "js" / "live_player.js"], body)
        self.assertNotIn("&bull;", res["standby"])
        self.assertIn("%E2%80%A2", res["standby"])
        self.assertIn("data:image/svg+xml", res["pausedSrc"])
        self.assertIn("/stream/cam_1?annotated=false", res["resumedSrc"])

    def test_telemetry_connection_pill_and_enrollment_scrubber_seek(self) -> None:
        body = """
        const pill = makeEl('connection-status-pill'), txt = makeEl('connection-status-text');
        const drawer = makeEl('drawer-connection-status-pill');
        const dSpan = makeEl('d-span'); drawer.querySelector = () => dSpan;
        byId.set('connection-status-pill', pill); byId.set('connection-status-text', txt); byId.set('drawer-connection-status-pill', drawer);
        const statuses = [];
        ['hibernating', 'simulation', 'offline', 'online'].forEach((st) => {
          sandbox.TelemetryGateway.updateConnectionStatus({ status: st, camera_id: 'cam_1' });
          statuses.push({ cls: pill.className, txt: txt.textContent, dCls: drawer.className });
        });
        const studVid = makeEl('scrubber-video-player', 'video'); studVid.currentTime = 14.5;
        const enrVid = makeEl('enroll-scrubber-video', 'video'); enrVid.videoWidth = 320; enrVid.videoHeight = 240; enrVid.duration = 30;
        const box = makeEl('enroll-video-scrubber-box'); const cnv = makeEl('enroll-bbox-canvas', 'canvas');
        ['scrubber-video-player','enroll-scrubber-video','enroll-video-scrubber-box','enroll-bbox-canvas','enroll-scrubber-slider','enroll-scrubber-time','enroll-scrubber-play','enroll-scrubber-prev','enroll-scrubber-next','enroll-scrubber-grab'].forEach((id) => { if (!byId.has(id)) byId.set(id, id === 'scrubber-video-player' ? studVid : id === 'enroll-scrubber-video' ? enrVid : makeEl(id)); });
        let captured = 0;
        sandbox.ScrubberTimelineSlider.mountEnrollmentScrubber('/videos/clip.mp4', cnv, null, () => { captured += 1; });
        enrVid.dispatchEvent({ type: 'loadedmetadata' });
        enrVid.dispatchEvent({ type: 'loadeddata' });
        console.log(JSON.stringify({ statuses, seekedTime: enrVid.currentTime, captured }));
        """
        res = _run_vm(
            [STATIC_DIR / "js" / "telemetry.js", STATIC_DIR / "js" / "enrollment_stage_controller.js", STATIC_DIR / "js" / "scrubber_timeline_slider.js"],
            body,
        )
        self.assertEqual([s["cls"] for s in res["statuses"]], [
            "connection-status-pill hibernating",
            "connection-status-pill simulation",
            "connection-status-pill offline",
            "connection-status-pill online",
        ])
        self.assertEqual(res["seekedTime"], 14.5)
        self.assertGreaterEqual(res["captured"], 1)

    def test_detector_panel_payload_and_alerts_row_selection(self) -> None:
        body = """
        ['cam-detector-select','cam-tracker-select','cam-conf-range','cam-conf-input','cam-conf-display','cam-classes-input','cam-coco-class-select','cam-armed-checkbox','cam-agnostic-nms-checkbox'].forEach((id) => byId.set(id, makeEl(id)));
        byId.get('cam-detector-select').value = 'yolov8';
        byId.get('cam-tracker-select').value = 'sort';
        byId.get('cam-conf-input').value = '0.45';
        byId.get('cam-agnostic-nms-checkbox').checked = true;
        sandbox.fetch = async (url) => {
          if (url === '/api/system/capabilities') return { ok: true, json: async () => ({ detectors: ['yolov8'], trackers: ['sort'], coco_classes: ['person', 'car'] }) };
          return { ok: true, json: async () => ({ unread_alert_count: 0, deleted: 2 }) };
        };
        await sandbox.CameraAIConfig.init();
        const detVals = sandbox.CameraAIConfig.getValues();
        sandbox.AlertsView.state.eventsByIndex = [{ id: 10 }, { id: 11 }];
        sandbox.AlertsView.toggleSelectAllVisible(true);
        const ackCalls = [];
        sandbox.AlertsAdmin = { acknowledgeEvents: async (p) => ackCalls.push(p), clearMatchingEvents: async (f) => ackCalls.push({ clear: f }), deleteEvent: async (id) => ackCalls.push({ del: id }) };
        await sandbox.AlertsView.bulkAckSelected(true);
        sandbox.AlertsView.toggleSelectAllMatching(true);
        await sandbox.AlertsView.bulkDeleteSelected();
        console.log(JSON.stringify({ detVals, cocoHtml: byId.get('cam-coco-class-select').innerHTML, ackCalls }));
        """
        res = _run_vm(
            [STATIC_DIR / "js" / "detector_config_panel.js", STATIC_DIR / "js" / "camera_ai_config.js", STATIC_DIR / "js" / "alerts_view.js"],
            body,
        )
        self.assertIsNone(res["detVals"]["classes"])
        self.assertTrue(res["detVals"]["agnostic_nms"])
        self.assertIn("person", res["cocoHtml"])
        self.assertEqual(res["ackCalls"][0], {"eventIds": [10, 11], "isRead": True})
        self.assertIn("clear", res["ackCalls"][1])

    def test_modal_grid_and_studio_banner_html_css_contracts(self) -> None:
        modals_css = (STATIC_DIR / "css" / "modals.css").read_text(encoding="utf-8")
        entity_html = (STATIC_DIR / "partials" / "modals" / "entity_modals.html").read_text(encoding="utf-8")
        studio_html = (STATIC_DIR / "partials" / "tabs" / "studio.html").read_text(encoding="utf-8")
        self.assertIn("minmax(min(100%, 440px), 1fr)", modals_css)
        self.assertIn("min(96dvw, 1400px)", modals_css)
        self.assertIn("min-width: 0", entity_html)
        self.assertIn("flex-wrap: wrap", entity_html)
        self.assertIn('id="studio-status-banner" style="display: none;"', studio_html)


if __name__ == "__main__":
    unittest.main()
