"""Step 4 Part 2 Tests: Filtered Historical DB Heatmaps (OBS-023)."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from dashboard import dependencies as deps
from dashboard.app import app
from dashboard.services.heatmap_history_service import (
    build_filtered_heatmap_jpeg,
    build_filtered_heatmap_json,
)
from intelligent_tracker.analytics.heatmap import OccupancyHeatmap
from intelligent_tracker.database import TrackerDB

ROOT = Path(__file__).resolve().parent.parent

_NODE_VM_HEATMAP_SCRIPT = r"""
const fs = require('fs');
const vm = require('vm');
const path = require('path');

function makeEl(id, initVal = '') {
  const listeners = {}, attrs = {}, dataset = {};
  const el = {
    id, value: initVal, textContent: '', innerHTML: '', href: '', src: '', disabled: false,
    style: {}, dataset,
    classList: { contains: (c) => c === 'active', toggle: () => {}, add: () => {}, remove: () => {} },
    getAttribute: (k) => attrs[k] ?? null,
    setAttribute: (k, v) => { attrs[k] = String(v); },
    addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
    dispatch: (ev) => (listeners[ev] || []).forEach((fn) => fn()),
  };
  return el;
}

const els = {
  'tab-analytics': makeEl('tab-analytics'),
  'analytics-source-select': makeEl('analytics-source-select', 'cam_a'),
  'analytics-zone-select': makeEl('analytics-zone-select', 'Vault'),
  'analytics-event-type-select': makeEl('analytics-event-type-select', 'zone_enter'),
  'analytics-range-select': makeEl('analytics-range-select', '900'),
  'analytics-heatmap-mode-select': makeEl('analytics-heatmap-mode-select', 'all'),
  'static-heatmap-img': makeEl('static-heatmap-img'),
  'btn-download-heatmap': makeEl('btn-download-heatmap'),
  'heatmap-camera-badge': makeEl('heatmap-camera-badge'),
  'heatmap-meta-summary': makeEl('heatmap-meta-summary'),
  'heatmap-legend-min': makeEl('heatmap-legend-min'),
  'heatmap-legend-mid': makeEl('heatmap-legend-mid'),
  'heatmap-legend-max': makeEl('heatmap-legend-max'),
  'btn-refresh-heatmap': makeEl('btn-refresh-heatmap'),
};
els['static-heatmap-img'].dataset.src = '/analytics/heatmap';

const fetches = [];
const sandbox = {
  console, URLSearchParams, Date,
  document: {
    getElementById: (id) => els[id] || null,
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener: () => {},
  },
  window: {
    App: { getActiveCameraId: () => 'cam_a' },
    AnalyticsDrilldown: { setHeatmapData: () => {}, setFlowData: () => {} },
  },
  fetch: async (url) => {
    fetches.push(String(url));
    if (String(url).startsWith('/zones')) return { ok: true, json: async () => [] };
    if (String(url).startsWith('/analytics/flows')) return { ok: true, json: async () => ({ buckets: [], totals: {} }) };
    return {
      ok: true,
      json: async () => ({
        initialized: true, mode: String(url).includes('mode=filtered') ? 'filtered' : 'all',
        point_count: 7, camera_id: 'cam_a', colormap: 'JET', resolution: [640, 480],
        max_value: 2.0, decay_rate: null, radius: 25, stops: [],
      }),
    };
  },
};
sandbox.window.document = sandbox.document;
sandbox.window.fetch = sandbox.fetch;
vm.createContext(sandbox);

for (const rel of ['dashboard/static/js/live_player.js', 'dashboard/static/js/analytics_view.js']) {
  vm.runInContext(fs.readFileSync(path.join(process.env.IT_ROOT, rel), 'utf8'), sandbox);
}

