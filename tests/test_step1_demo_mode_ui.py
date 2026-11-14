#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Node VM and static modularity tests for Step 1 Demo Mode isolation & camera focus sync."""

import json
import os
import pathlib
import shutil
import subprocess
import unittest

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
JS_DIR = ROOT_DIR / "dashboard" / "static" / "js"
STATIC_DIR = ROOT_DIR / "dashboard" / "static"

_VM_PRELUDE = r"""
const fs = require('fs'), vm = require('vm'), path = require('path');
const byId = new Map(), routes = new Map(), toasts = [], switchedCams = [], recFocused = [], gridCalls = [];
function makeEl(tag = 'div', id = '') {
  const listeners = new Map(), classes = new Set();
  const el = {
    tagName: tag.toUpperCase(), id, style: {}, value: '', textContent: '', title: '', src: '', options: [], _html: '',
    classList: {
      add: (...c) => c.forEach(x => classes.add(x)),
      remove: (...c) => c.forEach(x => classes.delete(x)),
      toggle: (c, f) => (f === undefined ? (classes.has(c) ? (classes.delete(c), false) : (classes.add(c), true)) : (f ? (classes.add(c), true) : (classes.delete(c), false))),
    },
    getAttribute: () => '',
    addEventListener: (t, fn) => { if (!listeners.has(t)) listeners.set(t, []); listeners.get(t).push(fn); },
    dispatchEvent: (ev) => { ev.currentTarget = el; ev.target = ev.target || el; return Promise.all((listeners.get(ev.type) || []).map(fn => fn(ev))); },
    click: () => el.dispatchEvent({ type: 'click' }),
    querySelectorAll: () => [],
  };
  Object.defineProperty(el, 'innerHTML', {
    get: () => el._html,
    set: (html) => {
      el._html = String(html);
      if (tag === 'select') {
        const opts = [];
        const re = /<option[^>]*value="([^"]*)"[^>]*>([^<]*)<\/option>/g;
        for (let m; (m = re.exec(el._html)) !== null;) opts.push({ value: m[1], textContent: m[2] });
        el.options = opts;
      }
    },
  });
  return el;
}
[
  ['cam-detector-select', 'select'], ['cam-tracker-select', 'select'], ['cam-source-input', 'input'],
  ['cam-name-input', 'input'], ['cam-id-input', 'input'], ['cam-conf-range', 'input'],
  ['cam-conf-input', 'input'], ['cam-conf-display', 'span'], ['cam-classes-input', 'input'],
  ['btn-quick-real-cam', 'button'], ['live-stream-img', 'img'], ['video-stream-title', 'div'],
  ['active-camera-select', 'select'], ['active-cameras-table-body', 'tbody'],
  ['multi-grid-container', 'div'], ['video-wrapper', 'div'], ['cam-preset-select', 'select'],
].forEach(([id, tag]) => byId.set(id, makeEl(tag, id)));
const detSel = byId.get('cam-detector-select');
detSel.options = [{ value: 'yolov8', textContent: 'YOLOv8' }, { value: 'mock', textContent: 'Synthetic Mock (Testing)' }];
detSel.value = 'yolov8';
let activeCam = 'cam_01';
const sandbox = {
  console, Math, Number, String, Array, Object, Map, Set, JSON, Promise, isNaN, parseFloat, parseInt, encodeURIComponent,
  document: { readyState: 'complete', getElementById: (id) => byId.get(id) || null, querySelectorAll: () => [], addEventListener: () => {} },
  App: { getActiveCameraId: () => activeCam, switchCamera: (c) => { activeCam = c; switchedCams.push(c); } },
  CameraRecording: { onCameraFocused: (c) => recFocused.push(c) },
  CameraGrid: { renderGrid: (cams, fid) => gridCalls.push({ count: cams.length, fid }) },
  CameraDiscovery: { testConnection: () => {} },
  showToast: (msg, type) => toasts.push({ msg, type }),
  fetch: async (url) => {
    const h = routes.get(url);
    return h ? h() : { ok: false, json: async () => ({}) };
  },
};
sandbox.window = sandbox;
sandbox.addEventListener = () => {};
vm.createContext(sandbox);
"""

_JS_MOCK_GATING = """
const mockOptBefore = detSel.options.find(o => o.value === 'mock').textContent;
routes.set('/api/system/capabilities', () => ({
  ok: true,
  json: async () => ({ detectors: ['yolov8', 'yolo11', 'mock', 'onnx'], trackers: ['centroid', 'sort'] }),
}));
await sandbox.CameraAIConfig.loadCapabilities();
const mockOptAfter = detSel.options.find(o => o.value === 'mock').textContent;

const srcInput = byId.get('cam-source-input');
srcInput.value = 'rtsp://192.168.1.10/stream1';
detSel.value = 'mock';
await detSel.dispatchEvent({ type: 'change' });
const sourceAfterSelectMock = srcInput.value;

await byId.get('btn-quick-real-cam').click();
const detAfterQuickReal = detSel.value;

detSel.value = 'mock';
srcInput.value = '0';
await srcInput.dispatchEvent({ type: 'change' });
const detAfterUsbZero = detSel.value;

sandbox.CameraAIConfig.setValues({ detector: 'mock', source: 'data/videos/sample.mp4', type: 'video_file' });
const detAfterSetValuesReal = detSel.value;
sandbox.CameraAIConfig.setValues({ detector: 'mock', source: 'synthetic', type: 'synthetic' });
const detAfterSetValuesSynth = detSel.value;

console.log(JSON.stringify({
  mockOptBefore, mockOptAfter, sourceAfterSelectMock, detAfterQuickReal, detAfterUsbZero,
  detAfterSetValuesReal, detAfterSetValuesSynth,
  synthFlags: [
    sandbox.CameraAIConfig.isSyntheticSource('synthetic'),
    sandbox.CameraAIConfig.isSyntheticSource('mock'),
    sandbox.CameraAIConfig.isSyntheticSource(0),
    sandbox.CameraAIConfig.isSyntheticSource('0'),
    sandbox.CameraAIConfig.isSyntheticSource('rtsp://cam/stream'),
  ],
  toasts,
}));
"""

