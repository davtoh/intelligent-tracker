#!/usr/bin/env python3
"""Isolated unit tests for debug session isolation, runtime crash capture, and debug_inspect."""

import contextlib
import io
import json
import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dashboard import server
from dashboard.services.debug_session import (
    get_issue_context,
    install_debug_runtime,
    prepare_debug_session_env,
    record_debug_event,
    summarize_debug_session,
    uninstall_debug_runtime,
)
from scripts import debug_inspect


class TestDebugSessionAndInspector(unittest.TestCase):
    """Verify --debug/--clean-debug env isolation, crash capture, and deduplicated triage."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.debug_dir = Path(self._tmp.name) / "debug_session"
        self.addCleanup(uninstall_debug_runtime)

    def test_server_parse_args_and_clean_debug_env(self) -> None:
        args = server.parse_args(["--debug", "--clean-debug", "--debug-dir", str(self.debug_dir)])
        self.assertTrue(args.debug)
        self.assertTrue(args.clean_debug)

        stale_file = self.debug_dir / "stale.txt"
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        stale_file.write_text("old", encoding="utf-8")

        with patch.dict(os.environ, {}, clear=False):
            env_vals = prepare_debug_session_env(self.debug_dir, clean=True)
            self.assertFalse(stale_file.exists())
            self.assertTrue((self.debug_dir / "crops").is_dir())
            self.assertTrue((self.debug_dir / "reports").is_dir())
            self.assertEqual(env_vals["IT_DEBUG_MODE"], "1")
            self.assertEqual(Path(env_vals["TRACKER_DB_PATH"]), self.debug_dir / "tracker.db")
            self.assertEqual(Path(env_vals["CAMERAS_CONFIG_PATH"]), self.debug_dir / "cameras.json")
            self.assertEqual(Path(env_vals["SCENARIOS_CONFIG_PATH"]), self.debug_dir / "scenarios.yaml")
            self.assertEqual(env_vals["PYTHONASYNCIODEBUG"], "1")

    def test_runtime_capture_deduplication_and_context(self) -> None:
        info = install_debug_runtime(self.debug_dir)
        self.assertTrue(Path(info["faulthandler_log"]).is_file())

        test_logger = logging.getLogger("intelligent_tracker.test_debug")
        test_logger.debug("Starting synthetic debug step")
        for _ in range(3):
            try:
                raise RuntimeError("Synthetic pipeline boom")
            except RuntimeError:
                test_logger.exception("Pipeline step failed")
        test_logger.warning("Low disk headroom warning")

        try:
            raise ValueError("Bad query param")
        except ValueError as exc:
            record_debug_event(exc, http_method="GET", http_path="/api/test", debug_dir=self.debug_dir)

        # Simulate native crash output in faulthandler.log
        uninstall_debug_runtime()
        (self.debug_dir / "faulthandler.log").write_text("Fatal Python error: Segmentation fault\n", encoding="utf-8")

        summary = summarize_debug_session(self.debug_dir, min_level="WARNING", limit=20)
        self.assertTrue(summary["native_crash_detected"])
        self.assertEqual(summary["totals"]["ERROR"], 4)
        self.assertEqual(summary["totals"]["WARNING"], 1)
        self.assertEqual(summary["unique_issues"], 3)

        top_issue = summary["issues"][0]
        self.assertEqual(top_issue["count"], 3)
        self.assertEqual(top_issue["tag"], "ERR")

        ctx = get_issue_context(self.debug_dir, "1", context_lines=5)
        self.assertIsNotNone(ctx)
        assert ctx is not None
        self.assertIn("RuntimeError: Synthetic pipeline boom", ctx["issue"]["traceback"])
        self.assertTrue(any("Pipeline step failed" in line for line in ctx["log_context"]))

    def test_debug_inspect_cli_summary_json_and_context(self) -> None:
        install_debug_runtime(self.debug_dir)
        logging.getLogger("dashboard.test_cli").error("Stream decode stalled")
        uninstall_debug_runtime()

        buf_human = io.StringIO()
        with contextlib.redirect_stdout(buf_human):
            rc1 = debug_inspect.main(["--dir", str(self.debug_dir)])
        self.assertEqual(rc1, 0)
        self.assertIn("[#1 ERR x1", buf_human.getvalue())

        buf_json = io.StringIO()
        with contextlib.redirect_stdout(buf_json):
            rc2 = debug_inspect.main(["--dir", str(self.debug_dir), "--json"])
        self.assertEqual(rc2, 0)
        parsed = json.loads(buf_json.getvalue())
        self.assertEqual(parsed["unique_issues"], 1)

        buf_ctx = io.StringIO()
        with contextlib.redirect_stdout(buf_ctx):
            rc3 = debug_inspect.main(["--dir", str(self.debug_dir), "--context", "1"])
        self.assertEqual(rc3, 0)
        self.assertIn("Stream decode stalled", buf_ctx.getvalue())

    def test_debug_session_probe_surfaces_open_observations_and_warning_status(self) -> None:
        import importlib.util

        probe_path = Path(__file__).resolve().parents[1] / ".diagnostics" / "probes" / "debug_session.py"
        spec = importlib.util.spec_from_file_location("debug_session_probe", probe_path)
        assert spec is not None and spec.loader is not None
        probe_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(probe_mod)

        catalog_file = Path(self._tmp.name) / "observation_catalog.json"

        # 1. Clean state: missing dir + missing catalog -> ok, 0 open observations
        clean = probe_mod.run_probe(self.debug_dir, catalog_path=catalog_file)
        self.assertEqual(clean["status"], "ok")
        self.assertEqual(clean["details"]["open_observations_count"], 0)

        # 2. Active observations in catalog (open + triaged; resolved/dismissed ignored) -> warning
        catalog_payload = {
            "schema_version": "1.0",
            "observations": [
                {"id": "OBS-001", "status": "open", "kind": "note", "message": "Stalled playback"},
                {"id": "OBS-002", "status": "triaged", "kind": "element", "message": "Misaligned badge"},
                {"id": "OBS-003", "status": "resolved", "kind": "note", "message": "Already fixed"},
                {"id": "OBS-004", "status": "dismissed", "kind": "idea", "message": "Won't do"},
            ],
        }
        catalog_file.write_text(json.dumps(catalog_payload), encoding="utf-8")
        warn_res = probe_mod.run_probe(self.debug_dir, catalog_path=catalog_file)
        self.assertEqual(warn_res["status"], "warning")
        self.assertEqual(warn_res["details"]["open_observations_count"], 2)
        self.assertIn("2 active observation", warn_res["summary"])

        # 3. Backend error takes precedence over warning while still surfacing open_observations_count
        install_debug_runtime(self.debug_dir)
        logging.getLogger("dashboard.test_probe_err").error("Synthetic probe failure")
        uninstall_debug_runtime()
        err_res = probe_mod.run_probe(self.debug_dir, catalog_path=catalog_file)
        self.assertEqual(err_res["status"], "error")
        self.assertEqual(err_res["details"]["open_observations_count"], 2)
        self.assertIn("open_obs=2", err_res["summary"])


if __name__ == "__main__":
    unittest.main()
