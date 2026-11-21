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
    setTimeout, clearTimeout,
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


if __name__ == "__main__":
    unittest.main()
