"""Step 4 Milestone 4 tests: multi-camera handoff, overlap deduplication, tactical minimap, and /api/topology/world-map."""

import ast
import json
import os
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
import numpy as np

from dashboard.app import app
from dashboard.dependencies import bind_app_state, clear_app_state
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.homography import GroundPlaneHomography
from intelligent_tracker.journey import TrajectoryJourneySearcher
from intelligent_tracker.scenarios import ScenarioManager
from intelligent_tracker.topology import SpatialTransitionLink
from intelligent_tracker.tracker import Track
from intelligent_tracker.world import (
    CameraWorldPose,
    GlobalCoordinateMapper,
    MultiCameraHandoffCoordinator,
    TransitionEdgeNode,
    WorldEntityBridge,
    WorldGraph,
    WorldTacticalMinimap,
    WorldTransitionRegistry,
)

ROOT_DIR = Path(__file__).resolve().parents[1]


def _make_homography(camera_id: str, width: float = 10.0, height: float = 10.0) -> GroundPlaneHomography:
    """Create a 100x100px -> width x height meter homography."""
    return GroundPlaneHomography(
        src_points=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        dst_points=[(0.0, 0.0), (width, 0.0), (width, height), (0.0, height)],
        metric_width=width,
        metric_height=height,
        camera_id=camera_id,
    )


