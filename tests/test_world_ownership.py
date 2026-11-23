"""End-to-end tests for WorldEdge, OwnershipAssociationEngine, UnattendedItemAlert, and live wiring."""

import tempfile
import time
import unittest
from unittest.mock import MagicMock

import numpy as np

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.events import EventBus, UnattendedItemAlert
from intelligent_tracker.memory import EventFTSIndex
from intelligent_tracker.pipeline.bundle import PipelineBundle, build_world
from intelligent_tracker.pipeline.config import PipelineConfig
from intelligent_tracker.pipeline.post_detection_governance import evaluate_tracks_governance
from intelligent_tracker.tracker.track import Track
from intelligent_tracker.world import OwnershipAssociationEngine, WorldEdge, WorldEntity, WorldGraph
from dashboard.services.stream_telemetry import _extract_track_telemetry


class TestWorldOwnership(unittest.TestCase):
    """Verify WorldEdge CRUD, cascade pruning, ownership association, FTS indexing, and governance wiring."""

    def test_world_edge_crud_and_cascade_pruning(self) -> None:
        graph = WorldGraph()
        p_ent = graph.upsert_entity(WorldEntity(entity_id=1, name="Alice", camera_tracks={"cam1": 10}))
        b_ent = graph.upsert_entity(WorldEntity(world_entity_id="track:cam1:20", camera_tracks={"cam1": 20}))

        e1 = graph.upsert_edge(WorldEdge(
            source_id=p_ent.world_entity_id,
            target_id=b_ent.world_entity_id,
            relation="CARRIES",
            camera_id="cam1",
        ))
        e2 = graph.upsert_edge(WorldEdge(
            source_id=b_ent.world_entity_id,
            target_id=p_ent.world_entity_id,
            relation="OWNED_BY",
            camera_id="cam1",
        ))
        self.assertEqual(len(graph.get_edges()), 2)
        self.assertEqual(len(graph.get_edges(relation="CARRIES", source_id=p_ent.world_entity_id)), 1)
        snap = graph.snapshot()
        self.assertEqual(len(snap["edges"]), 2)
        self.assertIn(e1.edge_id, snap["edges"])

        self.assertTrue(graph.remove_edge(e2.edge_id))
        self.assertEqual(len(graph.get_edges()), 1)

        # Cascade-prune when entity is removed
        self.assertTrue(graph.remove_node(b_ent.world_entity_id))
        self.assertEqual(len(graph.get_edges()), 0)

        # Cascade-prune when camera is removed
        graph.upsert_edge(WorldEdge(
            source_id=p_ent.world_entity_id,
            target_id="track:cam2:30",
            relation="CARRIES",
            camera_id="cam2",
        ))
        from intelligent_tracker.world import CameraNode
        graph.register_camera(CameraNode(camera_id="cam2"))
        graph.remove_camera("cam2")
        self.assertEqual(len(graph.get_edges()), 0)

    def _make_person_and_bag(self) -> tuple[WorldGraph, OwnershipAssociationEngine, Track, Track]:
        graph = WorldGraph()
        graph.upsert_entity(WorldEntity(
            entity_id=42, name="Bob", camera_tracks={"cam1": 1}, global_xy=(1.5, 2.5),
        ))
        graph.upsert_entity(WorldEntity(
            world_entity_id="track:cam1:2", camera_tracks={"cam1": 2}, global_xy=(3.0, 4.0),
        ))
        engine = OwnershipAssociationEngine(
            graph,
            proximity_px=100.0,
            min_carry_seconds=1.0,
            unattended_seconds=3.0,
            separation_px=150.0,
            alert_cooldown_seconds=10.0,
        )
        person = Track(track_id=1, bbox=(100, 100, 60, 140), centroid=(130.0, 170.0), label="person")
        person.entity_id = 42
        person.entity_name = "Bob"
        bag = Track(track_id=2, bbox=(120, 150, 40, 40), centroid=(140.0, 170.0), label="backpack")
        return graph, engine, person, bag

    def test_ownership_association_establishes_edges(self) -> None:
        graph, engine, person, bag = self._make_person_and_bag()
        self.assertEqual(engine.update("cam1", {1: person, 2: bag}, timestamp=1000.0, zone_lookup={2: "lobby"}), [])
        self.assertEqual(len(graph.get_edges()), 0)
        self.assertEqual(engine.update("cam1", {1: person, 2: bag}, timestamp=1001.5, zone_lookup={2: "lobby"}), [])
        self.assertEqual(len(graph.get_edges(relation="CARRIES")), 1)
        self.assertEqual(len(graph.get_edges(relation="OWNED_BY")), 1)
        self.assertEqual(len(person.carrying), 1)
        self.assertEqual(bag.carried_by["entity_id"], 42)

    def test_unattended_alert_and_owner_return(self) -> None:
        _, engine, person, bag = self._make_person_and_bag()
        engine.update("cam1", {1: person, 2: bag}, timestamp=1000.0, zone_lookup={2: "lobby"})
        engine.update("cam1", {1: person, 2: bag}, timestamp=1001.5, zone_lookup={2: "lobby"})

        person.centroid = (500.0, 170.0)
        person.bbox = (470, 100, 60, 140)
        self.assertEqual(engine.update("cam1", {1: person, 2: bag}, timestamp=1005.0, zone_lookup={2: "lobby"}), [])

        alerts = engine.update("cam1", {1: person, 2: bag}, timestamp=1008.5, zone_lookup={2: "lobby"})
        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual((alert.location, alert.global_xy, alert.owner_entity_id), ("lobby", (3.0, 4.0), 42))
        self.assertGreaterEqual(alert.unattended_duration_s, 3.5)
        self.assertTrue(bag.carried_by["unattended"])
        self.assertEqual(engine.update("cam1", {1: person, 2: bag}, timestamp=1010.0, zone_lookup={2: "lobby"}), [])

        person.centroid = (145.0, 170.0)
        person.bbox = (115, 100, 60, 140)
        self.assertEqual(engine.update("cam1", {1: person, 2: bag}, timestamp=1012.0, zone_lookup={2: "lobby"}), [])
        self.assertFalse(bag.carried_by["unattended"])

    def test_unattended_alert_indexed_in_event_fts(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        db = TrackerDB(f"{tmpdir.name}/test.db")
        self.addCleanup(db.close)
        bus = EventBus(capacity=50)
        bus.start()
        self.addCleanup(bus.stop)
        fts = EventFTSIndex(db=db, event_bus=bus, auto_attach=True)
        self.addCleanup(fts.detach)

        alert = UnattendedItemAlert(
            camera_id="cam1",
            location="gate_a",
            global_xy=(2.0, 3.0),
            bbox=(10, 20, 30, 40),
            owner_entity_id=7,
            owner_name="Charlie",
            bag_track_id=9,
            item_label="suitcase",
            unattended_duration_s=6.5,
            timestamp=1700000000.0,
        )
        bus.publish(alert)
        hits = []
        for _ in range(40):
            hits = db.search_timeline_events("suitcase")
            if hits:
                break
            time.sleep(0.05)
        self.assertGreaterEqual(len(hits), 1)
        self.assertEqual(hits[0]["event_type"], "unattended_item")
        self.assertEqual(hits[0]["zone_id"], "gate_a")

    def test_build_world_and_governance_wiring_plus_telemetry(self) -> None:
        cfg = PipelineConfig(camera_id="cam_live", source="0", detector_model="mock")
        bus = EventBus(capacity=50)
        bus.start()
        self.addCleanup(bus.stop)

        graph, bridge, rule_engine = build_world(cfg, analytics=None, event_bus=bus)
        if rule_engine is not None:
            self.addCleanup(rule_engine.stop)
        self.assertIsNotNone(getattr(graph, "ownership_engine", None))

        eng = graph.ownership_engine
        eng.min_carry_seconds = 0.0
        eng.unattended_seconds = 2.0

        bundle = PipelineBundle(
            config=cfg, event_bus=bus, world_graph=graph, world_bridge=bridge, world_rule_engine=rule_engine,
        )
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        person = Track(track_id=1, bbox=(50, 50, 40, 80), centroid=(70.0, 90.0), label="person")
        bag = Track(track_id=2, bbox=(60, 80, 30, 30), centroid=(75.0, 95.0), label="handbag")

        evaluate_tracks_governance(bundle, frame, {1: person, 2: bag}, timestamp=2000.0, run_reid=False)
        self.assertEqual(len(graph.get_edges(relation="CARRIES")), 1)

        homography = MagicMock()
        homography.track_to_ground.return_value = (1.0, 2.0)
        telem = _extract_track_telemetry({1: person, 2: bag}, homography)
        by_id = {t["id"]: t for t in telem}
        self.assertEqual(len(by_id[1]["carrying"]), 1)
        self.assertEqual(by_id[2]["carried_by"]["track_id"], 1)

        evaluate_tracks_governance(bundle, frame, {2: bag}, timestamp=2001.0, run_reid=False)
        evaluate_tracks_governance(bundle, frame, {2: bag}, timestamp=2004.0, run_reid=False)
        recent: list[UnattendedItemAlert] = []
        for _ in range(40):
            recent = [ev for ev in bus.get_recent_events(limit=10) if isinstance(ev, UnattendedItemAlert)]
            if recent:
                break
            time.sleep(0.05)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0].item_label, "handbag")


if __name__ == "__main__":
    unittest.main()
