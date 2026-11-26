"""Tests for Step 4 M3: stale camera pruning, remove_camera pose cleanup, and minimap interactions."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.camera_pool import CameraPool
from dashboard.dependencies import get_camera_pool, get_db, get_scenario_mgr
from dashboard.routers.topology import router as topology_router
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.scenarios import ScenarioManager
from intelligent_tracker.world import GlobalCoordinateMapper, WorldGraph

REPO_ROOT = Path(__file__).resolve().parents[1]


_NODE_HARNESS_HEAD = """
const fs = require('fs'), vm = require('vm'), calls = [], listeners = {};
const inputs = { 'world-pose-x': { value: '' }, 'world-pose-y': { value: '' }, 'world-pose-yaw': { value: '' }, 'world-pose-fov': { value: '' }, 'world-pose-range': { value: '' } };
const badge = { textContent: '', className: '' };
const selectEl = { value: 'cam_01', options: [{ value: 'cam_01' }, { value: 'cam_02' }], dispatched: [], dispatchEvent: (ev) => selectEl.dispatched.push(ev.type) };
const canvas = {
  width: 320, height: 320, dataset: {}, style: {},
  getBoundingClientRect: () => ({ left: 0, top: 0, width: 320, height: 320 }),
  getContext: () => new Proxy({}, { get: () => () => {} }),
  addEventListener: (ev, fn) => { listeners[ev] = fn; },
};
const worldData = {
  bounds: [0, 0, 20, 20], zones: [], transitions: [], entities: [],
  cameras: [
    { camera_id: 'cam_01', calibrated: true, world_pose: { origin_x: 5, origin_y: 5, yaw_deg: 0, fov_deg: 60, range_m: 6 } },
    { camera_id: 'cam_02', calibrated: false, world_pose: { origin_x: 15, origin_y: 15, yaw_deg: 90, fov_deg: 60, range_m: 6 } },
  ],
};
const sandbox = {
  console, Date, Math, Number, Object, Array, encodeURIComponent, Event: function(t) { this.type = t; },
  document: { getElementById: (id) => id === 'bev-minimap-canvas' ? canvas : (id === 'studio-camera-select' ? selectEl : (id === 'bev-metric-scale' ? badge : (inputs[id] || null))) },
  window: {},
  fetch: async (url, opts) => {
    calls.push({ url, method: opts?.method || 'GET', body: opts?.body ? JSON.parse(opts.body) : null });
    return { ok: true, json: async () => worldData };
  },
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('dashboard/static/js/world_minimap.js', 'utf8'), sandbox);
vm.runInContext(fs.readFileSync('dashboard/static/js/world_minimap_interactions.js', 'utf8'), sandbox);
"""


def _make_node_script(actions_js: str) -> str:
    return f"""{_NODE_HARNESS_HEAD}
(async () => {{
  let activeCam = 'cam_01';
  sandbox.WorldMinimapInteractions.bind(() => activeCam);
  await sandbox.WorldTacticalMinimapView.fetchAndRender(canvas, activeCam, null, []);
  {actions_js}
}})();
"""


class TestWorldMapPruningAndPoseCleanup(unittest.TestCase):
    """Backend tests for stale camera pruning and CameraPool.remove_camera pose deletion."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, "tracker.db")
        self.db = TrackerDB(self.db_path)
        self.addCleanup(self.db.close)
        self.mapper = GlobalCoordinateMapper()
        self.wg = WorldGraph(coordinate_mapper=self.mapper)
        self.sm = ScenarioManager(
            config_path=os.path.join(self._tmp.name, "scenarios.yaml"),
            db=self.db,
            world_graph=self.wg,
            coordinate_mapper=self.mapper,
        )

    def _build_client(self, pool_obj) -> TestClient:
        app = FastAPI()
        app.include_router(topology_router)
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_scenario_mgr] = lambda: self.sm
        app.dependency_overrides[get_camera_pool] = lambda: pool_obj
        return TestClient(app)

    def test_world_map_prunes_stale_cameras_when_pool_present(self) -> None:
        """GET /api/topology/world-map excludes deleted cameras absent from pool.camera_configs."""
        self.db.save_world_pose("cam_active", 1.0, 2.0, 45.0, 1.0, 75.0, 10.0)
        self.db.save_world_pose("cam_deleted", 8.0, 9.0, 90.0, 1.0, 75.0, 10.0)
        pool_stub = SimpleNamespace(camera_configs={"cam_active": {"enabled": False}}, world_graph=self.wg)
        client = self._build_client(pool_stub)
        res = client.get("/api/topology/world-map")
        self.assertEqual(res.status_code, 200)
        cam_ids = [c["camera_id"] for c in res.json()["cameras"]]
        self.assertEqual(cam_ids, ["cam_active"])
        self.assertNotIn("cam_deleted", self.wg.snapshot()["cameras"])

    def test_world_map_preserves_poses_when_pool_is_none(self) -> None:
        """GET /api/topology/world-map preserves DB poses when pool dependency is None."""
        self.db.save_world_pose("cam_only_db", 3.0, 4.0, 0.0, 1.0, 75.0, 12.0)
        client = self._build_client(None)
        res = client.get("/api/topology/world-map")
        self.assertEqual(res.status_code, 200)
        self.assertEqual([c["camera_id"] for c in res.json()["cameras"]], ["cam_only_db"])

    def test_remove_camera_deletes_persisted_world_pose(self) -> None:
        """CameraPool.remove_camera deletes the camera's row from camera_world_poses."""
        cfg_path = os.path.join(self._tmp.name, "cameras.json")
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump({"cam_01": {"name": "Cam 1", "source": "synthetic", "enabled": False}}, fh)
        pool = CameraPool(config_file=cfg_path, db_path=self.db_path, autostart=False)
        self.addCleanup(pool.stop_all)
        pool._db.save_world_pose("cam_01", 2.0, 3.0, 30.0, 1.0, 75.0, 12.0)
        self.assertIsNotNone(pool._db.get_world_pose("cam_01"))
        self.assertTrue(pool.remove_camera("cam_01"))
        self.assertIsNone(pool._db.get_world_pose("cam_01"))


