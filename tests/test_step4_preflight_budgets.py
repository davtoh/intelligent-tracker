"""Step 4 Milestone 1 modularity budget, AST hygiene, and behavioral tests."""

import ast
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.homography import GroundPlaneHomography
from intelligent_tracker.journey import (
    EntityJourney,
    JourneyHop,
    JourneyVideoExporter,
    TrajectoryJourneySearcher,
    build_journey_hop,
    build_journey_narrative,
    parse_sighting_timestamp,
    segment_sightings_into_hops,
)
from intelligent_tracker.scenario_storage import (
    load_scenarios_from_yaml,
    save_scenarios_to_yaml,
)
from intelligent_tracker.scenarios import DEFAULT_SCENARIOS_PATH, ScenarioManager

ROOT_DIR = Path(__file__).resolve().parents[1]

FILE_LINE_BUDGETS: dict[str, int] = {
    "intelligent_tracker/scenarios.py": 230,
    "intelligent_tracker/scenario_storage.py": 240,
    "intelligent_tracker/journey.py": 170,
    "intelligent_tracker/journey_segmenter.py": 160,
    "intelligent_tracker/journey_exporter.py": 210,
    "intelligent_tracker/homography.py": 330,
}


def _inspect_ast_metrics(rel_path: str) -> tuple[int, dict[str, int], list[tuple[str, int]], set[str]]:
    file_path = ROOT_DIR / rel_path
    source = file_path.read_text(encoding="utf-8")
    lines = len(source.splitlines())
    tree = ast.parse(source, filename=str(file_path))

    class_methods: dict[str, int] = {}
    oversized_funcs: list[tuple[str, int]] = []
    imported: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            methods = [
                child
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            class_methods[node.name] = len(methods)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end_lineno = getattr(node, "end_lineno", node.lineno)
            length = end_lineno - node.lineno + 1
            if length > 40:
                oversized_funcs.append((node.name, length))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module)
            for alias in node.names:
                imported.add(alias.name)

    return lines, class_methods, oversized_funcs, imported


