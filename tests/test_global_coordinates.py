"""Unit tests for GlobalCoordinateMapper, WorldEntity global projection, ScenarioManager sync, and Journey global paths."""

from datetime import datetime
import os
import tempfile
import unittest

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.homography import GroundPlaneHomography
from intelligent_tracker.journey import TrajectoryJourneySearcher
from intelligent_tracker.scenarios import ScenarioManager
from intelligent_tracker.tracker import Track
from intelligent_tracker.world import (
    CameraNode,
    CameraWorldPose,
    GlobalCoordinateMapper,
    WorldEntityBridge,
    WorldGraph,
)


def _identity_homography(camera_id: str, width: float = 10.0, height: float = 10.0) -> GroundPlaneHomography:
    """Create a clean 4-point calibrated homography mapping [0..100]px -> [0..W]x[0..H] meters."""
    return GroundPlaneHomography(
        src_points=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        dst_points=[(0.0, 0.0), (width, 0.0), (width, height), (0.0, height)],
        metric_width=width,
        metric_height=height,
        camera_id=camera_id,
    )


class TestGlobalCoordinates(unittest.TestCase):
    """Verify multi-camera global coordinate mapping, bridge trajectories, and journey projection."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.db_path = os.path.join(self.tmpdir.name, "global_coords.db")
        self.yaml_path = os.path.join(self.tmpdir.name, "scenarios.yaml")
        self.db = TrackerDB(self.db_path)
        self.addCleanup(self.db.close)

    def test_camera_world_pose_forward_and_inverse(self) -> None:
        with self.assertRaises(ValueError):
            CameraWorldPose(camera_id="cam_bad", scale=0.0)

        pose = CameraWorldPose(camera_id="cam_rot", origin_x=10.0, origin_y=5.0, yaw_deg=90.0, scale=2.0)
        gx, gy = pose.to_global((3.0, 1.0))
        # Scaled local = (6.0, 2.0); rotated +90 deg -> (-2.0, 6.0); translated -> (8.0, 11.0)
        self.assertAlmostEqual(gx, 8.0, places=4)
        self.assertAlmostEqual(gy, 11.0, places=4)

        lx, ly = pose.to_local((gx, gy))
        self.assertAlmostEqual(lx, 3.0, places=4)
        self.assertAlmostEqual(ly, 1.0, places=4)

    def test_global_coordinate_mapper_two_cameras_and_inverse(self) -> None:
        mapper = GlobalCoordinateMapper()
        with self.assertRaises(ValueError):
            mapper.register_camera("")
        with self.assertRaises(ValueError):
            mapper.register_camera("cam_01", pose=CameraWorldPose(camera_id="cam_other"))

        h1 = _identity_homography("cam_01", width=10.0, height=10.0)
        h2 = _identity_homography("cam_02", width=10.0, height=10.0)
        mapper.register_camera("cam_01", homography=h1, pose=CameraWorldPose("cam_01", origin_x=0.0, origin_y=0.0, yaw_deg=0.0))
        mapper.register_camera("cam_02", homography=h2, pose=CameraWorldPose("cam_02", origin_x=10.0, origin_y=0.0, yaw_deg=90.0))

        self.assertTrue(mapper.has_camera("cam_01"))
        self.assertFalse(mapper.has_camera("cam_missing"))
        self.assertIs(mapper.get_homography("cam_01"), h1)
        self.assertEqual(mapper.get_pose("cam_02").origin_x, 10.0)

        # cam_01 pixel (50, 50) -> local (5.0, 5.0) -> global (5.0, 5.0)
        gx1, gy1 = mapper.camera_to_global("cam_01", (50.0, 50.0))
        self.assertAlmostEqual(gx1, 5.0, places=3)
        self.assertAlmostEqual(gy1, 5.0, places=3)

        # cam_02 pixel (50, 50) -> local (5.0, 5.0) -> rotated 90 deg (-5, 5) + (10, 0) = (5.0, 5.0)
        gx2, gy2 = mapper.camera_to_global("cam_02", (50.0, 50.0))
        self.assertAlmostEqual(gx2, 5.0, places=3)
        self.assertAlmostEqual(gy2, 5.0, places=3)

        # Inverse round-trip back to pixel space
        ux, vy = mapper.global_to_camera("cam_02", (gx2, gy2))
        self.assertAlmostEqual(ux, 50.0, places=2)
        self.assertAlmostEqual(vy, 50.0, places=2)

        # BBox bottom-center projection: bbox=(40, 20, 20, 40) -> contact=(50, 60) -> local=(5, 6)
        bx, by = mapper.project_track_bbox("cam_01", (40, 20, 20, 40))
        self.assertAlmostEqual(bx, 5.0, places=3)
        self.assertAlmostEqual(by, 6.0, places=3)

        # Polygon projection & empty polygon edge case
        self.assertEqual(mapper.project_polygon("cam_01", []), [])
        poly = mapper.project_polygon("cam_02", [(0.0, 0.0), (100.0, 0.0)])
        self.assertAlmostEqual(poly[0][0], 10.0, places=3)
        self.assertAlmostEqual(poly[0][1], 0.0, places=3)
        self.assertAlmostEqual(poly[1][0], 10.0, places=3)
        self.assertAlmostEqual(poly[1][1], 10.0, places=3)

        # Unregistered camera identity fallback
        self.assertEqual(mapper.camera_to_global("cam_unreg", (12.0, 34.0)), (12.0, 34.0))
        self.assertEqual(mapper.global_to_camera("cam_unreg", (12.0, 34.0)), (12.0, 34.0))

    def test_world_entity_bridge_projects_global_xy_and_bounded_trajectory(self) -> None:
        graph = WorldGraph()
        mapper = GlobalCoordinateMapper()
        mapper.register_camera(
            "cam_01",
            homography=_identity_homography("cam_01", width=10.0, height=10.0),
            pose=CameraWorldPose("cam_01", origin_x=2.0, origin_y=3.0, yaw_deg=0.0),
        )
        graph.register_camera(CameraNode(camera_id="cam_01", name="Gate"))

        bridge = WorldEntityBridge(
            graph, db=self.db, sync_interval=0.0, coordinate_mapper=mapper, max_trajectory_points=3
        )
        eid = self.db.add_entity(name="Alice", category="staff")

        for idx, px in enumerate([10, 20, 30, 40]):
            trk = Track(track_id=1, bbox=(px, 10, 20, 40), timestamp=100.0 + idx)
            we = bridge.sync_track_identification("cam_01", trk, eid, timestamp=100.0 + idx)

        self.assertIsNotNone(we.global_xy)
        # Last bbox=(40, 10, 20, 40) -> contact=(50, 50) -> local=(5, 5) + origin(2, 3) = (7.0, 8.0)
        self.assertAlmostEqual(we.global_xy[0], 7.0, places=3)
        self.assertAlmostEqual(we.global_xy[1], 8.0, places=3)
        self.assertEqual(len(we.global_trajectory), 3)
        self.assertAlmostEqual(we.global_trajectory[0][0], 5.0, places=3)
        self.assertAlmostEqual(we.global_trajectory[-1][0], 7.0, places=3)
        self.assertEqual(we.global_trajectory[-1][2], 103.0)

    def test_world_entity_bridge_resolves_camera_node_matrix_and_pose(self) -> None:
        graph = WorldGraph()
        homo = _identity_homography("cam_node", width=10.0, height=10.0)
        graph.register_camera(
            CameraNode(
                camera_id="cam_node",
                homography=homo.H.tolist(),
                world_pose=(20.0, 10.0, 0.0),
            )
        )
        bridge = WorldEntityBridge(graph, db=self.db, sync_interval=0.0)
        trk = Track(track_id=2, bbox=(40, 10, 20, 40), timestamp=50.0)
        we = bridge.sync_session_track("cam_node", trk, session_id="s1", timestamp=50.0)

        self.assertIsNotNone(we.global_xy)
        self.assertAlmostEqual(we.global_xy[0], 25.0, places=3)
        self.assertAlmostEqual(we.global_xy[1], 15.0, places=3)
        self.assertEqual(len(we.global_trajectory), 1)

    def test_scenario_manager_syncs_homography_to_world_graph_and_mapper(self) -> None:
        graph = WorldGraph()
        mapper = GlobalCoordinateMapper()
        mgr = ScenarioManager(
            config_path=self.yaml_path,
            db=self.db,
            world_graph=graph,
            coordinate_mapper=mapper,
        )
        mgr.save_homography(
            camera_id="cam_01",
            src_points=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
            metric_width=8.0,
            metric_height=6.0,
        )

        cam_node = graph.get_node("cam_01", node_type="camera")
        self.assertIsNotNone(cam_node)
        self.assertIsNotNone(cam_node.homography)
        self.assertTrue(mapper.has_camera("cam_01"))

        # Reloading into a fresh ScenarioManager + graph/mapper restores homography sync
        graph2 = WorldGraph()
        mapper2 = GlobalCoordinateMapper()
        ScenarioManager(
            config_path=self.yaml_path,
            db=self.db,
            world_graph=graph2,
            coordinate_mapper=mapper2,
        )
        self.assertIsNotNone(graph2.get_node("cam_01", node_type="camera"))
        self.assertTrue(mapper2.has_camera("cam_01"))

    def test_trajectory_journey_searcher_projects_global_paths(self) -> None:
        eid = self.db.add_entity(name="Traveler", category="visitor")
        base_t = 1700000000.0
        self.db.add_sighting(
            entity_id=eid, track_id=1, source="cam_01",
            timestamp=datetime.fromtimestamp(base_t).isoformat(), bbox=[40, 10, 20, 40],
        )
        self.db.add_sighting(
            entity_id=eid, track_id=2, source="cam_02",
            timestamp=datetime.fromtimestamp(base_t + 12.0).isoformat(), bbox=[40, 10, 20, 40],
        )

        mapper = GlobalCoordinateMapper()
        mapper.register_camera("cam_01", _identity_homography("cam_01"), CameraWorldPose("cam_01", origin_x=0.0, origin_y=0.0))
        mapper.register_camera("cam_02", _identity_homography("cam_02"), CameraWorldPose("cam_02", origin_x=15.0, origin_y=0.0))

        searcher = TrajectoryJourneySearcher(self.db, coordinate_mapper=mapper)
        journey = searcher.search_journey(entity_id=eid)

        self.assertEqual(journey.total_hops, 2)
        self.assertAlmostEqual(journey.hops[0].global_start_xy[0], 5.0, places=3)
        self.assertAlmostEqual(journey.hops[0].global_start_xy[1], 5.0, places=3)
        self.assertAlmostEqual(journey.hops[1].global_start_xy[0], 20.0, places=3)
        self.assertAlmostEqual(journey.hops[1].global_start_xy[1], 5.0, places=3)
        self.assertEqual(len(journey.global_path), 2)
        self.assertEqual(journey.global_start_xy, journey.hops[0].global_start_xy)
        self.assertEqual(journey.global_end_xy, journey.hops[1].global_end_xy)


if __name__ == "__main__":
    unittest.main()

