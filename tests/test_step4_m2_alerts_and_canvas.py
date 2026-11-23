"""Unit, FastAPI TestClient, and Node VM tests for Step 4 M2: #alerts filters/pagination & canvas preview."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.dependencies import get_db
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.events.types import ZoneEvent
from intelligent_tracker.memory._event_formatters import format_zone_event

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "dashboard" / "static"


def _run_node_vm(js_files: list[Path], script: str) -> dict:
    """Execute a JS test snippet inside an isolated Node VM context."""
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node binary not available")
    loaders = "\n".join(
        f"vm.runInContext(fs.readFileSync({json.dumps(str(p))}, 'utf8'), ctx);"
        for p in js_files
    )
    runner = (
        "const fs = require('fs'); const vm = require('vm');\n"
        "const sandbox = { console, setTimeout, clearTimeout, URLSearchParams, Math, Date, Number, String, Boolean, Array, Object, JSON, Set, Map };\n"
        "sandbox.window = sandbox; sandbox.self = sandbox;\n"
        "const ctx = vm.createContext(sandbox);\n"
        f"{loaders}\n"
        f"Promise.resolve().then(async () => {{\n{script}\n}})"
        ".then(res => process.stdout.write(JSON.stringify(res)))\n"
        ".catch(err => { console.error(err); process.exit(1); });"
    )
    proc = subprocess.run([node, "-e", runner], capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


class TestMemoryAlertsFilterPagination(unittest.TestCase):
    """Verify MemoryMixin severity/offset/count and ZoneEvent bbox preservation."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = TrackerDB(db_path=str(Path(self._tmp.name) / "test.db"))

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()

    def test_zone_event_bbox_preserved_in_metadata(self) -> None:
        """format_zone_event preserves ZoneEvent.bbox inside metadata."""
        ev = ZoneEvent(
            camera_id="cam_1", zone_id="lobby", track_id=7,
            action="enter", timestamp=1700000100.0, bbox=(10, 20, 100, 200),
        )
        doc = format_zone_event(ev)
        self.assertEqual(doc["metadata"]["bbox"], [10, 20, 100, 200])

    def test_memory_severity_filter_offset_and_count(self) -> None:
        """MemoryMixin supports severity filtering, offset pagination, and count_timeline_events."""
        for idx in range(5):
            sev = "critical" if idx % 2 == 0 else "warning"
            self.db.index_timeline_event(
                summary=f"Alert {idx}",
                event_type="intrusion_alert",
                camera_id="cam_1",
                zone_id="vault",
                timestamp=1000.0 + idx,
                metadata={"severity": sev},
            )
        total_crit = self.db.count_timeline_events(camera_id="cam_1", severity="critical")
        self.assertEqual(total_crit, 3)
        page = self.db.search_timeline_events(
            camera_id="cam_1", severity="critical", limit=2, offset=1
        )
        self.assertEqual(len(page), 2)
        self.assertEqual(page[0]["timestamp"], 1002.0)
        self.assertEqual(page[1]["timestamp"], 1000.0)


