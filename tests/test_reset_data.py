#!/usr/bin/env python3
"""Isolated unit tests for dashboard.services.data_reset_service and scripts.reset_data."""

import io
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import zipfile

from dashboard.services.data_reset_service import (
    build_reset_plan,
    create_pre_reset_backup,
    execute_reset_items,
    resolve_reset_paths,
)
from scripts import reset_data


class TestDataResetServiceAndCli(unittest.TestCase):
    """Verify OS-agnostic path resolution, backups, prompts, and local/docker resets."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self._seed_workspace()

    def _seed_workspace(self) -> None:
        (self.root / "data" / "crops").mkdir(parents=True)
        (self.root / "data" / "reports").mkdir(parents=True)
        (self.root / "data" / "videos").mkdir(parents=True)
        (self.root / "data" / "debug_session").mkdir(parents=True)
        (self.root / "configs").mkdir(parents=True)

        db_file = self.root / "data" / "tracker.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE entities (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE entity_signatures (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE sightings (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        (self.root / "data" / "tracker.db-wal").write_bytes(b"wal")
        (self.root / "data" / "crops" / "alice.jpg").write_bytes(b"jpg")
        (self.root / "data" / "reports" / "rep.json").write_text("{}", encoding="utf-8")
        (self.root / "data" / "videos" / "clip.mp4").write_bytes(b"mp4")
        (self.root / "data" / "debug_session" / "debug.log").write_text("dbg", encoding="utf-8")
        (self.root / "configs" / "cameras.json").write_text("[]", encoding="utf-8")
        (self.root / "configs" / "scenarios.yaml").write_text("zones: []\n", encoding="utf-8")

    def test_resolve_paths_precedence_cli_over_env_over_default(self) -> None:
        env = {
            "TRACKER_DB": "data/from_legacy_env.db",
            "TRACKER_DB_PATH": "data/test_clean.db",
            "CAMERAS_CONFIG_PATH": "configs/custom_cams.json",
            "SCENARIOS_CONFIG_PATH": "configs/custom_scen.yaml",
        }
        with patch.dict(os.environ, env, clear=False):
            paths = resolve_reset_paths(self.root, cameras_config="configs/cli_cams.json")
        self.assertEqual(paths.db_path, self.root / "data" / "test_clean.db")
        self.assertEqual(paths.cameras_config, self.root / "configs" / "cli_cams.json")
        self.assertEqual(paths.scenarios_config, self.root / "configs" / "custom_scen.yaml")
        self.assertIn("TRACKER_DB_PATH", paths.active_env_vars)

    def test_default_backup_and_selective_delete(self) -> None:
        paths = resolve_reset_paths(self.root)
        backup_zip = create_pre_reset_backup(paths)
        self.assertIsNotNone(backup_zip)
        assert backup_zip is not None
        self.assertTrue(backup_zip.is_file())
        with zipfile.ZipFile(backup_zip, "r") as zf:
            self.assertIn("data/tracker.db", zf.namelist())
            self.assertIn("data/crops/alice.jpg", zf.namelist())

        plan = build_reset_plan(paths, target="local")
        default_items = [item for item in plan if item.default_yes]
        result = execute_reset_items(default_items, dry_run=False, repo_root=self.root)
        self.assertEqual(result["errors"], [])
        self.assertFalse((self.root / "data" / "tracker.db").exists())
        self.assertFalse((self.root / "data" / "tracker.db-wal").exists())
        self.assertFalse((self.root / "data" / "crops" / "alice.jpg").exists())
        self.assertTrue((self.root / "data" / "crops").is_dir())
        self.assertFalse((self.root / "data" / "debug_session").exists())
        # Videos and configs default_yes=False, so preserved
        self.assertTrue((self.root / "data" / "videos" / "clip.mp4").is_file())
        self.assertTrue((self.root / "configs" / "cameras.json").is_file())

    def test_cli_non_tty_requires_yes_or_prompt(self) -> None:
        fake_stdin = io.StringIO("")
        with (
            patch.object(reset_data, "REPO_ROOT", self.root),
            patch.object(reset_data, "check_running_server", return_value=[]),
            patch.object(sys_stdin := reset_data.sys, "stdin", fake_stdin),
        ):
            _ = sys_stdin
            rc = reset_data.main(["--target", "local"])
        self.assertEqual(rc, 2)
        self.assertTrue((self.root / "data" / "tracker.db").is_file())

    def test_cli_prompt_flag_works_headless_with_per_category_prompts(self) -> None:
        answers = iter(["n", "y", "n", "n", "n", "y"])
        with (
            patch.object(reset_data, "REPO_ROOT", self.root),
            patch.object(reset_data, "check_running_server", return_value=[]),
            patch("builtins.input", side_effect=lambda _prompt: next(answers)),
        ):
            rc = reset_data.main(["--prompt", "--no-backup"])
        self.assertEqual(rc, 0)
        self.assertTrue((self.root / "data" / "tracker.db").is_file())
        self.assertFalse((self.root / "data" / "crops" / "alice.jpg").exists())
        self.assertFalse((self.root / "configs" / "cameras.json").is_file())

    def test_cli_dry_run_only_and_include_flags(self) -> None:
        with (
            patch.object(reset_data, "REPO_ROOT", self.root),
            patch.object(reset_data, "check_running_server", return_value=[]),
        ):
            rc = reset_data.main(["--dry-run", "--only", "db,videos", "--include-videos"])
        self.assertEqual(rc, 0)
        self.assertTrue((self.root / "data" / "tracker.db").is_file())
        self.assertTrue((self.root / "data" / "videos" / "clip.mp4").is_file())

    def test_docker_reset_invokes_compose_down_v_and_handles_missing_docker(self) -> None:
        paths = resolve_reset_paths(self.root)
        docker_plan = build_reset_plan(paths, target="docker")
        fake_proc = MagicMock(returncode=0, stdout="Removed volumes", stderr="")
        with (
            patch("dashboard.services.data_reset_service.shutil.which", return_value="docker"),
            patch("dashboard.services.data_reset_service.subprocess.run", return_value=fake_proc) as run_mock,
        ):
            res = execute_reset_items(docker_plan, dry_run=False, repo_root=self.root)
        self.assertEqual(res["errors"], [])
        run_mock.assert_called_once()
        self.assertEqual(run_mock.call_args.args[0][1:], ["compose", "down", "-v"])

        with patch("dashboard.services.data_reset_service.shutil.which", return_value=None):
            err_res = execute_reset_items(docker_plan, dry_run=False, repo_root=self.root)
        self.assertTrue(err_res["errors"])


if __name__ == "__main__":
    unittest.main()