(async () => {
  const flush = async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); };
  sandbox.window.AnalyticsView.initChart();
  sandbox.window.AnalyticsView.initHeatmap();
  await flush();
  const liveUrl = sandbox.window.AnalyticsView.buildHeatmapUrl('/analytics/heatmap');
  const liveImgSrc = els['static-heatmap-img'].src;

  els['analytics-heatmap-mode-select'].value = 'filtered';
  els['analytics-heatmap-mode-select'].dispatch('change');
  await flush();
  const filteredImgSrc = els['static-heatmap-img'].src;
  const filteredDlHref = els['btn-download-heatmap'].href;
  const filteredSummary = els['heatmap-meta-summary'].textContent;

  els['analytics-zone-select'].value = 'Lobby';
  els['analytics-zone-select'].dispatch('change');
  await flush();
  const afterZoneChangeSrc = els['static-heatmap-img'].src;

  console.log(JSON.stringify({
    liveUrl, liveImgSrc, filteredImgSrc, filteredDlHref, filteredSummary, afterZoneChangeSrc,
    heatmapJsonFetches: fetches.filter((u) => u.includes('/analytics/heatmap?format=json')),
  }));
})();
"""


class TestFilteredHeatmapService(unittest.TestCase):
    """Verify historical DB footpoint filtering, normalization, and rendering."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.db = TrackerDB(os.path.join(self.tmpdir.name, "hm_hist.db"))
        self.addCleanup(self.db.close)
        self.now_ts = 1_700_000_000.0
        self.ent_a = self.db.add_entity("Alice", "person")
        self.ent_b = self.db.add_entity("Bob", "person")

        # Sighting inside Vault (recent, entity A, footpoint = (100+20, 100+40) = (120, 140))
        self.db.add_sighting(
            self.ent_a, track_id=1, source="cam_a", camera_id="cam_a",
            timestamp=self.now_ts - 120.0, zone_id="cam_a:zone:Vault", bbox=[100, 100, 40, 40],
        )
        # Sighting outside time window (too old)
        self.db.add_sighting(
            self.ent_a, track_id=2, source="cam_a", camera_id="cam_a",
            timestamp=self.now_ts - 7200.0, zone_id="Vault", bbox=[400, 300, 40, 40],
        )
        # Sighting in Lobby for entity B
        self.db.add_sighting(
            self.ent_b, track_id=3, source="cam_a", camera_id="cam_a",
            timestamp=self.now_ts - 60.0, zone_id="Lobby", bbox=[480, 320, 40, 40],
        )
        # Timeline zone_enter event in Vault with metadata_json.bbox (footpoint = (120, 140))
        self.db.index_timeline_event(
            summary="Alice entered Vault", event_type="zone_enter", entity_id=self.ent_a,
            entity_name="Alice", camera_id="cam_a", zone_id="Vault",
            timestamp=self.now_ts - 90.0, metadata={"bbox": [100, 100, 40, 40]},
        )

    def test_zone_event_type_range_and_entity_filters(self) -> None:
        all_vault = build_filtered_heatmap_json(
            self.db, camera_id="cam_a", zone_id="Vault", range_sec=3600, now_ts=self.now_ts,
        )
        self.assertEqual(all_vault["mode"], "filtered")
        self.assertEqual(all_vault["point_count"], 2)
        self.assertGreater(all_vault["max_value"], 0.0)
        self.assertTrue(all_vault["hotspots"])
        # Peak hotspot should be near footpoint (120, 140)
        peak = all_vault["peak_media_ref"]
        self.assertLess(abs(peak["px"] - 120), 30)
        self.assertLess(abs(peak["py"] - 140), 30)

        only_enter = build_filtered_heatmap_json(
            self.db, camera_id="cam_a", zone_id="Vault", event_type="zone_enter",
            range_sec=3600, now_ts=self.now_ts,
        )
        self.assertEqual(only_enter["point_count"], 1)

        only_ent_b = build_filtered_heatmap_json(
            self.db, camera_id="cam_a", entity_id=self.ent_b, range_sec=3600, now_ts=self.now_ts,
        )
        self.assertEqual(only_ent_b["point_count"], 1)
        self.assertGreater(only_ent_b["peak_media_ref"]["px"], 450)

        jpeg = build_filtered_heatmap_jpeg(
            self.db, camera_id="cam_a", zone_id="Vault", range_sec=3600, now_ts=self.now_ts,
        )
        self.assertTrue(jpeg.startswith(b"\xff\xd8"))


