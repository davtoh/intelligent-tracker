"""Step 4 M4 tests: #journey empty-prefix suggestions, #analytics filters/pagination & #alerts overlay isolation."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.dependencies import bind_app_state, clear_app_state, set_shutting_down
from intelligent_tracker.database import TrackerDB

REPO_ROOT = Path(__file__).resolve().parent.parent
JS_DIR = REPO_ROOT / "dashboard" / "static" / "js"


def _run_vm(js_files: list[Path], body: str) -> dict:
    """Run an async JS snippet inside an isolated Node.js VM context."""
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node binary not available")
    loaders = "\n".join(
        f"vm.runInContext(fs.readFileSync({json.dumps(str(p))}, 'utf8'), ctx);"
        for p in js_files
    )
    runner = (
        "const fs = require('fs'); const vm = require('vm');\n"
        "const sandbox = { console, setTimeout, clearTimeout, URLSearchParams, encodeURIComponent, "
        "Math, Date, Number, String, Boolean, Array, Object, JSON, Set, Map };\n"
        "sandbox.window = sandbox; sandbox.self = sandbox;\n"
        "const ctx = vm.createContext(sandbox);\n"
        f"{loaders}\n"
        f"vm.runInContext({json.dumps('(async () => {' + body + '})()')}, ctx)"
        ".then((r) => process.stdout.write(JSON.stringify(r)))"
        ".catch((e) => { console.error(e); process.exit(1); });"
    )
    proc = subprocess.run([node, "-e", runner], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise AssertionError(f"Node VM failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return json.loads(proc.stdout)


class TestAnalyticsFlowsFiltersAndPaginationBackend(unittest.TestCase):
    """Verify video:<filename>, zone_id, event_type, and bucket pagination in TrackerDB & /analytics/flows."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="step4_m4_")
        self.addCleanup(self._tmp.cleanup)
        self.db = TrackerDB(db_path=os.path.join(self._tmp.name, "tracker.db"))
        self.addCleanup(self.db.close)
        set_shutting_down(False)
        clear_app_state(app)
        self.addCleanup(clear_app_state, app)
        self.base_ts = 1_700_000_000.0
        self._seed_data()

    def _seed_data(self) -> None:
        with self.db._lock:
            cur = self.db._conn.cursor()
            rows = [
                ("zone_enter", "cam_a", "lobby", "", self.base_ts + 10, "{}"),
                ("zone_exit", "cam_a", "vault", "", self.base_ts + 70, "{}"),
                ("tripwire_cross", "cam_a", "lobby", "", self.base_ts + 130, '{"direction":"in"}'),
                ("zone_enter", "", "dock", "clip.mp4", self.base_ts + 190, "{}"),
            ]
            for etype, cam, zone, vfile, ts, meta in rows:
                cur.execute(
                    "INSERT INTO world_timeline_events (event_type, camera_id, zone_id, video_filename, timestamp, metadata_json) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (etype, cam, zone, vfile, ts, meta),
                )
            self.db._conn.commit()
        self.db.add_sighting(entity_id=None, track_id=1, source="video_job", video_filename="clip.mp4", zone_id="dock", timestamp=self.base_ts + 195)
        self.db.add_sighting(entity_id=None, track_id=2, source="cam_a", camera_id="cam_a", zone_id="lobby", timestamp=self.base_ts + 15)

    def test_video_prefix_matches_sightings_video_filename(self) -> None:
        """video:<filename> matches sightings.video_filename and world_timeline_events.video_filename."""
        res = self.db.get_traffic_flows(self.base_ts, self.base_ts + 240, bucket_sec=60, camera_id="video:clip.mp4")
        self.assertEqual(res["totals"]["inflow"], 1)
        self.assertEqual(res["totals"]["sightings"], 1)

    def test_zone_event_type_filters_and_bucket_pagination_api(self) -> None:
        """GET /analytics/flows filters by zone_id/event_type and paginates buckets."""
        bind_app_state(app, db=self.db)
        client = TestClient(app)

        r_zone = client.get(f"/analytics/flows?camera_id=cam_a&zone_id=lobby&range_sec=240&bucket_sec=60&end_time={self.base_ts + 240}")
        self.assertEqual(r_zone.status_code, 200)
        b_zone = r_zone.json()
        self.assertEqual(b_zone["totals"], {"inflow": 2, "outflow": 0, "total": 2, "sightings": 1})

        r_ev = client.get(f"/analytics/flows?camera_id=cam_a&event_type=zone_exit&range_sec=240&bucket_sec=60&end_time={self.base_ts + 240}")
        self.assertEqual(r_ev.status_code, 200)
        self.assertEqual(r_ev.json()["totals"], {"inflow": 0, "outflow": 1, "total": 1, "sightings": 0})

        r_sig = client.get(f"/analytics/flows?camera_id=video:clip.mp4&event_type=sighting&range_sec=240&bucket_sec=60&end_time={self.base_ts + 240}")
        self.assertEqual(r_sig.status_code, 200)
        self.assertEqual(r_sig.json()["totals"], {"inflow": 0, "outflow": 0, "total": 0, "sightings": 1})

        r_pg = client.get(f"/analytics/flows?camera_id=cam_a&range_sec=240&bucket_sec=60&end_time={self.base_ts + 240}&page=2&page_size=2")
        self.assertEqual(r_pg.status_code, 200)
        pg_body = r_pg.json()
        self.assertEqual(len(pg_body["buckets"]), 2)
        self.assertEqual(pg_body["pagination"], {"page": 2, "page_size": 2, "total_buckets": 4, "total_pages": 2, "has_prev": True, "has_next": False})


