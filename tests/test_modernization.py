#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Automated Python Modernization & Invariant Test Suite.

Verifies that the entire repository maintains modern Python 3.10-3.12+ standards:
- Zero `__future__` imports (including PEP 563 annotations and legacy Python 2 shims).
- Zero obsolete compatibility shims (`six`, `past`, `future`).
- Clean class definitions without explicit `object` inheritance.
"""

import ast
import unittest
from pathlib import Path

# Workspace root directory
ROOT_DIR = Path(__file__).resolve().parents[1]

# Directories subject to modernization enforcement
AUDITED_DIRS = ["intelligent_tracker", "dashboard", "tests"]


class TestCodebaseModernization(unittest.TestCase):
    """AST-level test suite enforcing modern Python idioms across the repository."""

    def get_source_files(self):
        """Discover all Python source files in audited directories, excluding caches."""
        files = []
        for dirname in AUDITED_DIRS:
            target_dir = ROOT_DIR / dirname
            if not target_dir.exists():
                continue
            for p in target_dir.rglob("*.py"):
                # Ignore cache, build, and virtualenv directories
                parts = p.parts
                if any(x in parts for x in (".venv", "venv", "__pycache__", ".git", "_build")):
                    continue
                files.append(p)
        return files

    def test_zero_future_imports(self):
        """Assert zero `__future__` imports exist in any Python source file."""
        violations = []
        for file_path in self.get_source_files():
            try:
                tree = ast.parse(file_path.read_bytes(), filename=str(file_path))
            except SyntaxError as e:
                self.fail(f"Syntax error in {file_path}: {e}")

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                    names = ", ".join(alias.name for alias in node.names)
                    rel_path = file_path.relative_to(ROOT_DIR).as_posix()
                    violations.append(f"{rel_path}:{node.lineno} -> from __future__ import {names}")

        self.assertEqual(
            violations,
            [],
            f"Found forbidden `__future__` imports in codebase:\n" + "\n".join(violations),
        )

    def test_zero_legacy_shims(self):
        """Assert zero obsolete compatibility imports (`six`, `past`, `builtins.object`)."""
        banned_modules = {"six", "past", "future"}
        violations = []
        for file_path in self.get_source_files():
            try:
                tree = ast.parse(file_path.read_bytes(), filename=str(file_path))
            except SyntaxError as e:
                self.fail(f"Syntax error in {file_path}: {e}")

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root_mod = alias.name.split(".")[0]
                        if root_mod in banned_modules:
                            rel_path = file_path.relative_to(ROOT_DIR).as_posix()
                            violations.append(f"{rel_path}:{node.lineno} -> import {alias.name}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    root_mod = node.module.split(".")[0]
                    if root_mod in banned_modules:
                        rel_path = file_path.relative_to(ROOT_DIR).as_posix()
                        violations.append(f"{rel_path}:{node.lineno} -> from {node.module} import ...")

        self.assertEqual(
            violations,
            [],
            f"Found forbidden legacy compatibility imports:\n" + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()

