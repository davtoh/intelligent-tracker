#!/usr/bin/env python3
"""Isolated unit and FastAPI tests for interactive Debug Observation Mode (Milestone 1)."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.routers.system import router as system_router
from dashboard.services.debug_session import (
    record_debug_event,
    record_user_observation,
    summarize_debug_session,
)


def _build_test_client() -> TestClient:
    """Create a minimal FastAPI TestClient mounting only the system router (no lifespan)."""
    app = FastAPI()
    app.include_router(system_router)
    return TestClient(app)


class TestDebugObservationModeBackend(unittest.TestCase):
    """Verify IT_DEBUG_MODE gating, events.jsonl persistence, and triage correlation."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.debug_dir = Path(self._tmp.name) / "debug_session"
        self.client = _build_test_client()

    def test_disabled_mode_blocks_observation_and_reports_flag_false(self) -> None:
        env = {"IT_DEBUG_MODE": "0", "TRACKER_DEBUG_DIR": str(self.debug_dir)}
        with patch.dict(os.environ, env, clear=False):
            res_summary = self.client.get("/api/system/debug/summary")
            self.assertEqual(res_summary.status_code, 200)
            body = res_summary.json()
            self.assertFalse(body["debug_mode"])
            self.assertEqual(body["observations_count"], 0)
            self.assertEqual(body["observations"], [])

            res_post = self.client.post(
                "/api/system/debug/observation",
                json={"note": "Should be rejected", "tab": "live"},
            )
            self.assertEqual(res_post.status_code, 403)
            self.assertFalse((self.debug_dir / "events.jsonl").exists())

    def test_enabled_mode_persists_bounded_observation_and_validates_note(self) -> None:
        env = {"IT_DEBUG_MODE": "1", "TRACKER_DEBUG_DIR": str(self.debug_dir)}
        many_crumbs = [{"type": "click", "target": f"#btn-{i}", "ts": i} for i in range(45)]
        long_note = "x" * 1400

        with patch.dict(os.environ, env, clear=False):
            res_summary = self.client.get("/api/system/debug/summary")
            self.assertEqual(res_summary.status_code, 200)
            self.assertTrue(res_summary.json()["debug_mode"])

            res_blank = self.client.post(
                "/api/system/debug/observation",
                json={"note": "   \t\n  ", "tab": "studio"},
            )
            self.assertEqual(res_blank.status_code, 400)

            res_ok = self.client.post(
                "/api/system/debug/observation",
                json={
                    "note": long_note,
                    "tab": "studio",
                    "url": "/#studio",
                    "breadcrumbs": many_crumbs,
                    "viewport": {"width": 1440, "height": 900},
                },
            )
            self.assertEqual(res_ok.status_code, 200)
            data = res_ok.json()
            self.assertEqual(data["status"], "recorded")
            obs = data["observation"]
            self.assertEqual(obs["level"], "OBSERVATION")
            self.assertEqual(len(obs["note"]), 1000)
            self.assertEqual(len(obs["breadcrumbs"]), 30)
            self.assertEqual(obs["breadcrumbs"][0]["target"], "#btn-15")
            self.assertEqual(obs["breadcrumbs"][-1]["target"], "#btn-44")
            self.assertEqual(obs["viewport"], {"width": 1440, "height": 900})

        events_path = self.debug_dir / "events.jsonl"
        self.assertTrue(events_path.is_file())
        lines = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["level"], "OBSERVATION")
        self.assertEqual(lines[0]["tab"], "studio")

    def test_triage_separates_observations_and_correlates_nearby_issues(self) -> None:
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        old_err = {
            "ts": "2026-01-01T00:00:00", "epoch": 1000.0, "level": "ERROR",
            "logger": "dashboard.old", "fingerprint": "oldfp12345",
            "exc_type": "RuntimeError", "message": "Ancient unrelated failure",
            "top_frames": [], "traceback": "",
        }
        (self.debug_dir / "events.jsonl").write_text(json.dumps(old_err) + "\n", encoding="utf-8")

        try:
            raise ValueError("Overlay canvas resize failed")
        except ValueError as exc:
            near_fp = record_debug_event(exc, http_method="GET", http_path="/api/cameras", debug_dir=self.debug_dir)

        record_user_observation(
            note="Overlay froze after switching to multiview",
            tab="multiview",
            url="/#multiview",
            breadcrumbs=[{"type": "click", "target": "#tab-multiview"}],
            viewport={"width": 1280, "height": 720},
            debug_dir=self.debug_dir,
        )

        summary = summarize_debug_session(self.debug_dir, min_level="WARNING", limit=20)
        self.assertEqual(summary["totals"], {"CRITICAL": 0, "ERROR": 2, "WARNING": 0})
        self.assertEqual(summary["unique_issues"], 2)
        self.assertEqual(summary["observations_count"], 1)
        obs_item = summary["observations"][0]
        self.assertEqual(obs_item["index"], 1)
        self.assertEqual(obs_item["tab"], "multiview")
        correlated_fps = {item["fingerprint"] for item in obs_item["correlated_issues"]}
        self.assertIn(near_fp, correlated_fps)
        self.assertNotIn("oldfp12345", correlated_fps)