_JOURNEY_VM_BODY = """
const listeners = {}; const docListeners = {}; const urls = [];
const makeEl = (id) => {
  const classes = new Set(['hidden']);
  return {
    id, value: '', innerHTML: '', children: [], dataset: {},
    classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c), contains: (c) => classes.has(c) },
    contains: (t) => t === elMap[id],
    addEventListener: (ev, fn) => { listeners[id + ':' + ev] = fn; },
  };
};
const elMap = {};
['journey-search-query', 'journey-suggest-list', 'btn-journey-search', 'btn-journey-export', 'journey-results-container']
  .forEach((id) => { elMap[id] = makeEl(id); });
window.document = {
  getElementById: (id) => elMap[id] || null,
  addEventListener: (ev, fn) => { docListeners[ev] = fn; },
};
window.fetch = async (url) => {
  urls.push(url);
  return { ok: true, json: async () => ({ items: [{ id: 1, name: 'Alice', category: 'person' }] }) };
};
window.JourneySearch.bind();
await listeners['journey-search-query:focus']();
const openAfterFocus = !elMap['journey-suggest-list'].classList.contains('hidden');
listeners['journey-search-query:keydown']({ key: 'Escape', preventDefault() {} });
const hiddenAfterEsc = elMap['journey-suggest-list'].classList.contains('hidden');
await listeners['journey-search-query:click']();
const openAfterClick = !elMap['journey-suggest-list'].classList.contains('hidden');
docListeners.pointerdown({ target: { id: 'outside' } });
const hiddenAfterOutside = elMap['journey-suggest-list'].classList.contains('hidden');
return { urls, openAfterFocus, hiddenAfterEsc, openAfterClick, hiddenAfterOutside };
"""

