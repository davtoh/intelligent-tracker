"""Milestone 1 tests for Step 2: Alerts SSOT Write-Through, Noise Elimination, Severity/Zone Parity & Dwell Window."""

import os
import tempfile
import unittest

from dashboard.camera_pool import CameraPool
from dashboard.services.video_analytics_service import _build_offline_analytics_and_bus
from intelligent_tracker.analytics.zone_stats import evaluate_zone_updates
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.events import (
    EntityIdentifiedEvent,
    EventBus,
    IntrusionAlert,
    OccupancyThresholdEvent,
    PetActivityEvent,
    RSACViolationEvent,
    TripwireCrossEvent,
    UnattendedItemAlert,
    ZoneEvent,
)
from intelligent_tracker.geometry.zone_roi import ZoneROI
from intelligent_tracker.memory import EventFTSIndex
from intelligent_tracker.memory._event_formatters import (
    normalize_event_doc,
    normalize_zone_id,
    resolve_event_severity,
)
from intelligent_tracker.pipeline import PipelineEngine
from intelligent_tracker.tracker import Track
from intelligent_tracker.world.events import EntityStateChangedEvent


class TestAlertsWriteThroughAndNoiseElimination(unittest.TestCase):
    """Verify EventBus write-through wiring and ADR-23 state-tick noise elimination."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.db_path = os.path.join(self.tmpdir.name, "alerts_m1.db")
        self.db = TrackerDB(self.db_path)
        self.addCleanup(self.db.close)

    def test_camera_pool_and_pipeline_engine_wire_write_through_handler(self) -> None:
        """CameraPool and PipelineEngine register EventFTSIndex synchronously via set_write_through_handler."""
        cfg_path = os.path.join(self.tmpdir.name, "cameras.json")
        pool = CameraPool(config_file=cfg_path, db_path=self.db_path, autostart=False)
        self.addCleanup(pool.stop_all)
        self.assertIsNotNone(pool.event_fts_index)
        self.assertEqual(pool.event_bus._write_through_handler, pool.event_fts_index.handle_event)

        bundle = PipelineEngine.from_dict(
            {"video": {"source": "synthetic"}, "detector": {"model": "mock"}, "reid": {"model": "none"}},
            db_path=self.db_path,
            enable_event_bus_fallback=True,
            enable_memory_indexing=True,
        )
        self.addCleanup(bundle.close)
        self.assertIsNotNone(bundle.event_fts_index)
        self.assertEqual(bundle.event_bus._write_through_handler, bundle.event_fts_index.handle_event)

    def test_state_events_stay_in_memory_while_zone_events_persist_synchronously(self) -> None:
        """OBS-030: world_entity_state_changed stays in-memory (0 SQLite rows); ZoneEvent gets db_id synchronously."""
        bus = EventBus(capacity=100)
        bus.start()
        self.addCleanup(bus.stop)
        fts = EventFTSIndex(self.db, event_bus=bus, auto_attach=True)
        self.addCleanup(fts.detach)

        received: list[str] = []
        bus.subscribe(lambda ev: received.append(ev.event_type))

        now = 1_700_000_000.0
        for idx in range(5):
            bus.publish(EntityStateChangedEvent(
                camera_id="usb_0",
                world_entity_id="entity:1",
                entity_id=None,
                change_type="updated",
                camera_tracks={"usb_0": 1},
                active_zones={"usb_0": ["usb_0:zone:Room_right"]},
                timestamp=now + idx * 0.5,
            ))

        z_ev = ZoneEvent(
            camera_id="usb_0",
            zone_id="usb_0:zone:Room_right",
            track_id=1,
            action="dwell",
            dwell_time=12.0,
            entry_time=now,
            timestamp=now + 12.0,
        )
        bus.publish(z_ev)
        self.assertIsNotNone(getattr(z_ev, "db_id", None))
        self.assertTrue(bus.wait_until_empty(timeout=3.0))

        self.assertEqual(len(received), 6)
        self.assertEqual(received.count("world_entity_state_changed"), 5)
        self.assertEqual(len(self.db.search_timeline_events(query="", event_type="world_entity_state_changed", limit=20)), 0)

        stored = self.db.get_timeline_event(int(getattr(z_ev, "db_id")))
        self.assertIsNotNone(stored)
        self.assertEqual(stored["zone_id"], "Room_right")
        self.assertEqual(stored["metadata"]["severity"], "info")


class TestSeverityZoneNormalizationAndDwellWindow(unittest.TestCase):
    """Verify OBS-031, OBS-032, OBS-033, and DBG-04 offline provenance under write-through."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.db_path = os.path.join(self.tmpdir.name, "formatters_m1.db")
        self.db = TrackerDB(self.db_path)
        self.addCleanup(self.db.close)

    def test_all_formatters_emit_canonical_severity_and_unscoped_zone_id(self) -> None:
        """Every event formatter + index_sighting/index_clip_caption emits canonical severity and unscoped zone_id."""
        self.assertEqual(normalize_zone_id("usb_0:zone:Room_right"), "Room_right")
        self.assertEqual(normalize_zone_id("Room_left"), "Room_left")
        self.assertEqual(resolve_event_severity(OccupancyThresholdEvent(severity="cleared")), "info")

        now = 1_700_000_100.0
        samples = [
            (ZoneEvent(camera_id="usb_0", zone_id="usb_0:zone:Room_right", track_id=1, action="enter", timestamp=now), "info", "Room_right"),
            (TripwireCrossEvent(camera_id="usb_0", tripwire_id="door", track_id=1, metadata={"zone_id": "usb_0:zone:Hall"}, timestamp=now), "info", "Hall"),
            (EntityIdentifiedEvent(camera_id="usb_0", track_id=1, entity_id=1, name="Alice", zone_id="usb_0:zone:Lobby", similarity=0.9, timestamp=now), "info", "Lobby"),
            (RSACViolationEvent(camera_id="usb_0", zone_id="usb_0:zone:Vault", track_id=2, severity="critical", timestamp=now), "critical", "Vault"),
            (IntrusionAlert(camera_id="usb_0", zone_id="usb_0:zone:Vault", track_id=3, severity="critical", timestamp=now), "critical", "Vault"),
            (OccupancyThresholdEvent(camera_id="usb_0", zone_id="usb_0:zone:Room_right", severity="warning", timestamp=now), "warning", "Room_right"),
            (PetActivityEvent(camera_id="usb_0", zone_id="usb_0:zone:Porch", track_id=4, timestamp=now), "info", "Porch"),
            (UnattendedItemAlert(camera_id="usb_0", location="usb_0:zone:Gate_A", bag_track_id=5, severity="warning", timestamp=now), "warning", "Gate_A"),
            (EntityStateChangedEvent(camera_id="usb_0", world_entity_id="e:1", active_zones={"usb_0": ["usb_0:zone:Room_right"]}, timestamp=now), "info", "Room_right"),
        ]
        for ev, expected_sev, expected_zone in samples:
            doc = normalize_event_doc(ev)
            self.assertIsNotNone(doc)
            self.assertEqual(doc["zone_id"], expected_zone, f"zone mismatch for {type(ev).__name__}")
            self.assertEqual(doc["metadata"]["severity"], expected_sev, f"severity mismatch for {type(ev).__name__}")
            self.assertIn(expected_sev, doc["tags"].split(","))

        fts = EventFTSIndex(self.db, auto_attach=False)
        s_id = fts.index_sighting(camera_id="usb_0", zone_id="usb_0:zone:Room_right", timestamp=now)
        c_id = fts.index_clip_caption("Person near desk", camera_id="usb_0", zone_id="usb_0:zone:Room_right", timestamp=now + 1)
        for row_id in (s_id, c_id):
            row = self.db.get_timeline_event(int(row_id))
            self.assertEqual(row["zone_id"], "Room_right")
            self.assertEqual(row["metadata"]["severity"], "info")
            self.assertIn("info", row["tags"].split(","))

    def test_zone_roi_to_fts_preserves_entry_exit_and_dwell_window(self) -> None:
        """OBS-033: ZoneROI -> evaluate_zone_updates -> EventFTSIndex preserves entry_time, exit_time, and dwell_time."""
        bus = EventBus(capacity=50)
        bus.start()
        self.addCleanup(bus.stop)
        fts = EventFTSIndex(self.db, event_bus=bus, auto_attach=True)
        self.addCleanup(fts.detach)

        zone = ZoneROI(polygon=[(0, 0), (100, 0), (100, 100), (0, 100)], name="Room_right", dwell_threshold=10.0)
        zones = {"Room_right": zone}
        trk_in = Track(track_id=7, bbox=(40, 40, 20, 20), centroid=(50.0, 50.0))
        trk_out = Track(track_id=7, bbox=(200, 200, 20, 20), centroid=(210.0, 210.0))

        t0 = 1_700_000_100.0
        evaluate_zone_updates({7: trk_in}, zones, "usb_0", bus, None, None, None, t0, [])
        evaluate_zone_updates({7: trk_in}, zones, "usb_0", bus, None, None, None, t0 + 12.0, [])
        evaluate_zone_updates({7: trk_out}, zones, "usb_0", bus, None, None, None, t0 + 25.0, [])
        self.assertTrue(bus.wait_until_empty(timeout=3.0))

        rows = {r["event_type"]: r for r in self.db.search_timeline_events(query="", limit=10)}
        self.assertIn("zone_enter", rows)
        self.assertIn("zone_dwell", rows)
        self.assertIn("zone_exit", rows)
        self.assertEqual(rows["zone_dwell"]["metadata"]["entry_time"], t0)
        self.assertAlmostEqual(rows["zone_dwell"]["metadata"]["dwell_time"], 12.0, places=2)
        self.assertIn("12.0s", rows["zone_dwell"]["summary"])
        self.assertEqual(rows["zone_exit"]["metadata"]["entry_time"], t0)
        self.assertEqual(rows["zone_exit"]["metadata"]["exit_time"], t0 + 25.0)
        self.assertAlmostEqual(rows["zone_exit"]["metadata"]["dwell_time"], 25.0, places=2)
        self.assertIn("25.0s", rows["zone_exit"]["summary"])

    def test_offline_batch_write_through_preserves_video_provenance(self) -> None:
        """DBG-04: Offline video analytics stamps video_filename, media_offset_sec, and run_id before write-through."""
        _, _, bus, collected, fts, media_state = _build_offline_analytics_and_bus(
            self.db, scenario_camera_id=None, safe_name="demo_clip.mp4"
        )
        self.addCleanup(bus.stop)
        self.addCleanup(fts.stop)

        base_ts = 1_700_000_500.0
        media_state["start_wall_time"] = base_ts
        media_state["run_id"] = "run_test1234"
        ev = ZoneEvent(
            camera_id="video:demo_clip.mp4",
            zone_id="Room_right",
            track_id=2,
            action="dwell",
            dwell_time=6.0,
            entry_time=base_ts + 4.0,
            timestamp=base_ts + 10.0,
        )
        bus.publish(ev)
        self.assertIsNotNone(getattr(ev, "db_id", None))
        self.assertEqual(len(collected), 1)

        stored = self.db.get_timeline_event(int(getattr(ev, "db_id")))
        self.assertEqual(stored["video_filename"], "demo_clip.mp4")
        self.assertAlmostEqual(stored["media_offset_sec"], 10.0, places=2)
        self.assertEqual(stored["metadata"]["run_id"], "run_test1234")