class TestStep4PreflightBudgets(unittest.TestCase):
    """Verify file, class, function, and import hygiene budgets for Step 4 Milestone 1."""

    def test_file_and_function_modularity_budgets(self) -> None:
        for rel_path, max_lines in FILE_LINE_BUDGETS.items():
            lines, class_methods, oversized_funcs, _ = _inspect_ast_metrics(rel_path)
            self.assertLess(
                lines,
                max_lines,
                f"{rel_path} has {lines} lines (budget < {max_lines})",
            )
            self.assertEqual(
                oversized_funcs,
                [],
                f"{rel_path} has functions > 40 lines: {oversized_funcs}",
            )
            for cls_name, count in class_methods.items():
                self.assertLessEqual(
                    count,
                    12,
                    f"{rel_path}:{cls_name} has {count} methods (ceiling 12)",
                )

    def test_unused_imports_removed(self) -> None:
        _, _, _, homo_imports = _inspect_ast_metrics("intelligent_tracker/homography.py")
        for forbidden in ("os", "json", "Union"):
            self.assertNotIn(forbidden, homo_imports)

        _, _, _, journey_imports = _inspect_ast_metrics("intelligent_tracker/journey.py")
        self.assertNotIn("Union", journey_imports)

    def test_public_exports_and_default_path_preserved(self) -> None:
        self.assertEqual(DEFAULT_SCENARIOS_PATH, "configs/scenarios.yaml")
        self.assertTrue(callable(parse_sighting_timestamp))
        self.assertTrue(callable(build_journey_hop))
        self.assertTrue(callable(segment_sightings_into_hops))
        self.assertTrue(callable(build_journey_narrative))
        self.assertTrue(callable(load_scenarios_from_yaml))
        self.assertTrue(callable(save_scenarios_to_yaml))
        self.assertIsNotNone(JourneyHop)
        self.assertIsNotNone(EntityJourney)
        self.assertIsNotNone(TrajectoryJourneySearcher)
        self.assertIsNotNone(JourneyVideoExporter)

    def test_homography_bev_minimap_renders_zones_and_tracks(self) -> None:
        homo = GroundPlaneHomography(
            src_points=[(10, 10), (300, 10), (300, 300), (10, 300)],
            metric_width=12.0,
            metric_height=10.0,
            camera_id="cam_test",
        )
        tracks = {
            1: {"bbox": (40, 40, 20, 50), "category": "person", "velocity": (3.0, 0.0), "entity_name": "Alice"},
            2: {"bbox": (100, 120, 25, 60), "category": "vip", "velocity": (0.0, 0.0)},
            3: {"bbox": (180, 160, 20, 50), "category": "restricted", "velocity": (-2.0, 1.0)},
        }
        zones = {
            "Lobby": {"polygon": [(20, 20), (150, 20), (150, 150), (20, 150)], "color": (0, 200, 100)},
        }
        canvas = homo.render_bev_minimap(tracks=tracks, zones=zones, canvas_size=(320, 320))
        self.assertEqual(canvas.shape, (320, 320, 3))
        self.assertGreater(int(np.sum(canvas > 0)), 0)

    def test_journey_segmenter_splits_gap_and_renders_video(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        db = TrackerDB(os.path.join(tmpdir.name, "tracker.db"))
        self.addCleanup(db.close)

        sightings = [
            {"source": "cam_01", "timestamp": 1700000000.0, "zone_id": "Gate", "bbox": [10, 10, 20, 40]},
            {"source": "cam_01", "timestamp": 1700000120.0, "zone_id": "Gate", "bbox": [15, 10, 20, 40]},
        ]
        hops = segment_sightings_into_hops(sightings, max_hop_gap_seconds=60.0)
        self.assertEqual(len(hops), 2)
        self.assertAlmostEqual(hops[1].transit_time_from_prev or 0.0, 120.0, places=1)

        journey = EntityJourney(
            entity_id=None,
            entity_name="Track #9",
            category="person",
            total_hops=len(hops),
            total_duration_seconds=120.0,
            first_seen=hops[0].start_time,
            last_seen=hops[-1].end_time,
            hops=hops,
            summary_narrative=build_journey_narrative("Track #9", hops),
        )
        exporter = JourneyVideoExporter(output_dir=os.path.join(tmpdir.name, "videos"))
        out_path = exporter.export_journey_video(
            journey,
            output_filename="preflight_test.mp4",
            resolution=(320, 240),
            fps=5,
            seconds_per_hop=0.4,
        )
        self.assertTrue(os.path.exists(out_path))
        self.assertGreater(os.path.getsize(out_path), 500)

    def test_scenario_manager_world_sync_and_yaml_roundtrip(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        yaml_path = os.path.join(tmpdir.name, "scenarios.yaml")
        db = TrackerDB(os.path.join(tmpdir.name, "tracker.db"))
        self.addCleanup(db.close)

        mgr = ScenarioManager(config_path=yaml_path, db=db)
        mgr.save_zone("cam_01", "Entry", [(0, 0), (50, 0), (50, 50), (0, 50)])
        mgr.save_tripwire("cam_01", "Door", [(0, 25), (50, 25)])
        mgr.save_homography("cam_01", [(0, 0), (100, 0), (100, 100), (0, 100)])

        fresh_db = TrackerDB(os.path.join(tmpdir.name, "fresh.db"))
        self.addCleanup(fresh_db.close)
        fresh = ScenarioManager(config_path=yaml_path, db=fresh_db)
        self.assertIn("Entry", fresh.cameras["cam_01"]["zones"])
        self.assertIn("Door", fresh.cameras["cam_01"]["tripwires"])
        self.assertTrue(fresh.get_homography("cam_01").is_calibrated)
