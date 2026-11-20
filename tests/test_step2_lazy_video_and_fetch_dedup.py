#!/usr/bin/env python
"""Node VM unit tests for Step 2 M3: Boot fetch dedup & lazy video report loading."""

import json
import pathlib
import shutil
import subprocess
import unittest

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
NAV_JS = ROOT_DIR / "dashboard" / "static" / "js" / "nav_tabs_manager.js"
BRIDGE_JS = ROOT_DIR / "dashboard" / "static" / "js" / "scrubber_library_bridge.js"

_DEDUP_PRELUDE = r"""
const fs = require('fs'), vm = require('vm');
let underlyingCalls = [];
function makeSandbox() {
  underlyingCalls = [];
  const rawFetch = (url, init) => {
    underlyingCalls.push({ url, method: (init && init.method) || 'GET' });
    const payload = url === '/api/cameras' ? [{ id: 'cam_01' }] : [{ filename: 'a.mp4' }];
    const makeResp = () => ({
      ok: true,
      json: async () => JSON.parse(JSON.stringify(payload)),
      clone: () => makeResp(),
    });
    return Promise.resolve(makeResp());
  };
  const sandbox = {
    console, Date, Map, Set, Promise,
    fetch: rawFetch,
    document: { readyState: 'complete', querySelector: () => null, getElementById: () => null, querySelectorAll: () => [], addEventListener: () => {} },
    addEventListener: () => {},
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(NAV_PATH, 'utf8'), sandbox);
  return sandbox;
}
"""