_ANALYTICS_VM_BODY = """
const urls = []; const els = {};
const makeEl = (id, val = '') => {
  const ls = {}; const cls = new Set();
  const el = {
    id, value: val, innerHTML: '', textContent: '', disabled: false, style: {}, dataset: {},
    classList: { add: (c) => cls.add(c), remove: (c) => cls.delete(c), toggle: (c, f) => (f ? cls.add(c) : cls.delete(c)), contains: (c) => cls.has(c) },
    addEventListener: (ev, fn) => { ls[ev] = fn; },
    trigger: (ev) => ls[ev]?.(),
    getContext: () => ({}),
  };
  els[id] = el; return el;
};
makeEl('trafficChart'); makeEl('tab-analytics');
makeEl('analytics-source-select', 'video:demo.mp4');
makeEl('analytics-zone-select', '');
makeEl('analytics-event-type-select', '');
makeEl('analytics-range-select', '3600');
makeEl('btn-analytics-prev'); makeEl('btn-analytics-next'); makeEl('btn-analytics-live');
makeEl('analytics-window-label'); makeEl('analytics-bucket-page-summary');
window.document = { getElementById: (id) => els[id] || null, querySelector: () => null, querySelectorAll: () => [] };
window.fetch = async (url) => {
  urls.push(url);
  if (url === '/zones') return { ok: true, json: async () => [{ name: 'lobby' }] };
  if (url.startsWith('/analytics/flows')) {
    return { ok: true, json: async () => ({
      start_time: 1000, end_time: 4600, bucket_sec: 300, is_live: !url.includes('end_time='),
      buckets: [{ bucket_start: 1000, label: '00:00', inflow: 2, outflow: 1 }],
      totals: { inflow: 2, outflow: 1, total: 3, sightings: 1 },
      pagination: { page: 1, page_size: 1, total_buckets: 3, total_pages: 3, has_prev: false, has_next: true },
    }) };
  }
  return { ok: true, json: async () => ({ initialized: false }) };
};
window.AnalyticsView.initChart();
await new Promise((r) => setTimeout(r, 15));
els['analytics-zone-select'].value = 'lobby';
els['analytics-event-type-select'].value = 'zone_enter';
els['analytics-zone-select'].trigger('change');
await new Promise((r) => setTimeout(r, 15));
els['btn-analytics-prev'].trigger('click');
await new Promise((r) => setTimeout(r, 15));
const liveBtnEnabledAfterPrev = !els['btn-analytics-live'].disabled;
els['btn-analytics-live'].trigger('click');
await new Promise((r) => setTimeout(r, 15));
return {
  urls,
  pageSummary: els['analytics-bucket-page-summary'].textContent,
  liveBtnEnabledAfterPrev,
  liveBtnDisabledAfterBack: els['btn-analytics-live'].disabled,
};
"""

_ALERTS_SNAPSHOT_VM_BODY = """
const els = {}; const urls = []; const drawStats = { zones: 0, boxes: 0, clears: 0 };
let roCallback = null; let roDisconnected = 0;
window.ResizeObserver = class {
  constructor(cb) { roCallback = cb; }
  observe() {}
  disconnect() { roDisconnected += 1; }
};
const makeEl = (id) => {
  const el = {
    id, value: '', innerHTML: '', textContent: '', disabled: false, hidden: false, style: {}, dataset: {},
    width: 640, height: 360, naturalWidth: 640, naturalHeight: 360, complete: true,
    addEventListener() {}, querySelectorAll: () => [],
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 640, height: 360 }),
    getContext: () => el._ctx,
  };
  els[id] = el; return el;
};
[
  'alerts-filter-camera', 'alerts-filter-severity', 'alerts-filter-type', 'alerts-filter-zone',
  'alerts-table-body', 'total-alerts-count', 'alerts-prev-btn', 'alerts-next-btn', 'alerts-page-info',
  'modal-snapshot-view', 'snapshot-modal-img', 'snapshot-modal-canvas', 'snapshot-modal-controls', 'snapshot-modal-meta',
].forEach(makeEl);
els['snapshot-modal-canvas']._ctx = {
  setTransform() {}, clearRect() { drawStats.clears += 1; }, save() {}, restore() {},
  fillRect() {}, strokeRect() { drawStats.boxes += 1; }, measureText: (t) => ({ width: t.length * 6 }),
  fillText() {}, beginPath() {}, moveTo() {}, lineTo() {}, closePath() {},
  fill() { drawStats.zones += 1; }, stroke() {}, setLineDash() {},
};
els['snapshot-modal-img'].parentElement = { getBoundingClientRect: () => ({ left: 0, top: 0, width: 640, height: 360 }) };
window.document = { getElementById: (id) => els[id] || null, querySelectorAll: () => [] };
window.App = { getActiveCameraId: () => 'cam_active' };
window.devicePixelRatio = 1;
window.fetch = async (url) => {
  urls.push(url);
  if (url.startsWith('/api/scenarios/')) {
    return { ok: true, json: async () => ({
      zones: [{ name: 'Vault', polygon: [[10, 10], [100, 10], [100, 100]] }],
      tripwires: [{ name: 'Door', line: [[0, 50], [200, 50]] }],
    }) };
  }
  return { ok: true, json: async () => ({
    items: [{ id: 1, event_type: 'zone_enter', camera_id: 'cam_1', zone_id: 'Vault', snapshot_base64: 'ZmFrZQ==', metadata: { bbox: [10, 20, 80, 90] } }],
    total: 1, offset: 0, limit: 50, has_more: false,
  }) };
};
els['alerts-filter-camera'].value = '';
await window.AlertsView.loadAlerts();
const allCamsUrl = urls[0];
window.AlertsView.openAlertSnapshot(0);
await new Promise((r) => setTimeout(r, 15));
const zonesAfterHydrate = drawStats.zones;
const boxesBeforeResize = drawStats.boxes;
if (roCallback) roCallback();
const boxesAfterResize = drawStats.boxes;
const controlsBeforeTimeline = els['snapshot-modal-controls'].innerHTML.includes('overlay-feature-pill');
window.GalleryTimeline.showSnapshotModal('/crops/s1.jpg', 'Timeline Crop');
return {
  allCamsUrl,
  zonesAfterHydrate,
  resized: boxesAfterResize > boxesBeforeResize,
  controlsBeforeTimeline,
  controlsHiddenAfterTimeline: els['snapshot-modal-controls'].hidden,
  controlsHtmlAfterTimeline: els['snapshot-modal-controls'].innerHTML,
  roDisconnected,
};
"""


