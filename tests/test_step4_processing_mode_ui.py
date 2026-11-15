#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit, Node VM, and FastAPI tests for Step 4 Milestone 1: Processing Mode UI."""

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from dashboard.app import app

REPO_ROOT = Path(__file__).resolve().parent.parent
CSS_PATH = REPO_ROOT / "dashboard" / "static" / "css" / "processing_mode.css"
STYLES_PATH = REPO_ROOT / "dashboard" / "static" / "styles.css"
JS_PATH = REPO_ROOT / "dashboard" / "static" / "js" / "processing_mode.js"
INDEX_PATH = REPO_ROOT / "dashboard" / "static" / "index.html"
NAV_TABS_PATH = REPO_ROOT / "dashboard" / "static" / "js" / "nav_tabs_manager.js"
LIVE_PLAYER_PATH = REPO_ROOT / "dashboard" / "static" / "js" / "live_player.js"

_NODE_PREAMBLE = """
function makeEl(id, initialVal) {
  const listeners = {};
  const classes = new Set();
  return {
    id, value: initialVal || '', textContent: '', title: '', className: '',
    dataset: {},
    classList: {
      toggle: (cls, force) => (force === undefined
        ? (classes.has(cls) ? classes.delete(cls) : classes.add(cls))
        : (force ? classes.add(cls) : classes.delete(cls))),
      contains: (cls) => classes.has(cls),
    },
    addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
    dispatch: (ev, payload) => (listeners[ev] || []).forEach(fn => fn(payload || {})),
  };
}
"""


_NODE_SANDBOX_TMPL = """
const els = {{
  'processing-mode-select': makeEl('processing-mode-select', 'focus_only'),
  'processing-mode-dot': makeEl('processing-mode-dot'),
  'processing-mode-deferred-badge': makeEl('processing-mode-deferred-badge'),
  'active-camera-select': makeEl('active-camera-select', 'cam_01'),
}};
const store = {{}};
if ({saved_js} !== null) store['it_processing_mode'] = {saved_js};
const fetchCalls = [];
const winListeners = {{}};
const docListeners = {{}};
const windowObj = {{
  localStorage: {{
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => {{ store[k] = String(v); }},
  }},
  addEventListener: (ev, fn) => {{ (winListeners[ev] = winListeners[ev] || []).push(fn); }},
  dispatchEvent: (ev) => (winListeners[ev.type] || []).forEach(fn => fn(ev)),
}};
const documentObj = {{
  readyState: 'complete',
  hidden: false,
  getElementById: (id) => els[id] || null,
  addEventListener: (ev, fn) => {{ (docListeners[ev] = docListeners[ev] || []).push(fn); }},
  dispatch: (ev) => (docListeners[ev] || []).forEach(fn => fn({{ type: ev }})),
}};
async function fakeFetch(url, opts) {{
  const method = (opts && opts.method) || 'GET';
  const bodyObj = opts && opts.body ? JSON.parse(opts.body) : null;
  fetchCalls.push({{ url, method, body: bodyObj }});
  const mode = (bodyObj && bodyObj.mode) || {saved_js} || 'focus_only';
  const cam = (bodyObj && bodyObj.focused_camera_id) || 'cam_01';
  const tab = (bodyObj && bodyObj.active_tab) || 'live';
  return {{
    ok: true,
    json: async () => ({{
      mode, focused_camera_id: cam, active_tab: tab, deferred_jobs: {deferred_js}
    }}),
  }};
}}
const sandbox = {{
  window: windowObj, document: documentObj, fetch: fakeFetch,
  Array, Object, String, Number, Boolean, JSON, Promise, console,
}};
sandbox.globalThis = sandbox;
vm.runInNewContext(code, sandbox);
"""


def _run_node(body: str, saved_mode: str | None = None, deferred_count: int = 0) -> dict:
    """Execute a JS test snippet with processing_mode.js loaded in a Node VM."""
    saved_js = json.dumps(saved_mode)
    deferred_js = json.dumps([{"job_id": f"j{i}"} for i in range(deferred_count)])
    script = (
        "const fs = require('fs'), vm = require('vm');\n"
        f"const code = fs.readFileSync({json.dumps(str(JS_PATH))}, 'utf8');\n"
        + _NODE_PREAMBLE
        + _NODE_SANDBOX_TMPL.format(saved_js=saved_js, deferred_js=deferred_js)
        + f"(async () => {{\n{body}\n}})().then(res => process.stdout.write(JSON.stringify(res)))"
        + ".catch(err => { console.error(err); process.exit(1); });\n"
    )
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, env=dict(os.environ), timeout=15)
    if proc.returncode != 0:
        raise AssertionError(f"Node VM failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}")
    return json.loads(proc.stdout)