HUD_JS_PATH = Path(__file__).resolve().parents[1] / "dashboard" / "static" / "js" / "debug_observation_hud.js"


def _run_hud_vm(js_body: str, *, debug_mode: bool = True) -> dict:
    """Execute debug_observation_hud.js inside a Node.js VM sandbox and return JSON output."""
    js_src = HUD_JS_PATH.read_text(encoding="utf-8")
    flag = "true" if debug_mode else "false"
    harness = (
        "const vm = require('vm');\n"
        "const docListeners = {}, winListeners = {}, bodyChildren = [], headChildren = [], fetchCalls = [];\n"
        "function mkEl(tag) { return { tagName: tag.toUpperCase(), className: '', textContent: '', hidden: false, value: '',"
        "  children: [], listeners: {}, appendChild(c) { this.children.push(c); return c; },"
        "  addEventListener(t, fn) { this.listeners[t] = fn; }, setAttribute() {},"
        "  contains(n) { return n === this || this.children.some((c) => c.contains && c.contains(n)); } }; }\n"
        "const activeTab = { getAttribute: (k) => (k === 'data-tab' ? 'tab-studio' : null) };\n"
        "const doc = { readyState: 'loading', body: { appendChild: (c) => bodyChildren.push(c) },"
        "  head: { appendChild: (c) => headChildren.push(c) }, createElement: mkEl,"
        "  querySelector: (s) => (s === '.nav-tab.active' ? activeTab : null),"
        "  addEventListener: (t, fn) => { (docListeners[t] = docListeners[t] || []).push(fn); } };\n"
        "const origFetch = async (url, init) => {\n"
        "  fetchCalls.push({ url: String(url), method: (init && init.method) || 'GET', body: init && init.body });\n"
        f"  if (String(url).includes('/api/system/debug/summary')) return {{ ok: true, status: 200, json: async () => ({{ debug_mode: {flag} }}) }};\n"
        "  if (String(url).includes('/api/fail-test')) return { ok: false, status: 500, json: async () => ({ detail: 'boom' }) };\n"
        "  return { ok: true, status: 200, json: async () => ({ status: 'recorded' }) }; };\n"
        "const win = { location: { pathname: '/', search: '', hash: '#tab-studio' }, innerWidth: 1440, innerHeight: 900,"
        "  fetch: origFetch, addEventListener: (t, fn) => { (winListeners[t] = winListeners[t] || []).push(fn); } };\n"
        "const _spy = { docListeners, winListeners, bodyChildren, fetchCalls };\n"
        "const sb = { window: win, document: doc, fetch: origFetch, _spy, Date, Number, String, Boolean, Array, Object, JSON, Promise, console };\n"
        "const ctx = vm.createContext(sb);\n"
        f"vm.runInContext({json.dumps(js_src)}, ctx);\n"
        f"vm.runInContext('(async () => {{ ' + {json.dumps(js_body)} + ' }})()', ctx)\n"
        "  .then((res) => process.stdout.write(JSON.stringify(res))).catch((e) => { console.error(e); process.exit(1); });\n"
    )
    proc = subprocess.run(["node", "-e", harness], capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(proc.stdout.strip())


@unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
class TestDebugObservationHudFrontend(unittest.TestCase):
    """Verify debug_observation_hud.js gating, 30-item ring buffer, interceptors, and POST payload."""

    def test_hud_noop_when_debug_mode_disabled(self) -> None:
        out = _run_hud_vm(
            "const ok = await window.DebugObservationHUD.init();"
            "return { ok, enabled: window.DebugObservationHUD.isEnabled(), mounted: _spy.bodyChildren.length,"
            "  clicks: (_spy.docListeners.click || []).length, wrapped: window.fetch !== fetch };",
            debug_mode=False,
        )
        self.assertFalse(out["ok"])
        self.assertFalse(out["enabled"])
        self.assertEqual(out["mounted"], 0)
        self.assertEqual(out["clicks"], 0)
        self.assertFalse(out["wrapped"])

    def test_hud_ring_buffer_cap_and_interceptors(self) -> None:
        body = (
            "await window.DebugObservationHUD.init();"
            "for (let i = 0; i < 35; i++) window.DebugObservationHUD.pushBreadcrumb({ type: 'click', target: '#item-' + i });"
            "const capped = window.DebugObservationHUD.getBreadcrumbs();"
            "_spy.docListeners.click[0]({ target: { tagName: 'BUTTON', id: 'tab-btn-studio', textContent: 'Studio', getAttribute: () => 'tab-studio' } });"
            "_spy.winListeners.hashchange[0]();"
            "_spy.winListeners.error[0]({ message: 'Canvas null', lineno: 42 });"
            "await window.fetch('/api/fail-test', { method: 'POST' });"
            "await window.fetch('/api/system/debug/summary?limit=1');"
            "const tail = window.DebugObservationHUD.getBreadcrumbs().slice(-4);"
            "return { mounted: _spy.bodyChildren.length, cappedLen: capped.length, firstTarget: capped[0].target, tail };"
        )
        out = _run_hud_vm(body, debug_mode=True)
        self.assertEqual(out["mounted"], 1)
        self.assertEqual(out["cappedLen"], 30)
        self.assertEqual(out["firstTarget"], "#item-5")
        self.assertEqual([c["type"] for c in out["tail"]], ["click", "nav", "error", "fetch_error"])
        self.assertEqual(out["tail"][0]["target"], "button#tab-btn-studio[data-tab=tab-studio]")
        self.assertEqual(out["tail"][3]["status"], 500)
        self.assertEqual(out["tail"][3]["url"], "/api/fail-test")

    def test_hud_submits_observation_payload_with_breadcrumbs(self) -> None:
        body = (
            "await window.DebugObservationHUD.init();"
            "_spy.docListeners.click[0]({ target: { tagName: 'BUTTON', id: 'btn-test', textContent: 'Run' } });"
            "const res = await window.DebugObservationHUD.submitObservation('Overlay misaligned on studio');"
            "const post = _spy.fetchCalls.find((c) => c.url === '/api/system/debug/observation');"
            "return { res, method: post && post.method, payload: post ? JSON.parse(post.body) : null };"
        )
        out = _run_hud_vm(body, debug_mode=True)
        self.assertTrue(out["res"]["ok"])
        self.assertEqual(out["method"], "POST")
        payload = out["payload"]
        self.assertEqual(payload["note"], "Overlay misaligned on studio")
        self.assertEqual(payload["tab"], "tab-studio")
        self.assertEqual(payload["url"], "/#tab-studio")
        self.assertEqual(payload["viewport"], {"width": 1440, "height": 900})
        self.assertEqual(payload["breadcrumbs"][-1]["target"], "button#btn-test")


PROBE_PATH = Path(__file__).resolve().parents[1] / ".diagnostics" / "probes" / "debug_session.py"


def _load_debug_session_probe():
    """Dynamically load .diagnostics/probes/debug_session.py without mutating sys.path."""
    spec = importlib.util.spec_from_file_location("debug_session_probe", PROBE_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestDebugObservationCliAndProbe(unittest.TestCase):
    """Verify scripts/debug_inspect.py --observations and .diagnostics/probes/debug_session.py."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.debug_dir = Path(self._tmp.name) / "debug_session"

    def test_debug_inspect_observations_human_and_json(self) -> None:
        from scripts import debug_inspect

        try:
            raise RuntimeError("Multiview websocket dropped")
        except RuntimeError as exc:
            fp = record_debug_event(exc, http_method="GET", http_path="/ws/multiview", debug_dir=self.debug_dir)

        record_user_observation(
            note="Tiles went blank after switching cameras",
            tab="multiview",
            url="/#multiview",
            breadcrumbs=[
                {"type": "click", "target": "button#tab-multiview"},
                {"type": "fetch_error", "url": "/api/cameras", "status": 502},
            ],
            viewport={"width": 1280, "height": 720},
            debug_dir=self.debug_dir,
        )

        buf_human = io.StringIO()
        with contextlib.redirect_stdout(buf_human):
            rc1 = debug_inspect.main(["--dir", str(self.debug_dir), "--observations"])
        self.assertEqual(rc1, 0)
        human_out = buf_human.getvalue()
        self.assertIn("[OBS #1", human_out)
        self.assertIn("Tiles went blank after switching cameras", human_out)
        self.assertIn("fetch_error:/api/cameras (502)", human_out)
        self.assertIn(f"fp={fp}", human_out)

        buf_json = io.StringIO()
        with contextlib.redirect_stdout(buf_json):
            rc2 = debug_inspect.main(["--dir", str(self.debug_dir), "--observations", "--json"])
        self.assertEqual(rc2, 0)
        parsed = json.loads(buf_json.getvalue())
        self.assertEqual(parsed["observations_count"], 1)
        self.assertEqual(parsed["observations"][0]["correlated_issues"][0]["fingerprint"], fp)

    def test_workspace_debug_session_probe_clean_and_correlated(self) -> None:
        probe_mod = _load_debug_session_probe()
        clean_res = probe_mod.run_probe(self.debug_dir)
        self.assertEqual(clean_res["status"], "ok")
        self.assertEqual(clean_res["details"]["observations_count"], 0)

        try:
            raise ValueError("Overlay canvas NaN height")
        except ValueError as exc:
            fp = record_debug_event(exc, http_method="GET", http_path="/api/studio", debug_dir=self.debug_dir)
        record_user_observation(
            note="Canvas collapsed on studio tab",
            tab="studio",
            url="/#studio",
            debug_dir=self.debug_dir,
        )

        err_res = probe_mod.run_probe(self.debug_dir)
        self.assertEqual(err_res["status"], "error")
        self.assertEqual(err_res["details"]["observations_count"], 1)
        self.assertEqual(err_res["details"]["observations"][0]["correlated_issues"][0]["fingerprint"], fp)


if __name__ == "__main__":
    unittest.main()
