#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Step 3 Architecture Budgets, DI Purity, and Jinja2 Partial Assembly Tests.
"""

import os
import pathlib
import tempfile
import unittest

from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.camera_pool import CameraPool
from dashboard.dependencies import bind_app_state, clear_app_state
from intelligent_tracker.database import TrackerDB

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR / "dashboard" / "static"

FROZEN_LEGACY_FILES = {
    "intelligent_tracker/high_objects.py",
}

EXPECTED_TABS = [
    "live",
    "videos",
    "gallery",
    "timeline",
    "analytics",
    "alerts",
    "studio",
    "journey",
    "review",
]

EXPECTED_MODALS = [
    "entity_modals.html",
    "camera_modals.html",
    "studio_modals.html",
    "video_modals.html",
]

EXPECTED_MODAL_IDS = [
    "modal-tag-entity",
    "modal-snapshot-view",
    "modal-camera-manager",
    "modal-camera-diagnostics",
    "modal-backup-manager",
    "modal-universal-enrollment",
    "modal-descriptor-versions",
    "modal-review-reassign",
    "modal-studio-zone",
    "modal-studio-tripwire",
    "modal-studio-homography",
    "modal-studio-transition",
    "modal-quick-enroll-entity",
    "modal-video-batch-analyze",
    "modal-feed-promotion",
]


class TestStep3ArchitectureBudgets(unittest.TestCase):
    """Verify Step 3 modularity ceilings, DI hygiene, and GET / partial rendering."""

    def test_zero_non_frozen_runtime_files_at_or_above_500_lines(self):
        """Every active runtime .py/.html/.js/.css file stays under 500 lines."""
        violations: list[str] = []
        extensions = {".py", ".html", ".js", ".css"}
        for base in ("intelligent_tracker", "dashboard"):
            base_path = ROOT_DIR / base
            for path in base_path.rglob("*"):
                if not path.is_file() or "__pycache__" in path.parts:
                    continue
                if path.suffix not in extensions:
                    continue
                rel = path.relative_to(ROOT_DIR).as_posix()
                if rel in FROZEN_LEGACY_FILES:
                    continue
                line_count = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
                if line_count >= 500:
                    violations.append(f"{rel}: {line_count} lines")
        self.assertEqual(violations, [], f"Files >= 500 lines: {violations}")

    def test_html_shell_and_partials_line_budgets(self):
        """index.html and extracted tab/modal partials meet Step 3 line ceilings."""
        index_lines = len((STATIC_DIR / "index.html").read_text(encoding="utf-8").splitlines())
        self.assertLess(index_lines, 180, f"index.html is {index_lines} lines (expected < 180)")

        for tab_name in EXPECTED_TABS:
            tab_path = STATIC_DIR / "partials" / "tabs" / f"{tab_name}.html"
            self.assertTrue(tab_path.is_file(), f"Missing tab partial: {tab_path}")
            tab_lines = len(tab_path.read_text(encoding="utf-8").splitlines())
            self.assertLess(tab_lines, 220, f"{tab_path.name} is {tab_lines} lines (expected < 220)")

        for modal_file in EXPECTED_MODALS:
            modal_path = STATIC_DIR / "partials" / "modals" / modal_file
            self.assertTrue(modal_path.is_file(), f"Missing modal partial: {modal_path}")
            modal_lines = len(modal_path.read_text(encoding="utf-8").splitlines())
            self.assertLess(modal_lines, 240, f"{modal_path.name} is {modal_lines} lines (expected < 240)")

    def test_zero_sys_modules_dashboard_app_usage(self):
        """Dashboard Python modules must not inspect sys.modules for dashboard.app."""
        offenders: list[str] = []
        for path in (ROOT_DIR / "dashboard").rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if 'sys.modules.get("dashboard.app")' in text or 'sys.modules["dashboard.app"]' in text:
                offenders.append(path.relative_to(ROOT_DIR).as_posix())
        self.assertEqual(offenders, [], f"Forbidden sys.modules dashboard.app lookups: {offenders}")

    def test_get_index_renders_all_partials_synchronously(self):
        """GET / renders Jinja2 index.html with all 9 tabs and 15 modals assembled."""
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        db_path = os.path.join(tmp_dir.name, "test_step3_ui.db")
        cam_cfg = os.path.join(tmp_dir.name, "cameras.json")
        db = TrackerDB(db_path)
        self.addCleanup(db.close)
        pool = CameraPool(config_file=cam_cfg, db_path=db_path, autostart=False)
        self.addCleanup(pool.stop_all)
        bind_app_state(app, camera_pool=pool, stream_manager=pool.primary_stream, db=db)
        self.addCleanup(clear_app_state, app)

        client = TestClient(app)
        res = client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.text
        self.assertNotIn("{% include", html)
        for tab_name in EXPECTED_TABS:
            self.assertIn(f'id="tab-{tab_name}"', html)
        for modal_id in EXPECTED_MODAL_IDS:
            self.assertIn(f'id="{modal_id}"', html)


if __name__ == "__main__":
    unittest.main()

