#!/usr/bin/env python3
"""Unit tests for dev-only Frontier Debug Observations HUD injection in GET /."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from dashboard import server
from dashboard.app import create_app
from dashboard.services import diagnostic_bridge
from dashboard.services.debug_session import prepare_debug_session_env

_HAS_OBS_ENGINE = diagnostic_bridge._obs is not None
_SKIP_NO_OBS = "system-diagnostics observation_routes engine not installed"


class TestDashboardDebugHud(unittest.TestCase):
    """Verify GET / injects the HUD scripts only when FRONTIER_DEBUG_OBSERVATIONS=1."""

    def test_index_omits_hud_scripts_when_flag_off(self) -> None:
        for flag in (None, "0", "false"):
            env_patch = {} if flag is None else {"FRONTIER_DEBUG_OBSERVATIONS": flag}
            with patch.dict(os.environ, env_patch, clear=False):
                if flag is None:
                    os.environ.pop("FRONTIER_DEBUG_OBSERVATIONS", None)
                app = create_app()
                client = TestClient(app, client=("127.0.0.1", 50000))
                resp = client.get("/")
                self.assertEqual(resp.status_code, 200)
                html = resp.text
                self.assertNotIn("window.__FRONTIER_DEBUG__ = true;", html)
                self.assertNotIn("/api/diagnostics/hud.js", html)
                self.assertNotIn("/static/js/debug_observation_hud.js", html)

    def test_index_renders_hud_tags_when_observations_enabled_is_true(self) -> None:
        with patch("dashboard.app.observations_enabled", return_value=True):
            app = create_app()
            client = TestClient(app, client=("127.0.0.1", 50000))
            resp = client.get("/")
            self.assertEqual(resp.status_code, 200)
            html = resp.text
            self.assertIn("<script>window.__FRONTIER_DEBUG__ = true;</script>", html)
            self.assertIn('<script src="/api/diagnostics/hud.js"></script>', html)
            self.assertNotIn("/static/js/debug_observation_hud.js", html)
            self.assertLess(
                html.index("window.__FRONTIER_DEBUG__ = true;"),
                html.index('/api/diagnostics/hud.js'),
            )

    @unittest.skipUnless(_HAS_OBS_ENGINE, _SKIP_NO_OBS)
    def test_index_injects_both_hud_scripts_when_flag_enabled(self) -> None:
        with patch.dict(os.environ, {"FRONTIER_DEBUG_OBSERVATIONS": "1"}, clear=False):
            app = create_app()
            client = TestClient(app, client=("127.0.0.1", 50000))
            resp = client.get("/")
            self.assertEqual(resp.status_code, 200)
            html = resp.text
            self.assertIn("<script>window.__FRONTIER_DEBUG__ = true;</script>", html)
            self.assertIn('<script src="/api/diagnostics/hud.js"></script>', html)
            self.assertNotIn("/static/js/debug_observation_hud.js", html)
            self.assertLess(
                html.index("window.__FRONTIER_DEBUG__ = true;"),
                html.index('/api/diagnostics/hud.js'),
            )

            hud_resp = client.get("/api/diagnostics/hud.js")
            self.assertEqual(hud_resp.status_code, 200)
            self.assertIn("javascript", hud_resp.headers.get("Content-Type", ""))

    def test_server_debug_args_and_prepare_env_align_observations_flag(self) -> None:
        args = server.parse_args(["--debug-observations"])
        self.assertTrue(args.debug_observations)
        default_args = server.parse_args([])
        self.assertFalse(default_args.debug_observations)

        with tempfile.TemporaryDirectory() as tmp:
            debug_dir = Path(tmp) / "debug_session"
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("FRONTIER_DEBUG_OBSERVATIONS", None)
                env_vals = prepare_debug_session_env(debug_dir, clean=False)
                self.assertEqual(env_vals["FRONTIER_DEBUG_OBSERVATIONS"], "1")

            with patch.dict(os.environ, {"FRONTIER_DEBUG_OBSERVATIONS": "0"}, clear=False):
                env_vals_opt_out = prepare_debug_session_env(debug_dir, clean=False)
                self.assertEqual(env_vals_opt_out["FRONTIER_DEBUG_OBSERVATIONS"], "0")


if __name__ == "__main__":
    unittest.main()
