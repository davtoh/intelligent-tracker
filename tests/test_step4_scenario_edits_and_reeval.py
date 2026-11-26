"""Milestone 1 tests: non-destructive PUT scenario editing & 0-GPU video re-evaluation."""

import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.dependencies import get_scenario_mgr
from dashboard.routers import scenarios as scenarios_router
from dashboard.routers import video_jobs as video_jobs_router
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.repositories.spatial_edit_helpers import (
    update_spatial_tripwire_sync,
    update_spatial_zone_sync,
)
from intelligent_tracker.scenario_edits import update_tripwire_in_place, update_zone_in_place
from intelligent_tracker.scenarios import ScenarioManager
from intelligent_tracker.world import WorldGraph


class _RollbackConnProxy:
    """Proxy wrapping sqlite3.Connection to spy on rollback() and inject UPDATE errors."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self.rollback_calls = 0

    def cursor(self):
        real_cur = self._conn.cursor()

        class _CurProxy:
            def execute(self, sql, params=()):
                if sql.strip().upper().startswith("UPDATE "):
                    raise sqlite3.OperationalError("injected update failure")
                return real_cur.execute(sql, params)

            def fetchone(self):
                return real_cur.fetchone()

            def close(self):
                return real_cur.close()

        return _CurProxy()

    def rollback(self) -> None:
        self.rollback_calls += 1
        self._conn.rollback()


class TestStep4ScenarioEditsAndReeval(unittest.TestCase):
    """Tests for in-place zone/tripwire edits, SQLite rollback, and 0-GPU re-evaluation."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "test.db")
        self.yaml_path = os.path.join(self.tmp.name, "scenarios.yaml")
        self.db = TrackerDB(self.db_path)
        self.addCleanup(self.db.close)
        self.wg = WorldGraph()
        self.sm = ScenarioManager(config_path=self.yaml_path, db=self.db, world_graph=self.wg)
        self.addCleanup(self.sm.close)

    def _seed_zone_and_tripwire(self) -> None:
        self.sm.save_zone("cam_01", "vault", [[10, 10], [100, 10], [100, 100], [10, 100]], dwell_threshold=1.0)
        self.sm.save_tripwire("cam_01", "gate", [[0, 50], [200, 50]], bidirectional=True)

    def test_in_place_zone_edit_preserves_live_counters_and_history(self) -> None:
        self._seed_zone_and_tripwire()
        z = self.sm.cameras["cam_01"]["zones"]["vault"]
        z.update({1: (50.0, 50.0)}, timestamp=100.0)
        self.assertEqual(z.total_entries, 1)
        self.assertEqual(z.occupancy, 1)

        eid = self.db.add_entity("Alice", category="staff")
        self.db.add_sighting(eid, source="cam_01", zone_id="vault", timestamp=100.0)
        self.db.index_timeline_event(event_type="enter", summary="Entered vault", entity_id=eid, camera_id="cam_01", zone_id="vault", timestamp=100.0)

        updated = update_zone_in_place(
            self.sm, "cam_01", "vault", name="vault_v2", polygon=[[0, 0], [120, 0], [120, 120], [0, 120]]
        )
        self.assertIs(updated, z)
        self.assertEqual(z.total_entries, 1)
        self.assertEqual(z.occupancy, 1)
        self.assertEqual(len(z.event_history), 1)
        self.assertIn("vault_v2", self.sm.cameras["cam_01"]["zones"])
        self.assertNotIn("vault", self.sm.cameras["cam_01"]["zones"])
        self.assertIsNotNone(self.wg.get_node("cam_01:zone:vault_v2"))
        self.assertIsNone(self.wg.get_node("cam_01:zone:vault"))
        self.assertEqual(self.db.get_sightings(entity_id=eid)[0]["zone_id"], "vault")
        self.assertEqual(self.db.search_timeline_events(entity_id=eid)[0]["zone_id"], "vault")

    def test_in_place_tripwire_edit_preserves_counts(self) -> None:
        self._seed_zone_and_tripwire()
        tw = self.sm.cameras["cam_01"]["tripwires"]["gate"]
        ev = tw.check_crossing(7, (50.0, 20.0), (50.0, 80.0), timestamp=50.0)
        self.assertIsNotNone(ev)
        self.assertEqual(tw.total_in + tw.total_out, 1)

        updated = update_tripwire_in_place(
            self.sm, "cam_01", "gate", name="gate_north", line_segment=[[0, 60], [220, 60]], bidirectional=False
        )
        self.assertIs(updated, tw)
        self.assertEqual(tw.total_in + tw.total_out, 1)
        self.assertEqual(len(tw.event_history), 1)
        self.assertFalse(tw.bidirectional)
        self.assertIn("gate_north", self.sm.cameras["cam_01"]["tripwires"])

    def test_sqlite_rollback_on_update_error(self) -> None:
        self._seed_zone_and_tripwire()
        proxy = _RollbackConnProxy(self.db._conn)
        fake_db = SimpleNamespace(_conn=proxy, _lock=self.db._lock)
        with self.assertRaises(sqlite3.OperationalError):
            update_spatial_zone_sync(fake_db, "cam_01", "vault", name="vault_err")
        with self.assertRaises(sqlite3.OperationalError):
            update_spatial_tripwire_sync(fake_db, "cam_01", "gate", name="gate_err")
        self.assertEqual(proxy.rollback_calls, 2)

    def test_put_routes_return_200_404_and_409(self) -> None:
        self._seed_zone_and_tripwire()
        self.sm.save_zone("cam_01", "lobby", [[200, 200], [300, 200], [300, 300]])
        self.sm.save_tripwire("cam_01", "rear", [[10, 200], [100, 200]])

        app = FastAPI()
        app.include_router(scenarios_router.router)
        app.dependency_overrides[get_scenario_mgr] = lambda: self.sm
        client = TestClient(app)

        with patch("dashboard.routers.scenarios.get_active_stream_manager", return_value=None):
            ok_z = client.put("/api/scenarios/zones/cam_01/vault", json={"name": "vault_2", "dwell_threshold": 2.5})
            self.assertEqual(ok_z.status_code, 200)
            self.assertEqual(ok_z.json()["zone"]["name"], "vault_2")

            miss_z = client.put("/api/scenarios/zones/cam_01/missing", json={"dwell_threshold": 3.0})
            self.assertEqual(miss_z.status_code, 404)

            clash_z = client.put("/api/scenarios/zones/cam_01/vault_2", json={"name": "lobby"})
            self.assertEqual(clash_z.status_code, 409)

            ok_tw = client.put("/api/scenarios/tripwires/cam_01/gate", json={"name": "gate_2", "bidirectional": False})
            self.assertEqual(ok_tw.status_code, 200)
            self.assertEqual(ok_tw.json()["tripwire"]["name"], "gate_2")

            miss_tw = client.put("/api/scenarios/tripwires/cam_01/missing", json={"bidirectional": True})
            self.assertEqual(miss_tw.status_code, 404)

            clash_tw = client.put("/api/scenarios/tripwires/cam_01/gate_2", json={"name": "rear"})
            self.assertEqual(clash_tw.status_code, 409)

    def test_zero_gpu_video_reeval_updates_metrics_alerts_and_invalidates_cache(self) -> None:
        self.sm.save_zone("cam_01", "restricted_z", [[0, 0], [100, 0], [100, 100], [0, 100]], dwell_threshold=1.0)
        self.sm.save_tripwire("cam_01", "entry_line", [[0, 50], [200, 50]], bidirectional=True)
        self.db.set_rsac_rule("cam_01", "restricted_z", allowed_categories=["staff"], alarm_on_breach=True)

        dets = [
            {"frame_idx": 0, "timestamp": 1.0, "media_offset_sec": 1.0, "tracks": [{"track_id": 1, "bbox": [40, 20, 20, 20], "centroid": [50.0, 30.0], "category": "visitor"}]},
            {"frame_idx": 1, "timestamp": 3.0, "media_offset_sec": 3.0, "tracks": [{"track_id": 1, "bbox": [40, 70, 20, 20], "centroid": [50.0, 80.0], "category": "visitor"}]},
        ]
        saved = self.db.save_video_run(
            "clip.mp4",
            run_type="offline_analytics",
            report={"zone_metrics": {}, "tripwire_counts": {}, "alerts": []},
            config={"scenario_camera_id": "cam_01"},
            frame_detections=dets,
        )
        replay_provider = MagicMock()
        fake_pool = SimpleNamespace(_lock=self.db._lock, streams={"cam_01": SimpleNamespace(_cached_replay_provider=replay_provider)})

        app = FastAPI()
        app.include_router(video_jobs_router.router)
        client = TestClient(app)
        with (
            patch("dashboard.routers.video_jobs.get_db", return_value=self.db),
            patch("dashboard.routers.video_jobs.get_scenario_mgr", return_value=self.sm),
            patch("dashboard.routers.video_jobs.get_camera_pool", return_value=fake_pool),
        ):
            resp = client.post(
                "/api/videos/re-evaluate-scenarios",
                json={"video_filename": "clip.mp4", "run_id": saved["run_id"], "scenario_camera_id": "cam_01"},
            )
        self.assertEqual(resp.status_code, 200)
        rep = resp.json()["report"]
        self.assertEqual(rep["zone_metrics"]["restricted_z"]["total_entries"], 1)
        tw_stats = rep["tripwire_counts"]["entry_line"]
        self.assertEqual(tw_stats["total_in"] + tw_stats["total_out"], 1)
        self.assertGreaterEqual(len(rep["alerts"]), 1)
        replay_provider.invalidate.assert_called_once()
