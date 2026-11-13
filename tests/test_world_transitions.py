"""Unit tests for WorldTransitionRegistry, TransitionEdgeNode, and kinematic Bayesian priors."""

import ast
import os
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.camera_pool import CameraPool
from dashboard.dependencies import bind_app_state, clear_app_state
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.events import EventBus
from intelligent_tracker.scenarios import ScenarioManager
from intelligent_tracker.topology import CrossCameraTopology, SpatialTransitionLink
from intelligent_tracker.world import (
    CameraNode,
    NodeAddedEvent,
    NodeRemovedEvent,
    TransitionEdgeNode,
    WorldEntity,
    WorldGraph,
    WorldTransitionRegistry,
)

ROOT_DIR = Path(__file__).resolve().parents[1]


class TestWorldTransitions(unittest.TestCase):
    """Verify TransitionEdgeNode lifecycle, cascading camera cleanup, and kinematic priors."""

    def test_transition_edge_registration_bidirectional_and_events(self) -> None:
        bus = EventBus()
        captured: list[object] = []
        bus.subscribe(captured.append)
        bus.start()
        self.addCleanup(bus.stop)

        graph = WorldGraph(event_bus=bus)
        registry = WorldTransitionRegistry(graph)

        edge = TransitionEdgeNode(
            link_id="gate_to_lobby",
            source_camera="cam_01",
            source_zone="Exit",
            target_camera="cam_02",
            target_zone="Entry",
            t_min=2.0,
            t_max=12.0,
            prior_boost=0.35,
            bidirectional=True,
        )
        created = registry.register_edge(edge)
        self.assertEqual(len(created), 2)
        self.assertIsNotNone(graph.get_node("gate_to_lobby", node_type="transition"))
        rev_node = graph.get_node("gate_to_lobby_rev", node_type="transition")
        self.assertIsNotNone(rev_node)
        self.assertEqual(rev_node.source_camera, "cam_02")
        self.assertEqual(rev_node.target_camera, "cam_01")
        self.assertFalse(rev_node.bidirectional)

        snap = graph.snapshot()
        self.assertIn("gate_to_lobby", snap["transitions"])
        self.assertIn("gate_to_lobby_rev", snap["transitions"])
        self.assertEqual(len(registry.list_edges(include_reverse=False)), 1)

        self.assertTrue(registry.remove_edge("gate_to_lobby"))
        self.assertFalse(registry.remove_edge("gate_to_lobby"))
        self.assertIsNone(graph.get_node("gate_to_lobby", node_type="transition"))
        self.assertIsNone(graph.get_node("gate_to_lobby_rev", node_type="transition"))

        # Verify WorldGraph.remove_node() also removes TransitionEdgeNode directly
        registry.register_edge(
            TransitionEdgeNode(
                link_id="direct_edge",
                source_camera="cam_01",
                source_zone="Exit",
                target_camera="cam_02",
                target_zone="Entry",
            )
        )
        self.assertTrue(graph.remove_node("direct_edge"))
        self.assertIsNone(graph.get_node("direct_edge", node_type="transition"))

        self.assertTrue(bus.wait_until_empty(timeout=2.0))
        added_types = [e.node_type for e in captured if isinstance(e, NodeAddedEvent)]
        removed_types = [e.node_type for e in captured if isinstance(e, NodeRemovedEvent)]
        self.assertEqual(added_types.count("transition"), 3)
        self.assertEqual(removed_types.count("transition"), 3)

    def test_cascading_cleanup_on_camera_deletion(self) -> None:
        bus = EventBus()
        captured: list[object] = []
        bus.subscribe(captured.append)
        bus.start()
        self.addCleanup(bus.stop)

        graph = WorldGraph(event_bus=bus)
        graph.register_camera(CameraNode(camera_id="cam_01", name="Gate"))
        graph.register_camera(CameraNode(camera_id="cam_02", name="Lobby"))
        graph.register_camera(CameraNode(camera_id="cam_03", name="Dock"))

        registry = WorldTransitionRegistry(graph)
        topo = CrossCameraTopology(world_transitions=registry)
        topo.add_link(
            SpatialTransitionLink(
                link_id="l_1_2",
                source_camera="cam_01",
                source_zone="Exit",
                target_camera="cam_02",
                target_zone="Entry",
                bidirectional=True,
            )
        )
        topo.add_link(
            SpatialTransitionLink(
                link_id="l_2_3",
                source_camera="cam_02",
                source_zone="Corridor",
                target_camera="cam_03",
                target_zone="Bay",
            )
        )

        removed = graph.remove_camera("cam_01")
        self.assertIn("cam_01", removed)
        self.assertIn("l_1_2", removed)
        self.assertIn("l_1_2_rev", removed)
        self.assertIsNone(graph.get_node("l_1_2", node_type="transition"))
        self.assertIsNone(graph.get_node("l_1_2_rev", node_type="transition"))
        self.assertIsNotNone(graph.get_node("l_2_3", node_type="transition"))

        remaining_ids = [lnk.link_id for lnk in topo.list_links()]
        self.assertEqual(remaining_ids, ["l_2_3"])
        self.assertEqual(topo.record_zone_exit("cam_01", "Exit", entity_id=1, timestamp=100.0), [])

        # Orphan pruning when a transition references an unregistered camera
        registry.register_edge(
            TransitionEdgeNode(
                link_id="orphan_edge",
                source_camera="cam_02",
                source_zone="A",
                target_camera="cam_missing",
                target_zone="B",
            )
        )
        pruned = registry.prune_orphaned_edges()
        self.assertEqual(pruned, ["orphan_edge"])

        self.assertTrue(bus.wait_until_empty(timeout=2.0))
        self.assertTrue(
            any(isinstance(e, NodeRemovedEvent) and e.node_id == "l_1_2" for e in captured)
        )

    def test_kinematic_aware_bayesian_prior_boosting(self) -> None:
        graph = WorldGraph()
        registry = WorldTransitionRegistry(graph, max_transit_speed_mps=5.0)
        topo = CrossCameraTopology(world_transitions=registry, max_transit_speed_mps=5.0)
        topo.add_link(
            SpatialTransitionLink(
                link_id="hall_link",
                source_camera="cam_01",
                source_zone="Exit",
                target_camera="cam_02",
                target_zone="Entry",
                t_min=2.0,
                t_max=10.0,
                prior_boost=0.35,
            )
        )
        graph.upsert_entity(
            WorldEntity(
                entity_id=42,
                name="Alice",
                camera_tracks={"cam_01": 1},
                global_xy=(2.0, 3.0),
            )
        )

        # Exit resolves global_xy=(2.0, 3.0) automatically from WorldGraph
        priors = topo.record_zone_exit(
            camera_id="cam_01",
            zone_name="Exit",
            entity_name="Alice",
            entity_id=42,
            timestamp=100.0,
        )
        self.assertEqual(len(priors), 1)
        self.assertEqual(priors[0].exit_global_xy, (2.0, 3.0))

        # Plausible travel: 8m in 4s -> 2.0 m/s <= 5.0 m/s -> boosted
        score_ok, matched_ok = topo.compute_weighted_similarity(
            visual_similarity=0.60,
            candidate_entity_id=42,
            candidate_name="Alice",
            target_camera="cam_02",
            target_zone="Entry",
            timestamp=104.0,
            candidate_global_xy=(10.0, 3.0),
        )
        self.assertIsNotNone(matched_ok)
        self.assertAlmostEqual(score_ok, 0.95, places=4)

        # Implausible teleportation: 100m in 4s -> 25.0 m/s > 5.0 m/s -> gated out
        score_bad, matched_bad = topo.compute_weighted_similarity(
            visual_similarity=0.60,
            candidate_entity_id=42,
            candidate_name="Alice",
            target_camera="cam_02",
            target_zone="Entry",
            timestamp=104.0,
            candidate_global_xy=(102.0, 3.0),
        )
        self.assertIsNone(matched_bad)
        self.assertAlmostEqual(score_bad, 0.60, places=4)

        # Registry direct query also enforces kinematic speed gating
        self.assertEqual(
            len(registry.query_active_priors("cam_02", "Entry", candidate_global_xy=(10.0, 3.0), timestamp=104.0)),
            1,
        )
        self.assertEqual(
            len(registry.query_active_priors("cam_02", "Entry", candidate_global_xy=(102.0, 3.0), timestamp=104.0)),
            0,
        )

        # Consuming prior marks both CrossCameraTopology and WorldTransitionRegistry
        self.assertTrue(topo.consume_prior(priors[0].prior_id))
        self.assertEqual(
            registry.query_active_priors("cam_02", "Entry", candidate_global_xy=(10.0, 3.0), timestamp=104.0),
            [],
        )

    def test_scenario_manager_and_api_sync_transitions_to_world_graph(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        yaml_path = os.path.join(tmpdir.name, "scenarios.yaml")
        db_path = os.path.join(tmpdir.name, "tracker.db")
        cam_cfg = os.path.join(tmpdir.name, "cameras.json")

        db = TrackerDB(db_path)
        self.addCleanup(db.close)

        graph = WorldGraph()
        sm = ScenarioManager(config_path=yaml_path, db=db, world_graph=graph)
        self.assertIsNotNone(sm.world_transitions)

        pool = CameraPool(config_file=cam_cfg, db_path=db_path, autostart=False)
        self.addCleanup(pool.stop_all)
        bind_app_state(app, camera_pool=pool, stream_manager=pool.primary_stream, scenario_manager=sm, db=db)
        self.addCleanup(clear_app_state, app)

        client = TestClient(app)
        resp = client.post(
            "/api/topology/transitions",
            json={
                "link_id": "api_link_1",
                "source_camera": "cam_01",
                "source_zone": "Gate",
                "target_camera": "cam_02",
                "target_zone": "Lobby",
                "t_min": 2.0,
                "t_max": 12.0,
                "prior_boost": 0.35,
                "bidirectional": True,
                "active": True,
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(graph.get_node("api_link_1", node_type="transition"))
        self.assertIsNotNone(graph.get_node("api_link_1_rev", node_type="transition"))

        # Reload ScenarioManager against fresh WorldGraph from DB -> edges materialize automatically
        reloaded_graph = WorldGraph()
        reloaded_sm = ScenarioManager(config_path=yaml_path, db=db, world_graph=reloaded_graph)
        self.assertIsNotNone(reloaded_graph.get_node("api_link_1", node_type="transition"))
        self.assertIsNotNone(reloaded_graph.get_node("api_link_1_rev", node_type="transition"))
        self.assertEqual(len(reloaded_sm.world_transitions.list_edges(include_reverse=False)), 1)

        del_resp = client.delete("/api/topology/transitions/api_link_1")
        self.assertEqual(del_resp.status_code, 200)
        self.assertIsNone(graph.get_node("api_link_1", node_type="transition"))
        self.assertIsNone(graph.get_node("api_link_1_rev", node_type="transition"))

    def test_milestone3_modularity_budgets(self) -> None:
        budgets = {
            "intelligent_tracker/world/nodes.py": 260,
            "intelligent_tracker/world/transitions.py": 230,
            "intelligent_tracker/world/graph.py": 300,
            "intelligent_tracker/world/_lifecycle.py": 330,
            "intelligent_tracker/topology.py": 340,
            "intelligent_tracker/scenarios.py": 230,
            "intelligent_tracker/scenario_storage.py": 240,
        }
        for rel_path, max_lines in budgets.items():
            source = (ROOT_DIR / rel_path).read_text(encoding="utf-8")
            lines = len(source.splitlines())
            self.assertLess(lines, max_lines, f"{rel_path} has {lines} lines (budget < {max_lines})")
            tree = ast.parse(source, filename=rel_path)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    methods = [c for c in node.body if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef))]
                    self.assertLessEqual(len(methods), 12, f"{rel_path}:{node.name} has {len(methods)} methods")
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    length = getattr(node, "end_lineno", node.lineno) - node.lineno + 1
                    self.assertLessEqual(length, 40, f"{rel_path}:{node.name} is {length} lines (> 40)")


if __name__ == "__main__":
    unittest.main()