class TestStep4M4FrontendContractsVM(unittest.TestCase):
    """Node VM tests for #journey suggestions, #analytics filters/pagination & #alerts overlay isolation."""

    def test_journey_empty_prefix_focus_click_and_dismiss(self) -> None:
        """#journey fetches empty-prefix suggestions on focus/click and dismisses on Escape/outside pointerdown."""
        out = _run_vm([JS_DIR / "journey_search.js"], _JOURNEY_VM_BODY)
        self.assertTrue(any(u == "/api/entities/suggest?q=&limit=8" for u in out["urls"]))
        self.assertTrue(out["openAfterFocus"])
        self.assertTrue(out["hiddenAfterEsc"])
        self.assertTrue(out["openAfterClick"])
        self.assertTrue(out["hiddenAfterOutside"])

    def test_analytics_zone_event_filters_pagination_and_back_to_live(self) -> None:
        """#analytics passes zone_id, event_type, video: source, renders bucket summary, and supports Back to Live."""
        out = _run_vm([JS_DIR / "analytics_view.js"], _ANALYTICS_VM_BODY)
        self.assertTrue(any("camera_id=video%3Ademo.mp4" in u for u in out["urls"]))
        self.assertTrue(any("zone_id=lobby" in u and "event_type=zone_enter" in u for u in out["urls"]))
        self.assertIn("Page 1/3", out["pageSummary"])
        self.assertTrue(out["liveBtnEnabledAfterPrev"])
        self.assertTrue(out["liveBtnDisabledAfterBack"])

    def test_alerts_all_cameras_parity_zone_hydration_resize_and_timeline_reset(self) -> None:
        """#alerts respects All Cameras (''), hydrates zones + ResizeObserver, and #timeline resets overlay cleanly."""
        out = _run_vm([
            JS_DIR / "unified_canvas_overlay.js",
            JS_DIR / "overlay_control_bar.js",
            JS_DIR / "snapshot_modal_overlay.js",
            JS_DIR / "alerts_view.js",
            JS_DIR / "gallery_timeline.js",
        ], _ALERTS_SNAPSHOT_VM_BODY)
        self.assertNotIn("camera_id=", out["allCamsUrl"])
        self.assertGreaterEqual(out["zonesAfterHydrate"], 1)
        self.assertTrue(out["resized"])
        self.assertTrue(out["controlsBeforeTimeline"])
        self.assertTrue(out["controlsHiddenAfterTimeline"])
        self.assertEqual(out["controlsHtmlAfterTimeline"], "")
        self.assertGreaterEqual(out["roDisconnected"], 1)


if __name__ == "__main__":
    unittest.main()
