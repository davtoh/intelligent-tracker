#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tests for Step 4 Milestone 1: #analytics time-bucketed flows & heatmap legend."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.dependencies import bind_app_state, clear_app_state, set_shutting_down
from intelligent_tracker.database import TrackerDB

REPO_ROOT = Path(__file__).resolve().parent.parent

_VM_PRELUDE = r"""
const fs = require('fs'), vm = require('vm');
function makeEl(id = '') {
  const listeners = {}, classes = new Set();
  return {
    id, value: '3600', src: '', textContent: '', innerHTML: '', disabled: false,
    style: {}, dataset: {},
    classList: {
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      toggle: (c, f) => (f === undefined ? (classes.has(c) ? classes.delete(c) : classes.add(c)) : (f ? classes.add(c) : classes.delete(c))),
      contains: (c) => classes.has(c),
    },
    getAttribute: () => '',
    addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
    click() { (listeners.click || []).forEach((f) => f()); },
    dispatch(ev) { (listeners[ev] || []).forEach((f) => f()); },
    getContext: () => ({}),
  };
}
function runAnalyticsVm(els, fetchImpl) {
  let lastChart = null;
  function FakeChart(_ctx, cfg) {
    this.data = cfg.data; this.options = cfg.options; this.updates = 0;
    this.update = () => { this.updates += 1; };
    lastChart = this;
  }
  const doc = {
    getElementById: (id) => els[id] || null,
    querySelector: (sel) => els['__q_' + sel] || null,
    querySelectorAll: () => [],
  };
  const win = {
    Chart: FakeChart, Date, Math, Number, String, Array, Object, JSON,
    encodeURIComponent, URLSearchParams,
    App: { getActiveCameraId: () => 'cam_a' },
  };
  win.window = win;
  const ctx = vm.createContext({ window: win, document: doc, fetch: fetchImpl, Chart: FakeChart, console, ...win });
  vm.runInContext(fs.readFileSync('dashboard/static/js/analytics_view.js', 'utf8'), ctx);
  return { win, els, getChart: () => lastChart };
}
"""


