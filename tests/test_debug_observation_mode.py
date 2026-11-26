#!/usr/bin/env python3
"""Isolated unit and FastAPI tests for interactive Debug Observation Mode (Milestone 1)."""

import json
import os
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
