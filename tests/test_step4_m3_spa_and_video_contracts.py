#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Node VM & contract unit tests for Step 4 Milestone 3 (P2-22)."""

import unittest

from tests.test_step4_p2_frontend_contracts import STATIC_DIR, _run_node


class TestStep4Milestone3FrontendContracts(unittest.TestCase):
    """Contract and Node VM checks for Milestone 3 SPA boot, cache & video isolation."""

    def test_index_html_loads_nav_tabs_and_helpers_before_app(self) -> None:
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        self.assertLess(len(html.splitlines()), 180)
        self.assertLess(html.index("nav_tabs_manager.js"), html.index("/static/app.js"))
        self.assertLess(html.index("app_ui_helpers.js"), html.index("/static/app.js"))
        self.assertLess(html.index("video_jobs_ui.js"), html.index("video_jobs.js"))
        self.assertIn('id="drawer-jobs-badge"', html)

    def test_spa_hash_boot_gates_live_ws_and_stream_and_syncs_drawer_badges(self) -> None:
        res = _run_node(r"""
        const wsCalls = [], streamCalls = [];
        const els = {
          'tab-videos': makeEl('tab-videos'), 'tab-live': makeEl('tab-live'),
          'header-alert-badge': makeEl('header-alert-badge'), 'drawer-alert-badge': makeEl('drawer-alert-badge'),
        };
        const domListeners = [], history = { pushState() {} };
        const win = {
          location: { hash: '#tab-videos', protocol: 'http:', host: 'localhost:8000' },
          localStorage: { getItem: () => 'cam_1' }, history, scrollX: 0, scrollY: 0, addEventListener: () => {},
          TelemetryGateway: { initWebSocket: (c, onTel) => { wsCalls.push(c); win.__onTel = onTel; }, updateKpiDisplays() {}, renderMiniAlerts() {} },
          LivePlayer: { attachLiveStream: (img, c) => streamCalls.push(c), detachLiveStream() {}, isPaused: () => false, bindHudButtons() {} },
          VideoScrubber: { loadVideosList() {}, onTabEnter() {} },
        };
        win.window = win;
        const ctx = vm.createContext({
          window: win, history, console, setTimeout, clearTimeout,
          document: {
            getElementById: (id) => els[id] || null,
            querySelectorAll: (s) => (s === '.tab-pane' ? [els['tab-live'], els['tab-videos']] : []),
            addEventListener: (ev, fn) => { if (ev === 'DOMContentLoaded') domListeners.push(fn); },
          },
        });
        vm.runInContext(fs.readFileSync('dashboard/static/js/app_ui_helpers.js', 'utf8'), ctx);
        vm.runInContext(fs.readFileSync('dashboard/static/app.js', 'utf8'), ctx);
        domListeners.forEach((fn) => fn());
        const bootWs = wsCalls.length, bootStreams = streamCalls.length;
        win.switchTab('tab-live');
        win.__onTel({ active_tracks: [], recent_alerts: [{ id: 1 }, { id: 2 }] });
        console.log(JSON.stringify({
          bootWs, bootStreams, afterLiveWs: wsCalls.length, afterLiveStream: streamCalls.length,
          hdrAlert: els['header-alert-badge'].textContent, drwAlert: els['drawer-alert-badge'].textContent,
        }));
        """)
        self.assertEqual((res["bootWs"], res["bootStreams"]), (0, 0))
        self.assertEqual((res["afterLiveWs"], res["afterLiveStream"]), (1, 1))
        self.assertEqual((res["hdrAlert"], res["drwAlert"]), ("2", "2"))

    def test_nav_tabs_cache_invalidation_and_recording_mode_refresh(self) -> None:
        res = _run_node(r"""
        let getCount = 0;
        const fetchImpl = async (url, init = {}) => {
          if (!init.method || init.method === 'GET') getCount += 1;
          return { ok: true, json: async () => ({}), clone() { return this; } };
        };
        const { win } = runScript('dashboard/static/js/nav_tabs_manager.js', { fetch: fetchImpl }, {}, fetchImpl);
        await win.fetch('/api/cameras');
        await win.fetch('/api/cameras');
        const cachedGets = getCount;
        await win.fetch('/api/cameras', { method: 'POST', body: '{}' });
        await win.fetch('/api/cameras');
        const afterMutGets = getCount;
        let refreshed = 0;
        const rec = runScript('dashboard/static/js/camera_recording.js', {
          ProcessingModeUI: { refresh: () => { refreshed += 1; } }, showToast() {}, setInterval: () => 1, clearInterval() {},
        }, { 'active-camera-select': makeEl('active-camera-select') }, async () => ({ ok: true, json: async () => ({ camera_id: 'c1', is_recording: true }) }));
        await rec.win.CameraRecording.startRecording('c1', {});
        console.log(JSON.stringify({ cachedGets, afterMutGets, refreshed }));
        """)
        self.assertEqual(res["cachedGets"], 1)
        self.assertEqual(res["afterMutGets"], 2)
        self.assertEqual(res["refreshed"], 1)

    def test_video_batch_scenarios_and_jobs_bridge_filename_isolation(self) -> None:
        res = _run_node(r"""
        const sel = makeEl('batch-scenario-select'), hdrBadge = makeEl('scrubber-header-job-badge'), drwBadge = makeEl('drawer-jobs-badge');
        const els = {
          'modal-video-batch-analyze': makeEl('modal-video-batch-analyze'),
          'batch-scenario-select': sel, 'scrubber-header-job-badge': hdrBadge, 'drawer-jobs-badge': drwBadge,
        };
        const fetchImpl = async (u) => u === '/api/scenarios'
          ? { ok: true, json: async () => ({ cameras: { cam_a: { zones: [1, 2], tripwires: [1] } } }) }
          : { ok: true, json: async () => ([{ job_id: 'j1', filename: 'other.mp4', job_type: 'analytics', status: 'running', progress: 45 }]) };
        const ce = function (t, o) { return { type: t, detail: o?.detail }; };
        const { win, doc } = runScript('dashboard/static/js/video_batch.js', { setInterval: () => 1, clearInterval() {}, CustomEvent: ce, dispatchEvent() {} }, els, fetchImpl);
        const origCreate = doc.createElement;
        doc.createElement = (t) => Object.assign(origCreate(t), { querySelector: () => null });
        const ctx = vm.createContext({ window: win, document: doc, fetch: fetchImpl, console, ...win });
        vm.runInContext(fs.readFileSync('dashboard/static/js/video_jobs_ui.js', 'utf8'), ctx);
        vm.runInContext(fs.readFileSync('dashboard/static/js/video_jobs.js', 'utf8'), ctx);
        win.VideoBatch.openBatchModal('clip.mp4');
        await new Promise((r) => setTimeout(r, 15));
        win.VideoJobClient.setCurrentViewedFilename('viewed.mp4');
        win.VideoJobClient._notify('job-update', { job_id: 'j1', filename: 'other.mp4', status: 'running', progress: 50 });
        console.log(JSON.stringify({ optCount: sel.children.length, hdrText: hdrBadge.textContent, drwText: drwBadge.textContent }));
        """)
        self.assertEqual(res["optCount"], 1)
        self.assertEqual(res["hdrText"], "")
        self.assertEqual(res["drwText"], "1")


if __name__ == "__main__":
    unittest.main()