def _ast_budgets(rel_path: str) -> tuple[int, dict[str, int], list[tuple[str, int]]]:
    source = (ROOT_DIR / rel_path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=rel_path)
    cls_counts: dict[str, int] = {}
    oversized: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            cls_counts[node.name] = sum(
                1 for c in node.body if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            length = getattr(node, "end_lineno", node.lineno) - node.lineno + 1
            if length > 40:
                oversized.append((node.name, length))
    return len(source.splitlines()), cls_counts, oversized


class TestMultiCameraHandoff(unittest.TestCase):
    """Verify overlapping FOV deduplication, two-camera transit handoff, minimap, and API."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.db = TrackerDB(os.path.join(self.tmpdir.name, "handoff.db"))
        self.addCleanup(self.db.close)
        self.yaml_path = os.path.join(self.tmpdir.name, "scenarios.yaml")

    def test_milestone4_exports_and_modularity_budgets(self) -> None:
        self.assertIsNotNone(TransitionEdgeNode)
        self.assertIsNotNone(WorldTransitionRegistry)
        self.assertIsNotNone(MultiCameraHandoffCoordinator)
        self.assertIsNotNone(WorldTacticalMinimap)

        budgets = {
            "intelligent_tracker/world/handoff.py": (240, {"MultiCameraHandoffCoordinator": 9}),
            "intelligent_tracker/world/_handoff_helpers.py": (200, {}),
            "intelligent_tracker/world/minimap.py": (230, {"WorldTacticalMinimap": 8}),
            "intelligent_tracker/world/_minimap_render.py": (160, {}),
            "dashboard/routers/topology.py": (240, {}),
        }
        for rel_path, (max_lines, max_methods) in budgets.items():
            lines, cls_counts, oversized = _ast_budgets(rel_path)
            self.assertLess(lines, max_lines, f"{rel_path} has {lines} lines (budget < {max_lines})")
            self.assertEqual(oversized, [], f"{rel_path} has >40L functions: {oversized}")
            for cls_name, limit in max_methods.items():
                self.assertLessEqual(cls_counts.get(cls_name, 0), limit)

    def test_overlapping_fov_deduplication_and_reid_guard(self) -> None:
        graph = WorldGraph()
        mapper = GlobalCoordinateMapper()
        mapper.register_camera("cam_01", _make_homography("cam_01"), CameraWorldPose("cam_01", 0.0, 0.0, 0.0))
        mapper.register_camera("cam_02", _make_homography("cam_02"), CameraWorldPose("cam_02", 0.3, 0.1, 0.0))

        coordinator = MultiCameraHandoffCoordinator(graph, coordinate_mapper=mapper, overlap_radius_m=1.2)
        t1 = Track(track_id=1, bbox=(40, 20, 20, 40), label="person", timestamp=100.0)
        t1.session_id = 101
        t2 = Track(track_id=2, bbox=(40, 20, 20, 40), label="person", timestamp=100.2)
        t2.session_id = 202

        e1 = coordinator.handoff_track("cam_01", t1, embedding=[1.0, 0.0, 0.0], timestamp=100.0)
        e2 = coordinator.handoff_track("cam_02", t2, embedding=[0.95, 0.1, 0.0], timestamp=100.2)
        self.assertEqual(e1.world_entity_id, e2.world_entity_id)
        self.assertEqual(e2.camera_tracks, {"cam_01": 1, "cam_02": 2})

        # Post-hoc bridge deduplication merges compatible entities, but rejects orthogonal Re-ID
        bridge = WorldEntityBridge(graph, db=self.db, coordinate_mapper=mapper)
        s_a = Track(track_id=11, bbox=(10, 10, 20, 40), label="person", timestamp=200.0)
        s_b = Track(track_id=12, bbox=(10, 10, 20, 40), label="person", timestamp=200.1)
        ent_a = bridge.sync_session_track("cam_01", s_a, session_id=11, timestamp=200.0)
        ent_b = bridge.sync_session_track("cam_02", s_b, session_id=12, timestamp=200.1)
        coordinator.register_embedding(ent_a.world_entity_id, [1.0, 0.0, 0.0])
        coordinator.register_embedding(ent_b.world_entity_id, [0.0, 1.0, 0.0])
        self.assertEqual(coordinator.deduplicate_overlapping_entities(timestamp=200.2), [])

        coordinator.register_embedding(ent_b.world_entity_id, [0.98, 0.05, 0.0])
        merges = coordinator.deduplicate_overlapping_entities(timestamp=200.2)
        self.assertEqual(len(merges), 1)
        kept = graph.get_node(merges[0][0], node_type="entity")
        self.assertEqual(kept.camera_tracks, {"cam_01": 11, "cam_02": 12})

    def test_golden_two_camera_handoff_minimap_api_and_journey(self) -> None:
        graph = WorldGraph()
        mapper = GlobalCoordinateMapper()
        mapper.register_camera("cam_01", _make_homography("cam_01"), CameraWorldPose("cam_01", 0.0, 0.0, 0.0))
        mapper.register_camera("cam_02", _make_homography("cam_02"), CameraWorldPose("cam_02", 12.0, 0.0, 0.0))

        sm = ScenarioManager(config_path=self.yaml_path, db=self.db, world_graph=graph, coordinate_mapper=mapper)
        sm.save_homography("cam_01", [(0, 0), (100, 0), (100, 100), (0, 100)])
        sm.save_homography("cam_02", [(0, 0), (100, 0), (100, 100), (0, 100)])
        sm.save_zone("cam_01", "exit_zone", [(70, 30), (100, 30), (100, 70), (70, 70)])
        sm.save_zone("cam_02", "entry_zone", [(0, 30), (30, 30), (30, 70), (0, 70)])
        sm.topology.add_link(SpatialTransitionLink(
            link_id="c1_to_c2", source_camera="cam_01", source_zone="exit_zone",
            target_camera="cam_02", target_zone="entry_zone", t_min=1.0, t_max=10.0, prior_boost=0.35,
        ))

        eid = self.db.add_entity("Agent Alice", category="vip")
        coordinator = MultiCameraHandoffCoordinator(graph, coordinate_mapper=mapper, topology=sm.topology)
        emb_alice = np.array([1.0, 0.2, 0.0], dtype=np.float32)

        # Subject walks across cam_01 toward exit_zone (t=1000..1002)
        t_cam1 = Track(track_id=10, bbox=(40, 10, 20, 40), label="person", timestamp=1000.0)
        t_cam1.entity_id = eid
        t_cam1.entity_name = "Agent Alice"
        t_cam1.entity_category = "vip"
        we1 = coordinator.handoff_track("cam_01", t_cam1, embedding=emb_alice, timestamp=1000.0)
        self.db.add_sighting(eid, track_id=10, source="cam_01", timestamp="2026-11-13T10:00:00", zone_id="exit_zone", bbox=[40, 10, 20, 40], confidence=0.95)

        t_cam1.bbox = (80, 10, 20, 40)
        we1 = coordinator.handoff_track("cam_01", t_cam1, zone_id="exit_zone", embedding=emb_alice, timestamp=1002.0)
        self.db.add_sighting(eid, track_id=10, source="cam_01", timestamp="2026-11-13T10:00:02", zone_id="exit_zone", bbox=[80, 10, 20, 40], confidence=0.95)

        coordinator.record_zone_exit("cam_01", "exit_zone", entity_id=eid, world_entity_id=we1.world_entity_id, embedding=emb_alice, timestamp=1002.0)

        # Subject enters cam_02 at t=1005 with a brand-new local track_id=88 (unidentified yet)
        t_cam2 = Track(track_id=88, bbox=(10, 10, 20, 40), label="person", timestamp=1005.0)
        we2 = coordinator.handoff_track("cam_02", t_cam2, zone_id="entry_zone", visual_similarity=0.30, timestamp=1005.0)
        self.db.add_sighting(t_cam2.entity_id, track_id=88, source="cam_02", timestamp="2026-11-13T10:00:05", zone_id="entry_zone", bbox=[10, 10, 20, 40], confidence=0.93)

        self.assertEqual(we2.world_entity_id, we1.world_entity_id)
        self.assertEqual(t_cam2.entity_id, eid)
        self.assertEqual(we2.camera_tracks, {"cam_01": 10, "cam_02": 88})
        self.assertEqual(len(we2.global_trajectory), 3)
        self.assertLess(we2.global_trajectory[0][0], 10.0)
        self.assertGreater(we2.global_trajectory[-1][0], 12.0)

        # Verify tactical minimap telemetry + BEV image
        minimap = WorldTacticalMinimap(graph, coordinate_mapper=mapper)
        telemetry = minimap.build_world_minimap_telemetry()
        self.assertEqual(telemetry["counts"]["cameras"], 2)
        self.assertEqual(telemetry["counts"]["zones"], 2)
        self.assertEqual(telemetry["counts"]["transitions"], 1)
        self.assertEqual(telemetry["counts"]["entities"], 1)
        self.assertIsNotNone(telemetry["transitions"][0]["source_xy"])
        self.assertIsNotNone(telemetry["transitions"][0]["target_xy"])
        canvas = minimap.render_world_minimap(canvas_size=(480, 320))
        self.assertEqual(canvas.shape, (320, 480, 3))
        self.assertGreater(int(np.sum(canvas > 0)), 0)

        # Verify /api/topology/world-map endpoint
        bind_app_state(app, scenario_manager=sm, db=self.db)
        self.addCleanup(clear_app_state, app)
        client = TestClient(app)
        resp = client.get("/api/topology/world-map")
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["counts"]["entities"], 1)
        self.assertEqual(payload["entities"][0]["world_entity_id"], we1.world_entity_id)

        # Verify 2-hop TrajectoryJourneySearcher global path continuity
        journey = TrajectoryJourneySearcher(self.db, coordinate_mapper=mapper).search_journey(entity_id=eid)
        self.assertEqual(journey.total_hops, 2)
        self.assertEqual(len(journey.global_path), 3)
        self.assertLess(journey.global_start_xy[0], 10.0)
        self.assertGreater(journey.global_end_xy[0], 12.0)

    def test_kinematic_rejection_category_mismatch_and_registry_fallback(self) -> None:
        graph = WorldGraph()
        mapper = GlobalCoordinateMapper()
        mapper.register_camera("cam_01", _make_homography("cam_01"), CameraWorldPose("cam_01", 0.0, 0.0, 0.0))
        mapper.register_camera("cam_02", _make_homography("cam_02"), CameraWorldPose("cam_02", 50.0, 0.0, 0.0))

        registry = WorldTransitionRegistry(graph, coordinate_mapper=mapper, max_transit_speed_mps=12.0)
        registry.register_edge(TransitionEdgeNode(
            link_id="edge_far", source_camera="cam_01", source_zone="exit",
            target_camera="cam_02", target_zone="entry", t_min=0.1, t_max=10.0, prior_boost=0.35,
        ))
        coordinator = MultiCameraHandoffCoordinator(
            graph, coordinate_mapper=mapper, transition_registry=registry, max_transit_speed_mps=12.0,
        )

        t1 = Track(track_id=1, bbox=(80, 10, 20, 40), label="person", timestamp=500.0)
        t1.session_id = 1
        we1 = coordinator.handoff_track("cam_01", t1, zone_id="exit", timestamp=500.0)
        coordinator.record_zone_exit("cam_01", "exit", world_entity_id=we1.world_entity_id, timestamp=500.0)

        # Vehicle track ("car") must not match a person prior even inside window
        t_car = Track(track_id=2, bbox=(10, 10, 20, 40), label="car", timestamp=505.0)
        we_car = coordinator.handoff_track("cam_02", t_car, zone_id="entry", timestamp=505.0)
        self.assertNotEqual(we_car.world_entity_id, we1.world_entity_id)

        # Teleporting 43m in 0.2s (~215 m/s > 12 m/s) must be rejected by kinematic speed gating
        t_fast = Track(track_id=3, bbox=(10, 10, 20, 40), label="person", timestamp=500.2)
        we_fast = coordinator.handoff_track("cam_02", t_fast, zone_id="entry", timestamp=500.2)
        self.assertNotEqual(we_fast.world_entity_id, we1.world_entity_id)

        # Plausible arrival at t=505.0 (~8.6 m/s <= 12 m/s) via sync_camera_tracks matches we1
        t_ok = Track(track_id=4, bbox=(10, 10, 20, 40), label="person", timestamp=505.0)
        synced = coordinator.sync_camera_tracks("cam_02", {4: t_ok}, zone_lookup={4: "entry"}, timestamp=505.0)
        self.assertEqual(synced[0].world_entity_id, we1.world_entity_id)
        self.assertEqual(synced[0].camera_tracks["cam_02"], 4)


if __name__ == "__main__":
    unittest.main()
