#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Node VM & contract unit tests for Step 4 Milestone 1 (P2-14..P2-16, P2-21, P2-22)."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "dashboard" / "static"

_VM_BASE = r"""
const fs = require('fs'), vm = require('vm');
function makeEl(id = '') {
  const listeners = {}, children = [];
  return {
    id, value: '', src: '', href: '', download: '', innerHTML: '', textContent: '',
    style: {}, dataset: {}, options: [], children, listeners, clicked: 0, disabled: false,
    classList: { add() {}, remove() {}, toggle() {} },
    getAttribute: (k) => (k === 'data-id' ? '42' : k === 'data-name' ? 'Alice' : ''),
    addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
    click() { this.clicked += 1; (listeners.click || []).forEach((f) => f()); },
    appendChild: (c) => { children.push(c); return c; },
    remove() {}, focus() {}, reset() {},
    querySelectorAll: () => [],
  };
}
function runScript(relPath, extraWin = {}, els = {}, fetchImpl = async () => ({ ok: true, json: async () => ({}) })) {
  const created = [];
  const doc = {
    getElementById: (id) => els[id] || null,
    querySelectorAll: (sel) => els['__q_' + sel] || [],
    querySelector: (sel) => (els['__q_' + sel] || [])[0] || null,
    createElement: (tag) => { const n = makeEl(tag); created.push(n); return n; },
    addEventListener: () => {},
    body: { appendChild: (c) => c },
  };
  const win = {
    location: { protocol: 'http:', host: 'localhost:8000' },
    encodeURIComponent, decodeURIComponent, Math, Date, Number, String, Array, Object, JSON,
    setTimeout, clearTimeout, addEventListener: () => {},
    ...extraWin,
  };
  win.window = win;
  const ctx = vm.createContext({ window: win, document: doc, fetch: fetchImpl, console, ...win });
  vm.runInContext(fs.readFileSync(relPath, 'utf8'), ctx);
  return { win, doc, els, created };
}
"""


