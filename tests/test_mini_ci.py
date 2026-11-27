#!/usr/bin/env python3
"""Unit tests for scripts/mini_ci.py and IT_DISABLE_EXTERNAL_SKILLS clean-env gate."""

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


class TestMiniCiCliAndHelpers(unittest.TestCase):
    """Verify CLI flag parsing, hash caching, venv resolution, and snapshot filtering."""

    def test_parse_args_defaults_to_fast(self) -> None:
        args = mini_ci.parse_args([])
        self.assertTrue(args.fast)
        self.assertFalse(args.linux)
        self.assertEqual(args.backend, "auto")
        self.assertIsNone(args.tests)
        self.assertFalse(args.skip_lint)
        self.assertFalse(args.skip_docs)

    def test_parse_args_linux_with_targeted_tests(self) -> None:
        args = mini_ci.parse_args([
            "--linux",
            "--backend",
            "docker",
            "--tests",
            "tests/test_mini_ci.py",
            "tests/test_diagnostics_contract.py",
            "--skip-docs",
            "--skip-lint",
            "--clean-snapshot",
        ])
        self.assertTrue(args.linux)
        self.assertFalse(args.fast)
        self.assertEqual(args.backend, "docker")
        self.assertEqual(args.tests, ["tests/test_mini_ci.py", "tests/test_diagnostics_contract.py"])
        self.assertTrue(args.skip_docs)
        self.assertTrue(args.skip_lint)
        self.assertTrue(args.clean_snapshot)

    def test_requirements_hash_changes_with_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            h1 = mini_ci.requirements_hash(root)
            h1_repeat = mini_ci.requirements_hash(root)
            (root / "requirements.txt").write_text("fastapi==0.116.0\n", encoding="utf-8")
            h2 = mini_ci.requirements_hash(root)
            self.assertEqual(h1, h1_repeat)
            self.assertEqual(len(h1), 12)
            self.assertNotEqual(h1, h2)

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

    def test_windows_to_wsl_path(self) -> None:
        self.assertEqual(
            mini_ci.windows_to_wsl_path(Path(r"C:\dev\projects\intelligent_tracker")),
            "/mnt/c/dev/projects/intelligent_tracker",
        )
        self.assertEqual(mini_ci.windows_to_wsl_path(Path("/home/user/repo")), "/home/user/repo")

    def test_create_clean_snapshot_excludes_local_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            dst = Path(tmp) / "dst"
            (src / "models").mkdir(parents=True)
            (src / "data").mkdir(parents=True)
            (src / ".venv" / "bin").mkdir(parents=True)
            (src / "models" / "osnet.onnx").write_bytes(b"weights")
            (src / "models" / "README.md").write_text("keep", encoding="utf-8")
            (src / "data" / "tracker.db").write_bytes(b"sqlite")
            (src / "data" / "sample.json").write_text("{}", encoding="utf-8")
            (src / ".venv" / "bin" / "python").write_bytes(b"")
            (src / "requirements.txt").write_text("ruff\n", encoding="utf-8")

            mini_ci.create_clean_snapshot(src, dst)
            self.assertFalse((dst / "models" / "osnet.onnx").exists())
            self.assertTrue((dst / "models" / "README.md").exists())
            self.assertFalse((dst / "data" / "tracker.db").exists())
            self.assertTrue((dst / "data" / "sample.json").exists())
            self.assertFalse((dst / ".venv").exists())
            self.assertTrue((dst / "requirements.txt").exists())


class TestMiniCiCommandConstruction(unittest.TestCase):
    """Verify command and environment construction across --fast, wsl, and docker backends."""

    def test_build_fast_env_sets_flags_without_clobbering_userprofile(self) -> None:
        env = mini_ci.build_fast_env({"USERPROFILE": r"C:\Users\Alice", "PATH": "/usr/bin"})
        self.assertEqual(env["USERPROFILE"], r"C:\Users\Alice")
        self.assertEqual(env["MPLBACKEND"], "Agg")
        self.assertEqual(env["IT_DISABLE_EXTERNAL_SKILLS"], "1")

    def test_build_ci_step_commands_targeted_and_full(self) -> None:
        full = mini_ci.build_ci_step_commands("/venv/python")
        self.assertEqual([label for label, _ in full], ["Ruff Linter", "Full Test Suite", "Sphinx Docs"])
        self.assertEqual(full[1][1], ["/venv/python", "-m", "unittest", "discover", "tests"])

        targeted = mini_ci.build_ci_step_commands(
            "/venv/python", tests=["tests/test_mini_ci.py"], skip_lint=True, skip_docs=True
        )
        self.assertEqual(len(targeted), 1)
        self.assertEqual(targeted[0][1], ["/venv/python", "-m", "unittest", "-v", "tests/test_mini_ci.py"])

    def test_wsl_script_uses_persistent_ext4_venv_and_isolated_home(self) -> None:
        script = mini_ci.build_wsl_script(
            "/mnt/c/dev/repo",
            "abc123def456",
            tests=["tests/test_mini_ci.py"],
            skip_docs=True,
        )
        self.assertIn("$HOME/.venvs/intelligent_tracker", script)
        self.assertIn('REQ_HASH="abc123def456"', script)
        self.assertIn('HASH_FILE="$VENV/.req_sha256"', script)
        self.assertIn('export HOME="$CLEAN_HOME"', script)
        self.assertIn('export IT_DISABLE_EXTERNAL_SKILLS="1"', script)
        self.assertIn('export MPLBACKEND="Agg"', script)
        self.assertIn("unittest -v tests/test_mini_ci.py", script)
        self.assertNotIn("-m sphinx", script)

        cmd = mini_ci.build_wsl_command("Ubuntu-24.04", script)
        self.assertEqual(cmd[:5], ["wsl", "-d", "Ubuntu-24.04", "--", "bash"])

    def test_docker_run_command_uses_hashed_image_and_isolated_home(self) -> None:
        tag = mini_ci.docker_image_tag("deadbeef1234")
        self.assertEqual(tag, "intelligent-tracker-mini-ci:deadbeef1234")
        cmd = mini_ci.build_docker_run_command(
            Path("."),
            tag,
            tests=["tests/test_mini_ci.py"],
            skip_lint=True,
        )
        self.assertEqual(cmd[:3], ["docker", "run", "--rm"])
        self.assertIn("IT_DISABLE_EXTERNAL_SKILLS=1", cmd)
        self.assertIn("MPLBACKEND=Agg", cmd)
        self.assertIn("HOME=/tmp/mini_ci_home", cmd)
        self.assertIn(tag, cmd)
        self.assertIn("unittest -v tests/test_mini_ci.py", cmd[-1])
        self.assertNotIn("ruff", cmd[-1])

    def test_select_linux_backend_auto(self) -> None:
        with patch("scripts.mini_ci.shutil.which", side_effect=lambda name: "/bin/wsl" if name == "wsl" else None):
            self.assertEqual(mini_ci.select_linux_backend("auto", platform="win32"), "wsl")
        with patch("scripts.mini_ci.shutil.which", side_effect=lambda name: "/usr/bin/docker" if name == "docker" else None):
            self.assertEqual(mini_ci.select_linux_backend("auto", platform="win32"), "docker")
            self.assertEqual(mini_ci.select_linux_backend("auto", platform="darwin"), "docker")


if __name__ == "__main__":
    unittest.main()