class TestFilteredHeatmapApi(unittest.TestCase):
    """Verify GET /analytics/heatmap mode=filtered offline fallback and mode=all parity."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.db = TrackerDB(os.path.join(self.tmpdir.name, "hm_api.db"))
        self.addCleanup(self.db.close)
        ent_id = self.db.add_entity("Carol", "person")
        self.db.add_sighting(
            ent_id, track_id=9, source="cam_off", camera_id="cam_off",
            zone_id="Gate", bbox=[200, 180, 40, 60],
        )
        self._orig_deps_db = deps._db
        self._orig_state_db = getattr(app.state, "db", None)
        deps._db = self.db
        app.state.db = self.db
        self.addCleanup(self._restore_db)
        self.client = TestClient(app)

    def _restore_db(self) -> None:
        deps._db = self._orig_deps_db
        app.state.db = self._orig_state_db

    def test_filtered_mode_works_offline_while_live_mode_preserves_503_and_200(self) -> None:
        with patch("dashboard.routers.analytics.get_active_stream_manager", return_value=None), patch.object(
            deps, "get_db", return_value=self.db,
        ):
            r_live = self.client.get("/analytics/heatmap?camera_id=cam_off&format=json")
            self.assertEqual(r_live.status_code, 503)
            r_json = self.client.get("/analytics/heatmap?camera_id=cam_off&format=json&mode=filtered&zone_id=Gate")
            self.assertEqual(r_json.status_code, 200)
            payload = r_json.json()
            self.assertEqual((payload["mode"], payload["point_count"]), ("filtered", 1))
            r_img = self.client.get("/analytics/heatmap?camera_id=cam_off&mode=filtered&zone_id=Gate")
            self.assertEqual(r_img.status_code, 200)
            self.assertEqual(r_img.headers["content-type"], "image/jpeg")
            self.assertTrue(r_img.content.startswith(b"\xff\xd8"))

        hm = OccupancyHeatmap(width=320, height=240, decay_rate=None)
        hm.update([(160, 120)])
        fake_mgr = SimpleNamespace(
            camera_id="cam_live", video_filename="", run_id="",
            analytics=SimpleNamespace(heatmap=hm),
            get_heatmap_jpeg=lambda: b"\xff\xd8\xff\xd9",
        )
        with patch("dashboard.routers.analytics.get_active_stream_manager", return_value=fake_mgr):
            r_all = self.client.get("/analytics/heatmap?camera_id=cam_live&format=json")
            self.assertEqual(r_all.status_code, 200)
            self.assertEqual(r_all.json()["resolution"], [320, 240])


class TestFilteredHeatmapFrontend(unittest.TestCase):
    """Verify analytics.html lazy-load contract and Node VM filter propagation."""

    def test_analytics_html_mode_selector_and_lazy_src(self) -> None:
        html = (ROOT / "dashboard" / "static" / "partials" / "tabs" / "analytics.html").read_text(encoding="utf-8")
        self.assertIn('id="analytics-heatmap-mode-select"', html)
        self.assertIn('value="filtered"', html)
        self.assertIn('data-src="/analytics/heatmap"', html)
        self.assertIsNone(re.search(r'(?<!data-)src="/analytics/heatmap"', html))

    def test_node_vm_heatmap_mode_and_filter_propagation(self) -> None:
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        env = {**os.environ, "IT_ROOT": str(ROOT)}
        proc = subprocess.run(["node", "-e", _NODE_VM_HEATMAP_SCRIPT], capture_output=True, text=True, env=env, timeout=20, check=False)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        out = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(out["liveUrl"], "/analytics/heatmap?camera_id=cam_a")
        self.assertIn("camera_id=cam_a", out["liveImgSrc"])
        self.assertNotIn("mode=filtered", out["liveImgSrc"])
        for token in ("mode=filtered", "camera_id=cam_a", "zone_id=Vault", "event_type=zone_enter", "range_sec=3600"):
            self.assertIn(token, out["filteredImgSrc"])
            self.assertIn(token, out["filteredDlHref"])
        self.assertIn("7 pts", out["filteredSummary"])
        self.assertIn("zone_id=Lobby", out["afterZoneChangeSrc"])
        self.assertTrue(any("mode=filtered" in u and "zone_id=Lobby" in u for u in out["heatmapJsonFetches"]))


if __name__ == "__main__":
    unittest.main()
