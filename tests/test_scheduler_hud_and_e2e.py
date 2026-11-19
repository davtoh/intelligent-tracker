"""Tests for Scheduler HUD, processing_mode.js camera_states fix, API contract & budgets."""

import json
import pathlib
import shutil
import subprocess
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.dependencies import get_camera_pool, set_shutting_down
from dashboard.schemas import ProcessingModeStatusResponse
from dashboard.services.processing_mode_service import ProcessingModeService

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEDULER_HUD_JS = REPO_ROOT / "dashboard" / "static" / "js" / "scheduler_hud.js"
PROCESSING_MODE_JS = REPO_ROOT / "dashboard" / "static" / "js" / "processing_mode.js"


def _run_node_json(script: str) -> dict:
    proc = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, encoding="utf-8", check=True
    )
    return json.loads(proc.stdout.strip())


def _hud_vm_prefix() -> str:
    return (
        "const fs = require('fs'), vm = require('vm');\n"
        f"const code = fs.readFileSync({json.dumps(str(SCHEDULER_HUD_JS))}, 'utf8');\n"
        "const created = {};\n"
        "const hudCenter = { appendChild: (el) => { created[el.id] = el; } };\n"
        "const hudAnchor = { parentElement: hudCenter };\n"
        "const doc = {\n"
        "  getElementById: (id) => id === 'stream-telemetry-hud' ? hudAnchor : (created[id] || null),\n"
        "  createElement: (tag) => ({ tagName: tag, id: '', className: '', textContent: '', title: '', hidden: false }),\n"
        "};\n"
        "const win = {};\n"
        "vm.runInNewContext(code, { window: win, document: doc, String, Number, console });\n"
    )


