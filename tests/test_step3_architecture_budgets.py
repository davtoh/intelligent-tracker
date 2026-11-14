#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Step 3 Architecture Budgets, DI Purity, and Jinja2 Partial Assembly Tests.
"""

import os
import pathlib
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import dashboard.app as dashboard_app
from dashboard.app import app
from dashboard.camera_pool import CameraPool
from dashboard.dependencies import bind_app_state, clear_app_state, get_db
from dashboard.services.stream_pool_coordinator import StreamPoolCoordinator
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.world import WorldGraph

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

    def test_cameras_router_under_350_lines(self):
        """dashboard/routers/cameras.py stays under the 350-line WARN budget."""
        cam_router = ROOT_DIR / "dashboard" / "routers" / "cameras.py"
        lines = len(cam_router.read_text(encoding="utf-8").splitlines())
        self.assertLess(lines, 350, f"cameras.py is {lines} lines (expected < 350)")

    def test_jinja_env_cached_with_autoescape_and_fallback_db_reused(self):
        """App caches _jinja_env with autoescape and reuses/closes fallback TrackerDB."""
        self.assertTrue(dashboard_app._jinja_env.autoescape)

        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        mock_pool = MagicMock(spec=CameraPool)
        mock_pool.db_path = os.path.join(tmp_dir.name, "fallback.db")
        mock_pool.get_stream.return_value = None
        mock_pool.primary_stream = None
        bind_app_state(app, camera_pool=mock_pool, stream_manager=None, db=None)
        self.addCleanup(clear_app_state, app)

        db1 = get_db()
        db2 = get_db()
        self.assertIsInstance(db1, TrackerDB)
        self.assertIs(db1, db2)
        self.assertIsNotNone(db1._conn)

        clear_app_state(app)
        self.assertIsNone(db1._conn)

    def test_stream_pool_coordinator_starts_outside_lock_and_skips_errors(self):
        """restore_enabled_streams/start_all release lock before start() and skip error sources."""
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        db_path = os.path.join(tmp_dir.name, "coord.db")
        lock = threading.RLock()
        coord = StreamPoolCoordinator(
            db_path=db_path,
            base_config_path=str(ROOT_DIR / "configs" / "alert_demo.yaml"),
            world_graph=WorldGraph(),
            lock=lock,
        )

        observed_unlocked: list[bool] = []

        def _fake_start(self_mgr):
            probe_result: list[bool] = []

            def _probe():
                acquired = lock.acquire(blocking=False)
                if acquired:
                    lock.release()
                probe_result.append(acquired)

            t = threading.Thread(target=_probe)
            t.start()
            t.join(timeout=2.0)
            observed_unlocked.append(bool(probe_result and probe_result[0]))
            self_mgr.is_running = True

        mock_mgr_ok = MagicMock()
        mock_mgr_ok.is_running = False
        mock_mgr_ok.start.side_effect = lambda: _fake_start(mock_mgr_ok)

        mock_mgr_err = MagicMock()
        mock_mgr_err.is_running = False

        with (
            patch("dashboard.services.stream_pool_coordinator.StreamManager", side_effect=[mock_mgr_ok, mock_mgr_err]),
            patch(
                "dashboard.services.stream_pool_coordinator.CameraPathResolver.resolve_camera_source",
                side_effect=[("synthetic", {"status": "ok"}), ("missing.mp4", {"status": "error"})],
            ),
        ):
            coord.restore_enabled_streams(
                {
                    "cam_ok": {"name": "OK", "source": "synthetic", "enabled": True},
                    "cam_err": {"name": "Broken", "source": "missing.mp4", "enabled": True},
                },
                autostart=True,
            )

        self.assertEqual(observed_unlocked, [True])
        mock_mgr_ok.start.assert_called_once()
        mock_mgr_err.start.assert_not_called()

        # Verify start_all also runs outside lock for stopped healthy streams and skips error streams
        mock_mgr_ok.is_running = False
        observed_unlocked.clear()
        coord.start_all(
            {
                "cam_ok": {"name": "OK", "source": "synthetic", "enabled": True},
                "cam_err": {"name": "Broken", "source": "missing.mp4", "enabled": True},
            }
        )
        self.assertEqual(observed_unlocked, [True])
        self.assertEqual(mock_mgr_ok.start.call_count, 2)
        mock_mgr_err.start.assert_not_called()


if __name__ == "__main__":
    unittest.main()