class TestMinimapInteractionsVM(unittest.TestCase):
    """Node VM tests for WorldMinimapInteractions pointer hit-testing and drag PUT."""

    def _run_node(self, actions_js: str) -> dict:
        if not shutil.which("node"):
            self.skipTest("Node.js not installed")
        res = subprocess.run(
            ["node", "-e", _make_node_script(actions_js)],
            cwd=str(REPO_ROOT),
            capture_output=True, text=True, encoding="utf-8", timeout=15, check=False,
        )
        self.assertEqual(res.returncode, 0, msg=f"Node failed:\n{res.stderr}\n{res.stdout}")
        return json.loads(res.stdout.strip().splitlines()[-1])

    def test_cone_click_focuses_camera_in_studio_select(self) -> None:
        """Clicking a camera FOV cone focuses that camera in #studio-camera-select."""
        out = self._run_node("""
          const [tx, ty] = sandbox.WorldTacticalMinimapView.toCanvasXY(15, 18, [0, 0, 20, 20], 320, 320, 20);
          listeners.mousedown({ clientX: tx, clientY: ty });
          await listeners.mouseup({});
          console.log(JSON.stringify({ selected: selectEl.value, dispatched: selectEl.dispatched }));
        """)
        self.assertEqual(out["selected"], "cam_02")
        self.assertEqual(out["dispatched"], ["change"])

    def test_origin_drag_syncs_inputs_suppresses_snapback_and_commits_put(self) -> None:
        """Dragging origin handle updates origin_x/y, suppresses 250ms loop snap-back, and PUTs."""
        out = self._run_node("""
          const [ox, oy] = sandbox.WorldTacticalMinimapView.toCanvasXY(5, 5, [0, 0, 20, 20], 320, 320, 20);
          const [nx, ny] = sandbox.WorldTacticalMinimapView.toCanvasXY(8, 9, [0, 0, 20, 20], 320, 320, 20);
          listeners.mousedown({ clientX: ox, clientY: oy });
          listeners.mousemove({ clientX: nx, clientY: ny });
          const fetchesBeforeLoop = calls.length;
          await sandbox.WorldTacticalMinimapView.fetchAndRender(canvas, activeCam, null, []);
          const fetchesDuringDrag = calls.length;
          const liveX = inputs['world-pose-x'].value;
          const liveY = inputs['world-pose-y'].value;
          await listeners.mouseup({});
          const putCall = calls.find((c) => c.method === 'PUT');
          console.log(JSON.stringify({ fetchesBeforeLoop, fetchesDuringDrag, liveX, liveY, putCall }));
        """)
        self.assertEqual(out["fetchesBeforeLoop"], out["fetchesDuringDrag"])
        self.assertAlmostEqual(float(out["liveX"]), 8.0, places=1)
        self.assertAlmostEqual(float(out["liveY"]), 9.0, places=1)
        self.assertEqual(out["putCall"]["url"], "/api/topology/world-pose/cam_01")
        self.assertAlmostEqual(out["putCall"]["body"]["origin_x"], 8.0, places=1)

    def test_tip_drag_updates_yaw_and_range_and_commits_put(self) -> None:
        """Dragging yaw/range tip handle updates yaw_deg and range_m and commits PUT."""
        out = self._run_node("""
          const [ox, oy] = sandbox.WorldTacticalMinimapView.toCanvasXY(5, 5, [0, 0, 20, 20], 320, 320, 20);
          const tipX = ox + 6 * ((320 - 40) / 20);
          const [nx, ny] = sandbox.WorldTacticalMinimapView.toCanvasXY(5, 15, [0, 0, 20, 20], 320, 320, 20);
          listeners.mousedown({ clientX: tipX, clientY: oy });
          listeners.mousemove({ clientX: nx, clientY: ny });
          const yaw = inputs['world-pose-yaw'].value;
          const range = inputs['world-pose-range'].value;
          await listeners.mouseup({});
          const putCall = calls.find((c) => c.method === 'PUT');
          console.log(JSON.stringify({ yaw, range, putCall }));
        """)
        self.assertAlmostEqual(float(out["yaw"]), 90.0, places=1)
        self.assertAlmostEqual(float(out["range"]), 10.0, places=1)
        self.assertAlmostEqual(out["putCall"]["body"]["yaw_deg"], 90.0, places=1)
        self.assertAlmostEqual(out["putCall"]["body"]["range_m"], 10.0, places=1)


if __name__ == "__main__":
    unittest.main()
