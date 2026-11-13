"""Headless integration tests for scoped WorldGraph across PipelineEngine, CLI, and CameraPool."""

from argparse import Namespace
import json
import os
import tempfile
import unittest

import numpy as np

from dashboard.camera_pool import CameraPool
from dashboard.stream_manager import StreamManager
from intelligent_tracker.cli import CliAppRunner, build_pipeline, parse_args
from intelligent_tracker.pipeline import (
    FrameProcessor,
    PipelineConfig,
    PipelineEngine,
)
from intelligent_tracker.pipeline.bundle import build_world
from intelligent_tracker.reid import ReIDExtractorFactory
from intelligent_tracker.world import TripwireNode, WorldEntity, WorldGraph, ZoneNode


def _make_synthetic_frames(count: int = 6, width: int = 640, height: int = 480) -> list[np.ndarray]:
    """Build deterministic BGR frames with a moving synthetic foreground patch."""
    frames: list[np.ndarray] = []
    for idx in range(count):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[50:170, 50 + idx * 5 : 110 + idx * 5] = (40, 200, 90)
        frames.append(frame)
    return frames


def _base_config(db_path: str) -> dict:
    """Return isolated pipeline config with mock detector, zone, and tripwire."""
    return {
        "video": {"source": "synthetic", "resolution": "640x480", "framerate": 30},
        "detector": {"model": "mock", "confidence": 0.9},
        "tracker": {"type": "centroid", "max_disappeared": 2, "min_hits": 1, "iou_threshold": 0.2},
        "reid": {"model": "color", "threshold": 0.4},
        "database": {"path": db_path},
        "analytics": {
            "heatmap_enabled": False,
            "tripwires": [
                {"name": "entry_line", "line": [[105, 40], [105, 240]], "bidirectional": True}
            ],
            "zones": [
                {
                    "name": "lobby",
                    "polygon": [[75, 90], [180, 90], [180, 180], [75, 180]],
                    "dwell_threshold": 0.1,
                }
            ],
        },
    }


