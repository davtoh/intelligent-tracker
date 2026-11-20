#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""End-to-end integration, latency, and modularity budget tests for Step 4 Milestone 2."""

import ast
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.camera_pool import CameraPool
from dashboard.dependencies import get_camera_pool
from dashboard.services.processing_mode_service import ProcessingModeService
from dashboard.services.stream_recording import StreamRecordingController
from dashboard.services.stream_worker import StreamWorker

REPO_ROOT = Path(__file__).resolve().parent.parent

STEP1_4_CODE_BUDGETS = {
    "dashboard/services/stream_worker.py": 285,
    "dashboard/services/stream_subscribers.py": 350,
    "dashboard/services/stream_recording.py": 350,
    "dashboard/services/stream_pool_coordinator.py": 350,
    "dashboard/services/processing_mode_service.py": 220,
    "dashboard/routers/processing_mode.py": 120,
    "dashboard/routers/tagging.py": 350,
    "dashboard/routers/streaming.py": 350,
    "dashboard/services/video_report_migration.py": 350,
    "intelligent_tracker/repositories/video_run_repo.py": 350,
    "dashboard/static/js/processing_mode.js": 220,
    "dashboard/static/css/processing_mode.css": 140,
    "dashboard/static/js/nav_tabs_manager.js": 350,
    "dashboard/static/js/live_player.js": 350,
    "dashboard/static/studio.js": 350,
    "dashboard/static/js/scrubber_library_bridge.js": 350,
    "dashboard/static/index.html": 180,
}

STEP1_4_PYTHON_FILES = [
    path for path in STEP1_4_CODE_BUDGETS if path.endswith(".py")
]


class _FakeWriter:
    """In-memory PipelineVideoWriter test double."""

    def __init__(self, path, fps=10.0, resolution=(64, 48), max_frames=None, max_duration_s=None):
        self.path, self.fps, self.resolution = path, fps, resolution
        self.frames = []
        self.is_open = True

    def write(self, frame):
        self.frames.append(frame.copy())
        return True

    def release(self):
        self.is_open = False

    def snapshot(self):
        w, h = self.resolution
        return {"codec": "mp4v", "width": w, "height": h, "frames_written": len(self.frames)}


def _make_stub_stream(cam_id: str, subscriber_count: int = 0, is_recording: bool = False):
    """Create a lightweight StreamManager-compatible stub for pool & worker tests."""
    vs = MagicMock()
    return SimpleNamespace(
        camera_id=cam_id,
        name=f"Cam {cam_id}",
        subscriber_count=subscriber_count,
        is_recording=is_recording,
        is_running=True,
        _is_hibernating=False,
        _running=True,
        _stop_event=threading.Event(),
        _lock=threading.RLock(),
        _latest_telemetry={"camera_id": cam_id, "status": "online", "fps": 12.0},
        video_source=vs,
        _in_camera_pool=True,
    )


def _make_isolated_pool(tmpdir: str) -> CameraPool:
    """Create an isolated CameraPool with two stubbed cameras."""
    cfg_path = os.path.join(tmpdir, "cameras.json")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(
            [{"id": "cam_01", "name": "Front", "enabled": False}, {"id": "cam_02", "name": "Rear", "enabled": False}],
            fh,
        )
    pool = CameraPool(config_file=cfg_path, db_path=os.path.join(tmpdir, "tracker.db"), autostart=False)
    pool._coordinator.streams = {
        "cam_01": _make_stub_stream("cam_01", subscriber_count=1),
        "cam_02": _make_stub_stream("cam_02", subscriber_count=0),
    }
    return pool


