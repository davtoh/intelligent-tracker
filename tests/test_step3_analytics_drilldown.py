#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Step 3 Milestone 2: Analytics Explicit X/Y Axes, 32x24 Heatmap Grid & Drill-Down Tests.
"""

import json
import pathlib
import re
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.dependencies import get_db
from dashboard.services.analytics_query_service import build_heatmap_json
from intelligent_tracker.database import TrackerDB

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

_VM_DRILLDOWN_SCRIPT = r"""
const vm = require('vm');
const fs = require('fs');
function makeEl(id, extra = {}) {
  const listeners = {};
  return Object.assign({
    id, value: '', textContent: '', innerHTML: '', disabled: false, hidden: true,
    dataset: {}, style: {}, clientWidth: 320, clientHeight: 240, width: 640, height: 480,
    classList: { _s: new Set(['active']), toggle(c, f) { f ? this._s.add(c) : this._s.delete(c); }, contains(c) { return this._s.has(c); } },
    getBoundingClientRect() { return { left: 0, top: 0, width: 320, height: 240 }; },
    getContext() { return { clearRect() {}, save() {}, restore() {}, strokeRect() {}, fillRect() {}, setTransform() {} }; },
    addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
    dispatch(ev, payload = {}) { (listeners[ev] || []).forEach((fn) => fn(payload)); },
  }, extra);
}
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
  'heatmap-axis-x': makeEl('heatmap-axis-x'),
  'heatmap-axis-y': makeEl('heatmap-axis-y'),
  'heatmap-hotspot-canvas': makeEl('heatmap-hotspot-canvas'),
  'heatmap-hotspot-tooltip': makeEl('heatmap-hotspot-tooltip'),
  '__q_#heatmap-colorbar-legend .heatmap-colorbar': makeEl('colorbar'),
};
const calls = { tabs: [], filters: [], toasts: [] };
let chartInst = null;
class FakeChart {
  constructor(ctx, cfg) { this.data = cfg.data; this.options = cfg.options; chartInst = this; }
  update() {}
}
const ctx = {
  console, Math, Number, String, Array, Object, Date, URLSearchParams, setTimeout, clearTimeout,
  devicePixelRatio: 2,
  Chart: FakeChart,
  document: { getElementById: (id) => els[id] || null, querySelector: (sel) => els[`__q_${sel}`] || null },
  fetch: async (url) => ({
    ok: true,
    json: async () => url.includes('/analytics/flows')
      ? {
          camera_id: 'cam_a', start_time: 1700000000, end_time: 1700000120, bucket_sec: 60,
          axes: { x: { label: 'Time', unit: 'epoch_s' }, y: { label: 'Crossings / Events', unit: 'count' } },
          buckets: [
            { bucket_start: 1700000000, bucket_end: 1700000060, label: '00:00', inflow: 5, outflow: 1, total: 6, sightings: 3 },
            { bucket_start: 1700000060, bucket_end: 1700000120, label: '00:01', inflow: 2, outflow: 0, total: 2, sightings: 1 },
          ],
          totals: { inflow: 7, outflow: 1, total: 8, sightings: 4 },
        }
      : {
          initialized: true, camera_id: 'cam_a', resolution: [640, 480], max_value: 10.0,
          colormap: 'JET', radius: 25, grid_size: [32, 24],
          grid: Array.from({ length: 24 }, (_, r) => Array.from({ length: 32 }, (_, c) => (r === 12 && c === 16 ? 1.0 : 0.2))),
          x_ticks: [0, 160, 320, 480, 640], y_ticks: [0, 120, 240, 360, 480],
          stops: [{ ratio: 0, color: '#1d4ed8' }, { ratio: 1, color: '#ef4444' }],
        },
  }),
};
ctx.window = ctx;
ctx.App = { getActiveCameraId: () => 'cam_a' };
ctx.switchTab = (t) => calls.tabs.push(t);
ctx.TimelineView = { applyFilter: (f) => calls.filters.push(f) };
ctx.showToast = (t, m) => calls.toasts.push({ t, m });
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('dashboard/static/js/analytics_drilldown.js', 'utf8'), ctx);
vm.runInContext(fs.readFileSync('dashboard/static/js/analytics_view.js', 'utf8'), ctx);
(async () => {
  ctx.AnalyticsView.initChart();
  await new Promise((r) => setTimeout(r, 20));
  chartInst.options.onClick({ native: {} }, [{ index: 0 }], chartInst);
  const peakDrill = Object.assign({}, ctx.AnalyticsDrilldown.state.lastDrilldown);
  els['heatmap-hotspot-canvas'].dispatch('mousemove', { clientX: 165, clientY: 125 });
  const tipText = els['heatmap-hotspot-tooltip'].textContent;
  const tipHidden = els['heatmap-hotspot-tooltip'].hidden;
  els['heatmap-hotspot-canvas'].dispatch('click', { clientX: 165, clientY: 125 });
  const cellDrill = Object.assign({}, ctx.AnalyticsDrilldown.state.lastDrilldown);
  console.log(JSON.stringify({
    xTitle: chartInst.options.scales.x.title.text,
    yTitle: chartInst.options.scales.y.title.text,
    xTicksHtml: els['heatmap-axis-x'].innerHTML,
    yTicksHtml: els['heatmap-axis-y'].innerHTML,
    peakDrill, tipText, tipHidden, cellDrill, calls,
  }));
})();
"""


class TestStep3AnalyticsDrilldown(unittest.TestCase):
    """Verify Step 3 Milestone 2 analytics axes, 32x24 heatmap grid, and drill-down."""

    def _make_temp_db(self) -> TrackerDB:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = TrackerDB(db_path=str(pathlib.Path(tmp.name) / "tracker.db"))
        self.addCleanup(db.close)
        return db

    def test_flows_buckets_have_bucket_end_and_axes(self):
        """query_traffic_flows_sync includes bucket_end on every bucket and axes metadata."""
        db = self._make_temp_db()
        res = db.get_traffic_flows(1700000000.0, 1700000180.0, 60, camera_id="cam_a")
        self.assertIn("axes", res)
        self.assertEqual(res["axes"]["x"]["bucket_sec"], 60)
        self.assertEqual(res["axes"]["y"]["unit"], "count")
        self.assertGreaterEqual(len(res["buckets"]), 3)
        for b in res["buckets"]:
            self.assertIn("bucket_end", b)
            self.assertAlmostEqual(b["bucket_end"] - b["bucket_start"], 60.0)

    def test_heatmap_json_32x24_grid_and_empty_safety(self):
        """build_heatmap_json computes normalized 32x24 grid + ticks and handles empty/None."""
        density = np.zeros((48, 64), dtype=np.float32)
        density[24:26, 32:34] = 5.0
        hm = SimpleNamespace(width=640, height=480, density=density, colormap=2, decay_rate=0.99, radius=25)
        mgr = SimpleNamespace(camera_id="cam_a", analytics=SimpleNamespace(heatmap=hm))
        payload = build_heatmap_json(mgr, "cam_a")
        self.assertTrue(payload["initialized"])
        self.assertEqual(payload["grid_size"], [32, 24])
        self.assertEqual(len(payload["grid"]), 24)
        self.assertEqual(len(payload["grid"][0]), 32)
        self.assertEqual(payload["grid"][12][16], 1.0)
        self.assertEqual(payload["x_ticks"], [0, 160, 320, 480, 640])
        self.assertEqual(payload["y_ticks"], [0, 120, 240, 360, 480])

        empty_mgr = SimpleNamespace(camera_id="cam_a", analytics=SimpleNamespace(heatmap=None))
        empty_payload = build_heatmap_json(empty_mgr, None)
        self.assertFalse(empty_payload["initialized"])
        self.assertEqual(empty_payload["grid"], [])

    def test_fastapi_analytics_flows_and_heatmap_routes(self):
        """FastAPI /analytics/flows and /analytics/heatmap?format=json return Milestone 2 fields."""
        db = self._make_temp_db()
        density = np.ones((24, 32), dtype=np.float32) * 2.0
        hm = SimpleNamespace(width=320, height=240, density=density, colormap=2, decay_rate=None, radius=20)
        fake_mgr = MagicMock()
        fake_mgr.camera_id = "cam_b"
        fake_mgr.analytics = SimpleNamespace(heatmap=hm)
        prev_overrides = dict(app.dependency_overrides)
        app.dependency_overrides[get_db] = lambda: db
        self.addCleanup(lambda: app.dependency_overrides.clear() or app.dependency_overrides.update(prev_overrides))

        with unittest.mock.patch("dashboard.routers.analytics.get_active_stream_manager", return_value=fake_mgr):
            client = TestClient(app)
            r_flow = client.get("/analytics/flows?camera_id=cam_b&range_sec=120&bucket_sec=60&end_time=1700000120")
            self.assertEqual(r_flow.status_code, 200)
            self.assertIn("axes", r_flow.json())
            self.assertIn("bucket_end", r_flow.json()["buckets"][0])
            r_hm = client.get("/analytics/heatmap?format=json&camera_id=cam_b")
            self.assertEqual(r_hm.status_code, 200)
            self.assertEqual(r_hm.json()["grid_size"], [32, 24])

    def test_html_partials_and_lazy_heatmap_invariant(self):
        """analytics.html, scripts_traceability.html, and index.html satisfy DOM & budget contracts."""
        html = (REPO_ROOT / "dashboard" / "static" / "partials" / "tabs" / "analytics.html").read_text(encoding="utf-8")
        idx = (REPO_ROOT / "dashboard" / "static" / "index.html").read_text(encoding="utf-8")
        part = (REPO_ROOT / "dashboard" / "static" / "partials" / "scripts_traceability.html").read_text(encoding="utf-8")
        for dom_id in ("heatmap-stage-wrap", "heatmap-hotspot-canvas", "heatmap-axis-x", "heatmap-axis-y", "heatmap-hotspot-tooltip"):
            self.assertIn(f'id="{dom_id}"', html)
        self.assertIn('data-src="/analytics/heatmap"', html)
        self.assertIsNone(re.search(r'(?<!data-)src="/analytics/heatmap"', html))
        self.assertLess(len(idx.splitlines()), 180)
        self.assertIn("scripts_traceability.html", idx)
        self.assertIn("analytics_drilldown.js", part)

    def test_node_vm_chart_peak_and_heatmap_hotspot_drilldown(self):
        """Node VM verifies Chart.js axes, peak click drill-down, and HiDPI 32x24 hotspot click."""
        proc = subprocess.run(["node", "-e", _VM_DRILLDOWN_SCRIPT], cwd=str(REPO_ROOT), capture_output=True, text=True, check=True)
        out = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertIn("Time", out["xTitle"])
        self.assertEqual(out["yTitle"], "Crossings / Events")
        self.assertIn("640px", out["xTicksHtml"])
        self.assertIn("480px", out["yTicksHtml"])
        self.assertEqual(out["peakDrill"]["startTime"], 1700000000)
        self.assertEqual(out["peakDrill"]["endTime"], 1700000060)
        self.assertFalse(out["tipHidden"])
        self.assertIn("Cell (16,12)", out["tipText"])
        self.assertEqual(out["cellDrill"]["cellX"], 16)
        self.assertEqual(out["cellDrill"]["cellY"], 12)
        self.assertEqual(out["calls"]["tabs"], ["tab-timeline", "tab-timeline"])
