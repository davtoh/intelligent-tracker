"""Unit tests for scoped WorldGraph, WorldNode types, cascading teardown, and EventBus safety."""

import ast
import json
from pathlib import Path
import threading
import unittest

from intelligent_tracker.events import EventBus
from intelligent_tracker.world import (
    CameraNode,
    EntityStateChangedEvent,
    NodeAddedEvent,
    NodeRemovedEvent,
    TripwireNode,
    WorldEntity,
    WorldGraph,
    WorldPolicy,
    WorldPolicyUpdatedEvent,
    ZoneNode,
)

ROOT_DIR = Path(__file__).resolve().parents[1]


class _ReentrantTestBus:
    """Synchronous fake EventBus that re-enters WorldGraph inside publish()."""

    def __init__(self, graph: WorldGraph) -> None:
        self.graph = graph
        self.events = []
        self.snapshots_inside_publish = []
        self.lock_was_held = []

    def publish(self, event) -> None:
        self.events.append(event)
        # Verify WorldGraph._lock is not held on another thread by probing from a worker thread
        held = [False]

        def _probe():
            acquired = self.graph._lock.acquire(blocking=False)
            if acquired:
                self.graph._lock.release()
                held[0] = False
            else:
                held[0] = True

        t = threading.Thread(target=_probe)
        t.start()
        t.join(timeout=2.0)
        self.lock_was_held.append(held[0])
        self.snapshots_inside_publish.append(self.graph.snapshot())


