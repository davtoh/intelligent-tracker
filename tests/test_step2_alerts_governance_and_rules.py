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


if __name__ == "__main__":
    unittest.main()