class TestWorldPipelineIntegration(unittest.TestCase):
    """Verify live WorldGraph integration for CLI, PipelineEngine, and Dashboard CameraPool."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.db_path = os.path.join(self.tmpdir.name, "world_integration.db")

    def test_cli_build_pipeline_and_runner_populate_and_close_world_graph(self) -> None:
        cfg_path = os.path.join(self.tmpdir.name, "cli_cfg.json")
        with open(cfg_path, "w", encoding="utf-8") as handle:
            json.dump(_base_config(self.db_path), handle)

        args = parse_args([
            "--headless",
            "--frames", "4",
            "--config", cfg_path,
            "--detector", "mock",
            "--source", "synthetic",
            "--reid", "color",
            "--db", self.db_path,
        ])
        ctx = build_pipeline(args, _base_config(self.db_path))
        self.assertIsNotNone(ctx.bundle)
        self.assertIsInstance(ctx.bundle.world_graph, WorldGraph)
        self.assertIsNotNone(ctx.bundle.world_bridge)

        graph = ctx.bundle.world_graph
        self.assertIsNotNone(graph.get_node("default", node_type="camera"))
        self.assertIsNotNone(graph.get_node("default:zone:lobby", node_type="zone"))
        self.assertIsNotNone(graph.get_node("default:tripwire:entry_line", node_type="tripwire"))

        runner = CliAppRunner(ctx)
        runner.run()

        self.assertEqual(runner.frame_count, 4)
        self.assertTrue(ctx.bundle._closed)
        snap = graph.snapshot()
        self.assertGreaterEqual(snap["counts"]["entities"], 1)

    def test_scoped_isolation_and_shared_cross_camera_world_graph(self) -> None:
        frames = _make_synthetic_frames(count=5)
        isolated_a = PipelineEngine.from_dict(
            _base_config(os.path.join(self.tmpdir.name, "iso_a.db")), camera_id="cam_iso"
        )
        isolated_b = PipelineEngine.from_dict(
            _base_config(os.path.join(self.tmpdir.name, "iso_b.db")), camera_id="cam_iso"
        )
        self.addCleanup(isolated_a.close)
        self.addCleanup(isolated_b.close)
        self.assertIsNot(isolated_a.world_graph, isolated_b.world_graph)

        shared_graph = WorldGraph()
        shared_db_path = os.path.join(self.tmpdir.name, "shared.db")
        bundle_1 = PipelineEngine.from_dict(
            _base_config(shared_db_path), camera_id="cam_01", world_graph=shared_graph
        )
        bundle_2 = PipelineEngine.from_dict(
            _base_config(shared_db_path), camera_id="cam_02", world_graph=shared_graph
        )
        self.addCleanup(bundle_1.close)
        self.addCleanup(bundle_2.close)

        self.assertIs(bundle_1.world_graph, shared_graph)
        self.assertIs(bundle_2.world_graph, shared_graph)
        self.assertIsNotNone(bundle_1.world_rule_engine)
        self.assertTrue(bundle_1.world_rule_engine.is_running)

        # Enroll synthetic crop embedding so both cameras converge on one persistent entity
        extractor = ReIDExtractorFactory.create("color")
        sample_box = (80, 100, 50, 70)
        emb = extractor.extract(frames[2], sample_box)
        eid = bundle_1.db.add_entity("SharedGuest", "visitor")
        bundle_1.db.add_signature(eid, emb)
        bundle_1.gallery_matcher.reload_gallery()
        bundle_2.gallery_matcher.reload_gallery()

        proc_1 = FrameProcessor(bundle_1)
        proc_2 = FrameProcessor(bundle_2)
        for idx, frame in enumerate(frames):
            ts = 2000.0 + idx * 0.1
            proc_1.step(frame, timestamp=ts)
            proc_2.step(frame, timestamp=ts)

        self.assertTrue(bundle_1.event_bus.wait_until_empty(timeout=2.0))
        self.assertTrue(bundle_2.event_bus.wait_until_empty(timeout=2.0))

        snap = shared_graph.snapshot()
        self.assertEqual(snap["counts"]["cameras"], 2)
        self.assertEqual(snap["counts"]["zones"], 2)
        self.assertEqual(snap["counts"]["tripwires"], 2)
        self.assertGreaterEqual(snap["counts"]["entities"], 1)

        we = shared_graph.get_node(f"entity:{eid}", node_type="entity")
        self.assertIsNotNone(we)
        self.assertIn("cam_01", we.camera_tracks)
        self.assertIn("cam_02", we.camera_tracks)

        bundle_1.close()
        self.assertFalse(bundle_1.world_rule_engine.is_running)

    def test_frame_processor_empty_tracks_prunes_stale_world_entities(self) -> None:
        bundle = PipelineEngine.from_dict(
            _base_config(os.path.join(self.tmpdir.name, "prune.db")),
            camera_id="cam_prune",
        )
        self.addCleanup(bundle.close)
        proc = FrameProcessor(bundle)
        bundle.world_graph.upsert_entity(
            WorldEntity(
                world_entity_id="entity:99",
                entity_id=99,
                name="Ghost",
                camera_tracks={"cam_prune": 77},
                last_seen=10.0,
            )
        )
        # Force empty tracks and advance past stale_ttl
        bundle.detector = None
        bundle.tracker = None
        bundle.world_bridge.stale_ttl = 1.0
        proc.step(np.zeros((480, 640, 3), dtype=np.uint8), timestamp=25.0)
        self.assertIsNone(bundle.world_graph.get_node("entity:99", node_type="entity"))

    def test_build_world_without_analytics_uses_config_geometry_fallback(self) -> None:
        cfg = PipelineConfig.from_dict(_base_config(self.db_path), camera_id="cam_fallback")
        graph, bridge, rule_engine = build_world(cfg, analytics=None, event_bus=None)
        self.assertIsNone(rule_engine)
        self.assertIsNotNone(bridge)
        self.assertIsNotNone(graph.get_node("cam_fallback", node_type="camera"))
        self.assertIsNotNone(graph.get_node("cam_fallback:zone:lobby", node_type="zone"))
        self.assertIsNotNone(graph.get_node("cam_fallback:tripwire:entry_line", node_type="tripwire"))

    def test_camera_pool_owns_world_graph_and_cascades_on_remove_camera(self) -> None:
        cam_json = os.path.join(self.tmpdir.name, "cameras.json")
        base_yaml = os.path.join(self.tmpdir.name, "base_cfg.json")
        with open(base_yaml, "w", encoding="utf-8") as handle:
            json.dump(_base_config(self.db_path), handle)

        pool = CameraPool(
            config_file=cam_json,
            db_path=self.db_path,
            base_config_path=base_yaml,
            autostart=False,
        )
        self.addCleanup(pool.stop_all)

        self.assertIsInstance(pool.world_graph, WorldGraph)
        sm1 = pool.get_stream("cam_01")
        self.assertIsInstance(sm1, StreamManager)
        self.assertIs(sm1.world_graph, pool.world_graph)
        self.assertIsNotNone(sm1.world_bridge)

        sm2 = pool.add_camera(
            "cam_02",
            "Side Gate",
            "synthetic",
            cam_type="synthetic",
            detector="mock",
            autostart=False,
        )
        sm3 = pool.add_camera(
            "cam_03",
            "Paused Door",
            "synthetic",
            cam_type="synthetic",
            enabled=False,
            autostart=False,
        )
        self.assertIs(sm2.world_graph, pool.world_graph)
        self.assertIs(sm3.world_graph, pool.world_graph)

        pool.world_graph.register_zone(ZoneNode(zone_id="gate_zone", camera_id="cam_02"))
        pool.world_graph.register_tripwire(TripwireNode(tripwire_id="gate_tw", camera_id="cam_02"))
        pool.world_graph.upsert_entity(
            WorldEntity(
                world_entity_id="entity:501",
                entity_id=501,
                name="MultiCamVisitor",
                camera_tracks={"cam_01": 1, "cam_02": 2},
                active_zones={"cam_02": {"cam_02:zone:gate_zone"}},
            )
        )

        self.assertTrue(pool.remove_camera("cam_02"))
        self.assertIsNone(pool.world_graph.get_node("cam_02", node_type="camera"))
        self.assertIsNone(pool.world_graph.get_node("cam_02:zone:gate_zone", node_type="zone"))
        self.assertIsNone(pool.world_graph.get_node("cam_02:tripwire:gate_tw", node_type="tripwire"))

        ent = pool.world_graph.get_node("entity:501", node_type="entity")
        self.assertIsNotNone(ent)
        self.assertEqual(ent.camera_tracks, {"cam_01": 1})
        self.assertEqual(ent.active_zones, {})

        rule_engine = sm1.world_rule_engine
        pool.stop_all()
        if rule_engine is not None:
            self.assertFalse(rule_engine.is_running)


if __name__ == "__main__":
    unittest.main()