class TestAlertRulesSchemaPromotionAndFiltering(unittest.TestCase):
    """Milestone 2: SQLite v6, AlertRulesMixin, AlertPromotionEngine, SQL/REST filtering."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, "tracker.db")
        self.db = TrackerDB(self.db_path)
        self.addCleanup(self.db.close)

    def test_v6_schema_crud_and_rollback_guard(self) -> None:
        """SQLite v6 creates tables idempotently, supports CRUD, and rolls back on sqlite3.Error."""
        import sqlite3

        self.assertEqual(self.db.get_schema_version(), 6)
        self.db._conn.execute("PRAGMA user_version = 5;")
        self.db._conn.commit()
        self.db._init_schema()
        self.assertEqual(self.db.get_schema_version(), 6)

        r = self.db.create_alert_rule(name="Vault Dwell", event_type="zone_dwell", zone_id="vault", min_dwell_time=10.0, target_severity="critical")
        self.assertEqual(r["target_severity"], "critical")
        upd = self.db.update_alert_rule(r["id"], enabled=False, target_severity="warning")
        self.assertIsNotNone(upd)
        self.assertEqual(len(self.db.list_alert_rules(enabled_only=True)), 0)
        self.assertTrue(self.db.delete_alert_rule(r["id"]))
        pol = self.db.update_alert_policy(dwell_override=15.0, alert_sensitivity=1.5, quiet_hours={"start": "22:00"})
        self.assertAlmostEqual(pol["dwell_override"], 15.0)

        rolled: list[bool] = []
        raw_conn = self.db._conn

        class _ConnProxy:
            def cursor(self):
                class _BadCur:
                    def execute(self, *_a, **_k): raise sqlite3.OperationalError("forced write failure")
                    def close(self): pass
                return _BadCur()
            def rollback(self):
                rolled.append(True)
                raw_conn.rollback()
            def __getattr__(self, name): return getattr(raw_conn, name)

        self.db._conn = _ConnProxy()
        try:
            with self.assertRaises(sqlite3.OperationalError):
                self.db.create_alert_rule(name="Fail Rule")
        finally:
            self.db._conn = raw_conn
        self.assertTrue(rolled)

    def test_promotion_engine_live_write_through_and_no_downgrade(self) -> None:
        """AlertPromotionEngine upgrades zone_dwell >= min_dwell without downgrading higher severities."""
        from intelligent_tracker.events.promotion_engine import AlertPromotionEngine
        from intelligent_tracker.world.graph import WorldGraph

        self.db.create_alert_rule(
            name="Long Vault Dwell", event_type="zone_dwell", zone_id="vault",
            min_dwell_time=8.0, target_severity="critical", add_tags="vip_alert",
        )
        self.db.create_alert_rule(
            name="Info Downgrade Attempt", event_type="zone_dwell", zone_id="vault", target_severity="info",
        )
        wg = WorldGraph()
        engine = AlertPromotionEngine(db=self.db, world_graph=wg)
        bus = EventBus(capacity=50)
        bus.start()
        fts = EventFTSIndex(db=self.db, event_bus=bus, auto_attach=True, promotion_engine=engine)
        self.addCleanup(bus.stop)
        self.addCleanup(fts.stop)

        short_ev = ZoneEvent(camera_id="cam_1", zone_id="cam_1:zone:restricted_vault", track_id=1, action="dwell", dwell_time=3.0, timestamp=100.0)
        long_ev = ZoneEvent(camera_id="cam_1", zone_id="cam_1:zone:restricted_vault", track_id=1, action="dwell", dwell_time=12.0, timestamp=110.0)
        bus.publish(short_ev)
        bus.publish(long_ev)
        self.assertTrue(bus.wait_until_empty(timeout=3.0))

        short_row = self.db.get_timeline_event(int(short_ev.db_id))
        long_row = self.db.get_timeline_event(int(long_ev.db_id))
        self.assertEqual(short_row["severity"], "info")
        self.assertNotIn("promoted_by_rule", short_row["metadata"])
        self.assertEqual(long_row["severity"], "critical")
        self.assertEqual(long_row["metadata"]["promoted_by_rule"], "Long Vault Dwell")
        self.assertIn("vip_alert", long_row["tags"])

        no_down = engine.evaluate({"event_type": "zone_dwell", "zone_id": "restricted_vault", "metadata": {"severity": "warning", "dwell_time": 2.0}, "tags": "warning"})
        self.assertEqual(no_down["metadata"]["severity"], "warning")
        engine.sync_policy({"dwell_override": 20.0, "alert_sensitivity": 1.25})
        self.assertAlmostEqual(wg.get_policy().dwell_override, 20.0)

    def test_normalized_multi_term_filtering_facets_and_rest_crud(self) -> None:
        """Normalized/substring/multi-term filters, min_severity hierarchy, facets, and /api/alerts/* REST."""
        from types import SimpleNamespace
        from fastapi.testclient import TestClient
        import dashboard.dependencies as deps
        from dashboard.app import app
        from intelligent_tracker.events.promotion_engine import AlertPromotionEngine
        from intelligent_tracker.world.graph import WorldGraph

        self.db.index_timeline_event(summary="Enter lobby", event_type="zone_enter", camera_id="cam_1", zone_id="cam_1:zone:Main_Lobby", timestamp=10.0, metadata={"severity": "info"})
        self.db.index_timeline_event(summary="Dwell lobby", event_type="zone_dwell", camera_id="cam_1", zone_id="Main_Lobby", timestamp=20.0, metadata={"severity": "warning"})
        self.db.index_timeline_event(summary="Vault breach", event_type="access_violation", camera_id="cam_2", zone_id="restricted_vault", timestamp=30.0, metadata={"severity": "critical"})

        self.assertEqual(self.db.get_timeline_event_facets()["zones"], ["Main_Lobby", "restricted_vault"])
        self.assertEqual(len(self.db.search_timeline_events(zone_id="lobby")), 2)
        self.assertEqual(len(self.db.search_timeline_events(event_type="zone_enter, violation")), 2)
        self.assertEqual(len(self.db.search_timeline_events(min_severity="warning")), 2)
        self.assertEqual(self.db.count_timeline_events(min_severity="critical"), 1)

        wg = WorldGraph()
        engine = AlertPromotionEngine(db=self.db, world_graph=wg)
        prev = (deps._db, getattr(app.state, "db", None), getattr(app.state, "camera_pool", None))
        deps._db, app.state.db = self.db, self.db
        app.state.camera_pool = SimpleNamespace(promotion_engine=engine, world_graph=wg, streams={})

        def _restore() -> None:
            deps._db, app.state.db, app.state.camera_pool = prev

        self.addCleanup(_restore)
        client = TestClient(app)
        res = client.post("/api/alerts/rules", json={"name": "Lobby Escalate", "event_type": "zone_dwell", "zone_id": "lobby", "target_severity": "critical"})
        self.assertEqual(res.status_code, 201)
        rule_id = res.json()["rule"]["id"]
        self.assertEqual(len(engine.get_rules()), 1)
        self.assertEqual(client.put(f"/api/alerts/rules/{rule_id}", json={"enabled": False}).json()["rule"]["enabled"], False)
        self.assertEqual(len(engine.get_rules()), 0)
        self.assertEqual(client.delete(f"/api/alerts/rules/{rule_id}").status_code, 200)
        self.assertEqual(client.put("/api/alerts/policy", json={"dwell_override": 9.5, "alert_sensitivity": 1.4}).status_code, 200)
        self.assertAlmostEqual(wg.get_policy().dwell_override, 9.5)
        self.assertEqual(len(client.get("/events", params={"min_severity": "warning", "zone_id": "lobby, vault"}).json()), 2)


if __name__ == "__main__":
    unittest.main()
