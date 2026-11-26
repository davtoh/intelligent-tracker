#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit and Node VM tests for Step 2 M1: tab-scoped streams and lazy HTML src."""

import json
import pathlib
import re
import shutil
import subprocess
import unittest

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
PARTIALS_DIR = ROOT_DIR / "dashboard" / "static" / "partials" / "tabs"
JS_DIR = ROOT_DIR / "dashboard" / "static" / "js"

_VM_PRELUDE = r"""
const fs = require('fs'), vm = require('vm');
const byId = new Map(), events = [], origCalls = [];
function makeEl(id, dataSrc = '') {
  const attrs = new Map();
  if (dataSrc) attrs.set('data-src', dataSrc);
  const el = {
    id, src: '', dataset: dataSrc ? { src: dataSrc } : {}, value: '',
    style: {}, scrollWidth: 100, clientWidth: 100, scrollLeft: 0,
    classList: { toggle: () => {} },
    getAttribute: (k) => attrs.get(k) || '',
    setAttribute: (k, v) => attrs.set(k, v),
    addEventListener: () => {},
    querySelectorAll: () => [],
    querySelector: () => null,
    getBoundingClientRect: () => ({ left: 0, right: 100, width: 100 }),
  };
  return el;
}
byId.set('live-stream-img', makeEl('live-stream-img'));
byId.get('live-stream-img').src = '/stream/cam_01?annotated=false';
byId.set('studio-live-img', makeEl('studio-live-img', '/stream/cam_01'));
byId.set('studio-camera-select', Object.assign(makeEl('studio-camera-select'), { value: 'cam_02' }));
byId.set('static-heatmap-img', makeEl('static-heatmap-img', '/analytics/heatmap'));

function CustomEvent(type, opts = {}) {
  this.type = type;
  this.detail = opts.detail || {};
}
const sandbox = {
  console, Date, Math, encodeURIComponent, CustomEvent,
  setTimeout: () => 0, clearTimeout: () => {},
  scrollX: 0, scrollY: 0, scrollTo: () => {},
  App: { getActiveCameraId: () => 'cam_01' },
  document: {
    readyState: 'complete',
    getElementById: (id) => byId.get(id) || null,
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener: () => {},
  },
  addEventListener: () => {},
  dispatchEvent: (ev) => { events.push({ type: ev.type, detail: ev.detail }); },
  switchTab: (tabId) => { origCalls.push(tabId); },
};
sandbox.window = sandbox;
vm.createContext(sandbox);
"""


def _run_node_vm(files: list[pathlib.Path], script: str) -> dict:
    if not shutil.which("node"):
        raise unittest.SkipTest("Node.js not installed")
    loads = "\n".join(
        f"vm.runInContext(fs.readFileSync({json.dumps(str(f))}, 'utf8'), sandbox);"
        for f in files
    )
    proc = subprocess.run(
        ["node", "-e", _VM_PRELUDE + "\n" + loads + "\n" + script],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"Node VM failed:\n{proc.stderr}\n{proc.stdout}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


class TestStep2TabScopedStreams(unittest.TestCase):
    """Verify eager stream src removal and tab-scoped LivePlayer/NavTabsManager."""

    def test_studio_html_omits_eager_stream_src(self):
        html = (PARTIALS_DIR / "studio.html").read_text(encoding="utf-8")
        self.assertIn('id="studio-live-img"', html)
        self.assertNotIn("cam_01", html)
        self.assertIsNone(re.search(r'(?<![-\w])src="/stream/', html))

    def test_analytics_html_omits_eager_heatmap_src(self):
        html = (PARTIALS_DIR / "analytics.html").read_text(encoding="utf-8")
        self.assertIn('id="static-heatmap-img"', html)
        self.assertIn('data-src="/analytics/heatmap"', html)
        self.assertIsNone(re.search(r'(?<![-\w])src="/analytics/heatmap"', html))

    def test_live_player_sync_tab_streams_live_to_studio_and_back(self):
        script = """
        const LP = sandbox.window.LivePlayer;
        LP.syncTabStreams('tab-live', 'tab-studio');
        const liveAfterStudio = byId.get('live-stream-img').src;
        const studioAfterStudio = byId.get('studio-live-img').src;
        LP.syncTabStreams('tab-studio', 'tab-live');
        const studioAfterLive = byId.get('studio-live-img').src;
        const liveAfterLive = byId.get('live-stream-img').src;
        console.log(JSON.stringify({
          liveAfterStudio, studioAfterStudio, studioAfterLive, liveAfterLive
        }));
        """
        out = _run_node_vm([JS_DIR / "live_player.js"], script)
        self.assertTrue(out["liveAfterStudio"].startswith("data:image/svg+xml"))
        self.assertIn("/stream/cam_02?t=", out["studioAfterStudio"])
        self.assertTrue(out["studioAfterLive"].startswith("data:image/svg+xml"))
        self.assertIn("/stream/cam_01?annotated=false&t=", out["liveAfterLive"])

    def test_live_player_sync_tab_streams_analytics_heatmap(self):
        script = """
        sandbox.window.LivePlayer.syncTabStreams('tab-live', 'tab-analytics');
        console.log(JSON.stringify({
          liveSrc: byId.get('live-stream-img').src,
          heatmapSrc: byId.get('static-heatmap-img').src,
        }));
        """
        out = _run_node_vm([JS_DIR / "live_player.js"], script)
        self.assertTrue(out["liveSrc"].startswith("data:image/svg+xml"))
        self.assertIn("/analytics/heatmap?camera_id=cam_01&t=", out["heatmapSrc"])

    def test_nav_tabs_manager_and_wrapped_switch_tab_emit_lifecycle(self):
        script = """
        const syncs = [];
        sandbox.window.LivePlayer.syncTabStreams = (p, t) => syncs.push([p, t]);
        sandbox.window.navTabsManager.switchTab('tab-studio');
        sandbox.window.switchTab('tab-analytics');
        console.log(JSON.stringify({ syncs, events, origCalls }));
        """
        out = _run_node_vm(
            [JS_DIR / "live_player.js", JS_DIR / "nav_tabs_manager.js"], script
        )
        self.assertEqual(out["syncs"], [["tab-live", "tab-studio"], ["tab-studio", "tab-analytics"]])
        self.assertEqual(out["origCalls"], ["tab-studio", "tab-analytics"])
        self.assertEqual(
            out["events"],
            [
                {"type": "tab-changed", "detail": {"previousTab": "tab-live", "activeTab": "tab-studio"}},
                {"type": "tab-changed", "detail": {"previousTab": "tab-studio", "activeTab": "tab-analytics"}},
            ],
        )


if __name__ == "__main__":
    unittest.main()
