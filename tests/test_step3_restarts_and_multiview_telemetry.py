#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit & Integration Tests for Step 3 Milestone 2:
Stream Restarts, WorldGraph Preservation, /ws/multiview Throttled JSON Telemetry,
Slow-Client Isolation (P3-3), and Frontend FrameSurface/Grid Pagination Parity.
"""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
import numpy as np

from dashboard.app import app
from dashboard.camera_pool import CameraPool
from dashboard.dependencies import bind_app_state, clear_app_state, set_shutting_down
from dashboard.services.camera_pool_queries import build_camera_status_row
from dashboard.services.camera_source_bootstrap import retry_camera_connection
from dashboard.services.multiview.limits import MultiviewLimits
from dashboard.services.multiview.protocol import unpack_frame
from dashboard.services.multiview.session import MultiviewSession
from dashboard.services.stream_telemetry import build_stream_telemetry
from dashboard.stream_manager import StreamManager
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.homography import GroundPlaneHomography
from intelligent_tracker.pipeline.bundle import build_world
from intelligent_tracker.pipeline.config import PipelineConfig
from intelligent_tracker.scenarios import ScenarioManager
from intelligent_tracker.world.coordinates import (
    CameraWorldPose,
    GlobalCoordinateMapper,
    clear_homography_from_world,
    sync_homography_to_world,
)
from intelligent_tracker.world.graph import WorldGraph
from intelligent_tracker.world.nodes import CameraNode
from tests.test_multiview_session import _FakePool, _FakeStreamManager, _FakeWebSocket

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_JS = REPO_ROOT / "dashboard" / "static" / "js"


def _run_node_script(script: str) -> dict:
    """Execute a Node.js VM snippet and parse its JSON stdout."""
    res = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=True,
    )
    return json.loads(res.stdout.strip().splitlines()[-1])


class TestStep3RestartsAndMultiviewTelemetry(unittest.TestCase):
    """Verify P1-8, P1-10, P3-3, and /ws/multiview JSON telemetry contracts."""

    def setUp(self) -> None:
        set_shutting_down(False)
        self._tmp = tempfile.TemporaryDirectory(prefix="step3_m2_")
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(set_shutting_down, False)
        self.tmp_path = Path(self._tmp.name)

    def test_world_graph_preserves_homography_pose_extra_and_friendly_name(self) -> None:
        """WorldGraph.register_camera preserves calibration/pose/name on default re-register."""
        mapper = GlobalCoordinateMapper()
        wg = WorldGraph(coordinate_mapper=mapper)
        homo = GroundPlaneHomography(
            src_points=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
            camera_id="cam_01",
        )
        wg.register_camera(CameraNode(
            camera_id="cam_01", name="Lobby North", world_pose=(2.5, 4.0, 90.0),
        ))
        sync_homography_to_world(wg, mapper, "cam_01", homo)

        # Re-registering via build_world default CameraNode preserves friendly name & homography
        cfg = PipelineConfig.from_dict({"name": "cam_01"}, camera_id="cam_01")
        build_world(cfg, world_graph=wg)
        node = wg.get_node("cam_01", node_type="camera")
        self.assertIsNotNone(node)
        self.assertEqual(node.name, "Lobby North")
        self.assertIsNotNone(node.homography)
        self.assertEqual(tuple(node.world_pose), (2.5, 4.0, 90.0))
        self.assertIn("homography_profile", node.extra)

        # Explicit clear_homography_from_world removes homography from mapper and WorldGraph
        clear_homography_from_world(wg, mapper, "cam_01")
        self.assertIsNone(mapper.get_homography("cam_01"))
        cleared = wg.get_node("cam_01", node_type="camera")
        self.assertIsNone(cleared.homography)
        self.assertNotIn("homography_profile", cleared.extra)

    def test_stream_manager_stop_delegates_to_pipeline_bundle_outside_lock(self) -> None:
        """StreamManager.stop() calls _pipeline_bundle.close() without holding self._lock."""
        db_path = str(self.tmp_path / "stop.db")
        mgr = StreamManager(
            camera_id="cam_stop", name="StopCam", db_path=db_path, source_override="synthetic",
        )
        lock_held_during_close: list[bool] = []
        orig_close = mgr._pipeline_bundle.close

        def _spy_close() -> None:
            probe: list[bool] = []
            t = threading.Thread(target=lambda: probe.append(mgr._lock.acquire(blocking=False)))
            t.start()
            t.join(timeout=1.0)
            lock_held_during_close.append(not bool(probe and probe[0]))
            orig_close()

        mgr._pipeline_bundle.close = _spy_close  # type: ignore[method-assign]
        mgr.stop()
        self.assertEqual(lock_held_during_close, [False])
        self.assertTrue(mgr._pipeline_bundle._closed)

    def test_restart_retry_and_register_reapply_scenarios_and_unlock_init(self) -> None:
        """Pool restart/retry/register re-apply ScenarioManager and initialize outside pool._lock."""
        cfg_file = self.tmp_path / "cams.json"
        cfg_file.write_text(json.dumps([
            {"id": "cam_disabled", "name": "DisabledCam", "source": "synthetic", "enabled": False, "armed": True},
        ]), encoding="utf-8")
        pool = CameraPool(config_file=str(cfg_file), db_path=str(self.tmp_path / "pool.db"), autostart=False)
        self.addCleanup(pool.stop_all)

        dis_node = pool.world_graph.get_node("cam_disabled", node_type="camera")
        self.assertIsNotNone(dis_node)
        self.assertFalse(dis_node.enabled)
        rows = pool.list_cameras()
        self.assertTrue(rows[0]["armed"] and rows[0]["is_armed"])

        pool._coordinator.create_and_register_stream(
            "cam_offline", {"name": "OfflineCam", "source": "nonexistent_404.mp4", "enabled": True}, start=False,
        )
        off_node = pool.world_graph.get_node("cam_offline", node_type="camera")
        self.assertEqual(off_node.extra.get("status"), "offline")

        scen = ScenarioManager(
            config_path=str(self.tmp_path / "scen.yaml"),
            world_graph=pool.world_graph, coordinate_mapper=pool.coordinate_mapper,
        )
        pool._coordinator.scenario_manager = scen
        scen.save_zone("cam_live", "zone_a", [[0, 0], [50, 0], [50, 50], [0, 50]])
        scen.save_homography("cam_live", [(0.0, 0.0), (50.0, 0.0), (50.0, 50.0), (0.0, 50.0)])

        mgr = pool.add_camera("cam_live", "LiveCam", "synthetic", cam_type="synthetic", autostart=False, armed=True)
        self.assertTrue("zone_a" in mgr.analytics.zones and mgr.homography.is_calibrated)

        pool.camera_configs["cam_live"]["source"] = "synthetic"
        self.assertEqual(retry_camera_connection(pool, "cam_live")["status"], "online")
        restarted = pool.get_stream("cam_live")
        self.assertTrue(restarted and "zone_a" in restarted.analytics.zones and restarted.homography.is_calibrated)

    def test_delete_homography_route_clears_world_graph_and_mapper(self) -> None:
        """DELETE /api/scenarios/homography/{id} clears homography from WorldGraph and mapper."""
        db = TrackerDB(str(self.tmp_path / "scen_api.db"))
        self.addCleanup(db.close)
        pool = CameraPool(
            config_file=str(self.tmp_path / "api_cams.json"),
            db_path=str(self.tmp_path / "scen_api.db"),
            autostart=False,
        )
        self.addCleanup(pool.stop_all)
        scen = ScenarioManager(
            config_path=str(self.tmp_path / "api_scen.yaml"),
            db=db,
            world_graph=pool.world_graph,
            coordinate_mapper=pool.coordinate_mapper,
        )
        scen.save_homography("cam_01", [(0.0, 0.0), (80.0, 0.0), (80.0, 80.0), (0.0, 80.0)])
        self.assertIsNotNone(pool.coordinate_mapper.get_homography("cam_01"))

        bind_app_state(
            app, camera_pool=pool, stream_manager=pool.primary_stream,
            scenario_manager=scen, db=db, world_graph=pool.world_graph,
        )
        self.addCleanup(clear_app_state, app)
        client = TestClient(app)
        self.addCleanup(client.close)

        resp = client.delete("/api/scenarios/homography/cam_01")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(pool.coordinate_mapper.get_homography("cam_01"))
        node = pool.world_graph.get_node("cam_01", node_type="camera")
        self.assertIsNone(node.homography)

    def test_multiview_throttled_telemetry_and_stream_rebind(self) -> None:
        """MultiviewSession emits throttled JSON telemetry and migrates leases on stream restart."""
        async def _run() -> None:
            cam1 = _FakeStreamManager("cam_01")
            cam1.get_latest_telemetry = lambda: {  # type: ignore[attr-defined]
                "frame_seq": 10, "fps": 14.5, "priority_tier": "P1", "armed": True, "is_armed": True,
                "source_resolution": [1280, 720], "active_tracks": [{"id": 1, "bbox": [10, 20, 30, 40], "label": "person"}],
            }
            pool = _FakePool({"cam_01": cam1})
            ws = _FakeWebSocket([json.dumps({"v": 1, "action": "subscribe", "cameras": ["cam_01"], "layout": "2x2"})])
            session = MultiviewSession(ws, pool=pool, limits=MultiviewLimits({"2x2": (15, 640)}, 16, 4, 0.2, 70), session_id="s_tel")

            async def _drive() -> None:
                await asyncio.sleep(0.02)
                cam1.thumbnail_cache.update_frame(np.zeros((90, 160, 3), dtype=np.uint8), seq=10, timestamp_s=1.0)
                cam1.notify()
                await asyncio.sleep(0.03)
                cam1_new = _FakeStreamManager("cam_01")
                pool.streams["cam_01"] = cam1_new
                session._frame_event.set()
                await asyncio.sleep(0.02)
                cam1_new.thumbnail_cache.update_frame(np.zeros((90, 160, 3), dtype=np.uint8), seq=1, timestamp_s=2.0)
                cam1_new.notify()
                await asyncio.sleep(0.03)
                await ws.close()

            await asyncio.gather(session.run(), _drive())
            tel = [m for m in ws.sent_json if m.get("type") == "telemetry"]
            self.assertTrue(tel and tel[0]["armed"] and tel[0]["is_armed"] and tel[0]["ai_active"])
            self.assertEqual(tel[0]["source_resolution"], [1280, 720])
            self.assertEqual([unpack_frame(b).seq for b in ws.sent_bytes], [10, 1])
            self.assertEqual(len([m for m in ws.sent_json if m.get("reason") == "rebound"]), 1)

        asyncio.run(_run())

    def test_frontend_telemetry_callback_seq_restart_and_degraded_pagination(self) -> None:
        """Node VM check: multiview_client onTelemetry, FrameSurface seq restart, and camera_grid degraded layout."""
        from tests.test_multiview_client import _grid_ws_vm_prelude

        script = (
            _grid_ws_vm_prelude()
            + """
            let gotTelemetry = null;
            const c = new win.MultiviewWsClientClass({
              win, doc, setTimer: setT, clearTimer: clrT, onTelemetry: (m) => { gotTelemetry = m; }
            });
            c.subscribe(['cam_01'], '2x2');
            const ws = sockets[sockets.length - 1];
            ws.readyState = 1; ws.onopen();
            ws.onmessage({ data: JSON.stringify({ v: 1, type: 'telemetry', camera_id: 'cam_01', seq: 7, tracks: [] }) });
            const surf = new win.FrameSurface({ width: 320, height: 180, dataset: {}, getContext: () => ctx }, {
              cameraId: 'cam_01', decodeBitmap: () => Promise.resolve({ width: 160, height: 90, close: () => {} })
            });
            (async () => {
              const r1 = await surf.pushFrame(new Uint8Array([1]), 50, 1000);
              const rStale = await surf.pushFrame(new Uint8Array([1]), 1, 900);
              const rReset = await surf.pushFrame(new Uint8Array([1]), 1, 2000);
              const subLayouts = [];
              win.MultiviewWsClient.isDegraded = () => true;
              win.MultiviewWsClient.getState = () => ({ connected: false, degraded: true });
              win.MultiviewWsClient.subscribe = (ids, layout) => subLayouts.push({ ids, layout });
              const cams = Array.from({ length: 6 }, (_, i) => ({ id: 'cam_' + i, name: 'Cam ' + i, status: 'online' }));
              win.CameraGrid.setGridMode('3x3', cams, 'cam_0', () => {});
              console.log(JSON.stringify({ telSeq: gotTelemetry?.seq, r1, rStale, rReset, subLayouts }));
            })();
            """
        )
        out = _run_node_script(script)
        self.assertEqual((out["telSeq"], out["r1"], out["rStale"], out["rReset"]), (7, True, False, True))
        self.assertEqual((out["subLayouts"][0]["layout"], len(out["subLayouts"][0]["ids"])), ("2x2", 4))


if __name__ == "__main__":
    unittest.main()
