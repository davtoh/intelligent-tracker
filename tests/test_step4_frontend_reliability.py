"""Step 4 frontend reliability tests: cam_01 404 removal, null .scrollLeft, MjpegReconnect."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIVE_HTML = ROOT / "dashboard" / "static" / "partials" / "tabs" / "live.html"
DIAG_JS = ROOT / "dashboard" / "static" / "js" / "camera_diagnostics_ui.js"
NAV_JS = ROOT / "dashboard" / "static" / "js" / "nav_tabs_manager.js"
RECONNECT_JS = ROOT / "dashboard" / "static" / "js" / "mjpeg_reconnect.js"


def _run_node(script: str) -> dict:
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(proc.stdout.strip())


class TestStep4FrontendReliability(unittest.TestCase):
    """Verify live.html placeholder, diagnostics polling guard, null wrapper safety, and MjpegReconnect."""

    def test_live_html_uses_loading_placeholder_and_no_cam01_src(self) -> None:
        html = LIVE_HTML.read_text(encoding="utf-8")
        self.assertIn('<option value="">Loading cameras...</option>', html)
        self.assertNotIn('<option value="cam_01">', html)
        self.assertIn('id="live-stream-img"', html)
        self.assertNotIn('/stream/cam_01', html)

    @unittest.skipUnless(shutil.which("node"), "Node.js required for JS VM tests")
    def test_diagnostics_skips_empty_or_unloaded_camera_id(self) -> None:
        script = f"""
const fs = require('fs'), vm = require('vm');
const code = fs.readFileSync({json.dumps(str(DIAG_JS))}, 'utf8');
const calls = [];
const selectEl = {{ value: '', options: [{{ value: '' }}] }};
const doc = {{ getElementById: (id) => (id === 'active-camera-select' ? selectEl : null), addEventListener: () => {{}} }};
const win = {{}};
const sb = {{ window: win, document: doc, fetch: (u) => {{ calls.push(u); return Promise.resolve({{ ok: true, json: async () => ({{}}) }}); }}, setInterval: () => 1, encodeURIComponent, Array, Object, Promise, console }};
sb.globalThis = sb;
vm.runInNewContext(code, sb);
(async () => {{
  await win.CameraDiagnosticsUI.checkActiveCameraHealth();
  selectEl.value = 'cam_01';
  selectEl.options = [{{ value: 'cam_usb_0' }}];
  await win.CameraDiagnosticsUI.checkActiveCameraHealth();
  process.stdout.write(JSON.stringify({{ count: calls.length }}));
}})();
"""
        self.assertEqual(_run_node(script)["count"], 0)

    @unittest.skipUnless(shutil.which("node"), "Node.js required for JS VM tests")
    def test_diagnostics_polls_loaded_camera_id(self) -> None:
        script = f"""
const fs = require('fs'), vm = require('vm');
const code = fs.readFileSync({json.dumps(str(DIAG_JS))}, 'utf8');
const calls = [];
const selectEl = {{ value: 'cam_usb_0', options: [{{ value: 'cam_usb_0' }}] }};
const doc = {{ getElementById: (id) => (id === 'active-camera-select' ? selectEl : null), addEventListener: () => {{}} }};
const win = {{}};
const sb = {{ window: win, document: doc, fetch: (u) => {{ calls.push(u); return Promise.resolve({{ ok: true, json: async () => ({{ status: 'online' }}) }}); }}, setInterval: () => 1, encodeURIComponent, Array, Object, Promise, console }};
sb.globalThis = sb;
vm.runInNewContext(code, sb);
(async () => {{
  await win.CameraDiagnosticsUI.checkActiveCameraHealth();
  process.stdout.write(JSON.stringify({{ calls }}));
}})();
"""
        self.assertEqual(_run_node(script)["calls"], ["/api/cameras/cam_usb_0/diagnostics"])

    @unittest.skipUnless(shutil.which("node"), "Node.js required for JS VM tests")
    def test_nav_tabs_manager_null_wrapper_scrollleft_safe(self) -> None:
        script = f"""
