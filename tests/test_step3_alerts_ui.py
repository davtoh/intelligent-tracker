#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Node VM and HTML/JS surface contract tests for #alerts lifecycle & badge sync (Step 3 M4)."""

import json
import pathlib
import subprocess
import unittest

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR / "dashboard" / "static"

_HARNESS_HEAD = (
    "const fs = require('fs'), vm = require('vm');\n"
    "const byId = new Map();\n"
    "const makeEl = (id, extra = {}) => {\n"
    "  const el = {\n"
    "    id, value: '', innerHTML: '', textContent: '', disabled: false, hidden: false,\n"
    "    style: {}, dataset: {}, children: [], _listeners: {}, _classes: new Set(),\n"
    "    classList: {\n"
    "      add(c) { el._classes.add(c); }, remove(c) { el._classes.delete(c); },\n"
    "      toggle(c, f) { const on = f === undefined ? !el._classes.has(c) : Boolean(f); on ? el._classes.add(c) : el._classes.delete(c); return on; },\n"
    "    },\n"
    "    addEventListener(ev, fn) { this._listeners[ev] = fn; },\n"
    "    dispatchEvent(ev) { const fn = this._listeners[ev?.type]; if (fn) fn(ev); },\n"
    "    querySelectorAll() { return []; }, click() { this._clicked = true; },\n"
    "    remove() { this._removed = true; }, appendChild(c) { this.children.push(c); },\n"
    "    getBoundingClientRect() { return { left: 0, top: 0, width: 640, height: 360 }; }, ...extra,\n"
    "  }; byId.set(id, el); return el;\n"
    "};\n"
    "const sandbox = {\n"
    "  console, setTimeout, clearTimeout, setInterval: () => 1, clearInterval() {}, addEventListener() {}, scrollTo() {}, scrollX: 0, scrollY: 0,\n"
    "  URLSearchParams, encodeURIComponent, Event: function (t) { this.type = t; },\n"
    "  document: {\n"
    "    body: { appendChild() {} }, getElementById: (id) => byId.get(id) || null,\n"
    "    querySelectorAll: () => [],\n"
    "    createElement: (tag) => ({ tag, style: {}, click() { this._clicked = true; }, remove() {} }),\n"
    "  }, window: null,\n"
    "};\n"
    "sandbox.window = sandbox;\n"
)


