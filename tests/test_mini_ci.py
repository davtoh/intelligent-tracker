#!/usr/bin/env python3
"""Unit tests for `.diagnostics/mini_ci.json`, `scripts/mini_ci.py` wrapper, and clean-env gate."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from dashboard.services import diagnostic_bridge
from scripts import mini_ci


class TestExternalSkillIsolation(unittest.TestCase):
    """Verify IT_DISABLE_EXTERNAL_SKILLS=1 prevents external skill discovery."""

    def test_engine_candidates_empty_when_disabled(self) -> None:
        for val in ("1", "true", "YES", " 1 "):
            with patch.dict(os.environ, {"IT_DISABLE_EXTERNAL_SKILLS": val}, clear=False):
                self.assertEqual(diagnostic_bridge._engine_candidates(), [])

    def test_engine_candidates_non_empty_when_enabled(self) -> None:
        with patch.dict(os.environ, {"IT_DISABLE_EXTERNAL_SKILLS": "0"}, clear=False):
            self.assertGreater(len(diagnostic_bridge._engine_candidates()), 0)

    def test_fresh_import_with_flag_disables_observation_engine(self) -> None:
        env = dict(os.environ)
        env["IT_DISABLE_EXTERNAL_SKILLS"] = "1"
        env.pop("SYSTEM_DIAGNOSTICS_DIR", None)
        code = (
            "from dashboard.services import diagnostic_bridge as db; "
            "assert db._engine_candidates() == []; "
            "assert db._obs is None; "
            "assert db._recorder_mod is None"
        )
        res = subprocess.run(
            [sys.executable, "-c", code],
            cwd=mini_ci.REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0, msg=res.stderr)


class TestMiniCiConfigAndWrapper(unittest.TestCase):
    """Verify `.diagnostics/mini_ci.json` SSOT and `scripts/mini_ci.py` delegation."""

    def test_mini_ci_json_declares_required_parity_contract(self) -> None:
        self.assertTrue(mini_ci.CONFIG_PATH.is_file(), "Missing .diagnostics/mini_ci.json")
        cfg = json.loads(mini_ci.CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(cfg["env"]["IT_DISABLE_EXTERNAL_SKILLS"], "1")
        for pkg in ("libgl1", "libglib2.0-0", "ffmpeg", "nodejs"):
            self.assertIn(pkg, cfg["apt_packages"])
        for pkg in ("ruff", "sphinx", "sphinx-rtd-theme"):
            self.assertIn(pkg, cfg["pip_packages"])
        for excl in ("models", "data", "_build"):
            self.assertIn(excl, cfg["exclude_dirs"])
        joined = [" ".join(step) for step in cfg["steps"]]
        self.assertTrue(any("ruff" in s for s in joined))
        self.assertTrue(any("unittest" in s for s in joined))
        self.assertTrue(any("sphinx" in s for s in joined))

    def test_resolve_host_python_windows_and_posix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            win_py = root / ".venv" / "Scripts" / "python.exe"
            win_py.parent.mkdir(parents=True)
            win_py.write_bytes(b"")
            self.assertEqual(mini_ci.resolve_host_python(root, platform="win32"), win_py)

            posix_py = root / ".venv" / "bin" / "python"
            posix_py.parent.mkdir(parents=True)
            posix_py.write_bytes(b"")
            self.assertEqual(mini_ci.resolve_host_python(root, platform="linux"), posix_py)

    def test_find_diagnose_script_prefers_env_then_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            env_diag = base / "custom_sd" / "scripts" / "diagnose.py"
            env_diag.parent.mkdir(parents=True)
            env_diag.write_text("# stub\n", encoding="utf-8")
            found = mini_ci.find_diagnose_script(
                env={"SYSTEM_DIAGNOSTICS_DIR": str(base / "custom_sd")},
                home=base / "empty_home",
            )
            self.assertEqual(found, env_diag)

            home_diag = base / "home" / ".gemini" / "config" / "skills" / "system-diagnostics" / "scripts" / "diagnose.py"
            home_diag.parent.mkdir(parents=True)
            home_diag.write_text("# stub\n", encoding="utf-8")
            self.assertEqual(mini_ci.find_diagnose_script(env={}, home=base / "home"), home_diag)
            self.assertIsNone(mini_ci.find_diagnose_script(env={}, home=base / "missing"))

    def test_build_diagnose_argv_injects_repo_path_and_forwards_flags(self) -> None:
        diag = Path("/skills/system-diagnostics/scripts/diagnose.py")
        cmd = mini_ci.build_diagnose_argv(
            diag,
            ["--linux", "--backend", "docker", "--tests", "tests/test_mini_ci.py"],
            python_exe=Path("/venv/python"),
            repo_root=Path("/repo"),
        )
        self.assertEqual(
            cmd,
            [
                str(Path("/venv/python")),
                str(diag),
                "ci",
                "--path",
                str(Path("/repo")),
                "--linux",
                "--backend",
                "docker",
                "--tests",
                "tests/test_mini_ci.py",
            ],
        )

    def test_main_delegates_to_diagnose_when_available(self) -> None:
        fake_diag = Path("/fake/diagnose.py")
        with (
            patch.object(mini_ci, "find_diagnose_script", return_value=fake_diag),
            patch("scripts.mini_ci.subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 0
            rc = mini_ci.main(["--fast", "--dry-run"])
            self.assertEqual(rc, 0)
            called_cmd = mock_run.call_args.args[0]
            self.assertIn("ci", called_cmd)
            self.assertIn("--fast", called_cmd)
            self.assertIn("--dry-run", called_cmd)

    def test_standalone_fallback_dry_run_and_linux_error(self) -> None:
        with patch.object(mini_ci, "find_diagnose_script", return_value=None):
            self.assertEqual(mini_ci.main(["--fast", "--dry-run"]), 0)
            self.assertEqual(mini_ci.main(["--linux"]), 2)


if __name__ == "__main__":
    unittest.main()