class TestGetEventsEndpoint(unittest.TestCase):
    """Verify GET /events filtering and paginated vs. legacy list compatibility."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = TrackerDB(db_path=str(Path(self._tmp.name) / "events_api.db"))
        for idx, (cam, sev, zone) in enumerate([
            ("cam_a", "critical", "gate"),
            ("cam_a", "warning", "lobby"),
            ("cam_a", "critical", "gate"),
            ("cam_b", "info", "dock"),
        ]):
            self.db.index_timeline_event(
                summary=f"Event {idx}",
                event_type="zone_enter",
                camera_id=cam,
                zone_id=zone,
                timestamp=2000.0 + idx * 10,
                metadata={"severity": sev, "bbox": [10, 20, 30, 40]},
            )
        app.dependency_overrides[get_db] = lambda: self.db
        app.state.stream_manager = None
        app.state.camera_pool = None
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.db.close()
        self._tmp.cleanup()

    def test_legacy_flat_list_default(self) -> None:
        """GET /events without paginated/offset returns a flat list for legacy callers."""
        resp = self.client.get("/events?limit=10")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 4)

    def test_filters_and_paginated_envelope(self) -> None:
        """GET /events supports camera/severity/zone/time filters and paginated envelope."""
        resp = self.client.get(
            "/events?camera_id=cam_a&severity=critical&zone_id=gate"
            "&start_time=2000&end_time=2025&limit=1&offset=1&paginated=true"
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["offset"], 1)
        self.assertEqual(body["limit"], 1)
        self.assertFalse(body["has_more"])
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["timestamp"], 2000.0)


_ALERTS_VM_SCRIPT = """
const els = {};
const makeEl = (id) => {
  const el = {
    id, value: '', innerHTML: '', textContent: '', disabled: false,
    hidden: false, style: {}, dataset: {}, children: [],
    width: 0, height: 0, naturalWidth: 640, naturalHeight: 360, complete: true,
    _listeners: {},
    addEventListener(ev, fn) { this._listeners[ev] = fn; },
    querySelectorAll() { return []; },
    getBoundingClientRect() { return { left: 0, top: 0, width: 640, height: 360 }; },
    getContext() { return this._ctx; },
  };
  els[id] = el;
  return el;
};
const ids = [
  'alerts-filter-camera', 'alerts-filter-severity', 'alerts-filter-type',
  'alerts-filter-zone', 'alerts-filter-apply', 'alerts-filter-reset',
  'alerts-prev-btn', 'alerts-next-btn', 'alerts-page-info',
  'alerts-table-body', 'total-alerts-count',
  'modal-snapshot-view', 'snapshot-modal-img', 'snapshot-modal-canvas',
  'snapshot-modal-controls', 'snapshot-modal-meta'
];
ids.forEach(makeEl);
const drawCalls = [];
els['snapshot-modal-canvas']._ctx = {
  setTransform() {}, clearRect() {}, save() {}, restore() {},
  fillRect() {}, strokeRect(...a) { drawCalls.push(a); },
  measureText(t) { return { width: t.length * 6 }; },
  fillText() {}, beginPath() {}, moveTo() {}, lineTo() {}, closePath() {}, fill() {}, stroke() {},
};
els['snapshot-modal-img'].parentElement = {
  getBoundingClientRect() { return { left: 0, top: 0, width: 640, height: 360 }; }
};
sandbox.document = { getElementById: (id) => els[id] || null, querySelectorAll: () => [] };
sandbox.devicePixelRatio = 1;
const fetched = [];
sandbox.fetch = async (url) => {
  fetched.push(url);
  return {
    json: async () => ({
      items: [{
        event_type: 'zone_enter', camera_id: 'cam_1', zone_id: 'lobby',
        timestamp: 1700000100, snapshot_base64: 'ZmFrZQ==',
        metadata: { severity: 'critical', bbox: [20, 30, 80, 120] },
      }],
      total: 3, offset: 0, limit: 50, has_more: true,
    }),
  };
};
els['alerts-filter-camera'].value = 'cam_1';
els['alerts-filter-severity'].value = 'critical';
await sandbox.AlertsView.loadAlerts();
sandbox.AlertsView.openAlertSnapshot(0);
return {
  url: fetched[0],
  badge: els['total-alerts-count'].textContent,
  nextDisabled: els['alerts-next-btn'].disabled,
  modalDisplay: els['modal-snapshot-view'].style.display,
  controlsHidden: els['snapshot-modal-controls'].hidden,
  hasFeaturePills: els['snapshot-modal-controls'].innerHTML.includes('overlay-feature-pill'),
  drawCallsCount: drawCalls.length,
};
"""


class TestAlertsViewAndCanvasPreviewVM(unittest.TestCase):
    """Node VM tests for AlertsView filtering/pagination and UnifiedCanvasOverlay preview."""

    def test_alerts_view_pagination_and_snapshot_canvas_reuse(self) -> None:
        """AlertsView builds filtered /events URLs and renders bbox via UnifiedCanvasOverlay."""
        res = _run_node_vm([
            STATIC_DIR / "js" / "unified_canvas_overlay.js",
            STATIC_DIR / "js" / "overlay_control_bar.js",
            STATIC_DIR / "js" / "alerts_view.js",
        ], _ALERTS_VM_SCRIPT)
        self.assertIn("paginated=true", res["url"])
        self.assertIn("camera_id=cam_1", res["url"])
        self.assertIn("severity=critical", res["url"])
        self.assertEqual(res["badge"], "3 events")
        self.assertFalse(res["nextDisabled"])
        self.assertEqual(res["modalDisplay"], "flex")
        self.assertFalse(res["controlsHidden"])
        self.assertTrue(res["hasFeaturePills"])
        self.assertGreaterEqual(res["drawCallsCount"], 1)


if __name__ == "__main__":
    unittest.main()
