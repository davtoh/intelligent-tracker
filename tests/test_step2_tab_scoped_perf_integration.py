#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""End-to-end Node VM integration tests for Step 2: tab-scoped streams & lazy loading."""

import json
import pathlib
import re
import shutil
import subprocess
import unittest

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
PARTIALS_DIR = ROOT_DIR / "dashboard" / "static" / "partials" / "tabs"
JS_DIR = ROOT_DIR / "dashboard" / "static" / "js"
STUDIO_JS = ROOT_DIR / "dashboard" / "static" / "studio.js"

_INTEGRATION_PRELUDE = r"""
const fs = require('fs'), vm = require('vm');
const byId = new Map(), docListeners = {}, winListeners = {}, timers = new Map();
const underlyingFetches = [], calls = { loadPlayer: [], restoreReport: [], loadDetections: [] };
let nextTimerId = 1, bevRenders = 0;

function makeEl(id, active = false, dataSrc = '') {
  const classes = new Set(active ? ['active'] : []);
  const attrs = new Map(dataSrc ? [['data-src', dataSrc]] : []);
  return {
    id, src: '', value: 'cam_01', dataset: dataSrc ? { src: dataSrc } : {},
    style: {}, options: [], selectedOptions: [], children: [], innerHTML: '', textContent: '', title: '', duration: 120,
    scrollWidth: 100, clientWidth: 100, scrollLeft: 0,
    classList: {
      contains: (c) => classes.has(c),
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      toggle: (c, f) => (f === undefined ? (classes.has(c) ? classes.delete(c) : classes.add(c)) : (f ? classes.add(c) : classes.delete(c))),
    },
    getAttribute: (k) => attrs.get(k) || '',
    setAttribute: (k, v) => attrs.set(k, v),
    appendChild: () => {},
    addEventListener: () => {},
    querySelectorAll: () => [],
    querySelector: () => null,
    getBoundingClientRect: () => ({ left: 0, right: 100, width: 100 }),
    getContext: () => ({}),
  };
}

['tab-live', 'tab-studio', 'tab-analytics', 'tab-videos'].forEach((id) => {
  byId.set(id, makeEl(id, id === 'tab-live'));
});
byId.set('live-stream-img', makeEl('live-stream-img'));
byId.get('live-stream-img').src = '/stream/cam_01?annotated=false';
byId.set('studio-live-img', makeEl('studio-live-img', false, '/stream/cam_01'));
byId.set('studio-camera-select', Object.assign(makeEl('studio-camera-select'), { value: 'cam_02' }));
byId.set('static-heatmap-img', makeEl('static-heatmap-img', false, '/analytics/heatmap'));
byId.set('bev-minimap-canvas', makeEl('bev-minimap-canvas'));
byId.set('studio-status-banner', makeEl('studio-status-banner'));
byId.set('scrubber-loaded-title', makeEl('scrubber-loaded-title'));
byId.set('scrubber-video-player', makeEl('scrubber-video-player'));

function CustomEvent(type, opts = {}) { this.type = type; this.detail = opts.detail || {}; }
const rawFetch = (url, init) => {
  underlyingFetches.push({ url, method: (init && init.method) || 'GET' });
  const data = url === '/api/cameras' ? [{ id: 'cam_01' }]
    : url === '/api/videos' ? [{ filename: 'clip1.mp4', video_url: '/api/videos/clip1.mp4', web_compatible: true, codec: 'h264' }]
    : { events: [] };
  const makeResp = () => ({ ok: true, json: async () => JSON.parse(JSON.stringify(data)), clone: () => makeResp() });
  return Promise.resolve(makeResp());
};

const sandbox = {
  console, Date, Math, Map, Set, Promise, Number, Boolean, encodeURIComponent, CustomEvent,
  CSS: { escape: (s) => s },
  fetch: rawFetch,
  setTimeout, clearTimeout,
  setInterval: (fn, ms) => { const id = nextTimerId++; timers.set(id, { fn, ms }); return id; },
  clearInterval: (id) => { timers.delete(id); },
  scrollX: 0, scrollY: 0, scrollTo: () => {},
  App: { getActiveCameraId: () => 'cam_01' },
  BEVMinimap: { render: () => { bevRenders += 1; } },
  StudioOverlays: { init: () => {}, bindOverlayToolbar: () => {}, loadCameraOverlays: () => {}, renderScenarioListUI: () => {}, renderTopologyLinksUI: () => {} },
  JourneySearch: { bind: () => {} },
  ScenarioModals: { init: () => {} },
  VideoLibrary: { registerVideos: () => {}, renderVideoFileCard: (f) => `<div>${f.filename}</div>`, setActiveVideoCard: () => {} },
  VideoJobClient: { setCurrentViewedFilename: () => {}, updateSidebarCards: () => {} },
  VideoBatch: { setCurrentBatchFilename: () => {}, restoreReportForFile: (fn) => calls.restoreReport.push(fn) },
  ScrubberOverlay: { loadDetections: (fn) => calls.loadDetections.push(fn) },
  VideoTimelineLinks: { extractEventsFromReport: () => [], renderTimelineTicks: () => {} },
  document: {
    readyState: 'complete',
    createElement: (tag) => makeEl(tag),
    getElementById: (id) => byId.get(id) || null,
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener: (ev, fn) => { (docListeners[ev] = docListeners[ev] || []).push(fn); },
  },
  addEventListener: (ev, fn) => { (winListeners[ev] = winListeners[ev] || []).push(fn); },
  dispatchEvent: (ev) => (winListeners[ev.type] || []).forEach((fn) => fn(ev)),
  switchTab: (tabId) => {
    ['tab-live', 'tab-studio', 'tab-analytics', 'tab-videos'].forEach((id) => {
      byId.get(id).classList.toggle('active', id === tabId);
    });
  },
  _tickIntervals: () => [...timers.values()].forEach((t) => t.fn()),
};
sandbox.window = sandbox;
vm.createContext(sandbox);
"""