def _run_node(js_body: str) -> dict:
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node runtime not found")
    proc = subprocess.run(
        [node, "-e", _VM_BASE + "\n(async () => {\n" + js_body + "\n})();"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"Node VM failed:\n{proc.stderr}\n{proc.stdout}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


class TestStep4Milestone1FrontendContracts(unittest.TestCase):
    """Contract and Node VM checks for Milestone 1 frontend fixes."""

    def test_avatar_placeholder_svg_exists_and_no_png_refs(self) -> None:
        svg = STATIC_DIR / "avatar-placeholder.svg"
        self.assertTrue(svg.is_file(), "avatar-placeholder.svg must exist")
        self.assertIn("<svg", svg.read_text(encoding="utf-8"))
        for js_path in STATIC_DIR.rglob("*.js"):
            self.assertNotIn("avatar-placeholder.png", js_path.read_text(encoding="utf-8"), str(js_path))

    def test_review_and_rsac_crops_fields_and_confirm(self) -> None:
        res = _run_node(r"""
        const els = {
          'review-queue-container': makeEl('review-queue-container'),
          'review-inbox-counter': makeEl('review-inbox-counter'),
          'header-review-badge': makeEl('header-review-badge'),
        };
        const items = [{
          id: 7, track_id: 9, camera_id: 'cam_1', status: 'pending',
          similarity_score: 0.62, matched_entity_name: 'Bob',
          crop_path: 'data/crops/face_7.jpg', created_at: 1700000000,
        }];
        const toasts = [];
        const fetchImpl = async (url) => url.includes('/confirm')
          ? { ok: true, json: async () => ({}) }
          : { ok: true, json: async () => ({ items }) };
        const { win } = runScript('dashboard/static/review_and_rsac.js', { showToast: (...a) => toasts.push(a) }, els, fetchImpl);
        await win.ReviewAndRSAC.loadQueue('pending');
        const html = els['review-queue-container'].innerHTML;
        console.log(JSON.stringify({
          hasCrop: html.includes('/crops/face_7.jpg'),
          hasOneShot: html.includes('this.onerror=null'),
          hasBob: html.includes('Bob'),
          hasPct: html.includes('62.0%'),
          hasTs: !html.includes('undefined'),
        }));
        """)
        self.assertTrue(all(res.values()), res)

    def test_rsac_versions_renders_notes_source_and_crop_url(self) -> None:
        res = _run_node(r"""
        const els = {
          'modal-descriptor-versions': makeEl('modal-descriptor-versions'),
          'versions-modal-title': makeEl('versions-modal-title'),
          'versions-timeline-container': makeEl('versions-timeline-container'),
        };
        const fetchImpl = async () => ({
          ok: true,
          json: async () => ({ versions: [{ version: 2, notes: 'Operator anchor', crop_url: '/crops/v2.jpg', created_at: '2026-01-01' }] }),
        });
        const { win } = runScript('dashboard/static/js/rsac_versions.js', {}, els, fetchImpl);
        await win.RSACVersions.openVersionsModal(5, 'Alice');
        const html = els['versions-timeline-container'].innerHTML;
        console.log(JSON.stringify({ hasNotes: html.includes('Operator anchor'), hasCrop: html.includes('/crops/v2.jpg') }));
        """)
        self.assertEqual(res, {"hasNotes": True, "hasCrop": True})

    def test_gallery_timeline_awaits_filters_and_downloads_freeze_frame(self) -> None:
        res = _run_node(r"""
        const btnSightings = makeEl(), btnSave = makeEl('btn-snapshot-save');
        const els = {
          'entity-gallery-grid': makeEl('entity-gallery-grid'),
          'timeline-entity-select': makeEl('timeline-entity-select'),
          'timeline-zone-select': makeEl('timeline-zone-select'),
          'sightings-timeline-list': makeEl('sightings-timeline-list'),
          'btn-snapshot-save': btnSave,
          '__q_.btn-view-sightings': [btnSightings],
          '__q_.btn-view-versions': [], '__q_.btn-delete-entity': [],
        };
        const calls = [];
        const fetchImpl = async (url) => {
          calls.push(url);
          if (url === '/entities') return { ok: true, json: async () => [{ id: 42, name: 'Alice', category: 'vip' }] };
          if (url === '/zones') return { ok: true, json: async () => [] };
          if (url.includes('/freeze_frame')) return { ok: true, json: async () => ({ image_base64: 'data:image/jpeg;base64,AA==' }) };
          return { ok: true, json: async () => [] };
        };
        const { win, created } = runScript('dashboard/static/js/gallery_timeline.js', { App: { getActiveCameraId: () => 'cam_1' }, window: {} }, els, fetchImpl);
        win.GalleryTimeline.initSnapshotModal();
        await win.GalleryTimeline.loadGallery();
        await btnSave.listeners.click[0]();
        await btnSightings.listeners.click[0]();
        console.log(JSON.stringify({
          calls, selectedVal: els['timeline-entity-select'].value,
          dlHref: created.find((c) => c.download)?.href || '',
        }));
        """)
        self.assertIn("/api/cameras/cam_1/freeze_frame", res["calls"])
        self.assertFalse(any("/stream/" in c for c in res["calls"]))
        self.assertEqual(res["dlHref"], "data:image/jpeg;base64,AA==")

    def test_interactive_canvas_track_id_and_coco_category_fallback(self) -> None:
        res = _run_node(r"""
        const els = {
          'modal-tag-entity': makeEl('modal-tag-entity'), 'tag-track-id': makeEl('tag-track-id'),
          'tag-modal-title': makeEl('tag-modal-title'), 'tag-category-select': makeEl('tag-category-select'),
          'tag-name-input': makeEl('tag-name-input'), 'tag-entity-id': makeEl('tag-entity-id'),
          'tag-roi-preview-panel': makeEl('tag-roi-preview-panel'), 'tag-identity-candidates': makeEl('tag-identity-candidates'),
          'tag-ai-class-badge': makeEl('tag-ai-class-badge'), 'tag-roi-crop-img': makeEl('tag-roi-crop-img'),
        };
        els['tag-category-select'].options = [{ value: 'person' }, { value: 'vehicle' }, { value: 'custom' }];
        const fetchImpl = async () => ({ ok: true, json: async () => ({ data: { classification: { label: 'backpack', confidence: 0.9 }, candidates: [] } }) });
        const { win } = runScript('dashboard/static/js/interactive_canvas.js', {}, els, fetchImpl);
        win.InteractiveCanvas.openWithRecognition({ track: { track_id: 77, bbox: [1, 2, 3, 4] }, bbox: [1, 2, 3, 4] });
        await new Promise((r) => setTimeout(r, 10));
        console.log(JSON.stringify({ trackId: els['tag-track-id'].value, cat: els['tag-category-select'].value }));
        """)
        self.assertEqual(res, {"trackId": 77, "cat": "custom"})

    def test_analytics_and_telemetry_contracts(self) -> None:
        res = _run_node(r"""
        const els = { 'alerts-table-body': makeEl('alerts-table-body'), 'total-alerts-count': makeEl('total-alerts-count'), 'live-alerts-feed': makeEl('live-alerts-feed') };
        const urls = [];
        const fetchImpl = async (u) => {
          urls.push(u);
          return { ok: true, json: async () => [{ severity: 'CRITICAL', name: 'Eve', message: 'Zone breach', event_type: 'alert', timestamp: 1700000000 }] };
        };
        const aRes = runScript('dashboard/static/js/analytics_view.js', { App: { getActiveCameraId: () => 'cam_2' } }, els, fetchImpl);
        await aRes.win.AnalyticsView.loadAlerts();
        const wsCreated = [];
        class MockWS { constructor(u) { this.url = u; this.closed = false; wsCreated.push(this); } close() { this.closed = true; } }
        const tRes = runScript('dashboard/static/js/telemetry.js', { WebSocket: MockWS, MULTIVIEW_TOKEN: 'tok123' }, els);
        tRes.win.TelemetryGateway.initWebSocket('cam_2', () => {}, () => {});
        const ws = wsCreated[0];
        tRes.win.TelemetryGateway.closeWebSocket();
        tRes.win.TelemetryGateway.renderMiniAlerts([{ severity: 'CRITICAL', suggested_name: 'Eve', summary: 'Gate breach', event_type: 'alert' }]);
        console.log(JSON.stringify({
          url: urls[0], rowHtml: els['alerts-table-body'].innerHTML,
          wsUrl: ws.url, wsClosed: ws.closed, oncloseCleared: ws.onclose === null,
          miniHtml: els['live-alerts-feed'].innerHTML,
        }));
        """)
        self.assertIn("camera_id=cam_2", res["url"])
        self.assertIn("Eve", res["rowHtml"])
        self.assertIn("Zone breach", res["rowHtml"])
        self.assertIn("token=tok123", res["wsUrl"])
        self.assertTrue(res["wsClosed"] and res["oncloseCleared"])
        self.assertIn("Gate breach", res["miniHtml"])

    def test_journey_search_guards_empty_and_uses_track_id(self) -> None:
        res = _run_node(r"""
        const els = { 'journey-results-container': makeEl(), 'journey-export-status': makeEl() };
        const calls = [];
        const fetchImpl = async (u, opts) => {
          calls.push({ u, body: opts?.body || '' });
          return { ok: true, json: async () => ({ hops: [], video_url: '/v.mp4', video_file: 'v.mp4' }) };
        };
        const { win } = runScript('dashboard/static/js/journey_search.js', {}, els, fetchImpl);
        await win.JourneySearch.search('   ');
        await win.JourneySearch.exportVideo('');
        const emptyCalls = calls.length;
        await win.JourneySearch.search('123');
        await win.JourneySearch.exportVideo('123');
        console.log(JSON.stringify({ emptyCalls, calls }));
        """)
        self.assertEqual(res["emptyCalls"], 0)
        self.assertIn("track_id=123", res["calls"][0]["u"])
        self.assertEqual(json.loads(res["calls"][1]["body"]), {"track_id": 123})


class TestStep4Milestone2FrontendContracts(unittest.TestCase):
    """Contract and Node VM checks for Milestone 2 camera & enrollment modals."""

    def test_camera_manager_edit_preserves_enabled_type_and_cancel(self) -> None:
        res = _run_node(r"""
        const mk = (id, v = '') => Object.assign(makeEl(id), { value: v });
        const els = {
          'modal-camera-manager': mk('modal-camera-manager'), 'modal-cam-cancel': mk('modal-cam-cancel'),
          'camera-config-form': mk('camera-config-form'), 'cam-id-input': mk('cam-id-input'),
          'cam-name-input': mk('cam-name-input'), 'cam-source-input': mk('cam-source-input'),
          'cam-type-select': mk('cam-type-select', 'rtsp'), 'cam-preset-select': mk('cam-preset-select', 'hikvision'),
          'cam-detector-select': mk('cam-detector-select', 'yolov8'), 'cam-tracker-select': mk('cam-tracker-select', 'centroid'),
          'cam-conf-input': mk('cam-conf-input', '0.40'), 'cam-classes-input': mk('cam-classes-input'),
          'cam-armed-checkbox': Object.assign(mk('cam-armed-checkbox'), { checked: false }),
        };
        const sent = [], cams = [{ id: 'c1', name: 'USB Cam', source: '0', type: 'usb', enabled: false, detector: 'yolo11', tracker: 'sort', confidence: 0.75, device_name: 'HD Cam' }];
        const fetchImpl = async (u, opts) => {
          if (opts?.body) sent.push(JSON.parse(opts.body));
          if (u.includes('/presets')) return { ok: true, json: async () => [] };
          if (u === '/api/cameras') return { ok: true, json: async () => cams };
          if (u === '/api/system/capabilities') return { ok: true, json: async () => ({ detectors: ['yolov8', 'yolo11'], trackers: ['centroid', 'sort'] }) };
          return { ok: true, json: async () => ({}) };
        };
        const { win, doc } = runScript('dashboard/static/js/camera_form_helpers.js', { showToast() {} }, els, fetchImpl);
        const ctx = vm.createContext({ window: win, document: doc, fetch: fetchImpl, console, ...win });
        vm.runInContext(fs.readFileSync('dashboard/static/js/camera_ai_config.js', 'utf8'), ctx);
        vm.runInContext(fs.readFileSync('dashboard/static/camera_manager.js', 'utf8'), ctx);
        await new Promise((r) => setTimeout(r, 15));
        await win.CameraManager.editCamera('c1');
        const preset = els['cam-preset-select'].value, det = els['cam-detector-select'].value;
        await els['camera-config-form'].listeners.submit[0]({ preventDefault() {} });
        els['modal-cam-cancel'].click();
        console.log(JSON.stringify({ n: win.CameraManager.getActiveCameras().length, preset, det, payload: sent[0], closed: els['modal-camera-manager'].style.display === 'none' }));
        """)
        self.assertEqual((res["n"], res["preset"], res["det"]), (1, "hikvision", "yolo11"))
        self.assertFalse(res["payload"]["enabled"])
        self.assertEqual(res["payload"]["type"], "usb")
        self.assertNotIn("device_name", res["payload"])
        self.assertTrue(res["closed"])

    def test_discovery_forwards_type_and_ai_presets_scoped(self) -> None:
        res = _run_node(r"""
        const btnScan = makeEl('btn-scan-devices'), listEl = makeEl('discovered-devices-list');
        const addBtn = makeEl('add');
        addBtn.getAttribute = (k) => ({ 'data-id': 'usb_0', 'data-name': 'Logi', 'data-source': '0', 'data-type': 'usb', 'data-device-name': 'Logi C920' }[k] || '');
        listEl.querySelectorAll = (s) => (s === '.btn-add-discovered' ? [addBtn] : []);
        const batchBtn = makeEl('batch');
        batchBtn.classList = { added: 0, add() { this.added++; }, remove() {}, toggle() {} };
        const els = {
          'btn-scan-devices': btnScan, 'discovered-devices-list': listEl,
          'modal-camera-manager': makeEl('modal-camera-manager'), 'cam-classes-input': makeEl('cam-classes-input'),
          '__q_#modal-camera-manager .btn-tag-preset:not([data-target])': [],
          '__q_.btn-tag-preset': [batchBtn],
        };
        const fetchImpl = async () => ({ ok: true, json: async () => [{ id: 'usb_0', name: 'Logi', source: '0', type: 'usb' }] });
        const { win, doc } = runScript('dashboard/static/js/camera_discovery.js', {}, els, fetchImpl);
        const ctx = vm.createContext({ window: win, document: doc, fetch: fetchImpl, console, ...win });
        vm.runInContext(fs.readFileSync('dashboard/static/js/camera_ai_config.js', 'utf8'), ctx);
        let picked = null;
        await win.CameraDiscovery.scanDevices((sel) => { picked = sel; });
        addBtn.click();
        win.CameraAIConfig.resetValues();
        console.log(JSON.stringify({ picked, batchAdded: batchBtn.classList.added }));
        """)
        self.assertEqual(res["picked"], {"id": "usb_0", "name": "Logi", "source": "0", "type": "usb", "device_name": "Logi C920"})
        self.assertEqual(res["batchAdded"], 0)

    def test_universal_enrollment_image_only_categories_and_routing(self) -> None:
        res = _run_node(r"""
        const catSel = makeEl('enroll-category-select');
        catSel.innerHTML = '<option value="person">Person</option>';
        const els = {
          'modal-universal-enrollment': makeEl('modal-universal-enrollment'),
          'universal-enrollment-form': makeEl('universal-enrollment-form'),
          'enroll-category-select': catSel, 'enroll-camera-select': makeEl('enroll-camera-select'),
          'enroll-name-input': Object.assign(makeEl('enroll-name-input'), { value: 'Visitor X' }),
          'enroll-bbox-canvas': makeEl('enroll-bbox-canvas'), 'enroll-canvas-placeholder': makeEl('enroll-canvas-placeholder'),
          'enroll-crop-preview-box': makeEl('enroll-crop-preview-box'), 'enroll-crop-preview-img': makeEl('enroll-crop-preview-img'),
          'btn-enroll-modal': makeEl('btn-enroll-modal'),
        };
        els['enroll-bbox-canvas'].getContext = () => ({ drawImage() {}, clearRect() {}, strokeRect() {}, fillRect() {} });
        const posted = [];
        const fetchImpl = async (u, opts) => {
          if (u === '/api/enroll') { posted.push(JSON.parse(opts.body)); return { ok: true, json: async () => ({ entity_id: 9 }) }; }
          if (u === '/api/rsac/categories') return { ok: true, json: async () => [] };
          if (u === '/api/cameras') return { ok: true, json: async () => [{ id: 'cam_1', name: 'Lobby' }] };
          return { ok: true, json: async () => ({}) };
        };
        class MockImg { set src(v) { this.naturalWidth = 100; this.naturalHeight = 100; this.onload?.(); } }
        const { win, doc } = runScript('dashboard/static/js/universal_enrollment.js', { Image: MockImg, showToast() {} }, els, fetchImpl);
        win.UniversalEnrollment.init();
        await win.UniversalEnrollment.openModal();
        const catsPreserved = catSel.innerHTML.includes('person');
        const camPopulated = els['enroll-camera-select'].innerHTML.includes('cam_1');
        win.UniversalEnrollment.loadFreezeImage('data:image/jpeg;base64,AA==', els['enroll-bbox-canvas'], els['enroll-canvas-placeholder']);
        const fakeCanvas = { width: 10, height: 10, getContext: () => ({ drawImage() {} }), toDataURL: () => 'data:image/jpeg;base64,CROP' };
        doc.createElement = () => fakeCanvas;
        els['enroll-bbox-canvas'].getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100 });
        els['enroll-bbox-canvas'].listeners.mousedown[0]({ clientX: 0, clientY: 0 });
        els['enroll-bbox-canvas'].listeners.mouseup[0]({ clientX: 50, clientY: 50 });
        await els['universal-enrollment-form'].listeners.submit[0]({ preventDefault() {} });
        console.log(JSON.stringify({ catsPreserved, camPopulated, postedCount: posted.length, camId: posted[0]?.camera_id }));
        """)
        self.assertTrue(res["catsPreserved"])
        self.assertTrue(res["camPopulated"])
        self.assertEqual(res["postedCount"], 1)
        self.assertIsNone(res["camId"])


if __name__ == "__main__":
    unittest.main()
