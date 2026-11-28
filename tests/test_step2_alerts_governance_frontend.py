"""Milestone 3 Node VM frontend contract tests for Step 2: Alerts Governance & Rules UI."""

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
    "    id, value: '', innerHTML: '', textContent: '', disabled: false, style: {}, dataset: {},\n"
    "    _listeners: {},\n"
    "    addEventListener(ev, fn) { this._listeners[ev] = fn; },\n"
    "    dispatchEvent(ev) { const fn = this._listeners[ev?.type]; if (fn) fn(ev); },\n"
    "    querySelectorAll() { return []; }, click() { this._clicked = true; },\n"
    "    ...extra,\n"
    "  }; byId.set(id, el); return el;\n"
    "};\n"
    "const sandbox = {\n"
    "  console, setTimeout, clearTimeout, URLSearchParams, encodeURIComponent,\n"
    "  document: { body: { appendChild() {} }, getElementById: (id) => byId.get(id) || null, querySelectorAll: () => [] },\n"
    "  window: null,\n"
    "};\n"
    "sandbox.window = sandbox;\n"
)


def _run_vm(scripts: list[pathlib.Path], body: str) -> dict:
    """Execute a Node VM harness loading JS files and return parsed JSON."""
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


_RULES_FETCH_MOCK = """
['alerts-filter-min-severity','alert-rules-list','alert-rules-count','alert-policy-status',
 'alert-rule-name','alert-rule-event-type','alert-rule-zone','alert-rule-min-dwell',
 'alert-rule-severity','alert-rule-tags','btn-alert-rule-add','btn-alerts-save-policy'].forEach((id) => makeEl(id));
const calls = [];
let rules = [{ id: 1, name: 'Existing Rule', enabled: true, event_type: 'zone_dwell', zone_id: 'vault', min_dwell_time: 10, target_severity: 'warning' }];
let policy = { dwell_override: null, alert_sensitivity: 1.0, extra: { min_severity: 'warning' } };
sandbox.fetch = async (url, opts = {}) => {
  const method = opts.method || 'GET', payload = opts.body ? JSON.parse(opts.body) : null;
  calls.push({ url, method, payload });
  if (url === '/api/alerts/rules' && method === 'GET') return { ok: true, json: async () => ({ rules }) };
  if (url === '/api/alerts/rules' && method === 'POST') { const c = { id: 2, ...payload }; rules = [...rules, c]; return { ok: true, json: async () => ({ rule: c }) }; }
  if (url === '/api/alerts/rules/2' && method === 'PUT') { rules = rules.map((r) => (r.id === 2 ? { ...r, ...payload } : r)); return { ok: true, json: async () => ({ rule: rules.find((r) => r.id === 2) }) }; }
  if (url === '/api/alerts/rules/2' && method === 'DELETE') { rules = rules.filter((r) => r.id !== 2); return { ok: true, json: async () => ({ deleted: true, rule_id: 2 }) }; }
  if (url === '/api/alerts/policy' && method === 'GET') return { ok: true, json: async () => ({ policy }) };
  if (url === '/api/alerts/policy' && method === 'PUT') { policy = { ...policy, extra: { ...policy.extra, ...(payload.extra || {}) } }; return { ok: true, json: async () => ({ policy }) }; }
  return { ok: false, status: 404, json: async () => ({}) };
};
"""


