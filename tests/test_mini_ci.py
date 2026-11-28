#!/usr/bin/env python3
"""Unit tests for `.diagnostics/mini_ci.json`, standalone `scripts/mini_ci.py`, and clean-env gate."""

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


class TestMiniCiConfigAndHelpers(unittest.TestCase):
    """Verify `.diagnostics/mini_ci.json` SSOT, CLI parsing, and snapshot filtering."""

    def test_mini_ci_json_declares_required_parity_contract(self) -> None:
        self.assertTrue(mini_ci.CONFIG_PATH.is_file(), "Missing .diagnostics/mini_ci.json")
        cfg = mini_ci.load_config(mini_ci.REPO_ROOT)
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

    def test_parse_args_defaults_and_linux_flags(self) -> None:
        args = mini_ci.parse_args([], config={"wsl_distro": "Ubuntu-24.04"})
        self.assertTrue(args.fast)
        self.assertFalse(args.linux)
        self.assertEqual(args.wsl_distro, "Ubuntu-24.04")

        linux = mini_ci.parse_args(["--linux", "--backend", "docker", "--tests", "tests/test_mini_ci.py", "--skip-lint", "--skip-docs"])
        self.assertTrue(linux.linux)
        self.assertFalse(linux.fast)
        self.assertEqual(linux.backend, "docker")
        self.assertEqual(linux.tests, ["tests/test_mini_ci.py"])
        self.assertTrue(linux.skip_lint and linux.skip_docs)

    def test_resolve_host_python_respects_platform(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            win_py = root / ".venv" / "Scripts" / "python.exe"
            win_py.parent.mkdir(parents=True)
            win_py.write_bytes(b"")
            self.assertEqual(mini_ci.resolve_host_python(root, platform="win32"), win_py)
            self.assertEqual(mini_ci.resolve_host_python(root, platform="linux"), Path(sys.executable))

            posix_py = root / ".venv" / "bin" / "python"
            posix_py.parent.mkdir(parents=True)
            posix_py.write_bytes(b"")
            self.assertEqual(mini_ci.resolve_host_python(root, platform="linux"), posix_py)

    def test_windows_to_wsl_path_and_snapshot_excludes(self) -> None:
        self.assertEqual(mini_ci.windows_to_wsl_path(Path(r"C:\dev\repo")), "/mnt/c/dev/repo")
        self.assertEqual(mini_ci.windows_to_wsl_path(Path("/home/user/repo")), "/home/user/repo")
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "src", Path(tmp) / "dst"
            for d in ("models", "data", ".venv"):
                (src / d).mkdir(parents=True)
                (src / d / "file.bin").write_bytes(b"x")
            (src / "requirements.txt").write_text("ruff\n", encoding="utf-8")
            mini_ci.create_clean_snapshot(src, dst, exclude_dirs=["models", "data"])
            self.assertFalse((dst / "models").exists())
            self.assertFalse((dst / "data").exists())
            self.assertFalse((dst / ".venv").exists())
            self.assertTrue((dst / "requirements.txt").exists())


class TestMiniCiCommandConstruction(unittest.TestCase):
    """Verify standalone command construction across --fast, WSL, and Docker."""

    def test_steps_env_and_skip_filters(self) -> None:
        cfg = json.loads(mini_ci.CONFIG_PATH.read_text(encoding="utf-8"))
        env = mini_ci.build_fast_env({"USERPROFILE": r"C:\Users\Alice"}, config=cfg)
        self.assertEqual(env["USERPROFILE"], r"C:\Users\Alice")
        self.assertEqual(env["MPLBACKEND"], "Agg")
        self.assertEqual(env["IT_DISABLE_EXTERNAL_SKILLS"], "1")

        full = mini_ci.build_ci_step_commands("/venv/python", config=cfg)
        self.assertEqual(len(full), 3)
        only_tests = mini_ci.build_ci_step_commands("/venv/python", config=cfg, skip_lint=True, skip_docs=True)
        self.assertEqual(only_tests, [["/venv/python", "-m", "unittest", "discover", "tests"]])
        targeted = mini_ci.build_ci_step_commands("/venv/python", config=cfg, tests=["tests/test_mini_ci.py"])
        self.assertEqual(targeted, [["/venv/python", "-m", "unittest", "-v", "tests/test_mini_ci.py"]])

    def test_wsl_script_and_docker_commands(self) -> None:
        cfg = mini_ci.load_config(mini_ci.REPO_ROOT)
        script = mini_ci.build_wsl_script("/mnt/c/repo", cfg, tests=["tests/test_mini_ci.py"])
        self.assertNotIn("\r", script)
        self.assertIn('if [ ! -f "$VENV/.ready" ]; then', script)
        self.assertIn("import ensurepip", script)
        self.assertIn("export IT_DISABLE_EXTERNAL_SKILLS=1", script)
        self.assertIn("unittest -v tests/test_mini_ci.py", script)

        df = mini_ci.build_dockerfile(cfg)
        self.assertIn("nodejs", df)
        with tempfile.TemporaryDirectory() as tmp:
            req = Path(tmp) / "requirements.txt"
            req.write_text("a==1\n", encoding="utf-8")
            tag1 = mini_ci.docker_image_tag(df, req)
            req.write_text("a==2\n", encoding="utf-8")
            tag2 = mini_ci.docker_image_tag(df, req)
            self.assertNotEqual(tag1, tag2)

        cmd = mini_ci.build_docker_run_command(Path("."), tag1, cfg, tests=["tests/test_mini_ci.py"])
        self.assertEqual(cmd[:3], ["docker", "run", "--rm"])
        self.assertIn("IT_DISABLE_EXTERNAL_SKILLS=1", cmd)
        self.assertIn("HOME=/tmp/mini_ci_home", cmd)
        self.assertIn("unittest -v tests/test_mini_ci.py", cmd[-1])

    def test_select_linux_backend_auto(self) -> None:
        with patch("scripts.mini_ci.shutil.which", side_effect=lambda name: "/bin/wsl" if name == "wsl" else None):
            self.assertEqual(mini_ci.select_linux_backend("auto", platform="win32"), "wsl")
        with patch("scripts.mini_ci.shutil.which", side_effect=lambda name: "/usr/bin/docker" if name == "docker" else None):
            self.assertEqual(mini_ci.select_linux_backend("auto", platform="win32"), "docker")
            self.assertEqual(mini_ci.select_linux_backend("auto", platform="darwin"), "docker")


if __name__ == "__main__":
    unittest.main()