def _run_integration_vm(script: str) -> dict:
    if not shutil.which("node"):
        raise unittest.SkipTest("Node.js not installed")
    files = [
        JS_DIR / "live_player.js",
        JS_DIR / "nav_tabs_manager.js",
        STUDIO_JS,
        JS_DIR / "scrubber_library_bridge.js",
    ]
    loads = "\n".join(
        f"vm.runInContext(fs.readFileSync({json.dumps(str(f))}, 'utf8'), sandbox);"
        for f in files
    )
    boot = "(docListeners['DOMContentLoaded'] || []).forEach((fn) => fn());"
    proc = subprocess.run(
        ["node", "-e", _INTEGRATION_PRELUDE + "\n" + loads + "\n" + boot + "\n" + script],
        capture_output=True, text=True, check=False, timeout=15,
    )
    if proc.returncode != 0:
        raise AssertionError(f"Node VM failed:\n{proc.stderr}\n{proc.stdout}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


@unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM tests")
class TestStep2TabScopedPerfIntegration(unittest.TestCase):
    """End-to-end integration tests for Step 2 tab-scoped streams & lazy data."""

    def test_boot_live_tab_opens_only_live_stream_and_coalesces_fetches(self):
        script = """
        (async () => {
          await Promise.all([sandbox.fetch('/api/cameras'), sandbox.fetch('/api/cameras')]);
          await sandbox.ScrubberLibraryBridge.loadVideosList({
            videoFilesList: makeEl('video-files-list'),
            getCurrentFilename: () => null,
            loadVideoIntoPlayer: (_u, fn) => {
              calls.loadPlayer.push(fn);
              sandbox.ScrubberLibraryBridge.syncLoadedVideoUI(fn, true, 'h264', {}, {});
            },
            reloadList: () => {},
          });
          const rendersBeforeTick = bevRenders;
          sandbox._tickIntervals();
          console.log(JSON.stringify({
            liveSrc: byId.get('live-stream-img').src,
            studioSrc: byId.get('studio-live-img').src,
            heatmapSrc: byId.get('static-heatmap-img').src,
            timers: timers.size, rendersAfterTick: bevRenders - rendersBeforeTick,
            loadPlayer: calls.loadPlayer, restoreReport: calls.restoreReport,
            fetches: underlyingFetches.map((x) => x.url),
          }));
        })();
        """
        out = _run_integration_vm(script)
        self.assertIn("/stream/cam_01", out["liveSrc"])
        self.assertEqual(out["studioSrc"], "")
        self.assertEqual(out["heatmapSrc"], "")
        self.assertEqual(out["timers"], 0)
        self.assertEqual(out["rendersAfterTick"], 0)
        self.assertEqual(out["loadPlayer"], [])
        self.assertEqual(out["restoreReport"], [])
        self.assertEqual(out["fetches"].count("/api/cameras"), 1)
        self.assertEqual(out["fetches"].count("/api/videos"), 1)
        self.assertFalse(any("/report" in u or "/detections" in u for u in out["fetches"]))

    def test_tab_transition_live_to_studio_and_back_toggles_streams_and_minimap(self):
        script = """
        sandbox.window.switchTab('tab-studio');
        const studioTimers = timers.size;
        sandbox._tickIntervals();
        const studioState = {
          live: byId.get('live-stream-img').src,
          studio: byId.get('studio-live-img').src,
          timers: studioTimers,
          renders: bevRenders,
        };
        sandbox.window.switchTab('tab-live');
        console.log(JSON.stringify({
          studioState,
          backLive: byId.get('live-stream-img').src,
          backStudio: byId.get('studio-live-img').src,
          backTimers: timers.size,
        }));
        """
        out = _run_integration_vm(script)
        self.assertTrue(out["studioState"]["live"].startswith("data:image/svg+xml"))
        self.assertIn("/stream/cam_02?t=", out["studioState"]["studio"])
        self.assertEqual(out["studioState"]["timers"], 1)
        self.assertGreaterEqual(out["studioState"]["renders"], 1)
        self.assertIn("/stream/cam_01?annotated=false&t=", out["backLive"])
        self.assertTrue(out["backStudio"].startswith("data:image/svg+xml"))
        self.assertEqual(out["backTimers"], 0)

    def test_tab_transition_analytics_and_videos_flushes_lazy_loads(self):
        script = """
        (async () => {
          await sandbox.ScrubberLibraryBridge.loadVideosList({
            videoFilesList: makeEl('video-files-list'),
            getCurrentFilename: () => null,
            loadVideoIntoPlayer: (_u, fn) => {
              calls.loadPlayer.push(fn);
              sandbox.ScrubberLibraryBridge.syncLoadedVideoUI(fn, true, 'h264', {}, {});
            },
            reloadList: () => {},
          });
          sandbox.window.switchTab('tab-analytics');
          const analyticsHeatmap = byId.get('static-heatmap-img').src;
          const analyticsLive = byId.get('live-stream-img').src;
          sandbox.window.switchTab('tab-videos');
          await new Promise((r) => setTimeout(r, 10));
          console.log(JSON.stringify({
            analyticsHeatmap, analyticsLive,
            loadPlayer: calls.loadPlayer,
            restoreReport: calls.restoreReport,
            loadDetections: calls.loadDetections,
            fetches: underlyingFetches.map((x) => x.url),
          }));
        })();
        """
        out = _run_integration_vm(script)
        self.assertTrue(out["analyticsLive"].startswith("data:image/svg+xml"))
        self.assertIn("/analytics/heatmap?t=", out["analyticsHeatmap"])
        self.assertEqual(out["loadPlayer"], ["clip1.mp4"])
        self.assertEqual(out["restoreReport"], ["clip1.mp4"])
        self.assertEqual(out["loadDetections"], ["clip1.mp4"])
        self.assertIn("/api/videos/clip1.mp4/reports", out["fetches"])

    def test_html_partials_omit_eager_srcs_and_preserve_dom_ids(self):
        studio_html = (PARTIALS_DIR / "studio.html").read_text(encoding="utf-8")
        analytics_html = (PARTIALS_DIR / "analytics.html").read_text(encoding="utf-8")
        self.assertIn('id="studio-live-img"', studio_html)
        self.assertIn('id="studio-camera-select"', studio_html)
        self.assertIsNone(re.search(r'(?<![-\w])src="/stream/', studio_html))
        self.assertIn('id="static-heatmap-img"', analytics_html)
        self.assertIsNone(re.search(r'(?<![-\w])src="/analytics/heatmap"', analytics_html))


if __name__ == "__main__":
    unittest.main()