_JS_INITIAL_FOCUS = """
const camsNoCam01 = [
  { id: 'vid_disabled', name: 'Disabled Feed', enabled: false, status: 'paused', fps: 0, source: 'a.mp4' },
  { id: 'vid_01', name: 'Lobby Clip', enabled: true, status: 'online', fps: 24, source: 'lobby.mp4' },
];
routes.set('/api/cameras', () => ({ ok: true, json: async () => camsNoCam01 }));
await sandbox.CameraManager.refreshCameras();
const stateAfterNoCam01 = {
  activeCam,
  streamSrc: byId.get('live-stream-img').src,
  streamTitle: byId.get('video-stream-title').textContent,
  selectVal: byId.get('active-camera-select').value,
  switchedCams: [...switchedCams],
  recFocused: [...recFocused],
  lastGridFid: gridCalls[gridCalls.length - 1]?.fid || null,
};
const keptCam01 = sandbox.CameraAIConfig.resolveInitialCameraId([{ id: 'cam_01', name: 'Main', enabled: true }], 'cam_01');
const emptyFallback = sandbox.CameraAIConfig.resolveInitialCameraId([], 'cam_01');
console.log(JSON.stringify({ stateAfterNoCam01, keptCam01, emptyFallback }));
"""


class TestStep1DemoModeUI(unittest.TestCase):
    """Verify Demo Simulation gating and initial camera focus sync in Node VM."""

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS runtime verification")
    def _run_vm(self, rel_files: list[str], body: str) -> dict:
        script = "\n".join([
            _VM_PRELUDE,
            "JSON.parse(process.env.JS_FILES).forEach(f => vm.runInContext(fs.readFileSync(path.join(process.env.STATIC_DIR, f), 'utf8'), sandbox, { filename: f }));",
            "(async () => {", body, "})().catch(err => { console.error(err); process.exit(1); });",
        ])
        env = dict(os.environ, STATIC_DIR=str(STATIC_DIR), JS_FILES=json.dumps(rel_files))
        proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", env=env, timeout=15)
        self.assertEqual(proc.returncode, 0, f"Node VM error:\nSTDOUT:{proc.stdout}\nSTDERR:{proc.stderr}")
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_demo_simulation_label_and_bidirectional_gating(self):
        """Mock detector displays Demo Simulation label and syncs cleanly with source changes."""
        out = self._run_vm(["js/camera_ai_config.js"], _JS_MOCK_GATING)
        expected_label = "🧪 Synthetic Mock (Demo Simulation Only)"
        self.assertEqual(out["mockOptBefore"], expected_label)
        self.assertEqual(out["mockOptAfter"], expected_label)
        self.assertEqual(out["sourceAfterSelectMock"], "synthetic")
        self.assertEqual(out["detAfterQuickReal"], "yolov8")
        self.assertEqual(out["detAfterUsbZero"], "yolov8")
        self.assertEqual(out["detAfterSetValuesReal"], "yolov8")
        self.assertEqual(out["detAfterSetValuesSynth"], "mock")
        self.assertEqual(out["synthFlags"], [True, True, False, False, False])
        toast_types = [t["type"] for t in out["toasts"]]
        self.assertIn("info", toast_types)
        self.assertIn("warning", toast_types)

    def test_initial_camera_focus_sync_when_cam01_absent(self):
        """CameraManager.refreshCameras syncs active stream and telemetry when cam_01 is missing."""
        out = self._run_vm(["js/camera_ai_config.js", "camera_manager.js"], _JS_INITIAL_FOCUS)
        state = out["stateAfterNoCam01"]
        self.assertEqual(state["activeCam"], "vid_01")
        self.assertEqual(state["streamSrc"], "/stream/vid_01?annotated=false")
        self.assertEqual(state["streamTitle"], "Camera Feed: LOBBY CLIP (vid_01)")
        self.assertEqual(state["selectVal"], "vid_01")
        self.assertIn("vid_01", state["switchedCams"])
        self.assertIn("vid_01", state["recFocused"])
        self.assertEqual(state["lastGridFid"], "vid_01")
        self.assertEqual(out["keptCam01"], "cam_01")
        self.assertEqual(out["emptyFallback"], "cam_01")

    def test_step1_modularity_line_budgets(self):
        """Modified frontend modules and pipeline bundle stay within modularity line ceilings."""
        ai_cfg_lines = len((JS_DIR / "camera_ai_config.js").read_text(encoding="utf-8").splitlines())
        cam_mgr_lines = len((STATIC_DIR / "camera_manager.js").read_text(encoding="utf-8").splitlines())
        bundle_lines = len((ROOT_DIR / "intelligent_tracker" / "pipeline" / "bundle.py").read_text(encoding="utf-8").splitlines())
        self.assertLess(ai_cfg_lines, 280)
        self.assertLessEqual(cam_mgr_lines, 366)
        self.assertLess(bundle_lines, 350)


if __name__ == "__main__":
    unittest.main()
