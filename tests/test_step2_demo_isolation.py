"""Isolated unit tests for Step 2 opt-in demo scenario isolation."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from dashboard.camera_pool import CameraPool
from dashboard.server import main as server_main, parse_args
from dashboard.services.base_config_resolver import (
    DEFAULT_CONFIG_PATH,
    DEMO_CONFIG_PATH,
    is_demo_scenarios_enabled,
    resolve_base_config_path,
)
from dashboard.stream_manager import StreamManager


class TestBaseConfigResolver(unittest.TestCase):
    """Verify precedence of explicit -> TRACKER_CONFIG -> IT_LOAD_DEMO_SCENARIOS -> default."""

    def test_default_resolves_to_clean_config(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(is_demo_scenarios_enabled())
            self.assertEqual(resolve_base_config_path(), DEFAULT_CONFIG_PATH)

    def test_demo_env_truthy_values_load_alert_demo(self) -> None:
        for val in ("1", "true", "yes", "TRUE", " Yes "):
            with self.subTest(val=val):
                with patch.dict(os.environ, {"IT_LOAD_DEMO_SCENARIOS": val}, clear=True):
                    self.assertTrue(is_demo_scenarios_enabled())
                    self.assertEqual(resolve_base_config_path(), DEMO_CONFIG_PATH)

    def test_demo_env_falsy_values_use_default(self) -> None:
        for val in ("0", "false", "no", ""):
            with self.subTest(val=val):
                with patch.dict(os.environ, {"IT_LOAD_DEMO_SCENARIOS": val}, clear=True):
                    self.assertFalse(is_demo_scenarios_enabled())
                    self.assertEqual(resolve_base_config_path(), DEFAULT_CONFIG_PATH)

    def test_tracker_config_overrides_demo_env(self) -> None:
        with patch.dict(
            os.environ,
            {"TRACKER_CONFIG": "configs/custom.yaml", "IT_LOAD_DEMO_SCENARIOS": "1"},
            clear=True,
        ):
            self.assertEqual(resolve_base_config_path(), "configs/custom.yaml")

    def test_explicit_path_overrides_all_env_vars(self) -> None:
        with patch.dict(
            os.environ,
            {"TRACKER_CONFIG": "configs/custom.yaml", "IT_LOAD_DEMO_SCENARIOS": "1"},
            clear=True,
        ):
            self.assertEqual(resolve_base_config_path("configs/explicit.yaml"), "configs/explicit.yaml")


class TestDefaultYamlIsolation(unittest.TestCase):
    """Verify configs/default.yaml has no demo zones, tripwires, or alerting rules."""

    def test_default_yaml_excludes_demo_blocks(self) -> None:
        default_path = Path("configs/default.yaml")
        self.assertTrue(default_path.exists(), "configs/default.yaml must exist")
        cfg = yaml.safe_load(default_path.read_text(encoding="utf-8"))
        self.assertIsInstance(cfg, dict)
        self.assertIn("analytics", cfg)
        self.assertNotIn("zones", cfg["analytics"])
        self.assertNotIn("tripwires", cfg["analytics"])
        self.assertNotIn("alerting", cfg)


class TestColdBootDemoIsolation(unittest.TestCase):
    """Verify CameraPool and StreamManager isolate demo scenarios unless opted in."""

    def test_default_cold_boot_has_zero_restricted_vault_zones(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg_file = os.path.join(tmp.name, "cameras.json")
        db_file = os.path.join(tmp.name, "tracker.db")

        with patch.dict(os.environ, {}, clear=True):
            pool = CameraPool(config_file=cfg_file, db_path=db_file, autostart=False)
            self.addCleanup(pool.stop_all)
            self.assertEqual(pool.base_config_path, DEFAULT_CONFIG_PATH)

            mgr = StreamManager(db_path=db_file, camera_id="cam_clean_test")
            self.addCleanup(mgr.stop)
            self.assertEqual(mgr.config_path, DEFAULT_CONFIG_PATH)
            self.assertFalse(mgr.cfg.get("analytics", {}).get("zones"))
            self.assertIsNone(mgr.cfg.get("alerting"))
            self.assertNotIn("restricted_vault", str(mgr.cfg))

    def test_opt_in_demo_env_wires_alert_demo_into_pool(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg_file = os.path.join(tmp.name, "cameras.json")
        db_file = os.path.join(tmp.name, "tracker.db")

        with patch.dict(os.environ, {"IT_LOAD_DEMO_SCENARIOS": "1"}, clear=True):
            pool = CameraPool(config_file=cfg_file, db_path=db_file, autostart=False)
            self.addCleanup(pool.stop_all)
            self.assertEqual(pool.base_config_path, DEMO_CONFIG_PATH)


class TestServerDemoFlag(unittest.TestCase):
    """Verify dashboard.server --demo sets IT_LOAD_DEMO_SCENARIOS before uvicorn.run()."""

    def test_parse_args_demo_flag(self) -> None:
        self.assertTrue(parse_args(["--demo"]).demo)
        self.assertFalse(parse_args([]).demo)

    def test_server_main_propagates_demo_env_before_uvicorn(self) -> None:
        observed_env: list[str | None] = []

        def fake_uvicorn_run(*_args: object, **_kwargs: object) -> None:
            observed_env.append(os.environ.get("IT_LOAD_DEMO_SCENARIOS"))

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("dashboard.server.process_supervisor.assign_to_job_object"),
            patch("dashboard.server.process_supervisor.check_port_available", return_value=True),
            patch("dashboard.server.uvicorn.run", side_effect=fake_uvicorn_run),
        ):
            server_main(["--demo", "--no-reload"])

        self.assertEqual(observed_env, ["1"])


if __name__ == "__main__":
    unittest.main()