const fs = require('fs'), vm = require('vm');
const code = fs.readFileSync({json.dumps(str(NAV_JS))}, 'utf8');
const doc = {{ readyState: 'complete', getElementById: () => null, querySelector: () => null, querySelectorAll: () => [], addEventListener: () => {{}} }};
const win = {{ scrollX: 0, scrollTo: () => {{}}, addEventListener: () => {{}} }};
const sb = {{ window: win, document: doc, Date, Map, Set, Array, String, Math, Promise, setTimeout: () => 1, console }};
sb.globalThis = sb;
vm.runInNewContext(code, sb);
const mgr = win.navTabsManager;
mgr.scrollNext();
mgr.scrollPrev();
const start = mgr.isAtStart();
const end = mgr.isAtEnd();
mgr.updateScrollButtons();
mgr.switchTab('tab-studio');
process.stdout.write(JSON.stringify({{ start, end }}));
"""
        res = _run_node(script)
        self.assertTrue(res["start"])
        self.assertTrue(res["end"])

    @unittest.skipUnless(shutil.which("node"), "Node.js required for JS VM tests")
    def test_mjpeg_reconnect_exponential_backoff_and_detach(self) -> None:
        script = f"""
const fs = require('fs'), vm = require('vm');
const code = fs.readFileSync({json.dumps(str(RECONNECT_JS))}, 'utf8');
let nextId = 1;
const timers = new Map();
const setT = (fn, ms) => {{ const id = nextId++; timers.set(id, {{ fn, ms }}); return id; }};
const clrT = (id) => timers.delete(id);
const listeners = {{}};
const img = {{ src: '/stream/cam_usb_0?annotated=true', isConnected: true, addEventListener: (k, f) => {{ listeners[k] = f; }}, removeEventListener: (k) => {{ delete listeners[k]; }} }};
const win = {{}};
const sb = {{ window: win, WeakMap, String, Math, encodeURIComponent, Date: {{ now: () => 12345 }}, setTimeout: setT, clearTimeout: clrT, console }};
vm.runInNewContext(code, sb);
win.MjpegReconnect.attach(img, {{ baseDelayMs: 1000, maxDelayMs: 4000, stallTimeoutMs: 0, now: () => 999 }});
listeners.error();
const [id1, first] = Array.from(timers.entries())[0];
timers.delete(id1);
first.fn();
const src1 = img.src;
listeners.error();
const second = Array.from(timers.values())[0];
win.MjpegReconnect.detach(img);
process.stdout.write(JSON.stringify({{ d1: first.ms, d2: second.ms, src1, remaining: timers.size }}));
"""
        res = _run_node(script)
        self.assertEqual(res["d1"], 1000)
        self.assertEqual(res["d2"], 2000)
        self.assertEqual(res["src1"], "/stream/cam_usb_0?annotated=true&_r=999")
        self.assertEqual(res["remaining"], 0)

    @unittest.skipUnless(shutil.which("node"), "Node.js required for JS VM tests")
    def test_mjpeg_reconnect_stall_watchdog_and_detach_all(self) -> None:
        script = f"""
const fs = require('fs'), vm = require('vm');
const code = fs.readFileSync({json.dumps(str(RECONNECT_JS))}, 'utf8');
let nextId = 1;
const timers = new Map();
const setT = (fn, ms) => {{ const id = nextId++; timers.set(id, {{ fn, ms }}); return id; }};
const clrT = (id) => timers.delete(id);
const img = {{ src: '/stream/cam_usb_0?annotated=true', isConnected: true, addEventListener: () => {{}}, removeEventListener: () => {{}} }};
const container = {{ querySelectorAll: () => [img] }};
const win = {{}};
const sb = {{ window: win, WeakMap, String, Math, encodeURIComponent, Date: {{ now: () => 555 }}, setTimeout: setT, clearTimeout: clrT, console }};
vm.runInNewContext(code, sb);
win.MjpegReconnect.attach(img, {{ baseDelayMs: 500, maxDelayMs: 4000, stallTimeoutMs: 5000, now: () => 777 }});
const stallTimer = Array.from(timers.entries())[0];
timers.delete(stallTimer[0]);
stallTimer[1].fn();
const retryMs = Array.from(timers.values())[0].ms;
win.MjpegReconnect.detachAll(container);
process.stdout.write(JSON.stringify({{ stallMs: stallTimer[1].ms, retryMs, remaining: timers.size }}));
"""
        res = _run_node(script)
        self.assertEqual(res["stallMs"], 5000)
        self.assertEqual(res["retryMs"], 500)
        self.assertEqual(res["remaining"], 0)