_BRIDGE_PRELUDE = r"""
const fs = require('fs'), vm = require('vm');
function makeBridgeSandbox(hasVideosTab, isVideosActive) {
  const calls = { loadPlayer: [], restoreReport: [], loadDetections: [], fetches: [] };
  const classes = new Set(isVideosActive ? ['active'] : []);
  const winListeners = {};
  const tabEl = hasVideosTab ? { id: 'tab-videos', classList: { contains: (c) => classes.has(c), add: (c) => classes.add(c), remove: (c) => classes.delete(c) } } : null;
  const titleEl = { textContent: '', title: '' };
  const listEl = { innerHTML: '', querySelectorAll: () => [] };
  const playerEl = { duration: 120 };
  const sandbox = {
    console, encodeURIComponent, Number, Boolean,
    CSS: { escape: (s) => s },
    fetch: async (url) => {
      calls.fetches.push(url);
      if (url === '/api/videos') return { ok: true, json: async () => [{ filename: 'clip1.mp4', video_url: '/api/videos/clip1.mp4', web_compatible: true, codec: 'h264' }] };
      return { ok: true, json: async () => ({ events: [] }) };
    },
    document: {
      getElementById: (id) => ({ 'tab-videos': tabEl, 'scrubber-loaded-title': titleEl, 'scrubber-video-player': playerEl }[id] || null),
      querySelector: () => null,
      querySelectorAll: () => [],
    },
    VideoLibrary: { registerVideos: () => {}, renderVideoFileCard: (f) => `<div>${f.filename}</div>`, setActiveVideoCard: () => {} },
    VideoJobClient: { setCurrentViewedFilename: () => {}, updateSidebarCards: () => {} },
    VideoBatch: { setCurrentBatchFilename: () => {}, restoreReportForFile: (fn) => calls.restoreReport.push(fn) },
    ScrubberOverlay: { loadDetections: (fn) => calls.loadDetections.push(fn) },
    VideoTimelineLinks: { extractEventsFromReport: () => [], renderTimelineTicks: () => {} },
    addEventListener: (ev, fn) => { (winListeners[ev] = winListeners[ev] || []).push(fn); },
    dispatchEvent: (ev) => (winListeners[ev.type] || []).forEach((fn) => fn(ev)),
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(BRIDGE_PATH, 'utf8'), sandbox);
  return { sandbox, calls, classes, listEl, titleEl };
}
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM tests")
class TestStep2LazyVideoAndFetchDedup(unittest.TestCase):
    """Verify boot GET fetch coalescing and deferred #tab-videos loading."""

    def _run_node(self, prelude: str, body: str, path_var: str, path_val: pathlib.Path) -> dict:
        script = f"const {path_var} = {json.dumps(str(path_val))};\n{prelude}\n{body}"
        res = subprocess.run(
            ["node", "-e", script], capture_output=True, text=True, check=False, timeout=15
        )
        self.assertEqual(res.returncode, 0, f"Node failed:\n{res.stderr}\n{res.stdout}")
        return json.loads(res.stdout.strip())

    def test_concurrent_boot_fetches_coalesce_to_single_http_call(self):
        body = """
        (async () => {
          const s = makeSandbox();
          const [c1, c2, v1, v2, p1, post1] = await Promise.all([
            s.fetch('/api/cameras'), s.fetch('/api/cameras'),
            s.fetch('/api/videos'), s.fetch('/api/videos'),
            s.fetch('/api/cameras/cam_01/probe'),
            s.fetch('/api/cameras', { method: 'POST' }),
          ]);
          const d1 = await c1.json(), d2 = await c2.json();
          console.log(JSON.stringify({ total: underlyingCalls.length, urls: underlyingCalls.map(x => x.url), d1, d2 }));
        })();
        """
        out = self._run_node(_DEDUP_PRELUDE, body, "NAV_PATH", NAV_JS)
        self.assertEqual(out["total"], 4)
        self.assertEqual(out["urls"].count("/api/cameras"), 2)  # 1 GET + 1 POST
        self.assertEqual(out["urls"].count("/api/videos"), 1)
        self.assertEqual(out["d1"], out["d2"])

    def test_clear_fetch_dedup_cache_forces_fresh_request(self):
        body = """
        (async () => {
          const s = makeSandbox();
          await s.fetch('/api/cameras');
          await s.fetch('/api/cameras');
          const beforeClear = underlyingCalls.length;
          s.clearFetchDedupCache();
          await s.fetch('/api/cameras');
          console.log(JSON.stringify({ beforeClear, afterClear: underlyingCalls.length }));
        })();
        """
        out = self._run_node(_DEDUP_PRELUDE, body, "NAV_PATH", NAV_JS)
        self.assertEqual(out["beforeClear"], 1)
        self.assertEqual(out["afterClear"], 2)

    def test_load_videos_list_defers_selection_until_videos_tab_active(self):
        body = """
        (async () => {
          const { sandbox, calls, classes, listEl } = makeBridgeSandbox(true, false);
          await sandbox.ScrubberLibraryBridge.loadVideosList({
            videoFilesList: listEl,
            getCurrentFilename: () => null,
            loadVideoIntoPlayer: (_u, fn) => calls.loadPlayer.push(fn),
            reloadList: () => {},
          });
          const beforeTab = calls.loadPlayer.slice();
          classes.add('active');
          sandbox.dispatchEvent({ type: 'tab-changed', detail: { activeTab: 'tab-videos' } });
          console.log(JSON.stringify({ beforeTab, afterTab: calls.loadPlayer, fetches: calls.fetches }));
        })();
        """
        out = self._run_node(_BRIDGE_PRELUDE, body, "BRIDGE_PATH", BRIDGE_JS)
        self.assertEqual(out["beforeTab"], [])
        self.assertEqual(out["afterTab"], ["clip1.mp4"])
        self.assertEqual(out["fetches"], ["/api/videos"])

    def test_sync_loaded_video_ui_defers_heavy_report_until_tab_active(self):
        body = """
        (async () => {
          const { sandbox, calls, classes, titleEl } = makeBridgeSandbox(true, false);
          sandbox.ScrubberLibraryBridge.syncLoadedVideoUI('clip1.mp4', true, 'h264', {}, {});
          const before = { restore: calls.restoreReport.slice(), det: calls.loadDetections.slice(), fetches: calls.fetches.slice(), title: titleEl.textContent };
          classes.add('active');
          sandbox.dispatchEvent({ type: 'tab-changed', detail: { activeTab: 'tab-videos' } });
          await new Promise(r => setTimeout(r, 10));
          console.log(JSON.stringify({ before, afterRestore: calls.restoreReport, afterDet: calls.loadDetections, afterFetches: calls.fetches }));
        })();
        """
        out = self._run_node(_BRIDGE_PRELUDE, body, "BRIDGE_PATH", BRIDGE_JS)
        self.assertEqual(out["before"]["title"], "Loaded: clip1.mp4")
        self.assertEqual(out["before"]["restore"], [])
        self.assertEqual(out["before"]["det"], [])
        self.assertEqual(out["before"]["fetches"], [])
        self.assertEqual(out["afterRestore"], ["clip1.mp4"])
        self.assertEqual(out["afterDet"], ["clip1.mp4"])
        self.assertIn("/api/videos/clip1.mp4/report", out["afterFetches"])

    def test_isolated_dom_without_tab_videos_remains_backward_compatible(self):
        body = """
        (async () => {
          const { sandbox, calls, listEl } = makeBridgeSandbox(false, false);
          await sandbox.ScrubberLibraryBridge.loadVideosList({
            videoFilesList: listEl,
            getCurrentFilename: () => null,
            loadVideoIntoPlayer: (_u, fn) => {
              calls.loadPlayer.push(fn);
              sandbox.ScrubberLibraryBridge.syncLoadedVideoUI(fn, true, 'h264', {}, {});
            },
            reloadList: () => {},
          });
          console.log(JSON.stringify({ active: sandbox.ScrubberLibraryBridge.isVideosTabActive(), calls }));
        })();
        """
        out = self._run_node(_BRIDGE_PRELUDE, body, "BRIDGE_PATH", BRIDGE_JS)
        self.assertTrue(out["active"])
        self.assertEqual(out["calls"]["loadPlayer"], ["clip1.mp4"])
        self.assertEqual(out["calls"]["restoreReport"], ["clip1.mp4"])
        self.assertEqual(out["calls"]["loadDetections"], ["clip1.mp4"])


if __name__ == "__main__":
    unittest.main()
