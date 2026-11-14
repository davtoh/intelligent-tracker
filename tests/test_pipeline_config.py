"""Unit tests for unified PipelineConfig, PipelineBundle, and PipelineEngine."""

from argparse import Namespace
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

import numpy as np

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.detectors import MockDetector
from intelligent_tracker.pipeline import (
    PipelineBundle,
    PipelineConfig,
    PipelineEngine,
    load_pipeline_config,
    parse_classes,
    parse_resolution,
)


class TestPipelineConfigParsing(unittest.TestCase):
    """Verify SSOT resolution, class filter, config loading, and DB Re-ID probing."""

    def _make_temp_dir(self) -> str:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        return tmpdir.name

    def test_parse_resolution_string_and_sequence_ssot(self) -> None:
        self.assertEqual(parse_resolution("1280x720"), (1280, 720))
        self.assertEqual(parse_resolution("1920X1080"), (1920, 1080))
        self.assertEqual(parse_resolution([1280, 720]), (1280, 720))
        self.assertEqual(parse_resolution((800, 600)), (800, 600))
        self.assertEqual(parse_resolution("invalid"), (640, 480))
        self.assertEqual(parse_resolution("0x480"), (640, 480))
        self.assertEqual(parse_resolution(None), (640, 480))

    def test_parse_classes_variants(self) -> None:
        self.assertEqual(parse_classes("person, car,  bicycle "), ["person", "car", "bicycle"])
        self.assertEqual(parse_classes(["person", 0]), ["person", "0"])
        self.assertIsNone(parse_classes(""))
        self.assertIsNone(parse_classes([]))
        self.assertIsNone(parse_classes(None))

    def test_load_pipeline_config_json_and_missing(self) -> None:
        tmpdir = self._make_temp_dir()
        cfg_path = os.path.join(tmpdir, "test.json")
        with open(cfg_path, "w", encoding="utf-8") as handle:
            json.dump({"video": {"resolution": "1280x720"}}, handle)
        self.assertEqual(load_pipeline_config(cfg_path), {"video": {"resolution": "1280x720"}})
        self.assertEqual(load_pipeline_config(os.path.join(tmpdir, "missing.json")), {})
        self.assertEqual(load_pipeline_config(None), {})

    def test_from_dict_normalizes_string_and_list_resolutions(self) -> None:
        tmpdir = self._make_temp_dir()
        db_path = os.path.join(tmpdir, "dash.db")
        cfg_str = PipelineConfig.from_dict(
            {"video": {"resolution": "1280x720"}, "tracker": {"type": "sort"}},
            db_path=db_path,
        )
        cfg_list = PipelineConfig.from_dict(
            {"video": {"resolution": [1280, 720]}, "tracker": {"type": "sort"}},
            db_path=db_path,
        )
        self.assertEqual(cfg_str.resolution, (1280, 720))
        self.assertEqual(cfg_list.resolution, (1280, 720))
        self.assertEqual(cfg_str.iou_threshold, 0.3)

    def test_db_signature_dim_probing_dual_and_onnx(self) -> None:
        tmpdir = self._make_temp_dir()
        for dim, expected in ((2560, "dual"), (512, "onnx")):
            db_path = os.path.join(tmpdir, f"probe_{dim}.db")
            db = TrackerDB(db_path)
            try:
                entity_id = db.add_entity(f"Person_{dim}")
                db.add_signature(entity_id, np.ones(dim, dtype=np.float32))
            finally:
                db.close()
            args = Namespace(
                config=None,
                source="synthetic",
                resolution=None,
                framerate=None,
                detector="mock",
                conf=None,
                classes=None,
                tracker=None,
                reid=None,
                reid_thresh=None,
                db=db_path,
                heatmap=False,
                output=None,
            )
            cfg = PipelineConfig.from_cli_args(args, {})
            self.assertEqual(cfg.reid_model, expected)