class TestProcessingModeAssetsAndBudgets(unittest.TestCase):
    """Verify static files, HTML/CSS wiring, and modularity line budgets."""

    def test_css_and_js_budgets_and_no_important(self) -> None:
        css_text = CSS_PATH.read_text(encoding="utf-8")
        js_text = JS_PATH.read_text(encoding="utf-8")
        self.assertLess(len(css_text.splitlines()), 140)
        self.assertNotIn("!important", css_text)
        self.assertLess(len(js_text.splitlines()), 220)
        self.assertIn("css/processing_mode.css", STYLES_PATH.read_text(encoding="utf-8"))

    def test_index_html_mounts_pill_and_stays_under_budget(self) -> None:
        html = INDEX_PATH.read_text(encoding="utf-8")
        self.assertLess(len(html.splitlines()), 180)
        for token in (
            "/static/css/processing_mode.css",
            'id="processing-mode-pill"',
            'id="processing-mode-select"',
            'id="processing-mode-dot"',
            'id="processing-mode-deferred-badge"',
            "/static/js/processing_mode.js",
        ):
            self.assertIn(token, html)

    def test_nav_tabs_and_live_player_hooks_present(self) -> None:
        nav_js = NAV_TABS_PATH.read_text(encoding="utf-8")
        live_js = LIVE_PLAYER_PATH.read_text(encoding="utf-8")
        self.assertIn("ProcessingModeUI?.syncTabChange", nav_js)
        self.assertIn("ProcessingModeUI?.syncCameraFocus", live_js)


class TestProcessingModeUIVM(unittest.TestCase):
    """Verify ProcessingModeUI behavior in isolated Node VM."""

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_init_fetches_status_and_renders_deferred_badge(self) -> None:
        res = _run_node(
            "for (let i = 0; i < 6; i++) await Promise.resolve();\n"
            "return { calls: fetchCalls, badge: els['processing-mode-deferred-badge'].textContent, "
            "hidden: els['processing-mode-deferred-badge'].classList.contains('is-hidden'), "
            "dot: els['processing-mode-dot'].className };",
            deferred_count=2,
        )
        self.assertEqual(res["calls"][0]["method"], "GET")
        self.assertEqual(res["badge"], "2")
        self.assertFalse(res["hidden"])
        self.assertIn("mode-focus_only", res["dot"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_init_restores_localstorage_mode_via_post(self) -> None:
        res = _run_node(
            "await Promise.resolve();\n"
            "return { calls: fetchCalls, selectVal: els['processing-mode-select'].value };",
            saved_mode="capture_only",
        )
        self.assertEqual(res["calls"][0]["method"], "POST")
        self.assertEqual(res["calls"][0]["body"]["mode"], "capture_only")
        self.assertEqual(res["selectVal"], "capture_only")

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_set_mode_persists_localstorage_and_updates_dot(self) -> None:
        res = _run_node(
            "await windowObj.ProcessingModeUI.setMode('full_realtime');\n"
            "return { stored: store['it_processing_mode'], dot: els['processing-mode-dot'].className, "
            "lastCall: fetchCalls[fetchCalls.length - 1] };"
        )
        self.assertEqual(res["stored"], "full_realtime")
        self.assertIn("mode-full_realtime", res["dot"])
        self.assertEqual(res["lastCall"]["body"], {"mode": "full_realtime"})

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_tab_change_visibility_and_camera_focus_sync(self) -> None:
        res = _run_node(
            "windowObj.dispatchEvent({ type: 'tab-changed', detail: { activeTab: 'tab-videos' } });\n"
            "documentObj.hidden = true; documentObj.dispatch('visibilitychange');\n"
            "documentObj.hidden = false; documentObj.dispatch('visibilitychange');\n"
            "els['active-camera-select'].dispatch('change', { target: { value: 'cam_02' } });\n"
            "await Promise.resolve();\n"
            "return { calls: fetchCalls.slice(1).map(c => c.body) };"
        )
        self.assertEqual(
            res["calls"],
            [
                {"active_tab": "videos"},
                {"active_tab": "hidden"},
                {"active_tab": "videos"},
                {"focused_camera_id": "cam_02"},
            ],
        )


class TestProcessingModeStaticEndpoints(unittest.TestCase):
    """Verify FastAPI serves the new processing mode CSS/JS assets and pill HTML."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_static_assets_and_index_return_200(self) -> None:
        for path in ("/static/css/processing_mode.css", "/static/js/processing_mode.js", "/"):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200, f"Failed GET {path}")
        html = self.client.get("/").text
        self.assertIn('id="processing-mode-pill"', html)
        self.assertIn('id="processing-mode-select"', html)


if __name__ == "__main__":
    unittest.main()
