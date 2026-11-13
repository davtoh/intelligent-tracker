#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit & Integration Tests for Milestone 2:
CameraPool Decomposition, FastAPI app.state DI & dependency_overrides.
"""

import ast
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.camera_pool import CameraPool
from dashboard.dependencies import (
    bind_app_state,
    clear_app_state,
    get_camera_pool,
    get_db,
    get_lifecycle_manager,
    get_scenario_mgr,
    get_stream_manager,
)
from dashboard.services.camera_config_store import CameraConfigStore
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.scenarios import ScenarioManager

REPO_ROOT = Path(__file__).resolve().parent.parent


def _count_class_methods(path: Path, class_name: str) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return sum(
                1 for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
    raise AssertionError(f"Class {class_name} not found in {path}")


class TestDashboardDIAndCameraPoolSplit(unittest.TestCase):
    """Verify FastAPI app.state DI, dependency_overrides, and CameraPool split invariants."""

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory(prefix="tracker_di_test_")
        self.addCleanup(self._tmp_dir.cleanup)
        self.config_file = os.path.join(self._tmp_dir.name, "cameras.json")
        self.db_path = os.path.join(self._tmp_dir.name, "tracker.db")
        self.scenarios_yaml = os.path.join(self._tmp_dir.name, "scenarios.yaml")

    def test_dependencies_zero_sys_modules_ast(self) -> None:
        """dashboard/dependencies.py must contain zero sys.modules lookups."""
        dep_path = REPO_ROOT / "dashboard" / "dependencies.py"
        src = dep_path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(dep_path))

        self.assertNotIn("sys.modules", src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertNotIn("sys", [alias.name for alias in node.names])

        app_src = (REPO_ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("get_scenario_manager", app_src)

    def test_camera_pool_modularity_budgets(self) -> None:
        """CameraPool facade and extracted services must satisfy modularity budgets."""
        pool_path = REPO_ROOT / "dashboard" / "camera_pool.py"
        store_path = REPO_ROOT / "dashboard" / "services" / "camera_config_store.py"
        coord_path = REPO_ROOT / "dashboard" / "services" / "stream_pool_coordinator.py"

        self.assertLess(len(pool_path.read_text(encoding="utf-8").splitlines()), 250)
        self.assertLess(len(store_path.read_text(encoding="utf-8").splitlines()), 180)
        self.assertLess(len(coord_path.read_text(encoding="utf-8").splitlines()), 240)

        self.assertLessEqual(_count_class_methods(pool_path, "CameraPool"), 10)
        self.assertLessEqual(_count_class_methods(store_path, "CameraConfigStore"), 8)
        self.assertLessEqual(_count_class_methods(coord_path, "StreamPoolCoordinator"), 10)

    def test_routers_no_direct_camera_pool_instantiation(self) -> None:
        """Routers must resolve CameraPool via Depends(get_camera_pool), never instantiate it."""
        for rel in (
            "dashboard/routers/cameras.py",
            "dashboard/routers/camera_diagnostics.py",
            "dashboard/routers/videos.py",
        ):
            path = REPO_ROOT / rel
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func_name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                    self.assertNotEqual(func_name, "CameraPool", f"Direct CameraPool() call in {rel}")

    def test_lifespan_populates_and_clears_app_state(self) -> None:
        """FastAPI lifespan binds camera_pool, stream_manager, scenario_manager, lifecycle_manager, and db."""
        mock_db = MagicMock(spec=TrackerDB)
        mock_sm = MagicMock()
        mock_sm.db = mock_db
        mock_pool = MagicMock(spec=CameraPool)
        mock_pool.primary_stream = mock_sm
        mock_pool.streams = {"cam_01": mock_sm}
        mock_pool.world_graph = MagicMock()
        mock_scen = MagicMock(spec=ScenarioManager)
        mock_lm = MagicMock()

        with (
            patch("dashboard.app.CameraPool", return_value=mock_pool),
            patch("dashboard.app.ScenarioManager", return_value=mock_scen),
            patch("dashboard.app.StreamLifecycleManager", return_value=mock_lm),
            patch("dashboard.app.async_shutdown_pool") as mock_shutdown,
            patch("dashboard.app.install_shutdown_handlers"),
            patch("dashboard.app.start_parent_watchdog"),
            patch("dashboard.app.stop_parent_watchdog"),
        ):
            with TestClient(app):
                self.assertIs(app.state.camera_pool, mock_pool)
                self.assertIs(app.state.stream_manager, mock_sm)
                self.assertIs(app.state.scenario_manager, mock_scen)
                self.assertIs(app.state.lifecycle_manager, mock_lm)
                self.assertIs(app.state.db, mock_db)
                mock_scen.apply_to_stream_manager.assert_called_once_with(mock_sm)

            mock_lm.stop_sampler.assert_called_once()
            mock_shutdown.assert_awaited_once_with(mock_pool)
            self.assertIsNone(app.state.camera_pool)
            self.assertIsNone(app.state.stream_manager)
            self.assertIsNone(app.state.scenario_manager)
            self.assertIsNone(app.state.lifecycle_manager)
            self.assertIsNone(app.state.db)

    def test_app_dependency_overrides_camera_pool_and_db(self) -> None:
        """app.dependency_overrides cleanly substitutes get_camera_pool and get_db."""
        db = TrackerDB(self.db_path)
        self.addCleanup(db.close)
        eid = db.add_entity("DI Test VIP", category="vip")
        db.add_sighting(entity_id=eid, track_id=9, source="cam_di", zone_id="lobby")

        pool = CameraPool(config_file=self.config_file, db_path=self.db_path, autostart=False)
        self.addCleanup(pool.stop_all)

        app.dependency_overrides[get_camera_pool] = lambda: pool
        app.dependency_overrides[get_db] = lambda: db
        self.addCleanup(lambda: app.dependency_overrides.clear())

        client = TestClient(app)
        cams_resp = client.get("/api/cameras")
        self.assertEqual(cams_resp.status_code, 200)
        self.assertEqual(cams_resp.json()[0]["id"], "cam_01")

        journey_resp = client.get(f"/api/journey/search?entity_id={eid}")
        self.assertEqual(journey_resp.status_code, 200)
        self.assertEqual(journey_resp.json()["entity_name"], "DI Test VIP")

    def test_app_state_routing_and_missing_pool_503(self) -> None:
        """Routes resolve app.state without module globals and return 503 when pool is absent."""
        clear_app_state(app)
        client = TestClient(app)

        resp_503 = client.post(
            "/api/cameras",
            json={"id": "cam_uninit", "name": "Uninit", "source": "synthetic"},
        )
        self.assertEqual(resp_503.status_code, 503)

        db = TrackerDB(self.db_path)
        self.addCleanup(db.close)
        pool = CameraPool(config_file=self.config_file, db_path=self.db_path, autostart=False)
        self.addCleanup(pool.stop_all)
        scen_mgr = ScenarioManager(config_path=self.scenarios_yaml, db=db)

        bind_app_state(
            app,
            camera_pool=pool,
            stream_manager=pool.primary_stream,
            scenario_manager=scen_mgr,
            db=db,
        )
        self.addCleanup(lambda: clear_app_state(app))

        self.assertEqual(client.get("/api/cameras").status_code, 200)
        self.assertEqual(client.get("/api/cameras/diagnostics/summary").status_code, 200)
        self.assertEqual(client.get("/api/scenarios").status_code, 200)
        self.assertEqual(client.get("/api/rsac/categories").status_code, 200)
        self.assertEqual(client.get("/status").status_code, 200)

        # Standalone no-request fallback checks
        self.assertIs(get_camera_pool(), pool)
        self.assertIs(get_stream_manager(), pool.primary_stream)
        self.assertIs(get_scenario_mgr(), scen_mgr)
        self.assertIsNotNone(get_lifecycle_manager())

    def test_camera_config_store_stream_source_env_bootstrap(self) -> None:
        """CameraConfigStore honors STREAM_SOURCE env var when seeding default camera."""
        store = CameraConfigStore(config_file=self.config_file)
        with patch.dict(os.environ, {"STREAM_SOURCE": "0"}, clear=False):
            configs, seeded = store.load_cameras()
        self.assertTrue(seeded)
        self.assertEqual(configs["cam_01"]["source"], "0")
        self.assertEqual(configs["cam_01"]["type"], "usb")
        self.assertEqual(configs["cam_01"]["detector"], "yolov8")


if __name__ == "__main__":
    unittest.main()

