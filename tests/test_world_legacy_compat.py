"""AST boundary, ScenarioManager WorldGraph sync, and legacy compatibility tests."""

import ast
import os
from pathlib import Path
import tempfile
import unittest

from intelligent_tracker.core.agents import Agent
from intelligent_tracker.core.spaces import Space
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.high_objects import Area, Line, Scene, World
from intelligent_tracker.scenarios import ScenarioManager
from intelligent_tracker.world import WorldGraph

ROOT_DIR = Path(__file__).resolve().parents[1]


def _collect_imported_modules(file_path: Path) -> set[str]:
    """Return all imported module/package names referenced in a Python file via AST."""
    tree = ast.parse(file_path.read_bytes(), filename=str(file_path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


class TestWorldLegacyCompatibility(unittest.TestCase):
    """Verify dead import removal, world layer boundaries, and legacy compat."""

    def test_scenarios_and_topology_do_not_import_high_objects(self) -> None:
        scenarios_imports = _collect_imported_modules(
            ROOT_DIR / "intelligent_tracker" / "scenarios.py"
        )
        topology_imports = _collect_imported_modules(
            ROOT_DIR / "intelligent_tracker" / "topology.py"
        )

        for mod_set, label in (
            (scenarios_imports, "scenarios.py"),
            (topology_imports, "topology.py"),
        ):
            self.assertFalse(
                any("high_objects" in mod for mod in mod_set),
                f"{label} still imports high_objects: {sorted(mod_set)}",
            )

        for unused_mod in ("cv2", "json", "numpy"):
            self.assertNotIn(unused_mod, scenarios_imports)

    def test_world_package_has_zero_dashboard_or_scripts_imports(self) -> None:
        world_dir = ROOT_DIR / "intelligent_tracker" / "world"
        for py_file in sorted(world_dir.glob("*.py")):
            imported = _collect_imported_modules(py_file)
            forbidden = [
                mod
                for mod in imported
                if mod.split(".")[0] in {"dashboard", "scripts"}
            ]
            self.assertEqual(
                forbidden,
                [],
                f"{py_file.name} violates layer direction with imports: {forbidden}",
            )

    def test_legacy_space_and_world_adapters_remain_functional(self) -> None:
        import intelligent_tracker.core.spaces as spaces_mod
        import intelligent_tracker.high_objects as high_objects_mod

        self.assertIn("WorldGraph", spaces_mod.__doc__ or "")
        self.assertIn("deprecated", (high_objects_mod.__doc__ or "").lower())
        self.assertIsNotNone(Scene)
        self.assertIsNotNone(Area)
        self.assertIsNotNone(Line)

        parent = Agent(name="legacy_parent_compat")
        child = Agent(name="legacy_child_compat", _space_parent=parent)
        self.assertIs(child._space_parent, parent)
        self.assertIsInstance(parent, Space)

        legacy_world = World(name="legacy_world_compat")
        self.assertEqual(legacy_world.name, "legacy_world_compat")

    def test_scenario_manager_optional_world_graph_sync(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        yaml_path = os.path.join(tmpdir.name, "scenarios.yaml")
        db_path = os.path.join(tmpdir.name, "tracker.db")
        db = TrackerDB(db_path)
        self.addCleanup(db.close)

        graph = WorldGraph()
        sm = ScenarioManager(
            config_path=yaml_path,
            db=db,
            world_graph=graph,
        )

        sm.save_zone(
            camera_id="cam_01",
            name="vault",
            polygon=[(10, 10), (100, 10), (100, 100), (10, 100)],
            capacity_limit=4,
        )
        zone_node = graph.get_node("cam_01:zone:vault", node_type="zone")
        self.assertIsNotNone(zone_node)
        self.assertEqual(zone_node.max_occupancy, 4)
        self.assertEqual(len(zone_node.points), 4)

        sm.save_tripwire(
            camera_id="cam_01",
            name="gate_line",
            line_segment=[(0, 50), (200, 50)],
            bidirectional=False,
        )
        tw_node = graph.get_node("cam_01:tripwire:gate_line", node_type="tripwire")
        self.assertIsNotNone(tw_node)
        self.assertEqual(tw_node.direction, "in")

        self.assertTrue(sm.delete_zone("cam_01", "vault"))
        self.assertIsNone(graph.get_node("cam_01:zone:vault", node_type="zone"))

        self.assertTrue(sm.delete_tripwire("cam_01", "gate_line"))
        self.assertIsNone(graph.get_node("cam_01:tripwire:gate_line", node_type="tripwire"))

        # Deleting missing entries does not error when synced
        self.assertFalse(sm.delete_zone("cam_01", "nonexistent_zone"))
        self.assertFalse(sm.delete_tripwire("cam_01", "nonexistent_tw"))

    def test_periferials_shim_reexports_and_mock_lifecycle(self) -> None:
        import intelligent_tracker.periferials as perif_mod
        from intelligent_tracker.video.legacy_camera import (
            CameraError,
            MockVideoCapture,
            PiCamera,
            PiRGBArray,
            UnifiedCamera,
        )
        from intelligent_tracker.video.legacy_sync import SyncCameras, VideoStream

        for name, expected in (
            ("CameraError", CameraError),
            ("MockVideoCapture", MockVideoCapture),
            ("UnifiedCamera", UnifiedCamera),
            ("PiRGBArray", PiRGBArray),
            ("PiCamera", PiCamera),
            ("VideoStream", VideoStream),
            ("SyncCameras", SyncCameras),
        ):
            self.assertIs(getattr(perif_mod, name), expected)

        with UnifiedCamera("mock") as cam:
            buf = PiRGBArray(cam, size=(160, 120))
            frame = cam.capture(buf, format="bgr")
            self.assertIsNotNone(frame)
            self.assertEqual(frame.shape[2], 3)

        stream = VideoStream("mock", resolution=(160, 120), framerate=30)
        stream._warm_up_time = 0
        with stream as active_stream:
            self.assertFalse(active_stream.closed())
            self.assertIsNotNone(active_stream.get_frame())
        self.assertTrue(stream.closed())

        sync = SyncCameras(["mock"], resolution=(160, 120), framerate=30)
        for s in sync.streams:
            s._warm_up_time = 0
        with sync:
            frames = sync.capture()
            self.assertEqual(len(frames), 1)
            self.assertIsNotNone(frames[0])
        self.assertTrue(sync.closed())

    def test_step3_milestone3_modularity_budgets(self) -> None:
        perif_path = ROOT_DIR / "intelligent_tracker" / "periferials.py"
        perif_lines = len(perif_path.read_text(encoding="utf-8").splitlines())
        self.assertLess(perif_lines, 50)

        self.assertFalse((ROOT_DIR / "intelligent_tracker" / "analytics.py").exists())
        budget_files = list((ROOT_DIR / "intelligent_tracker" / "analytics").glob("*.py")) + [
            ROOT_DIR / "intelligent_tracker" / "video" / "legacy_camera.py",
            ROOT_DIR / "intelligent_tracker" / "video" / "legacy_sync.py",
        ]
        for file_path in budget_files:
            line_count = len(file_path.read_text(encoding="utf-8").splitlines())
            self.assertLess(line_count, 260, f"{file_path.name} exceeded 260 lines ({line_count})")


if __name__ == "__main__":
    unittest.main()
