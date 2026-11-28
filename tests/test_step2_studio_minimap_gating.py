#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Node VM unit tests for Step 2 M2: Studio BEV minimap timer & stream gating."""

import json
import pathlib
import shutil
import subprocess
import unittest

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
STUDIO_JS = ROOT_DIR / "dashboard" / "static" / "studio.js"

_VM_PRELUDE = r"""
const fs = require('fs'), vm = require('vm');
const byId = new Map(), docListeners = {}, winListeners = {};
const timers = new Map();
let nextTimerId = 1, bevRenders = 0, clearedIds = [];

function makeEl(id, active = false) {
  const classes = new Set(active ? ['active'] : []);
  const listeners = {};
  return {
    id, src: '', value: 'cam_01', dataset: {}, style: {}, options: [], selectedOptions: [],
    classList: {
      contains: (c) => classes.has(c),
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
    },
    addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
    _emit: (ev, payload) => (listeners[ev] || []).forEach((fn) => fn(payload)),
    getContext: () => ({}),
  };
}
byId.set('tab-studio', makeEl('tab-studio', false));
byId.set('studio-live-img', makeEl('studio-live-img'));
byId.set('studio-camera-select', makeEl('studio-camera-select'));
byId.set('bev-minimap-canvas', makeEl('bev-minimap-canvas'));
byId.set('studio-status-banner', makeEl('studio-status-banner'));

const sandbox = {
  console, Date, Math, encodeURIComponent,
  fetch: () => Promise.resolve({ ok: false, json: async () => ({}) }),
  setInterval: (fn, ms) => { const id = nextTimerId++; timers.set(id, { fn, ms }); return id; },
  clearInterval: (id) => { clearedIds.push(id); timers.delete(id); },
  BEVMinimap: { render: () => { bevRenders += 1; } },
  StudioOverlays: { init: () => {}, bindOverlayToolbar: () => {}, loadCameraOverlays: () => {} },
  JourneySearch: { bind: () => {} },
  ScenarioModals: { init: () => {} },
  document: {
    getElementById: (id) => byId.get(id) || null,
    querySelectorAll: () => [],
    addEventListener: (ev, fn) => { (docListeners[ev] = docListeners[ev] || []).push(fn); },
  },
  addEventListener: (ev, fn) => { (winListeners[ev] = winListeners[ev] || []).push(fn); },
  dispatchEvent: (ev) => (winListeners[ev.type] || []).forEach((fn) => fn(ev)),
  _tickIntervals: () => [...timers.values()].forEach((t) => t.fn()),
};
sandbox.window = sandbox;
vm.createContext(sandbox);
const mediaPath = require('path').join(require('path').dirname(STUDIO_PATH), 'js', 'studio_media.js');
if (fs.existsSync(mediaPath)) vm.runInContext(fs.readFileSync(mediaPath, 'utf8'), sandbox);
const canvasPath = require('path').join(require('path').dirname(STUDIO_PATH), 'js', 'studio_canvas.js');
if (fs.existsSync(canvasPath)) vm.runInContext(fs.readFileSync(canvasPath, 'utf8'), sandbox);
vm.runInContext(fs.readFileSync(STUDIO_PATH, 'utf8'), sandbox);
(docListeners['DOMContentLoaded'] || []).forEach((fn) => fn());
"""


def _run_studio_vm(script: str) -> dict:
    if not shutil.which("node"):
        raise unittest.SkipTest("Node.js not installed")
    prelude = _VM_PRELUDE.replace("STUDIO_PATH", json.dumps(str(STUDIO_JS)))
    proc = subprocess.run(
        ["node", "-e", prelude + "\n" + script],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"Node VM failed:\n{proc.stderr}\n{proc.stdout}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


class TestStep2StudioMinimapGating(unittest.TestCase):
    """Verify tab-scoped 250ms BEV minimap loop and studio stream gating."""

    def test_boot_inactive_does_not_start_minimap_interval(self):
        script = """
        const initialTimers = timers.size;
        const rendersBefore = bevRenders;
        sandbox._tickIntervals();
        console.log(JSON.stringify({ initialTimers, rendersAfter: bevRenders - rendersBefore }));
        """
        out = _run_studio_vm(script)
        self.assertEqual(out["initialTimers"], 0)
        self.assertEqual(out["rendersAfter"], 0)

    def test_tab_changed_starts_and_stops_minimap_timer(self):
        script = """
        byId.get('tab-studio').classList.add('active');
        sandbox.dispatchEvent({ type: 'tab-changed', detail: { activeTab: 'tab-studio' } });
        const activeTimers = timers.size;
        const rendersOnEnter = bevRenders;
        sandbox._tickIntervals();
        const rendersAfterTick = bevRenders;
        byId.get('tab-studio').classList.remove('active');
        sandbox.dispatchEvent({ type: 'tab-changed', detail: { activeTab: 'tab-live' } });
        console.log(JSON.stringify({
          activeTimers, rendersOnEnter, rendersAfterTick,
          timersAfterLeave: timers.size, clearedCount: clearedIds.length
        }));
        """
        out = _run_studio_vm(script)
        self.assertEqual(out["activeTimers"], 1)
        self.assertEqual(out["rendersOnEnter"], 1)
        self.assertEqual(out["rendersAfterTick"], 2)
        self.assertEqual(out["timersAfterLeave"], 0)
        self.assertEqual(out["clearedCount"], 1)

    def test_minimap_loop_start_stop_idempotency(self):
        script = """
        sandbox.window.Studio.startMinimapLoop();
        sandbox.window.Studio.startMinimapLoop();
        const countAfterDoubleStart = timers.size;
        sandbox.window.Studio.stopMinimapLoop();
        sandbox.window.Studio.stopMinimapLoop();
        console.log(JSON.stringify({
          countAfterDoubleStart, countAfterDoubleStop: timers.size, cleared: clearedIds.length
        }));
        """
        out = _run_studio_vm(script)
        self.assertEqual(out["countAfterDoubleStart"], 1)
        self.assertEqual(out["countAfterDoubleStop"], 0)
        self.assertEqual(out["cleared"], 1)

    def test_camera_select_while_hidden_sets_dataset_only(self):
        script = """
        const sel = byId.get('studio-camera-select');
        const img = byId.get('studio-live-img');
        sel.value = 'cam_03';
        sel._emit('change', { target: sel });
        console.log(JSON.stringify({
          src: img.src, activeStreamSrc: img.dataset.activeStreamSrc || ''
        }));
        """
        out = _run_studio_vm(script)
        self.assertEqual(out["src"], "")
        self.assertEqual(out["activeStreamSrc"], "/stream/cam_03")

    def test_camera_select_while_active_sets_src_and_dataset(self):
        script = """
        byId.get('tab-studio').classList.add('active');
        const sel = byId.get('studio-camera-select');
        const img = byId.get('studio-live-img');
        sel.value = 'cam_04';
        sel._emit('change', { target: sel });
        console.log(JSON.stringify({
          src: img.src, activeStreamSrc: img.dataset.activeStreamSrc || ''
        }));
        """
        out = _run_studio_vm(script)
        self.assertIn("/stream/cam_04?annotated=false&t=", out["src"])
        self.assertEqual(out["activeStreamSrc"], "/stream/cam_04")


if __name__ == "__main__":
    unittest.main()