class TestStep4E2EPerformanceAndModes(unittest.TestCase):
    """End-to-end mode lifecycle, worker parity, deferred badge, latency, and budgets."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.pool = _make_isolated_pool(self._tmpdir.name)
        self.addCleanup(self.pool.stop_all, False)
        self.svc = ProcessingModeService(mode="focus_only", focused_camera_id="cam_01", active_tab="live")
        app.dependency_overrides[get_camera_pool] = lambda: self.pool
        self.addCleanup(app.dependency_overrides.clear)
        self._svc_patch = patch("dashboard.routers.processing_mode.get_processing_mode_service", return_value=self.svc)
        self._svc_patch.start()
        self.addCleanup(self._svc_patch.stop)
        self.client = TestClient(app)

    def test_full_mode_lifecycle_and_camera_pool_parity(self):
        """Verify focus_only -> full_realtime -> capture_only -> paused lifecycle parity."""
        r0 = self.client.get("/api/system/processing-mode")
        self.assertEqual(r0.status_code, 200)
        states = r0.json()["camera_states"]
        self.assertFalse(states["cam_01"]["should_hibernate"])
        self.assertTrue(states["cam_01"]["should_run_vision"])
        self.assertTrue(states["cam_02"]["should_hibernate"])
        self.assertFalse(states["cam_02"]["should_run_vision"])

        r1 = self.client.post("/api/system/processing-mode", json={"mode": "full_realtime"})
        self.assertEqual(r1.status_code, 200)
        self.assertFalse(r1.json()["camera_states"]["cam_02"]["should_hibernate"])
        self.assertTrue(r1.json()["camera_states"]["cam_02"]["should_run_vision"])

        r2 = self.client.post("/api/system/processing-mode", json={"mode": "capture_only"})
        self.assertEqual(r2.status_code, 200)
        self.assertFalse(r2.json()["camera_states"]["cam_01"]["should_run_vision"])

        r3 = self.client.post("/api/system/processing-mode", json={"mode": "paused"})
        self.assertEqual(r3.status_code, 200)
        self.assertTrue(r3.json()["camera_states"]["cam_01"]["should_hibernate"])
        self.assertTrue(r3.json()["camera_states"]["cam_02"]["should_hibernate"])

    def test_stream_worker_hibernation_matches_processing_mode_service(self):
        """Verify StreamWorker gating agrees with ProcessingModeService across modes."""
        cam1 = self.pool.streams["cam_01"]
        cam2 = self.pool.streams["cam_02"]
        cam1._processing_mode_service = self.svc
        cam2._processing_mode_service = self.svc
        w1, w2 = StreamWorker(cam1), StreamWorker(cam2)

        for mode in ("focus_only", "full_realtime", "capture_only", "paused"):
            self.svc.update(mode=mode)
            self.svc.apply_to_pool(self.pool)
            state = self.svc.get_state(self.pool)["camera_states"]
            self.assertEqual(w1._should_hibernate(False, 1), state["cam_01"]["should_hibernate"])
            self.assertEqual(w2._should_hibernate(False, 1), state["cam_02"]["should_hibernate"])
            self.assertEqual(w1._should_run_vision_step(False), state["cam_01"]["should_run_vision"])
            self.assertEqual(w2._should_run_vision_step(False), state["cam_02"]["should_run_vision"])

    def test_capture_only_deferred_job_propagates_to_api_and_ui_badge(self):
        """Verify capture_only stop queues a deferred job and processing_mode.js renders badge."""
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js not available in PATH")
        self.svc.update(mode="capture_only")
        fake_job = SimpleNamespace(job_id="def_e2e_1", status="queued")
        with patch("dashboard.services.processing_mode_service.submit_async_analytics_job", return_value=fake_job):
            ctrl = StreamRecordingController(
                "cam_01", output_dir=self._tmpdir.name, writer_factory=_FakeWriter,
                mode_service_getter=lambda: self.svc,
            )
            ctrl.start(filename="deferred_e2e.mp4", fps=10.0, resolution=(64, 48), annotated=True)
            ctrl.write_frame(np.zeros((48, 64, 3), dtype=np.uint8), np.zeros((48, 64, 3), dtype=np.uint8))
            stopped = ctrl.stop()
        self.assertEqual(stopped["deferred_job_id"], "def_e2e_1")
        payload = self.client.get("/api/system/processing-mode").json()
        self.assertEqual(len(payload["deferred_jobs"]), 1)
        self._assert_node_badge_renders(node, payload)

    def _assert_node_badge_renders(self, node_bin: str, server_payload: dict):
        """Run processing_mode.js in Node VM with live API payload and verify badge DOM."""
        js_src = (REPO_ROOT / "dashboard" / "static" / "js" / "processing_mode.js").read_text(encoding="utf-8")
        script = f"""