class TestStep2AlertsGovernanceFrontend(unittest.TestCase):
    """Verify #alerts dwell window, min_severity filter, canonical facets, and promotion rules UI."""

    def test_html_and_index_surface_budgets(self) -> None:
        """alerts.html exposes min-severity + rules panel; index.html loads alert_rules.js under 180L."""
        alerts_html = (STATIC_DIR / "partials" / "tabs" / "alerts.html").read_text(encoding="utf-8")
        index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        for el_id in (
            "alerts-filter-min-severity", "alerts-rules-panel", "alert-rules-list",
            "alert-rule-name", "btn-alert-rule-add", "btn-alerts-save-policy",
        ):
            self.assertIn(f'id="{el_id}"', alerts_html)
        self.assertIn("/static/js/alert_rules.js", index_html)
        self.assertLess(len(index_html.splitlines()), 180)

    def test_alerts_view_dwell_window_min_severity_and_reset(self) -> None:
        """OBS-033: ev.summary + dwell window render without title shadowing; min_severity wired & reset."""
        body = """
        ['alerts-filter-camera','alerts-filter-severity','alerts-filter-min-severity','alerts-filter-type',
         'alerts-filter-zone','alerts-type-options','alerts-zone-options','alerts-filter-apply',
         'alerts-filter-reset','alerts-prev-btn','alerts-next-btn','alerts-page-info','alerts-table-body',
         'total-alerts-count'].forEach((id) => makeEl(id));
        const urls = [];
        sandbox.fetch = async (url) => {
          urls.push(url);
          if (url === '/api/events/facets') return { ok: true, json: async () => ({ cameras: ['cam_1'], event_types: ['zone_exit'], zones: ['cam_1:zone:Lobby', 'Lobby'] }) };
          return { ok: true, json: async () => ({
            items: [{
              id: 5, event_type: 'zone_exit', severity: 'critical', camera_id: 'cam_1', zone_id: 'Lobby',
              timestamp: 1700000125, title: 'Zone Exit', summary: 'Track #7 exited Lobby after 25.0s',
              metadata: { entry_time: 1700000100, exit_time: 1700000125, dwell_time: 25.0, promoted_by_rule: 'Long Dwell' },
            }], total: 1, unread_alert_count: 1, has_more: false,
          }) };
        };
        await sandbox.AlertsView.applyFilter({ min_severity: 'warning', zone_id: 'lobby' });
        const rowHtml = byId.get('alerts-table-body').innerHTML, zoneOpts = byId.get('alerts-zone-options').innerHTML;
        byId.get('alerts-filter-reset').dispatchEvent({ type: 'click' });
        await new Promise((r) => setTimeout(r, 10));
        console.log(JSON.stringify({ urls, rowHtml, zoneOpts, minAfterReset: byId.get('alerts-filter-min-severity').value }));
        """
        res = _run_vm([STATIC_DIR / "js" / "alerts_admin.js", STATIC_DIR / "js" / "alerts_view.js"], body)
        self.assertTrue(any("min_severity=warning" in u for u in res["urls"]))
        self.assertIn("Track #7 exited Lobby after 25.0s", res["rowHtml"])
        self.assertIn("-&gt;", res["rowHtml"])
        self.assertIn("25.0s", res["rowHtml"])
        self.assertIn("Long Dwell", res["rowHtml"])
        self.assertEqual(res["zoneOpts"].count('value="Lobby"'), 1)
        self.assertEqual(res["minAfterReset"], "")

    def test_alert_rules_crud_and_policy_persistence(self) -> None:
        """alert_rules.js loads/creates/toggles/deletes promotion rules and persists min_severity policy."""
        body = _RULES_FETCH_MOCK + """
        await sandbox.AlertRules.ensureLoaded(true);
        const initMin = byId.get('alerts-filter-min-severity').value;
        byId.get('alert-rule-name').value = 'Lobby Dwell';
        byId.get('alert-rule-event-type').value = 'zone_dwell';
        byId.get('alert-rule-zone').value = 'lobby';
        byId.get('alert-rule-min-dwell').value = '15';
        byId.get('alert-rule-severity').value = 'critical';
        await sandbox.AlertRules.createRuleFromForm();
        const afterCreateHtml = byId.get('alert-rules-list').innerHTML;
        await sandbox.AlertRules.toggleRule(2, false);
        await sandbox.AlertRules.deleteRule(2);
        byId.get('alerts-filter-min-severity').value = 'critical';
        await sandbox.AlertRules.saveDefaultMinSeverity();
        console.log(JSON.stringify({ initMin, afterCreateHtml, status: byId.get('alert-policy-status').textContent, calls }));
        """
        res = _run_vm([STATIC_DIR / "js" / "alert_rules.js"], body)
        self.assertEqual(res["initMin"], "warning")
        self.assertIn("Lobby Dwell", res["afterCreateHtml"])
        self.assertEqual(res["status"], "Default: critical+")
        methods = [(c["method"], c["url"]) for c in res["calls"]]
        self.assertIn(("POST", "/api/alerts/rules"), methods)
        self.assertIn(("PUT", "/api/alerts/rules/2"), methods)
        self.assertIn(("DELETE", "/api/alerts/rules/2"), methods)
        self.assertIn(("PUT", "/api/alerts/policy"), methods)


if __name__ == "__main__":
    unittest.main()
