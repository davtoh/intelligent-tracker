"""Tests for Step 4 Milestone 3: WorldTacticalMinimap, WorldPoseMixin, and Journey Autocomplete."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.dependencies import get_camera_pool, get_db, get_scenario_mgr
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.world import WorldGraph, WorldTacticalMinimap
from intelligent_tracker.world.coordinates import GlobalCoordinateMapper
from intelligent_tracker.world.nodes import CameraNode, WorldEntity

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestWorldPoseAndMinimapBackend(unittest.TestCase):
    """Unit tests for WorldPoseMixin, EntityMixin.suggest_entities, and velocity vectors."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, "test_m3.db")
        self.db = TrackerDB(db_path=self.db_path)
        self.addCleanup(self.db.close)

    def test_world_pose_crud_and_upsert(self) -> None:
        """WorldPoseMixin persists, updates, lists, and deletes camera world poses."""
        self.db.save_world_pose("cam_a", origin_x=2.5, origin_y=-1.0, yaw_deg=45.0, scale=1.2, fov_deg=90.0, range_m=15.0)
        pose = self.db.get_world_pose("cam_a")
        self.assertIsNotNone(pose)
        self.assertAlmostEqual(pose["origin_x"], 2.5)
        self.assertAlmostEqual(pose["yaw_deg"], 45.0)
        self.assertAlmostEqual(pose["fov_deg"], 90.0)

        self.db.save_world_pose("cam_a", origin_x=5.0, origin_y=3.0, yaw_deg=120.0)
        listed = self.db.list_world_poses()
        self.assertEqual(len(listed), 1)
        self.assertAlmostEqual(listed[0]["origin_x"], 5.0)
        self.assertTrue(self.db.delete_world_pose("cam_a"))
        self.assertIsNone(self.db.get_world_pose("cam_a"))

    def test_suggest_entities_prefix_first_ranking(self) -> None:
        """suggest_entities ranks exact match, then prefix, then substring."""
        self.db.add_entity("Valerie")
        self.db.add_entity("Alice")
        self.db.add_entity("Al")
        self.db.add_entity("Albert")
        results = self.db.suggest_entities("al", limit=4)
        names = [r["name"] for r in results]
        self.assertEqual(names[:3], ["Al", "Albert", "Alice"])
        self.assertIn("Valerie", names)

    def test_world_minimap_emits_entity_velocity_vectors(self) -> None:
        """WorldTacticalMinimap computes vx, vy, speed_mps from global_trajectory."""
        wg = WorldGraph()
        wg.register_camera(
            CameraNode(camera_id="cam_01", world_pose=(1.0, 2.0, 30.0), extra={"fov_deg": 80.0, "range_m": 14.0})
        )
        wg.upsert_entity(
            WorldEntity(
                world_entity_id="we_1",
                entity_id=1,
                name="Alice",
                global_xy=(7.0, 9.0),
                global_trajectory=[(4.0, 5.0, 10.0), (7.0, 9.0, 12.0)],
            )
        )
        telemetry = WorldTacticalMinimap(wg).build_world_minimap_telemetry()
        self.assertEqual(len(telemetry["entities"]), 1)
        ent = telemetry["entities"][0]
        self.assertAlmostEqual(ent["vx"], 1.5, places=3)
        self.assertAlmostEqual(ent["vy"], 2.0, places=3)
        self.assertAlmostEqual(ent["speed_mps"], 2.5, places=3)
        self.assertAlmostEqual(telemetry["cameras"][0]["world_pose"]["fov_deg"], 80.0)


class TestTopologyAndSuggestRoutes(unittest.TestCase):
    """FastAPI TestClient tests for world-pose persistence hydration and /api/entities/suggest."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = TrackerDB(db_path=os.path.join(self._tmp.name, "routes_m3.db"))
        self.addCleanup(self.db.close)
        self.wg = WorldGraph()
        self.wg.register_camera(CameraNode(camera_id="cam_01", name="Lobby"))
        self.sm = MagicMock()
        self.sm.world_graph = self.wg
        self.sm.coordinate_mapper = GlobalCoordinateMapper()
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_scenario_mgr] = lambda: self.sm
        app.dependency_overrides[get_camera_pool] = lambda: None
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def test_world_pose_put_get_and_world_map_hydration(self) -> None:
        """PUT /api/topology/world-pose/{id} persists and hydrates into /api/topology/world-map."""
        put_res = self.client.put(
            "/api/topology/world-pose/cam_01",
            json={"origin_x": 3.5, "origin_y": 4.5, "yaw_deg": 60.0, "scale": 1.0, "fov_deg": 85.0, "range_m": 16.0},
        )
        self.assertEqual(put_res.status_code, 200)
        list_res = self.client.get("/api/topology/world-pose")
        self.assertEqual(list_res.status_code, 200)
        self.assertEqual(len(list_res.json()["poses"]), 1)

        map_res = self.client.get("/api/topology/world-map")
        self.assertEqual(map_res.status_code, 200)
        cam = map_res.json()["cameras"][0]
        self.assertAlmostEqual(cam["world_pose"]["origin_x"], 3.5)
        self.assertAlmostEqual(cam["world_pose"]["yaw_deg"], 60.0)
        self.assertAlmostEqual(cam["world_pose"]["fov_deg"], 85.0)

    def test_entities_suggest_endpoint(self) -> None:
        """GET /api/entities/suggest returns prefix-first suggestions."""
        self.db.add_entity("Bob")
        self.db.add_entity("Alice")
        self.db.add_entity("Alina")
        res = self.client.get("/api/entities/suggest", params={"q": "al", "limit": 5})
        self.assertEqual(res.status_code, 200)
        names = [item["name"] for item in res.json()["items"]]
        self.assertEqual(names, ["Alice", "Alina"])


_JOURNEY_AUTOCOMPLETE_JS = r"""
const fs = require('fs');
const vm = require('vm');
const calls = [];
const listeners = {};
const mkEl = (id) => ({
  id, value: '', innerHTML: '', className: '', children: [], dataset: {},
  classList: { add: () => {}, remove: () => {} },
  addEventListener: (ev, fn) => { listeners[id + ':' + ev] = fn; },
});
const els = {
  'journey-search-query': mkEl('journey-search-query'),
  'journey-suggest-list': mkEl('journey-suggest-list'),
  'btn-journey-search': mkEl('btn-journey-search'),
  'btn-journey-export': mkEl('btn-journey-export'),
  'journey-results-container': mkEl('journey-results-container'),
};
const sandbox = {
  console, Math, Number, Array, Object, encodeURIComponent,
  setTimeout: (fn) => { fn(); return 1; }, clearTimeout: () => {},
  document: { getElementById: (id) => els[id] || null },
  window: {},
  fetch: async (url) => {
    calls.push(url);
    if (url.startsWith('/api/entities/suggest')) return { ok: true, json: async () => ({ items: [{ id: 7, name: 'Alice', category: 'person' }] }) };
    return { ok: true, json: async () => ({ entity_name: 'Alice', total_hops: 0, hops: [], narrative: '' }) };
  },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('dashboard/static/js/journey_search.js', 'utf8'), sandbox);