class TestWorldGraph(unittest.TestCase):
    """Verify scoped WorldGraph isolation, cascading removal, policy sync, and thread safety."""

    def test_scoped_graph_isolation(self):
        graph_a = WorldGraph()
        graph_b = WorldGraph()

        graph_a.register_camera(CameraNode(camera_id="cam_01", name="Lobby A"))
        graph_a.register_zone(ZoneNode(zone_id="entry", camera_id="cam_01", restricted=True))
        graph_a.upsert_entity(
            WorldEntity(entity_id=7, name="Alice", camera_tracks={"cam_01": 1})
        )
        graph_a.set_policy(alert_sensitivity=0.8)

        graph_b.register_camera(CameraNode(camera_id="cam_01", name="Warehouse B"))

        snap_a = graph_a.snapshot()
        snap_b = graph_b.snapshot()

        self.assertEqual(snap_a["cameras"]["cam_01"]["name"], "Lobby A")
        self.assertEqual(snap_b["cameras"]["cam_01"]["name"], "Warehouse B")
        self.assertEqual(snap_a["counts"], {"cameras": 1, "zones": 1, "tripwires": 0, "entities": 1})
        self.assertEqual(snap_b["counts"], {"cameras": 1, "zones": 0, "tripwires": 0, "entities": 0})
        self.assertAlmostEqual(snap_a["policy"]["alert_sensitivity"], 0.8)
        self.assertAlmostEqual(snap_b["policy"]["alert_sensitivity"], 1.0)

    def test_scoped_zone_and_tripwire_ids_across_cameras(self):
        graph = WorldGraph()
        graph.register_zone(ZoneNode(zone_id="entry", camera_id="cam_01", points=[(0, 0), (10, 10)]))
        graph.register_zone(ZoneNode(zone_id="entry", camera_id="cam_02", points=[(5, 5), (20, 20)]))
        graph.register_tripwire(TripwireNode(tripwire_id="door", camera_id="cam_01"))

        children_1 = graph.get_children("cam_01")
        children_2 = graph.get_children("cam_02")

        self.assertEqual(len(children_1["zones"]), 1)
        self.assertEqual(len(children_1["tripwires"]), 1)
        self.assertEqual(len(children_2["zones"]), 1)
        self.assertEqual(children_2["zones"][0].node_id, "cam_02:zone:entry")
        # Ambiguous zone_id across two cameras should return None unless scoped node_id is given
        self.assertIsNone(graph.get_node("entry"))
        self.assertIsNotNone(graph.get_node("cam_01:zone:entry"))
        # Unambiguous tripwire_id lookup succeeds
        self.assertIsNotNone(graph.get_node("door"))

        # Updating camera metadata later preserves child edge sets
        updated_cam = graph.register_camera(CameraNode(camera_id="cam_01", name="Front Door"))
        self.assertIn("cam_01:zone:entry", updated_cam.zone_ids)
        self.assertIn("cam_01:tripwire:door", updated_cam.tripwire_ids)

    def test_cascading_camera_removal_detaches_children_and_entity_bindings(self):
        bus = EventBus()
        captured = []
        bus.subscribe(captured.append)
        bus.start()
        self.addCleanup(bus.stop)

        graph = WorldGraph(event_bus=bus)
        graph.register_camera(CameraNode(camera_id="cam_01", name="Gate"))
        graph.register_camera(CameraNode(camera_id="cam_02", name="Hall"))
        zone1 = graph.register_zone(ZoneNode(zone_id="entry", camera_id="cam_01"))
        tw1 = graph.register_tripwire(TripwireNode(tripwire_id="line_a", camera_id="cam_01"))
        zone2 = graph.register_zone(ZoneNode(zone_id="hall_z", camera_id="cam_02"))

        graph.upsert_entity(
            WorldEntity(
                entity_id=7,
                name="Bob",
                camera_tracks={"cam_01": 1, "cam_02": 4},
                active_zones={"cam_01": {zone1.node_id}, "cam_02": {zone2.node_id}},
            )
        )

        removed = graph.remove_camera("cam_01")
        self.assertEqual(set(removed), {"cam_01", zone1.node_id, tw1.node_id})
        self.assertEqual(graph.remove_camera("cam_missing"), [])

        self.assertIsNone(graph.get_node("cam_01"))
        self.assertIsNone(graph.get_node(zone1.node_id))
        self.assertIsNone(graph.get_node(tw1.node_id))
        self.assertIsNotNone(graph.get_node("cam_02"))
        self.assertIsNotNone(graph.get_node(zone2.node_id))

        entity = graph.get_node("entity:7", node_type="entity")
        self.assertIsNotNone(entity)
        self.assertEqual(entity.camera_tracks, {"cam_02": 4})
        self.assertEqual(entity.active_zones, {"cam_02": {zone2.node_id}})

        self.assertTrue(bus.wait_until_empty(timeout=2.0))
        removed_events = [e for e in captured if isinstance(e, NodeRemovedEvent)]
        cam_removed = [e for e in removed_events if e.node_type == "camera"]
        self.assertEqual(len(cam_removed), 1)
        self.assertEqual(set(cam_removed[0].cascade_removed_ids), {zone1.node_id, tw1.node_id})
        self.assertTrue(
            any(
                isinstance(e, EntityStateChangedEvent) and e.change_type == "camera_detached"
                for e in captured
            )
        )

    def test_remove_node_and_mutation_isolation(self):
        graph = WorldGraph()
        graph.register_camera(CameraNode(camera_id="cam_01"))
        z = graph.register_zone(ZoneNode(zone_id="vault", camera_id="cam_01"))
        tw = graph.register_tripwire(TripwireNode(tripwire_id="door", camera_id="cam_01"))
        ent = graph.upsert_entity(
            WorldEntity(
                entity_id=12,
                camera_tracks={"cam_01": 9},
                active_zones={"cam_01": {z.node_id}},
            )
        )

        # Mutating returned copies does not leak into graph
        ent.camera_tracks["cam_01"] = 999
        self.assertEqual(graph.get_node("entity:12").camera_tracks["cam_01"], 9)

        self.assertTrue(graph.remove_node(z.node_id))
        self.assertEqual(graph.get_node("entity:12").active_zones, {})
        self.assertTrue(graph.remove_node(tw.node_id))
        self.assertTrue(graph.remove_node("entity:12"))
        self.assertFalse(graph.remove_node("unknown_node"))

        snap = graph.snapshot()
        # Snapshot must be cleanly JSON-serializable
        encoded = json.dumps(snap)
        self.assertIn("cam_01", encoded)

    def test_policy_propagation_and_validation(self):
        bus = EventBus()
        events = []
        bus.subscribe(events.append, event_type=WorldPolicyUpdatedEvent)
        bus.start()
        self.addCleanup(bus.stop)

        graph = WorldGraph(event_bus=bus)
        policy = graph.set_policy(
            quiet_hours={"start": "22:00", "end": "06:00"},
            dwell_override=15.0,
            alert_sensitivity=0.65,
            extra={"vip_bypass": True},
        )
        policy.extra["vip_bypass"] = False
        self.assertTrue(graph.get_policy().extra["vip_bypass"])

        replaced = graph.set_policy(WorldPolicy(alert_sensitivity=0.9))
        self.assertAlmostEqual(replaced.alert_sensitivity, 0.9)

        with self.assertRaises(ValueError):
            graph.set_policy(nonexistent_field=123)

        self.assertTrue(bus.wait_until_empty(timeout=2.0))
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].changed_fields, ["quiet_hours", "dwell_override", "alert_sensitivity", "extra"])

    def test_outside_lock_event_publish_allows_reentrant_reads_without_deadlock(self):
        graph = WorldGraph()
        reentrant_bus = _ReentrantTestBus(graph)
        graph._event_bus = reentrant_bus

        graph.register_camera(CameraNode(camera_id="cam_01"))
        graph.register_zone(ZoneNode(zone_id="z1", camera_id="cam_01"))
        graph.upsert_entity(WorldEntity(entity_id=1, camera_tracks={"cam_01": 1}))
        graph.set_policy(alert_sensitivity=0.5)
        graph.remove_camera("cam_01")

        self.assertTrue(len(reentrant_bus.events) >= 5)
        self.assertTrue(all(not held for held in reentrant_bus.lock_was_held))
        self.assertEqual(len(reentrant_bus.snapshots_inside_publish), len(reentrant_bus.events))

    def test_concurrent_readers_and_writers(self):
        graph = WorldGraph()
        errors = []

        def _writer(worker_idx: int) -> None:
            try:
                cam_id = f"cam_{worker_idx}"
                graph.register_camera(CameraNode(camera_id=cam_id))
                graph.register_zone(ZoneNode(zone_id="z", camera_id=cam_id))
                for step in range(25):
                    graph.upsert_entity(
                        WorldEntity(
                            entity_id=worker_idx * 100 + step,
                            camera_tracks={cam_id: step + 1},
                        )
                    )
                graph.remove_camera(cam_id)
            except Exception as exc:
                errors.append(exc)

        def _reader() -> None:
            try:
                for _ in range(60):
                    snap = graph.snapshot()
                    self.assertIn("counts", snap)
                    graph.get_children("cam_0")
                    graph.get_policy()
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_writer, args=(i,)) for i in range(4)]
        threads.extend(threading.Thread(target=_reader) for _ in range(3))
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)
            self.assertFalse(t.is_alive())

        self.assertEqual(errors, [])

    def test_validation_and_layer_boundary_isolation(self):
        graph = WorldGraph()
        with self.assertRaises(ValueError):
            graph.register_camera(CameraNode(camera_id=""))
        with self.assertRaises(ValueError):
            graph.register_zone(ZoneNode(zone_id="z1", camera_id=""))
        with self.assertRaises(ValueError):
            graph.register_tripwire(TripwireNode(tripwire_id="", camera_id="cam_01"))

        world_dir = ROOT_DIR / "intelligent_tracker" / "world"
        for py_file in world_dir.rglob("*.py"):
            tree = ast.parse(py_file.read_bytes(), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root_pkg = alias.name.split(".")[0]
                        self.assertNotIn(root_pkg, {"dashboard", "scripts"})
                elif isinstance(node, ast.ImportFrom) and node.module:
                    root_pkg = node.module.split(".")[0]
                    self.assertNotIn(root_pkg, {"dashboard", "scripts"})


if __name__ == "__main__":
    unittest.main()

