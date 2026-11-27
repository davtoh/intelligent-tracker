#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Step 3 tests: Tripwire IN/OUT handle, camera discovery parity, batch provenance & arch hygiene."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dashboard.schemas import CameraTestRequest
from dashboard.services.camera_diagnostics import collect_active_usb_metadata, probe_camera_test_request
from dashboard.services.camera_pool_queries import CameraPoolQueryMixin
from dashboard.services.video_analytics_service import _teardown_indexer_bus, create_video_indexer
from intelligent_tracker.camera_device import CameraDeviceHandler
from intelligent_tracker.camera_device_enum import get_windows_device_names
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.geometry.tripwire import Tripwire
from intelligent_tracker.pipeline.post_detection_governance import resolve_camera_id

REPO_ROOT = Path(__file__).resolve().parents[1]
HAS_NODE = shutil.which("node") is not None


def _run_node(script: str) -> dict:
    proc = subprocess.run(
        ["node"],
        input=script, capture_output=True, text=True, encoding="utf-8", timeout=20, check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"Node script failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


@unittest.skipUnless(HAS_NODE, "Node.js required for JS VM contract tests")
class TestStep3TripwireVisualsAndFlip(unittest.TestCase):
    """Verify tripwire IN/OUT normal rendering parity and Studio single-flip + rollback."""

    def test_tripwire_in_out_normal_matches_backend_check_crossing(self) -> None:
        tw = Tripwire(name="Gate", line_segment=[(100, 100), (200, 100)])
        ev_in = tw.check_crossing(track_id=1, prev_centroid=(150, 90), curr_centroid=(150, 110))
        ev_out = tw.check_crossing(track_id=2, prev_centroid=(150, 110), curr_centroid=(150, 90))
        self.assertIsNotNone(ev_in)
        self.assertEqual(ev_in.direction, "in")
        self.assertIsNotNone(ev_out)
        self.assertEqual(ev_out.direction, "out")

        overlay_src = (REPO_ROOT / "dashboard/static/js/unified_canvas_overlay.js").read_text(encoding="utf-8")
        script = f"""
const vm = require('vm');
const texts = [];
const ctx = {{
  save(){{}}, restore(){{}}, beginPath(){{}}, moveTo(){{}}, lineTo(){{}}, closePath(){{}},
  fill(){{}}, stroke(){{}}, fillRect(){{}}, setLineDash(){{}},
  measureText(t){{ return {{ width: t.length * 6 }}; }},
  fillText(t, x, y){{ texts.push({{ t, x, y }}); }},
}};
const sandbox = {{ window: {{}}, console }};
vm.createContext(sandbox);
vm.runInContext({json.dumps(overlay_src)}, sandbox);
const uco = sandbox.window.UnifiedCanvasOverlay;
const handle = uco.computeTripwireFlipHandle([100, 100], [200, 100], 26);
uco.drawTripwires(ctx, [{{ name: 'Gate', line_segment: [[100, 100], [200, 100]], in_count: 2, out_count: 1 }}], {{ offsetX: 0, offsetY: 0, scaleX: 1, scaleY: 1 }});
console.log(JSON.stringify({{ handle, texts }}));
"""
        out = _run_node(script)
        self.assertAlmostEqual(out["handle"]["nx"], 0.0, places=4)
        self.assertAlmostEqual(out["handle"]["ny"], 1.0, places=4)
        in_lbl = next(item for item in out["texts"] if item["t"] == "IN")
        out_lbl = next(item for item in out["texts"] if item["t"] == "OUT")
        self.assertGreater(in_lbl["y"], 100)
        self.assertLess(out_lbl["y"], 100)

    def test_studio_flip_handle_single_flip_put_and_rollback(self) -> None:
        uco_src = (REPO_ROOT / "dashboard/static/js/unified_canvas_overlay.js").read_text(encoding="utf-8")
        ed_src = (REPO_ROOT / "dashboard/static/js/studio_shape_editor.js").read_text(encoding="utf-8")
        ov_src = (REPO_ROOT / "dashboard/static/js/studio_overlays.js").read_text(encoding="utf-8")
        script = f"""
const vm = require('vm');
const calls = []; let nextOk = true;
const state = {{ mode: 'idle', activeCamera: 'cam_1', zones: [], tripwires: [{{ name: 'Gate', line_segment: [[100, 100], [200, 100]], color: [0, 255, 255], bidirectional: true }}], topologyLinks: [] }};
const twListEl = {{ innerHTML: '', addEventListener(){{}} }};
const sandbox = {{
  window: {{ addEventListener(){{}} }}, console,
  document: {{ getElementById: (id) => (id === 'studio-tripwires-list' ? twListEl : null) }},
  fetch: async (url, opts) => {{ calls.push({{ url, method: opts.method, body: JSON.parse(opts.body) }}); return {{ ok: nextOk, status: nextOk ? 200 : 500, json: async () => ({{ detail: 'boom' }}) }}; }},
}};
vm.createContext(sandbox);
[{json.dumps(uco_src)}, {json.dumps(ed_src)}, {json.dumps(ov_src)}].forEach((s) => vm.runInContext(s, sandbox));
const ed = sandbox.window.StudioShapeEditor;
ed.init(() => state, {{ drawOverlay(){{}}, updateStatus(){{}}, showToast(){{}} }});
sandbox.window.StudioOverlays.init(() => state);
sandbox.window.StudioOverlays.renderScenarioListUI();
(async () => {{
  const h = sandbox.window.UnifiedCanvasOverlay.computeTripwireFlipHandle([100, 100], [200, 100], 26);
  ed.onMouseDown({{ x: h.x, y: h.y }}); ed.onMouseMove({{ x: h.x + 15, y: h.y + 15 }});
  const p1 = ed.onMouseUp(); const p2 = ed.onMouseUp(); await p1;
  const afterFlip = JSON.parse(JSON.stringify(state.tripwires[0].line_segment));
  nextOk = false; await ed.flipTripwire('Gate');
  const afterRollback = JSON.parse(JSON.stringify(state.tripwires[0].line_segment));
  console.log(JSON.stringify({{ calls, secondUp: p2, afterFlip, afterRollback, hasCardBtn: twListEl.innerHTML.includes('data-action="flip-tripwire"') }}));
}})();
"""
        out = _run_node(script)
        self.assertEqual(len(out["calls"]), 2)
        self.assertEqual(out["calls"][0]["url"], "/api/scenarios/tripwires/cam_1/Gate")
        self.assertEqual(out["calls"][0]["body"]["line_segment"], [[200, 100], [100, 100]])
        self.assertFalse(out["secondUp"])
        self.assertEqual(out["afterFlip"], [[200, 100], [100, 100]])
        self.assertEqual(out["afterRollback"], [[200, 100], [100, 100]])
        self.assertTrue(out["hasCardBtn"])


class TestStep3DiscoveryAndTestParity(unittest.TestCase):
    """Verify Windows duplicate device names, hikvision exclusion, and /api/cameras/test parity."""

    def test_windows_device_names_preserve_duplicates(self) -> None:
        entries = [("k0", "Logitech C920"), ("k1", "Logitech C920"), ("k2", "GoPro Webcam")]

        class _Ctx:
            def __init__(self, key): self.key = key
            def __enter__(self): return self.key
            def __exit__(self, *args): return False

        fake_winreg = SimpleNamespace(
            HKEY_CLASSES_ROOT=1,
            OpenKey=lambda root, path: _Ctx(path),
            EnumKey=lambda _k, idx: entries[idx][0] if idx < len(entries) else (_ for _ in ()).throw(OSError()),
            QueryValueEx=lambda k, _v: (dict(entries)[k], 1),
        )
        with patch.dict(sys.modules, {"winreg": fake_winreg}):
            names = get_windows_device_names()
        self.assertEqual(names, ["Logitech C920", "Logitech C920", "GoPro Webcam"])

    def test_discover_usb_cameras_preserves_active_device_name(self) -> None:
        active = {0: {"device_name": "GoPro Webcam", "backend": "DSHOW", "is_virtual": False, "resolution": "1280x720"}}
        with (
            patch.object(CameraDeviceHandler, "get_friendly_name", return_value="Drifted Virtual"),
            patch.object(CameraDeviceHandler, "probe_device", return_value=None),
        ):
            found = CameraDeviceHandler.discover_usb_cameras(max_devices=2, active_indices={0}, active_devices=active)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["device_name"], "GoPro Webcam")
        self.assertEqual(found[0]["backend"], "DSHOW")
        self.assertTrue(found[0]["in_use"])

    def test_hikvision_active_index_and_resolved_source_excluded(self) -> None:
        class _DummyPool(CameraPoolQueryMixin):
            def __init__(self):
                self._lock = threading.RLock()
                self.camera_configs = {
                    "cam_hik": {"type": "hikvision", "source": "0"},
                    "cam_remapped": {"type": "usb", "source": "auto"},
                }
                self.streams = {
                    "cam_hik": SimpleNamespace(is_running=True, source_override=None, _resolved_source=None, video_source=None),
                    "cam_remapped": SimpleNamespace(is_running=True, source_override=None, _resolved_source=2, video_source=None),
                }

        pool = _DummyPool()
        self.assertEqual(pool.get_active_usb_indices(), {0, 2})

    def test_camera_test_request_device_name_and_active_pool_match(self) -> None:
        mgr = SimpleNamespace(
            is_running=True, _resolved_source=2, _backend="DSHOW", video_source=SimpleNamespace(source=2),
            get_latest_frame_jpeg=lambda: b"jpgbytes", get_latest_telemetry=lambda: {"width": 1280, "height": 720, "fps": 29.9},
        )
        pool = SimpleNamespace(
            _lock=threading.RLock(),
            streams={"cam_usb": mgr},
            camera_configs={"cam_usb": {"source": "0", "device_name": "GoPro Webcam"}},
            list_cameras=lambda: [{"id": "cam_usb", "source": "0", "device_name": "GoPro Webcam", "resolution": "1280x720", "fps": 29.9}],
        )
        meta = collect_active_usb_metadata(pool, {2})
        self.assertEqual(meta[2]["device_name"], "GoPro Webcam")
        self.assertEqual(meta[2]["backend"], "DSHOW")

        req = CameraTestRequest(source="0", device_name="GoPro Webcam")
        with patch("intelligent_tracker.camera_resolver.CameraPathResolver.resolve_camera_source", return_value=(2, {"status": "ok", "device_name": "GoPro Webcam"})):
            res = probe_camera_test_request(req, pool=pool)
        self.assertTrue(res["success"])
        self.assertEqual(res["active_stream_id"], "cam_usb")
        self.assertEqual(res["device_name"], "GoPro Webcam")

    @unittest.skipUnless(HAS_NODE, "Node.js required for camera_discovery.js test")
    def test_camera_discovery_js_forwards_device_name(self) -> None:
        js_src = (REPO_ROOT / "dashboard/static/js/camera_discovery.js").read_text(encoding="utf-8")
        script = f"""
const vm = require('vm');
let posted = null;
const sourceEl = {{ value: '', dataset: {{}} }};
const listEl = {{
  innerHTML: '',
  querySelectorAll(sel) {{
    if (sel === '.btn-test-discovered') return [{{ getAttribute: (k) => (k === 'data-source' ? '1' : 'GoPro Webcam'), addEventListener: (_e, fn) => {{ this._click = fn; }} }}];
    return [];
  }},
}};
const sandbox = {{
  window: {{}}, console,
  document: {{ getElementById: (id) => (id === 'cam-source-input' ? sourceEl : (id === 'discovered-devices-list' ? listEl : (id === 'btn-scan-devices' ? {{}} : null))) }},
  fetch: async (url, opts) => {{
    if (url === '/api/cameras/discover') return {{ json: async () => [{{ id: 'usb_1', name: 'GoPro Webcam', source: 1, type: 'usb', details: {{ device_name: 'GoPro Webcam' }} }}] }};
    posted = JSON.parse(opts.body);
    return {{ json: async () => ({{ success: true, resolution: '640x480', fps: 30, snapshot_base64: 'AA==' }}) }};
  }},
}};
vm.createContext(sandbox);
vm.runInContext({json.dumps(js_src)}, sandbox);
(async () => {{
  await sandbox.window.CameraDiscovery.scanDevices();
  await listEl._click();
  console.log(JSON.stringify({{ hasAttr: listEl.innerHTML.includes('data-device-name="GoPro Webcam"'), posted }}));
}})();
"""
        out = _run_node(script)
        self.assertTrue(out["hasAttr"])
        self.assertEqual(out["posted"], {"source": "1", "device_name": "GoPro Webcam"})


