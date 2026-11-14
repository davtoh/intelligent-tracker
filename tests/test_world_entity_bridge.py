"""Isolated unit tests for WorldEntityBridge, WorldRuleEngine, and GalleryMatcher integration."""

import os
import tempfile
import unittest

import numpy as np

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.events import (
    EntityIdentifiedEvent,
    EventBus,
    RestrictedEntityAlert,
    TripwireCrossEvent,
    ZoneEvent,
)
from intelligent_tracker.matcher import GalleryMatcher
from intelligent_tracker.reid import MockFeatureExtractor
from intelligent_tracker.tracker import Track
from intelligent_tracker.world import (
    CameraNode,
    TripwireNode,
    WorldEntityBridge,
    WorldGraph,
    WorldPolicyUpdatedEvent,
    WorldRuleEngine,
    ZoneNode,
)


class TestWorldEntityBridgeAndRules(unittest.TestCase):
    """Verify Track <-> WorldEntity <-> Entity convergence and reactive EventBus rules."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.db_path = os.path.join(self.tmpdir.name, "world_bridge.db")
        self.db = TrackerDB(self.db_path)
        self.addCleanup(self.db.close)

        self.bus = EventBus()
        self.bus.start()
        self.addCleanup(self.bus.stop)

        self.graph = WorldGraph(event_bus=self.bus)
        self.graph.register_camera(CameraNode(camera_id="cam_01", name="Lobby"))
        self.graph.register_camera(CameraNode(camera_id="cam_02", name="Hallway"))
        self.graph.register_zone(ZoneNode(zone_id="entry", camera_id="cam_01"))
        self.graph.register_zone(ZoneNode(zone_id="corridor", camera_id="cam_02"))
        self.graph.register_tripwire(TripwireNode(tripwire_id="gate", camera_id="cam_01"))

        self.bridge = WorldEntityBridge(self.graph, db=self.db, sync_interval=1.0, stale_ttl=10.0)
        self.extractor = MockFeatureExtractor(embedding_dim=16)

    def test_cross_camera_entity_convergence_via_gallery_matcher(self) -> None:
        frame = np.zeros((160, 160, 3), dtype=np.uint8)
        frame[20:80, 20:80] = [0, 220, 60]

        eid = self.db.add_entity(name="Alice", category="staff")
        feat = self.extractor.extract(frame, (20, 20, 60, 60))
        self.db.add_signature(eid, feat)

        matcher_1 = GalleryMatcher(
            db=self.db,
            extractor=self.extractor,
            reid_threshold=0.70,
            min_track_hits=2,
            camera_id="cam_01",
            world_bridge=self.bridge,
        )
        matcher_2 = GalleryMatcher(
            db=self.db,
            extractor=self.extractor,
            reid_threshold=0.70,
            min_track_hits=2,
            camera_id="cam_02",
            world_bridge=self.bridge,
        )

        trk_cam1 = Track(track_id=1, bbox=(20, 20, 60, 60), timestamp=100.0)
        trk_cam1.hits = 3
        trk_cam2 = Track(track_id=4, bbox=(20, 20, 60, 60), timestamp=100.5)
        trk_cam2.hits = 3

        ev1 = matcher_1.match_tracks(
            {1: trk_cam1}, frame, source="cam_01", timestamp=100.0, zone_lookup={1: "entry"}
        )
        ev2 = matcher_2.match_tracks(
            {4: trk_cam2}, frame, source="cam_02", timestamp=100.5, zone_lookup={4: "corridor"}
        )

        self.assertEqual(len(ev1), 1)
        self.assertEqual(len(ev2), 1)

        we = self.graph.get_node(f"entity:{eid}", node_type="entity")
        self.assertIsNotNone(we)
        self.assertEqual(we.entity_id, eid)
        self.assertEqual(we.name, "Alice")
        self.assertEqual(we.category, "staff")
        self.assertEqual(we.camera_tracks, {"cam_01": 1, "cam_02": 4})
        self.assertEqual(
            we.active_zones,
            {"cam_01": {"cam_01:zone:entry"}, "cam_02": {"cam_02:zone:corridor"}},
        )
        self.assertEqual(self.graph.snapshot()["counts"]["entities"], 1)

    def test_session_isolation_and_promotion_to_persistent_entity(self) -> None:
        frame = np.full((120, 120, 3), 90, dtype=np.uint8)
        matcher_1 = GalleryMatcher(
            db=self.db, extractor=self.extractor, min_track_hits=2,
            camera_id="cam_01", world_bridge=self.bridge,
        )
        matcher_2 = GalleryMatcher(
            db=self.db, extractor=self.extractor, min_track_hits=2,
            camera_id="cam_02", world_bridge=self.bridge,
        )

        trk1 = Track(track_id=11, bbox=(10, 10, 40, 40), label="person", timestamp=10.0)
        trk1.hits = 3
        trk2 = Track(track_id=22, bbox=(10, 10, 40, 40), label="person", timestamp=10.0)
        trk2.hits = 3

        matcher_1.match_tracks({11: trk1}, frame, source="cam_01", timestamp=10.0, zone_lookup={11: "entry"})
        matcher_2.match_tracks({22: trk2}, frame, source="cam_02", timestamp=10.0, zone_lookup={22: "corridor"})

        sess1 = self.graph.get_node("session:cam_01:1", node_type="entity")
        sess2 = self.graph.get_node("session:cam_02:1", node_type="entity")
        self.assertIsNotNone(sess1)
        self.assertIsNotNone(sess2)
        self.assertEqual(sess1.camera_tracks, {"cam_01": 11})
        self.assertEqual(sess2.camera_tracks, {"cam_02": 22})

        # Simulate zone occupancy referencing the session WorldEntity before promotion
        zone = self.graph.get_node("cam_01:zone:entry", node_type="zone")
        zone.active_entity_ids.add("session:cam_01:1")
        self.graph.register_zone(zone)

        # Promote cam_01 session track to persistent DB entity
        eid = self.db.add_entity(name="Promoted Guest", category="visitor")
        self.assertTrue(matcher_1.reassign_track(trk1, eid, frame=frame))

        self.assertIsNone(self.graph.get_node("session:cam_01:1", node_type="entity"))
        self.assertIsNotNone(self.graph.get_node("session:cam_02:1", node_type="entity"))
        promoted = self.graph.get_node(f"entity:{eid}", node_type="entity")
        self.assertIsNotNone(promoted)
        self.assertEqual(promoted.camera_tracks, {"cam_01": 11})
        self.assertEqual(promoted.active_zones, {"cam_01": {"cam_01:zone:entry"}})

        updated_zone = self.graph.get_node("cam_01:zone:entry", node_type="zone")
        self.assertIn(f"entity:{eid}", updated_zone.active_entity_ids)
        self.assertNotIn("session:cam_01:1", updated_zone.active_entity_ids)

    def test_reassign_track_transfers_binding_and_handles_missing_entity(self) -> None:
        eid1 = self.db.add_entity(name="Bob", category="visitor")
        eid2 = self.db.add_entity(name="VIP Dana", category="vip")

        trk = Track(track_id=5, bbox=(15, 15, 30, 30), timestamp=50.0)
        trk.hits = 3
        self.bridge.sync_track_identification("cam_01", trk, eid1, zone_id="entry", timestamp=50.0)
        self.assertIsNotNone(self.graph.get_node(f"entity:{eid1}", node_type="entity"))

        # Reassigning to non-existent DB entity fails cleanly
        self.assertFalse(self.bridge.reassign_track("cam_01", trk, 99999))
        self.assertEqual(trk.entity_id, eid1)

        matcher = GalleryMatcher(
            db=self.db, extractor=self.extractor, camera_id="cam_01", world_bridge=self.bridge
        )
        self.assertTrue(matcher.reassign_track(trk, eid2))
        self.assertEqual(trk.entity_id, eid2)
        self.assertEqual(trk.entity_name, "VIP Dana")
        self.assertIsNone(self.graph.get_node(f"entity:{eid1}", node_type="entity"))

        new_we = self.graph.get_node(f"entity:{eid2}", node_type="entity")
        self.assertIsNotNone(new_we)
        self.assertEqual(new_we.camera_tracks, {"cam_01": 5})
        self.assertEqual(new_we.active_zones, {"cam_01": {"cam_01:zone:entry"}})

    def test_sync_camera_tracks_throttling_and_prune_stale_tracks(self) -> None:
        eid = self.db.add_entity(name="Carlos", category="staff")
        trk1 = Track(track_id=1, bbox=(10, 10, 20, 20), timestamp=100.0)
        trk1.entity_id = eid
        trk1.entity_name = "Carlos"
        trk1.entity_category = "staff"
        trk1.reid_score = 0.9

        # First sync pushes immediately
        first = self.bridge.sync_camera_tracks(
            "cam_01", {1: trk1}, zone_lookup={1: "entry"}, timestamp=100.0
        )
        self.assertEqual(len(first), 1)

        # Within sync_interval (1.0s) and unchanged zone -> skipped for 30 FPS efficiency
        skipped = self.bridge.sync_camera_tracks(
            "cam_01", {1: trk1}, zone_lookup={1: "entry"}, timestamp=100.2
        )
        self.assertEqual(skipped, [])

        # Past sync_interval -> synced
        refreshed = self.bridge.sync_camera_tracks(
            "cam_01", {1: trk1}, zone_lookup={1: "entry"}, timestamp=101.5
        )
        self.assertEqual(len(refreshed), 1)

        # Bind same entity on cam_02 as well
        trk2 = Track(track_id=9, bbox=(30, 30, 20, 20), timestamp=101.5)
        trk2.entity_id = eid
        self.bridge.sync_track_identification("cam_02", trk2, eid, timestamp=101.5)

        # Prune missing track on cam_01 -> cam_02 binding stays intact
        pruned_cam1 = self.bridge.prune_stale_tracks(
            camera_id="cam_01", active_track_ids=set(), timestamp=102.0
        )
        self.assertEqual(pruned_cam1, [f"entity:{eid}"])
        we = self.graph.get_node(f"entity:{eid}", node_type="entity")
        self.assertIsNotNone(we)
        self.assertEqual(we.camera_tracks, {"cam_02": 9})

        # TTL expiration across remaining camera prunes the empty live entity
        pruned_ttl = self.bridge.prune_stale_tracks(max_age=5.0, timestamp=110.0)
        self.assertEqual(pruned_ttl, [f"entity:{eid}"])
        self.assertIsNone(self.graph.get_node(f"entity:{eid}", node_type="entity"))

    def test_world_rule_engine_reactive_occupancy_restriction_and_policy(self) -> None:
        engine = WorldRuleEngine(self.graph, self.bus)
        self.addCleanup(engine.stop)
        self.assertTrue(engine.start())
        self.assertFalse(engine.start())  # idempotent
        self.assertTrue(engine.is_running)

        eid = self.db.add_entity(name="Eve", category="visitor")
        trk = Track(track_id=7, bbox=(20, 20, 30, 30), timestamp=200.0)
        self.bridge.sync_track_identification("cam_01", trk, eid, timestamp=200.0)

        self.bus.publish(ZoneEvent(camera_id="cam_01", zone_id="entry", track_id=7, action="enter"))
        self.bus.publish(TripwireCrossEvent(camera_id="cam_01", tripwire_id="gate", track_id=7))
        self.bus.publish(
            RestrictedEntityAlert(
                camera_id="cam_01", zone_id="entry", track_id=7, entity_id=eid, name="Eve"
            )
        )
        self.bus.publish(
            WorldPolicyUpdatedEvent(
                camera_id="world",
                policy={"alert_sensitivity": 0.45, "dwell_override": 12.0},
                changed_fields=["alert_sensitivity", "dwell_override"],
            )
        )
        # Event for unregistered/removed camera must not resurrect nodes
        self.bus.publish(ZoneEvent(camera_id="cam_gone", zone_id="z_ghost", track_id=1, action="enter"))

        self.assertTrue(self.bus.wait_until_empty(timeout=2.0))

        zone = self.graph.get_node("cam_01:zone:entry", node_type="zone")
        self.assertIn(7, zone.active_track_ids)
        self.assertIn(f"entity:{eid}", zone.active_entity_ids)

        tw = self.graph.get_node("cam_01:tripwire:gate", node_type="tripwire")
        self.assertEqual(tw.crossing_count, 1)

        we = self.graph.get_node(f"entity:{eid}", node_type="entity")
        self.assertTrue(we.restricted)
        self.assertIn("cam_01:zone:entry", we.active_zones.get("cam_01", set()))

        policy = self.graph.get_policy()
        self.assertAlmostEqual(policy.alert_sensitivity, 0.45)
        self.assertAlmostEqual(policy.dwell_override, 12.0)
        self.assertIsNone(self.graph.get_node("cam_gone", node_type="camera"))

        # Exit clears zone occupancy and stops reacting after stop()
        self.bus.publish(ZoneEvent(camera_id="cam_01", zone_id="entry", track_id=7, action="exit"))
        self.assertTrue(self.bus.wait_until_empty(timeout=2.0))
        zone_after = self.graph.get_node("cam_01:zone:entry", node_type="zone")
        self.assertNotIn(7, zone_after.active_track_ids)
        self.assertNotIn(f"entity:{eid}", zone_after.active_entity_ids)

        self.assertTrue(engine.stop())
        self.assertFalse(engine.stop())
        self.assertFalse(engine.is_running)

        self.bus.publish(TripwireCrossEvent(camera_id="cam_01", tripwire_id="gate", track_id=7))
        self.assertTrue(self.bus.wait_until_empty(timeout=2.0))
        self.assertEqual(self.graph.get_node("cam_01:tripwire:gate", node_type="tripwire").crossing_count, 1)

    def test_world_rule_engine_entity_identified_event_creates_node(self) -> None:
        engine = WorldRuleEngine(self.graph, self.bus)
        self.addCleanup(engine.stop)
        engine.start()

        self.bus.publish(
            EntityIdentifiedEvent(
                camera_id="cam_02",
                track_id=31,
                entity_id=88,
                name="Mallory",
                category="blacklisted",
                similarity=0.92,
                zone_id="corridor",
            )
        )
        self.assertTrue(self.bus.wait_until_empty(timeout=2.0))

        we = self.graph.get_node("entity:88", node_type="entity")
        self.assertIsNotNone(we)
        self.assertEqual(we.camera_tracks, {"cam_02": 31})
        self.assertTrue(we.restricted)
        self.assertEqual(we.active_zones, {"cam_02": {"cam_02:zone:corridor"}})


if __name__ == "__main__":
    unittest.main()

