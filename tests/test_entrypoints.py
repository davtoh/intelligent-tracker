"""Tests for pyproject.toml console entrypoints, package layering, and ctl URL resolution."""

import ast
import os
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from intelligent_tracker.cli.ctl import resolve_dashboard_url


REPO_ROOT = Path(__file__).resolve().parent.parent


class TestEntrypoints(unittest.TestCase):
    """Verify PEP 621 entrypoints, architectural layer isolation, and CLI --help."""

    def test_pyproject_scripts_resolve_and_help(self) -> None:
        """All [project.scripts] targets must resolve to callables and support --help."""
        pyproject_path = REPO_ROOT / "pyproject.toml"
        self.assertTrue(pyproject_path.is_file(), "pyproject.toml must exist at repo root")

        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        scripts = data.get("project", {}).get("scripts", {})
        expected = {
            "intelligent-tracker": "intelligent_tracker.cli:main",
            "intelligent-tracker-server": "dashboard.server:main",
            "intelligent-tracker-ctl": "intelligent_tracker.cli.ctl:main",
        }
        self.assertEqual(scripts, expected)

        for name, target in scripts.items():
            module_name, attr_name = target.split(":", 1)
            probe = (
                f"import importlib, sys; "
                f"mod = importlib.import_module({module_name!r}); "
                f"fn = getattr(mod, {attr_name!r}); "
                f"assert callable(fn); "
                f"sys.argv = [{name!r}, '--help']; "
                f"fn()"
            )
            proc = subprocess.run(
                [sys.executable, "-c", probe],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(
                proc.returncode,
                0,
                f"{name} ({target}) --help failed with rc={proc.returncode}: {proc.stderr}",
            )
            self.assertIn("usage:", proc.stdout.lower(), f"{name} --help missing usage output")

    def test_core_package_never_imports_dashboard_or_scripts(self) -> None:
        """intelligent_tracker/ must never import dashboard, and must not add scripts imports."""
        core_root = REPO_ROOT / "intelligent_tracker"
        known_legacy_scripts_imports = {
            ("intelligent_tracker/detectors/onnx_detector.py", "scripts.download_models"),
        }
        violations: list[str] = []

        for py_file in core_root.rglob("*.py"):
            rel_path = py_file.relative_to(REPO_ROOT).as_posix()
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".", 1)[0]
                        if top in {"dashboard", "scripts"}:
                            violations.append(f"{rel_path}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    top = node.module.split(".", 1)[0]
                    if top == "dashboard" or (
                        top == "scripts" and (rel_path, node.module) not in known_legacy_scripts_imports
                    ):
                        violations.append(f"{rel_path}: from {node.module}")

        self.assertEqual(violations, [], f"Layering violations found: {violations}")

    def test_ctl_resolve_dashboard_url_precedence(self) -> None:
        """resolve_dashboard_url prioritizes explicit --url, TRACKER_DASHBOARD_URL, then APP_URL."""
        with patch.dict(os.environ, {"TRACKER_DASHBOARD_URL": "http://env-dash:9000/", "APP_URL": "http://app:8000"}, clear=True):
            self.assertEqual(resolve_dashboard_url("http://explicit:7000/"), "http://explicit:7000")
            self.assertEqual(resolve_dashboard_url(None), "http://env-dash:9000")

        with patch.dict(os.environ, {"APP_URL": "http://app:8000/"}, clear=True):
            self.assertEqual(resolve_dashboard_url(None), "http://app:8000")

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                resolve_dashboard_url(None)


if __name__ == "__main__":
    unittest.main()