class TestStep3ProvenanceAndArchHygiene(unittest.TestCase):
    """Verify video:<filename> batch provenance, WorldPolicy preservation, and modularity hygiene."""

    def test_non_scenario_batch_provenance_uses_video_prefix(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        db = TrackerDB(os.path.join(tmpdir.name, "prov.db"))
        self.addCleanup(db.close)
        idx = create_video_indexer(
            db, {"detector": "mock", "sample_rate": 4, "confidence": 0.4, "classes": None}, safe_name="clip_a.mp4",
        )
        self.addCleanup(idx.close)
        self.addCleanup(_teardown_indexer_bus, idx)
        self.assertEqual(idx.analytics.camera_id, "video:clip_a.mp4")

        bundle = SimpleNamespace(
            analytics=SimpleNamespace(camera_id="offline_video"),
            config=SimpleNamespace(camera_id=None),
            gallery_matcher=SimpleNamespace(video_filename="clip_b.mp4"),
        )
        self.assertEqual(resolve_camera_id(bundle), "video:clip_b.mp4")

    def test_world_policy_preserved_and_import_hygiene(self) -> None:
        from intelligent_tracker.world import WorldGraph, WorldPolicy, WorldRuleEngine

        self.assertIsNotNone(WorldPolicy)
        self.assertIsNotNone(WorldGraph)
        self.assertIsNotNone(WorldRuleEngine)

        rsac_text = (REPO_ROOT / "dashboard/routers/rsac.py").read_text(encoding="utf-8")
        guard_text = (REPO_ROOT / "intelligent_tracker/video/_capture_guard_worker.py").read_text(encoding="utf-8")
        self.assertNotIn("create_custom_category", rsac_text)
        self.assertNotIn("Tuple", guard_text.splitlines()[7])
        self.assertLess(len((REPO_ROOT / "dashboard/dependencies.py").read_text(encoding="utf-8").splitlines()), 350)
        self.assertLess(len(rsac_text.splitlines()), 350)
        self.assertLessEqual(len((REPO_ROOT / "dashboard/static/js/studio_shape_editor.js").read_text(encoding="utf-8").splitlines()), 300)
        self.assertLessEqual(len((REPO_ROOT / "dashboard/static/js/studio_overlays.js").read_text(encoding="utf-8").splitlines()), 250)


if __name__ == "__main__":
    unittest.main()