def _run_vm(scripts: list[pathlib.Path], body: str) -> dict:
    """Execute a Node VM harness loading the given JS files and return parsed JSON."""
    paths_json = json.dumps([str(s) for s in scripts])
    harness = (
        f"{_HARNESS_HEAD}"
        f"for (const p of {paths_json}) vm.runInNewContext(fs.readFileSync(p, 'utf8'), sandbox);\n"
        f"(async () => {{\n{body}\n}})().catch((e) => {{ console.error(e); process.exit(1); }});\n"
    )
    proc = subprocess.run(["node", "-e", harness], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Node VM failed ({proc.returncode}): {proc.stderr or proc.stdout}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


class TestStep3AlertsUI(unittest.TestCase):
    """Verify #alerts admin lifecycle, real unread badge sync, and deep-links."""

    def test_alerts_html_and_scripts_surface_contract(self) -> None:
        alerts_html = (STATIC_DIR / "partials" / "tabs" / "alerts.html").read_text(encoding="utf-8")
        scripts_html = (STATIC_DIR / "partials" / "scripts_traceability.html").read_text(encoding="utf-8")
        modals_html = (STATIC_DIR / "partials" / "modals" / "video_modals.html").read_text(encoding="utf-8")
        for el_id in (
            "alerts-type-options", "alerts-zone-options", "btn-alerts-mark-all-read",
            "btn-alerts-bulk-clear", "btn-alerts-export-csv", "btn-alerts-export-json",
        ):
            self.assertIn(f'id="{el_id}"', alerts_html)
        self.assertIn("/static/js/alerts_admin.js", scripts_html)
        self.assertIn('id="btn-snapshot-download"', modals_html)
        self.assertLess(len(modals_html.splitlines()), 240)

    def test_facets_acknowledge_delete_clear_and_export(self) -> None:
        body = """
        ['alerts-filter-camera','alerts-filter-severity','alerts-filter-type','alerts-filter-zone',
         'alerts-type-options','alerts-zone-options','alerts-filter-apply','alerts-filter-reset',
         'alerts-prev-btn','alerts-next-btn','alerts-page-info','alerts-table-body','total-alerts-count',
         'btn-alerts-mark-all-read','btn-alerts-bulk-clear','btn-alerts-export-csv','btn-alerts-export-json',
         'btn-snapshot-download','modal-snapshot-view','snapshot-modal-img','snapshot-modal-canvas',
         'snapshot-modal-controls','snapshot-modal-meta','header-alert-badge','drawer-alert-badge'].forEach((id) => makeEl(id));
        const calls = [];
        let unread = 3;
        sandbox.fetch = async (url, opts = {}) => {
          calls.push({ url, method: opts.method || 'GET' });
          if (url === '/api/events/facets') return { ok: true, json: async () => ({ cameras: ['cam_a', 'cam_b'], event_types: ['intrusion'], zones: ['vault'] }) };
          if (url === '/api/events/acknowledge') { unread = 0; return { ok: true, json: async () => ({ updated: 3, is_read: true, unread_alert_count: 0 }) }; }
          if (url.startsWith('/api/events/12')) { unread = 2; return { ok: true, json: async () => ({ deleted: true, unread_alert_count: 2 }) }; }
          if (url === '/api/events/clear') { unread = 0; return { ok: true, json: async () => ({ deleted: 1, unread_alert_count: 0 }) }; }
          return { ok: true, json: async () => ({ items: [{ id: 12, event_type: 'intrusion', camera_id: 'cam_a', zone_id: 'vault', timestamp: 1700000100, is_read: false }], total: 1, unread_alert_count: unread, has_more: false }) };
        };
        await sandbox.AlertsView.applyFilter({ camera_id: 'cam_a', severity: 'critical' });
        const camOpts = byId.get('alerts-filter-camera').innerHTML;
        const rowsHtml = byId.get('alerts-table-body').innerHTML;
        await sandbox.AlertsAdmin.acknowledgeEvents({ markAll: true });
        const badgeAfterAck = byId.get('header-alert-badge').textContent;
        await sandbox.AlertsAdmin.deleteEvent(12);
        await sandbox.AlertsAdmin.clearMatchingEvents({ camera_id: 'cam_a' });
        const csvUrl = sandbox.AlertsAdmin.exportEvents('csv', { camera_id: 'cam_a' });
        console.log(JSON.stringify({ camOpts, rowsHtml, badgeAfterAck, csvUrl, calls }));
        """
        res = _run_vm([STATIC_DIR / "js" / "app_ui_helpers.js", STATIC_DIR / "js" / "alerts_admin.js", STATIC_DIR / "js" / "alerts_view.js"], body)
        self.assertIn("cam_a", res["camOpts"])
        self.assertIn("alert-row-unread", res["rowsHtml"])
        self.assertEqual(res["badgeAfterAck"], "0")
        self.assertIn("/api/events/export?format=csv&camera_id=cam_a", res["csvUrl"])
        methods = [(c["method"], c["url"]) for c in res["calls"]]
        self.assertIn(("PATCH", "/api/events/acknowledge"), methods)
        self.assertIn(("DELETE", "/api/events/12"), methods)
        self.assertIn(("POST", "/api/events/clear"), methods)

    def test_zone_source_deeplinks_and_real_unread_badge_sync(self) -> None:
        body = """
        ['header-alert-badge','drawer-alert-badge','tab-live','studio-camera-select'].forEach((id) => makeEl(id));
        const domListeners = [], tabs = [], switchedCams = [];
        sandbox.switchTab = (t) => tabs.push(t);
        sandbox.App = { switchCamera: (c) => switchedCams.push(c) };
        sandbox.AlertsAdmin.jumpToLiveMonitor('cam_a');
        sandbox.AlertsAdmin.jumpToScenarioStudio('cam_b', 'vault');
        sandbox.document.addEventListener = (ev, fn) => { if (ev === 'DOMContentLoaded') domListeners.push(fn); };
        sandbox.history = { pushState() {} };
        sandbox.location = { hash: '#tab-live', protocol: 'http:', host: 'localhost:8000' };
        sandbox.localStorage = { getItem: () => 'cam_1' };
        sandbox.TelemetryGateway = { initWebSocket: (c, onTel) => { sandbox.__onTel = onTel; }, updateKpiDisplays() {}, renderMiniAlerts() {} };
        sandbox.LivePlayer = { attachLiveStream() {}, detachLiveStream() {}, isPaused: () => false, bindHudButtons() {} };
        vm.runInNewContext(fs.readFileSync('dashboard/static/app.js', 'utf8'), sandbox);
        domListeners.forEach((fn) => fn());
        const eightRead = Array.from({ length: 8 }, (_, i) => ({ id: i + 1, is_read: true }));
        sandbox.__onTel({ active_tracks: [], recent_alerts: eightRead, unread_alert_count: 0 });
        const afterZero = byId.get('header-alert-badge').textContent;
        sandbox.fetch = async () => ({ ok: true, json: async () => ({ items: eightRead, unread_alert_count: 2 }) });
        await sandbox.GridTileOverlay.refreshPoolAlerts();
        console.log(JSON.stringify({ afterZero, afterPool: byId.get('header-alert-badge').textContent, drawerPool: byId.get('drawer-alert-badge').textContent, tabs, switchedCams, studioCam: byId.get('studio-camera-select').value }));
        """
        res = _run_vm([STATIC_DIR / "js" / "app_ui_helpers.js", STATIC_DIR / "js" / "alerts_admin.js", STATIC_DIR / "js" / "multiview" / "grid_tile_overlay.js"], body)
        self.assertEqual(res["afterZero"], "0")
        self.assertEqual(res["afterPool"], "2")
        self.assertEqual(res["drawerPool"], "2")
        self.assertEqual(res["tabs"], ["tab-live", "tab-studio"])
        self.assertEqual(res["switchedCams"], ["cam_a"])
        self.assertEqual(res["studioCam"], "cam_b")


if __name__ == "__main__":
    unittest.main()