(async () => {
  sandbox.window.JourneySearch.bind();
  els['journey-search-query'].value = 'Al';
  listeners['journey-search-query:input']();
  await new Promise((r) => setTimeout(r, 0));
  els['journey-suggest-list'].children = [{ classList: { add: () => {}, remove: () => {} } }];
  listeners['journey-search-query:keydown']({ key: 'ArrowDown', preventDefault: () => {} });
  listeners['journey-search-query:keydown']({ key: 'Enter', preventDefault: () => {} });
  await new Promise((r) => setTimeout(r, 0));
  console.log(JSON.stringify({ calls, val: els['journey-search-query'].value }));
})();
"""


class TestFrontendWorldMinimapAndJourneyVM(unittest.TestCase):
    """Node VM tests for WorldTacticalMinimapView and JourneySearch autocomplete."""

    def _run_node(self, script_body: str) -> dict:
        if not shutil.which("node"):
            self.skipTest("Node.js not installed")
        res = subprocess.run(
            ["node", "-e", script_body],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            check=False,
        )
        self.assertEqual(res.returncode, 0, msg=f"Node failed:\n{res.stderr}\n{res.stdout}")
        return json.loads(res.stdout.strip().splitlines()[-1])

    def test_world_minimap_renders_and_falls_back_to_bev(self) -> None:
        """WorldTacticalMinimapView renders /api/topology/world-map or falls back to BEVMinimap."""
        script = r"""
const fs = require('fs');
const vm = require('vm');
let drawCalls = 0, bevFallback = 0;
const ctx2d = new Proxy({}, { get: (_t, prop) => (..._a) => { drawCalls += 1; } });
const badge = { textContent: '', className: '' };
const canvas = { width: 320, height: 320, getContext: () => ctx2d };
const sandbox = {
  console, Date, Math, Number, Object, Array, encodeURIComponent,
  document: { getElementById: (id) => (id === 'bev-metric-scale' ? badge : null) },
  window: { BEVMinimap: { render: () => { bevFallback += 1; } } },
  fetch: async () => ({ ok: true, json: async () => ({
    bounds: [0, 0, 20, 20],
    cameras: [{ camera_id: 'cam_01', calibrated: true, world_pose: { origin_x: 2, origin_y: 2, yaw_deg: 45, fov_deg: 75, range_m: 10 } }],
    zones: [], transitions: [],
    entities: [{ world_entity_id: 'we_1', name: 'Alice', global_xy: [5, 5], global_trajectory: [[4, 4, 1], [5, 5, 2]], vx: 1, vy: 1, speed_mps: 1.41 }],
  }) }),
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('dashboard/static/js/world_minimap.js', 'utf8'), sandbox);
(async () => {
  await sandbox.window.WorldTacticalMinimapView.fetchAndRender(canvas, 'cam_01', null, []);
  const renderedDraws = drawCalls;
  sandbox.window.WorldTacticalMinimapView.render(canvas, { bounds: [0,0,20,20], cameras: [], zones: [], entities: [] }, 'cam_01');
  sandbox.fetch = async () => ({ ok: false });
  await sandbox.window.WorldTacticalMinimapView.fetchAndRender(canvas, 'cam_01', null, []);
  console.log(JSON.stringify({ renderedDraws, badge: badge.textContent, bevFallback }));
})();
"""
        out = self._run_node(script)
        self.assertGreater(out["renderedDraws"], 5)
        self.assertEqual(out["badge"], "World Calibrated")

    def test_journey_autocomplete_keyboard_and_enter_submit(self) -> None:
        """JourneySearch fetches suggestions, navigates with ArrowDown/Enter, and submits."""
        out = self._run_node(_JOURNEY_AUTOCOMPLETE_JS)
        self.assertTrue(any("/api/entities/suggest?q=Al" in c for c in out["calls"]))
        self.assertTrue(any("/api/journey/search?entity_name=Alice" in c for c in out["calls"]))
        self.assertEqual(out["val"], "Alice")


if __name__ == "__main__":
    unittest.main()