const vm = require('vm');
function mkEl(id, val) {{
  const cls = new Set(['is-hidden']);
  return {{ id, value: val || '', textContent: '', title: '', className: '', dataset: {{}},
    classList: {{ toggle: (c, f) => (f ? cls.add(c) : cls.delete(c)), contains: (c) => cls.has(c) }},
    addEventListener: () => {{}} }};
}}
const els = {{ 'processing-mode-select': mkEl('processing-mode-select', 'focus_only'),
  'processing-mode-dot': mkEl('processing-mode-dot'),
  'processing-mode-deferred-badge': mkEl('processing-mode-deferred-badge'),
  'active-camera-select': mkEl('active-camera-select', 'cam_01') }};
const payload = {json.dumps(server_payload)};
const sb = {{ window: {{ localStorage: {{ getItem: () => null, setItem: () => {{}} }}, addEventListener: () => {{}} }},
  document: {{ readyState: 'complete', hidden: false, getElementById: (id) => els[id] || null, addEventListener: () => {{}} }},
  fetch: async () => ({{ ok: true, json: async () => payload }}),
  console }};
sb.window.document = sb.document;
vm.runInNewContext({json.dumps(js_src)}, sb);
(async () => {{
  for (let i = 0; i < 6; i++) await Promise.resolve();
  console.log(JSON.stringify({{
    mode: els['processing-mode-select'].value,
    badgeText: els['processing-mode-deferred-badge'].textContent,
    badgeHidden: els['processing-mode-deferred-badge'].classList.contains('is-hidden'),
  }}));
}})();
"""
        proc = subprocess.run([node_bin, "-e", script], capture_output=True, text=True, check=True)
        out = json.loads(proc.stdout.strip())
        self.assertEqual(out["mode"], "capture_only")
        self.assertEqual(out["badgeText"], "1")
        self.assertFalse(out["badgeHidden"])

    def test_control_plane_latency_under_200ms(self):
        """Verify processing-mode GET/POST and camera list endpoints respond in < 200ms."""
        for mode in ("full_realtime", "capture_only", "paused", "focus_only"):
            t0 = time.perf_counter()
            post_resp = self.client.post("/api/system/processing-mode", json={"mode": mode})
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self.assertEqual(post_resp.status_code, 200)
            self.assertLess(elapsed_ms, 200.0, f"POST {mode} took {elapsed_ms:.1f}ms")

        t1 = time.perf_counter()
        get_resp = self.client.get("/api/system/processing-mode")
        self.assertEqual(get_resp.status_code, 200)
        self.assertLess((time.perf_counter() - t1) * 1000.0, 200.0)

    def test_step1_to_step4_file_and_function_modularity_budgets(self):
        """Verify all Step 1-4 touched files and Python functions respect modularity ceilings."""
        for rel_path, max_lines in STEP1_4_CODE_BUDGETS.items():
            lines = (REPO_ROOT / rel_path).read_text(encoding="utf-8").splitlines()
            self.assertLessEqual(len(lines), max_lines, f"{rel_path} has {len(lines)}L > {max_lines}L")

        for rel_path in STEP1_4_PYTHON_FILES:
            tree = ast.parse((REPO_ROOT / rel_path).read_text(encoding="utf-8"), filename=rel_path)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fn_len = (node.end_lineno or node.lineno) - node.lineno + 1
                    self.assertLessEqual(fn_len, 40, f"{rel_path}:{node.name} is {fn_len}L > 40L")

        css_text = (REPO_ROOT / "dashboard" / "static" / "css" / "processing_mode.css").read_text(encoding="utf-8")
        self.assertNotIn("!important", css_text)


if __name__ == "__main__":
    unittest.main()
