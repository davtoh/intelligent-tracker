"""Step 4 unit and Node VM tests for overflow containment, status popover cleanup, and JS guards."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / "dashboard" / "static"
JS = STATIC / "js"
CSS = STATIC / "css"


def _run_node(script: str) -> dict:
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False, timeout=20)
    if proc.returncode != 0:
        raise AssertionError(f"Node VM failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return json.loads(proc.stdout.strip())


def _dom_stub_js() -> str:
    return (
        "function mkEl(tag) {\n"
        "  const attrs = {}, cls = new Set();\n"
        "  return {\n"
        "    tagName: (tag || 'SPAN').toUpperCase(), textContent: '', title: '', className: '',\n"
        "    style: {}, dataset: {}, children: [],\n"
        "    classList: { add: (c) => cls.add(c), remove: (c) => cls.delete(c), contains: (c) => cls.has(c) },\n"
        "    setAttribute: (k, v) => { attrs[k] = String(v); }, getAttribute: (k) => attrs[k] ?? null,\n"
        "    hasAttribute: (k) => Object.prototype.hasOwnProperty.call(attrs, k),\n"
        "    removeAttribute: (k) => { delete attrs[k]; }, addEventListener: () => {},\n"
        "    querySelector: () => null, appendChild: () => {},\n"
        "    getBoundingClientRect: () => ({ left: 0, top: 0, right: 100, bottom: 20, width: 100, height: 20 }),\n"
        "  };\n"
        "}\n"
    )


class TestStep4CssAndBudgetContracts(unittest.TestCase):
    """Static CSS overflow-containment rules, zero !important, and line budgets."""

    def test_overflow_containment_css_rules_present_without_important(self) -> None:
        files = {
            "sidebar.css": (CSS / "sidebar.css").read_text(encoding="utf-8"),
            "scrubber.css": (CSS / "scrubber.css").read_text(encoding="utf-8"),
            "views.css": (CSS / "views.css").read_text(encoding="utf-8"),
            "analytics_alerts.css": (CSS / "analytics_alerts.css").read_text(encoding="utf-8"),
            "review.css": (CSS / "review.css").read_text(encoding="utf-8"),
        }
        for name, text in files.items():
            self.assertNotIn("!important", text, f"{name} must not use !important")
            self.assertLess(len(text.splitlines()), 350, f"{name} exceeded 350L soft ceiling")
        self.assertRegex(files["sidebar.css"], r"\.sidebar-column\s*\{[^}]*min-width:\s*0")
        self.assertRegex(files["scrubber.css"], r"\.upload-status-hint\s*\{[^}]*overflow-wrap:\s*anywhere")
        self.assertIn("minmax(0, 1fr) minmax(0, 1fr)", files["views.css"])
        self.assertRegex(files["analytics_alerts.css"], r"#analytics-source-select[^{]*\{[^}]*max-width:")
        self.assertRegex(files["review.css"], r"\.review-meta\s*\{[^}]*min-width:\s*0")
        self.assertRegex(files["review.css"], r"\.review-title\s*\{[^}]*overflow-wrap:\s*anywhere")

    def test_analytics_view_syncs_source_select_title(self) -> None:
        text = (JS / "analytics_view.js").read_text(encoding="utf-8")
        self.assertLess(len(text.splitlines()), 350)
        self.assertIn("sel.title =", text)


@unittest.skipUnless(shutil.which("node"), "Node.js required for JS VM tests")
class TestStep4PopoverCleanupContracts(unittest.TestCase):
    """Node VM tests verifying OBS-012 stale popover cleanup across camera/mode switches."""

    def test_text_truncation_manager_clear_removes_attributes_and_hides_popover(self) -> None:
        script = (
            "const fs = require('fs'), vm = require('vm');\n"
            + _dom_stub_js()
            + f"const tCode = fs.readFileSync({json.dumps(str(JS / 'text_truncation_manager.js'))}, 'utf8');\n"
            "const pop = mkEl('div'); pop.querySelector = () => mkEl('span');\n"
            "const target = mkEl('span');\n"
            "const doc = { readyState: 'loading', getElementById: (id) => id === 'text-truncation-popover' ? pop : null, createElement: mkEl, body: { appendChild: () => {} }, addEventListener: () => {}, querySelectorAll: () => [] };\n"
            "const sb = { window: { innerWidth: 1280 }, document: doc, console, Math, Number, String, Boolean, Array, Object, setTimeout, clearTimeout };\n"
            "sb.self = sb; vm.runInNewContext(tCode, sb);\n"
            "const mgr = sb.TextTruncationManager; mgr.popoverEl = pop; mgr.titleEl = mkEl('span'); mgr.bodyEl = mkEl('div');\n"
            "mgr.apply(target, { fullText: 'Connected (very_long_camera_identifier_01)', mode: 'middle', maxLength: 24, label: 'Active Stream' });\n"
            "mgr.showPopover(target, 'Connected (very_long_camera_identifier_01)', 'Active Stream');\n"
            "const before = { trigger: target.classList.contains('truncate-trigger'), full: target.getAttribute('data-full-text'), visible: pop.classList.contains('visible') };\n"
            "mgr.clear(target);\n"
            "const after = { trigger: target.classList.contains('truncate-trigger'), full: target.hasAttribute('data-full-text'), label: target.hasAttribute('data-truncate-label'), desc: target.hasAttribute('aria-describedby'), exp: target.hasAttribute('aria-expanded'), role: target.hasAttribute('role'), tab: target.hasAttribute('tabindex'), visible: pop.classList.contains('visible'), cur: mgr.currentTarget === null };\n"
            "process.stdout.write(JSON.stringify({ before, after }));\n"
        )
        out = _run_node(script)
        self.assertTrue(out["before"]["trigger"])
        self.assertTrue(out["before"]["visible"])
        self.assertFalse(out["after"]["trigger"])
        self.assertFalse(out["after"]["full"])
        self.assertFalse(out["after"]["label"])
        self.assertFalse(out["after"]["desc"])
        self.assertFalse(out["after"]["exp"])
        self.assertFalse(out["after"]["role"])
        self.assertFalse(out["after"]["tab"])
        self.assertFalse(out["after"]["visible"])
        self.assertTrue(out["after"]["cur"])

    def test_ws_and_telemetry_status_clear_stale_popover_on_short_camera(self) -> None:
        script = (
            "const fs = require('fs'), vm = require('vm');\n"
            + _dom_stub_js()
            + f"const tCode = fs.readFileSync({json.dumps(str(JS / 'text_truncation_manager.js'))}, 'utf8');\n"
            f"const hCode = fs.readFileSync({json.dumps(str(JS / 'app_ui_helpers.js'))}, 'utf8');\n"
            f"const gCode = fs.readFileSync({json.dumps(str(JS / 'telemetry.js'))}, 'utf8');\n"
            "const pill = mkEl('div'), txt = mkEl('span'), pop = mkEl('div');\n"
            "const els = { 'connection-status-pill': pill, 'connection-status-text': txt, 'text-truncation-popover': pop };\n"
            "const doc = { readyState: 'loading', getElementById: (id) => els[id] || null, addEventListener: () => {}, querySelectorAll: () => [] };\n"
            "const win = { innerWidth: 1280, location: { protocol: 'http:', host: '127.0.0.1' } };\n"
            "const sb = { window: win, document: doc, console, Math, Number, String, Boolean, Array, Object, setTimeout, clearTimeout };\n"
            "sb.self = sb; win.window = win; vm.runInNewContext(tCode, sb); win.TextTruncationManager = sb.TextTruncationManager;\n"
            "vm.runInNewContext(hCode, sb); vm.runInNewContext(gCode, sb);\n"
            "win.AppUIHelpers.updateWsStatus(true, 'vid_warehouse_long_recording_01', pill, txt);\n"
            "const afterLong = { cls: txt.classList.contains('truncate-trigger'), full: txt.getAttribute('data-full-text') };\n"
            "win.AppUIHelpers.updateWsStatus(true, 'cam_01', pill, txt);\n"
            "const afterShortWs = { cls: txt.classList.contains('truncate-trigger'), full: txt.hasAttribute('data-full-text'), text: txt.textContent };\n"
            "win.TelemetryGateway.updateConnectionStatus({ status: 'online', camera_id: 'vid_warehouse_long_recording_01' }, 'cam_01');\n"
            "const afterLongTel = { cls: txt.classList.contains('truncate-trigger'), full: txt.getAttribute('data-full-text') };\n"
            "win.TelemetryGateway.updateConnectionStatus({ status: 'simulation', camera_id: 'cam_01' }, 'cam_01');\n"
            "const afterSimTel = { cls: txt.classList.contains('truncate-trigger'), full: txt.hasAttribute('data-full-text'), text: txt.textContent };\n"
            "process.stdout.write(JSON.stringify({ afterLong, afterShortWs, afterLongTel, afterSimTel }));\n"
        )
        out = _run_node(script)
        self.assertTrue(out["afterLong"]["cls"])
        self.assertEqual(out["afterLong"]["full"], "Connected (vid_warehouse_long_recording_01)")
        self.assertFalse(out["afterShortWs"]["cls"])
        self.assertFalse(out["afterShortWs"]["full"])
        self.assertEqual(out["afterShortWs"]["text"], "Connected (cam_01)")
        self.assertTrue(out["afterLongTel"]["cls"])
        self.assertFalse(out["afterSimTel"]["cls"])
        self.assertFalse(out["afterSimTel"]["full"])
        self.assertEqual(out["afterSimTel"]["text"], "Simulation")

    def test_app_switch_camera_clears_stale_status_truncation(self) -> None:
        script = (
            "const fs = require('fs'), vm = require('vm');\n"
            + _dom_stub_js()
            + f"const hCode = fs.readFileSync({json.dumps(str(JS / 'app_ui_helpers.js'))}, 'utf8');\n"
            f"const aCode = fs.readFileSync({json.dumps(str(STATIC / 'app.js'))}, 'utf8');\n"
            "const txt = mkEl('span'); txt.classList.add('truncate-trigger'); txt.setAttribute('data-full-text', 'Connected (long_video_feed_name_01)');\n"
            "const listeners = {}; const els = { 'connection-status-text': txt };\n"
            "const doc = { readyState: 'complete', hidden: false, getElementById: (id) => els[id] || null, querySelector: () => null, querySelectorAll: () => [], addEventListener: (e, cb) => { (listeners[e] ||= []).push(cb); } };\n"
            "const win = { location: { hash: '' }, scrollX: 0, scrollTo: () => {}, history: { pushState: () => {} }, addEventListener: () => {} };\n"
            "const sb = { window: win, document: doc, history: win.history, console, Math, Number, String, Boolean, Array, Object, JSON, Promise, setTimeout, clearTimeout };\n"
            "vm.runInNewContext(hCode, sb); vm.runInNewContext(aCode, sb); (listeners.DOMContentLoaded || []).forEach((f) => f());\n"
            "win.App.switchCamera('cam_01');\n"
            "process.stdout.write(JSON.stringify({ cls: txt.classList.contains('truncate-trigger'), full: txt.hasAttribute('data-full-text') }));\n"
        )
        out = _run_node(script)
        self.assertFalse(out["cls"])
        self.assertFalse(out["full"])


if __name__ == "__main__":
    unittest.main()