class TestPipelineEngineAssembly(unittest.TestCase):
    """Verify PipelineEngine builds, error branches, governance toggles, and close()."""

    def _make_temp_dir(self) -> str:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        return tmpdir.name

    def _cli_args(self, db_path: str, **overrides) -> Namespace:
        defaults = {
            "config": None,
            "source": "synthetic",
            "resolution": "640x480",
            "framerate": 30,
            "detector": "mock",
            "conf": 0.3,
            "classes": "person",
            "tracker": "centroid",
            "reid": "color",
            "reid_thresh": 0.65,
            "db": db_path,
            "heatmap": False,
            "output": None,
            "governance": False,
        }
        defaults.update(overrides)
        return Namespace(**defaults)

    def test_build_dashboard_and_cli_bundles_without_dashboard_imports(self) -> None:
        had_dashboard = "dashboard" in sys.modules
        tmpdir = self._make_temp_dir()
        dash_bundle = PipelineEngine.from_dict(
            {
                "video": {"source": "synthetic", "resolution": "640x480"},
                "detector": {"model": "mock"},
                "tracker": {"type": "centroid"},
                "reid": {"model": "color"},
            },
            camera_id="cam_test",
            db_path=os.path.join(tmpdir, "dash.db"),
        )
        self.addCleanup(dash_bundle.close)
        self.assertIsNotNone(dash_bundle.video_source)
        self.assertIsInstance(dash_bundle.detector, MockDetector)
        self.assertIsNotNone(dash_bundle.rsac_manager)
        self.assertIsNotNone(dash_bundle.active_learning)
        self.assertIsNotNone(dash_bundle.enrollment_manager)
        self.assertIsNotNone(dash_bundle.event_bus)

        cli_bundle = PipelineEngine.from_cli_args(
            self._cli_args(os.path.join(tmpdir, "cli.db")),
            {},
        )
        self.addCleanup(cli_bundle.close)
        self.assertIsNotNone(cli_bundle.video_source)
        self.assertIsInstance(cli_bundle.detector, MockDetector)
        self.assertIsNone(cli_bundle.rsac_manager)
        self.assertIsNone(cli_bundle.active_learning)
        self.assertIsNone(cli_bundle.enrollment_manager)
        if not had_dashboard:
            self.assertNotIn("dashboard", sys.modules)

    def test_governance_true_vs_false_and_reid_none(self) -> None:
        tmpdir = self._make_temp_dir()
        bundle_off = PipelineEngine.from_dict(
            {"reid": {"model": "none"}, "detector": {"model": "mock"}},
            db_path=os.path.join(tmpdir, "gov_off.db"),
            enable_governance=False,
        )
        self.addCleanup(bundle_off.close)
        self.assertIsNone(bundle_off.reid_extractor)
        self.assertIsNone(bundle_off.gallery_matcher)
        self.assertIsNone(bundle_off.rsac_manager)

        bundle_on = PipelineEngine.from_dict(
            {"reid": {"model": "none"}, "detector": {"model": "mock"}},
            db_path=os.path.join(tmpdir, "gov_on.db"),
            enable_governance=True,
        )
        self.addCleanup(bundle_on.close)
        self.assertIsNotNone(bundle_on.rsac_manager)
        self.assertIsNotNone(bundle_on.active_learning)
        self.assertIsNotNone(bundle_on.enrollment_manager)

    def test_detector_fallback_mock_true_vs_false(self) -> None:
        tmpdir = self._make_temp_dir()
        fallback_bundle = PipelineEngine.from_dict(
            {"detector": {"model": "nonexistent_detector_xyz"}},
            db_path=os.path.join(tmpdir, "fb.db"),
            detector_fallback_mock=True,
        )
        self.addCleanup(fallback_bundle.close)
        self.assertIsInstance(fallback_bundle.detector, MockDetector)

        with self.assertRaises(ValueError):
            PipelineEngine.from_dict(
                {"detector": {"model": "nonexistent_detector_xyz"}},
                db_path=os.path.join(tmpdir, "strict.db"),
                detector_fallback_mock=False,
            )

    def test_bundle_close_is_idempotent_and_releases_subsystems(self) -> None:
        cfg = PipelineConfig()
        writer = MagicMock()
        video_source = MagicMock()
        rule_engine = MagicMock()
        mqtt = MagicMock()
        webhook = MagicMock()
        event_bus = MagicMock()
        db = MagicMock()
        bundle = PipelineBundle(
            config=cfg,
            db=db,
            video_source=video_source,
            event_bus=event_bus,
            event_pipeline={
                "rule_engine": rule_engine,
                "mqtt": mqtt,
                "webhooks": [webhook],
                "event_bus": event_bus,
            },
            writer=writer,
        )
        bundle.close()
        bundle.close()
        writer.release.assert_called_once()
        video_source.stop.assert_called_once()
        video_source.release.assert_called_once()
        rule_engine.stop.assert_called_once()
        mqtt.disconnect.assert_called_once()
        webhook.close.assert_called_once()
        event_bus.stop.assert_called_once()
        db.close.assert_called_once()