class TestSchedulerHudAndApi(unittest.TestCase):
    """Verify SchedulerHUD DOM badges, processing_mode.js camera_states fix, API & budgets."""

    def test_file_line_budgets(self) -> None:
        budgets = {
            "dashboard/static/index.html": 180,
            "dashboard/static/partials/tabs/live.html": 220,
            "dashboard/static/js/processing_mode.js": 220,
            "dashboard/static/js/scheduler_hud.js": 180,
        }
        for rel, cap in budgets.items():
            lines = len((REPO_ROOT / rel).read_text(encoding="utf-8").splitlines())
            self.assertLess(lines, cap, f"{rel} has {lines} lines (must be < {cap})")

    def test_processing_mode_status_schema_accepts_scheduler_summary(self) -> None:
        payload = ProcessingModeStatusResponse(
            mode="focus_only",
            focused_camera_id="cam_01",
            active_tab="live",
            valid_modes=["focus_only", "full_realtime", "capture_only", "paused"],
            deferred_jobs=[],
            camera_states={"cam_01": {"is_armed": True, "priority_tier": "P0"}},
            scheduler={"load_shed_stage": "normal", "rolling_fps": 12.0, "global_fps_budget": 18.0},
            updated_at=1.0,
        )
        self.assertEqual(payload.scheduler["load_shed_stage"], "normal")

    def test_processing_mode_endpoint_returns_scheduler_and_camera_states(self) -> None:
        set_shutting_down(False)
        app.dependency_overrides[get_camera_pool] = lambda: None
        self.addCleanup(lambda: (app.dependency_overrides.clear(), set_shutting_down(False)))
        svc = ProcessingModeService(mode="focus_only", focused_camera_id="cam_01", active_tab="live")
        with patch("dashboard.routers.processing_mode.get_processing_mode_service", return_value=svc), \
             TestClient(app) as client:
            resp = client.get("/api/system/processing-mode")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("scheduler", body)
        self.assertIn("load_shed_stage", body["scheduler"])
        self.assertIn("camera_states", body)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_processing_mode_js_reads_camera_states_for_armed_paused_count(self) -> None:
        script = (
            "const fs = require('fs'), vm = require('vm');\n"
            f"const code = fs.readFileSync({json.dumps(str(PROCESSING_MODE_JS))}, 'utf8');\n"
            "const sub = { textContent: '' };\n"
            "const elems = { 'live-paused-subtitle': sub, 'live-paused-overlay': { hidden: true } };\n"
            "const doc = { readyState: 'loading', hidden: false, addEventListener: () => {}, getElementById: (id) => elems[id] || null };\n"
            "const win = { addEventListener: () => {}, localStorage: { getItem: () => null, setItem: () => {} } };\n"
            "const fetchMock = async () => ({ ok: true, json: async () => ({\n"
            "  mode: 'paused', active_tab: 'live', deferred_jobs: [],\n"
            "  camera_states: { c1: { is_armed: true, should_hibernate: true }, c2: { is_armed: true, should_hibernate: true } },\n"
            "  scheduler: { load_shed_stage: 'normal' }\n"
            "}) });\n"
            "vm.runInNewContext(code, { window: win, document: doc, fetch: fetchMock, console, Promise, Set, Array, Object, Number, String });\n"
            "(async () => {\n"
            "  await win.ProcessingModeUI.refresh();\n"
            "  process.stdout.write(JSON.stringify({ count: win.ProcessingModeUI.getState().armedPausedCount, text: sub.textContent }));\n"
            "})();\n"
        )
        out = _run_node_json(script)
        self.assertEqual(out["count"], 2)
        self.assertIn("2 armed cameras paused", out["text"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_scheduler_hud_renders_p0_p1_p2_and_replay_tier_pills(self) -> None:
        script = _hud_vm_prefix() + (
            "const results = [];\n"
            "for (const sample of [\n"
            "  { priority_tier: 'P0', target_fps: 15.0 },\n"
            "  { priority_tier: 'P1', motion_active: true, target_fps: 8.0 },\n"
            "  { priority_tier: 'P1', motion_active: false, target_fps: 1.0 },\n"
            "  { priority_tier: 'P2', target_fps: 0.0 },\n"
            "  { priority_tier: 'REPLAY', replay_active: true },\n"
            "]) {\n"
            "  win.SchedulerHUD.updateCamera(sample);\n"
            "  results.push({ text: created['scheduler-tier-pill'].textContent, cls: created['scheduler-tier-pill'].className });\n"
            "}\n"
            "process.stdout.write(JSON.stringify({ results }));\n"
        )
        out = _run_node_json(script)
        texts = [r["text"] for r in out["results"]]
        self.assertEqual(texts, ["P0 LIVE", "P1 MOTION", "P1 IDLE 1FPS", "P2 BG", "ZERO-GPU REPLAY"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_scheduler_hud_toggles_load_shed_badge_across_stages(self) -> None:
        script = _hud_vm_prefix() + (
            "win.SchedulerHUD.updateGlobal({ scheduler: { load_shed_stage: 'elevated', rolling_fps: 14.0, global_fps_budget: 18.0, ewma_latency_ms: 120 } });\n"
            "const elev = { hidden: created['scheduler-shed-badge'].hidden, text: created['scheduler-shed-badge'].textContent, cls: created['scheduler-shed-badge'].className };\n"
            "win.SchedulerHUD.updateCamera({ priority_tier: 'P0', load_shed_stage: 'critical' });\n"
            "const crit = { hidden: created['scheduler-shed-badge'].hidden, text: created['scheduler-shed-badge'].textContent, cls: created['scheduler-shed-badge'].className };\n"
            "win.SchedulerHUD.updateCamera({ priority_tier: 'P0', load_shed_stage: 'normal' });\n"
            "const norm = { hidden: created['scheduler-shed-badge'].hidden, text: created['scheduler-shed-badge'].textContent };\n"
            "process.stdout.write(JSON.stringify({ elev, crit, norm }));\n"
        )
        out = _run_node_json(script)
        self.assertFalse(out["elev"]["hidden"])
        self.assertEqual(out["elev"]["text"], "SHED: ELEVATED")
        self.assertFalse(out["crit"]["hidden"])
        self.assertEqual(out["crit"]["text"], "SHED: CRITICAL")
        self.assertTrue(out["norm"]["hidden"])
        self.assertEqual(out["norm"]["text"], "")