def _run_node(js_body: str) -> dict:
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node runtime not found")
    proc = subprocess.run(
        [node, "-e", _VM_PRELUDE + "\n(async () => {\n" + js_body + "\n})();"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"Node VM failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


class TestAnalyticsFlowsRepoAndApi(unittest.TestCase):
    """Isolated TrackerDB and FastAPI TestClient checks for /analytics/flows & heatmap."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="step4_m1_")
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, "tracker.db")
        self.db = TrackerDB(db_path=self.db_path)
        self.addCleanup(self.db.close)
        set_shutting_down(False)
        clear_app_state(app)
        self.addCleanup(clear_app_state, app)

    def _seed_events(self, base_ts: float):
        with self.db._lock:
            cur = self.db._conn.cursor()
            rows = [
                ("tripwire_cross", "cam_a", base_ts + 30, '{"direction":"in"}'),
                ("zone_enter", "cam_a", base_ts + 45, "{}"),
                ("tripwire_cross", "cam_a", base_ts + 90, '{"direction":"out"}'),
                ("zone_exit", "cam_b", base_ts + 150, "{}"),
            ]
            for etype, cam, ts, meta in rows:
                cur.execute(
                    "INSERT INTO world_timeline_events (event_type, camera_id, timestamp, metadata_json) VALUES (?, ?, ?, ?)",
                    (etype, cam, ts, meta),
                )
            self.db._conn.commit()
        self.db.add_sighting(entity_id=None, track_id=1, source="cam_a", timestamp=base_ts + 20)
        self.db.add_sighting(entity_id=None, track_id=2, source="cam_b", timestamp=base_ts + 155)

    def test_get_traffic_flows_buckets_and_camera_filter(self):
        base_ts = 1_700_000_000.0
        self._seed_events(base_ts)
        res_all = self.db.get_traffic_flows(base_ts, base_ts + 180, bucket_sec=60)
        self.assertEqual(res_all["totals"], {"inflow": 2, "outflow": 2, "total": 4, "sightings": 2})
        self.assertEqual(len(res_all["buckets"]), 3)
        self.assertEqual(res_all["buckets"][0]["inflow"], 2)
        self.assertEqual(res_all["buckets"][0]["sightings"], 1)
        self.assertEqual(res_all["buckets"][1]["outflow"], 1)
        self.assertEqual(res_all["buckets"][2]["outflow"], 1)

        res_cam_a = self.db.get_traffic_flows(base_ts, base_ts + 180, bucket_sec=60, camera_id="cam_a")
        self.assertEqual(res_cam_a["totals"], {"inflow": 2, "outflow": 1, "total": 3, "sightings": 1})

    def test_api_flows_and_enriched_heatmap_metadata(self):
        base_ts = 1_700_000_000.0
        self._seed_events(base_ts)
        fake_hm = SimpleNamespace(
            width=640, height=480, density=np.array([[0.0, 2.0], [1.0, 1.0]], dtype=np.float32),
            colormap=2, decay_rate=0.995, radius=25,
        )
        fake_mgr = SimpleNamespace(camera_id="cam_a", analytics=SimpleNamespace(heatmap=fake_hm))
        bind_app_state(app, stream_manager=fake_mgr, db=self.db)
        client = TestClient(app)

        resp_hist = client.get(f"/analytics/flows?camera_id=cam_a&range_sec=180&bucket_sec=60&end_time={base_ts + 180}")
        self.assertEqual(resp_hist.status_code, 200)
        body = resp_hist.json()
        self.assertFalse(body["is_live"])
        self.assertEqual(body["totals"]["inflow"], 2)
        self.assertEqual(body["totals"]["outflow"], 1)

        resp_hm = client.get("/analytics/heatmap?format=json&camera_id=cam_a")
        self.assertEqual(resp_hm.status_code, 200)
        hm_data = resp_hm.json()
        self.assertTrue(hm_data["initialized"])
        self.assertEqual(hm_data["camera_id"], "cam_a")
        self.assertEqual(hm_data["colormap"], "JET")
        self.assertEqual(hm_data["radius"], 25)
        self.assertGreaterEqual(len(hm_data["stops"]), 4)

        fake_mgr.analytics.heatmap = None
        resp_empty = client.get("/analytics/heatmap?format=json")
        self.assertEqual(resp_empty.status_code, 200)
        self.assertEqual(resp_empty.json()["density"], [])
        self.assertFalse(resp_empty.json()["initialized"])


class TestAnalyticsFrontendContracts(unittest.TestCase):
    """Static HTML/CSS checks and Node VM verification for analytics_view.js."""

    def test_html_css_contracts_and_zero_eager_heatmap_src(self):
        html = (REPO_ROOT / "dashboard" / "static" / "partials" / "tabs" / "analytics.html").read_text(encoding="utf-8")
        css = (REPO_ROOT / "dashboard" / "static" / "css" / "analytics_alerts.css").read_text(encoding="utf-8")
        js = (REPO_ROOT / "dashboard" / "static" / "js" / "analytics_view.js").read_text(encoding="utf-8")

        for dom_id in (
            "analytics-range-select", "btn-analytics-prev", "btn-analytics-next",
            "btn-analytics-live", "analytics-window-label", "heatmap-legend-min",
            "heatmap-legend-mid", "heatmap-legend-max", "heatmap-meta-summary",
        ):
            self.assertIn(f'id="{dom_id}"', html)
        self.assertIn('data-src="/analytics/heatmap"', html)
        self.assertIsNone(re.search(r'(?<!data-)src="/analytics/heatmap"', html))
        self.assertNotIn("!important", css)
        self.assertIn("tabular-nums", css)
        self.assertNotIn("* 0.6", js)
        self.assertNotIn("* 0.4", js)

    _FLOW_VM_PROBE = r"""
const els = {
  trafficChart: makeEl('trafficChart'),
  'tab-analytics': makeEl('tab-analytics'),
  'analytics-range-select': makeEl('analytics-range-select'),
  'btn-analytics-prev': makeEl('btn-analytics-prev'),
  'btn-analytics-next': makeEl('btn-analytics-next'),
  'btn-analytics-live': makeEl('btn-analytics-live'),
  'analytics-window-label': makeEl('analytics-window-label'),
  'heatmap-legend-min': makeEl('heatmap-legend-min'),
  'heatmap-legend-mid': makeEl('heatmap-legend-mid'),
  'heatmap-legend-max': makeEl('heatmap-legend-max'),
  'heatmap-meta-summary': makeEl('heatmap-meta-summary'),
  '__q_#heatmap-colorbar-legend .heatmap-colorbar': makeEl('colorbar'),
};
const urls = [];
const fetchImpl = async (url) => {
  urls.push(url);
  if (url.includes('/analytics/flows')) {
    return {
      ok: true,
      json: async () => ({
        start_time: 1700000000, end_time: 1700003600, bucket_sec: 300, is_live: !url.includes('end_time='),
        buckets: [{ bucket_start: 1700000000, label: '00:00', inflow: 3, outflow: 1, total: 4, sightings: 2 }],
        totals: { inflow: 3, outflow: 1, total: 4, sightings: 2 },
      }),
    };
  }
  return {
    ok: true,
    json: async () => ({
      initialized: true, camera_id: 'cam_a', resolution: [640, 480], max_value: 8.4,
      colormap: 'JET', decay_rate: 0.995, radius: 25,
      stops: [{ ratio: 0, color: '#1d4ed8' }, { ratio: 1, color: '#ef4444' }],
    }),
  };
};
const { win, getChart } = runAnalyticsVm(els, fetchImpl);
win.AnalyticsView.initChart();
await new Promise((r) => setTimeout(r, 20));
const liveDisabledInit = els['btn-analytics-live'].disabled;
els['btn-analytics-prev'].click();
await new Promise((r) => setTimeout(r, 20));
const liveDisabledAfterPrev = els['btn-analytics-live'].disabled;
els['btn-analytics-live'].click();
await new Promise((r) => setTimeout(r, 20));
const chart = getChart();
console.log(JSON.stringify({
  urls,
  inflow: chart.data.datasets[0].data,
  outflow: chart.data.datasets[1].data,
  liveDisabledInit,
  liveDisabledAfterPrev,
  liveDisabledAfterBack: els['btn-analytics-live'].disabled,
  legendMax: els['heatmap-legend-max'].textContent,
  metaSummary: els['heatmap-meta-summary'].textContent,
  barBg: els['__q_#heatmap-colorbar-legend .heatmap-colorbar'].style.background,
}));
"""


    def test_node_vm_flow_pagination_back_to_live_and_heatmap_legend(self):
        out = _run_node(self._FLOW_VM_PROBE)
        self.assertEqual(out["inflow"], [3])
        self.assertEqual(out["outflow"], [1])
        self.assertTrue(out["liveDisabledInit"])
        self.assertFalse(out["liveDisabledAfterPrev"])
        self.assertTrue(out["liveDisabledAfterBack"])
        self.assertEqual(out["legendMax"], "8.40")
        self.assertIn("cam_a", out["metaSummary"])
        self.assertIn("JET", out["metaSummary"])
        self.assertIn("#ef4444", out["barBg"])
        self.assertTrue(any("end_time=" in u for u in out["urls"]))
        self.assertFalse("end_time=" in out["urls"][-1])


if __name__ == "__main__":
    unittest.main()
