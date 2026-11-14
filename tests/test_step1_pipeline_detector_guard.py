"""Unit tests for Step 1 Milestone 1: pipeline detector guardrails and demo isolation."""

import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from dashboard.services.pipeline_factory import StreamPipelineFactory
from intelligent_tracker.detectors import DetectorFactory, MockDetector
from intelligent_tracker.pipeline import PipelineConfig, PipelineEngine
from intelligent_tracker.pipeline._detector_setup import (
    EmptyDetector,
    build_detector_with_status,
)
from intelligent_tracker.pipeline.config import is_synthetic_source


class TestStep1PipelineDetectorGuard(unittest.TestCase):
    """Verify synthetic-source detection, EmptyDetector fallback, and bundle status."""

    def _make_temp_db(self) -> str:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        return os.path.join(tmpdir.name, "test_tracker.db")

    def test_is_synthetic_source_variants(self) -> None:
        self.assertTrue(is_synthetic_source(None))
        self.assertTrue(is_synthetic_source(""))
        self.assertTrue(is_synthetic_source("synthetic"))
        self.assertTrue(is_synthetic_source("MOCK"))
        self.assertTrue(is_synthetic_source("demo"))
        self.assertTrue(is_synthetic_source("0", cam_type="synthetic"))
        self.assertTrue(is_synthetic_source(0, cam_type="demo"))

        self.assertFalse(is_synthetic_source(0))
        self.assertFalse(is_synthetic_source("0"))
        self.assertFalse(is_synthetic_source("rtsp://10.0.0.5/stream1", cam_type="rtsp"))
        self.assertFalse(is_synthetic_source("sample.mp4", cam_type="file"))

    def test_reid_defaults_to_color_when_db_present_and_model_omitted(self) -> None:
        db_path = self._make_temp_db()
        cfg = PipelineConfig.from_dict({}, db_path=db_path, source_override="0")
        self.assertEqual(cfg.reid_model, "color")

        cfg_null = PipelineConfig.from_dict({"reid": {"model": None}}, db_path=db_path)
        self.assertEqual(cfg_null.reid_model, "color")

        cfg_disabled = PipelineConfig.from_dict({"reid": {"model": "none"}}, db_path=db_path)
        self.assertIsNone(cfg_disabled.reid_model)

    def test_build_detector_with_status_simulation_and_ready(self) -> None:
        sim_cfg = PipelineConfig(source="synthetic", detector_model="mock")
        det_sim, status_sim, err_sim = build_detector_with_status(sim_cfg)
        self.assertIsInstance(det_sim, MockDetector)
        self.assertEqual(status_sim, "simulation")
        self.assertIsNone(err_sim)

        fake_real = object()
        real_cfg = PipelineConfig(source="0", detector_model="yolov8", detector_confidence=0.4)
        with patch.object(DetectorFactory, "create", return_value=fake_real) as mock_create:
            det_real, status_real, err_real = build_detector_with_status(real_cfg)
        self.assertIs(det_real, fake_real)
        self.assertEqual(status_real, "ready")
        self.assertIsNone(err_real)
        mock_create.assert_called_once_with("yolov8", conf_threshold=0.4)

    def test_build_detector_with_status_unavailable_vs_fallback_and_raise(self) -> None:
        live_cfg = PipelineConfig(
            source="0",
            detector_model="nonexistent_detector",
            detector_fallback_mock=False,
        )
        det_unavail, status_unavail, err_unavail = build_detector_with_status(live_cfg)
        self.assertIsInstance(det_unavail, EmptyDetector)
        self.assertEqual(status_unavail, "unavailable")
        self.assertIsNotNone(err_unavail)
        self.assertEqual(det_unavail.detect(np.zeros((16, 16, 3), dtype=np.uint8)), [])

        with patch.object(DetectorFactory, "create", side_effect=RuntimeError("weights missing")):
            det_rt, status_rt, err_rt = build_detector_with_status(
                PipelineConfig(source="rtsp://cam/1", detector_model="yolov8", detector_fallback_mock=False)
            )
        self.assertIsInstance(det_rt, EmptyDetector)
        self.assertEqual(status_rt, "unavailable")
        self.assertIn("weights missing", err_rt or "")

        fb_cfg = PipelineConfig(
            source="synthetic",
            detector_model="nonexistent_detector",
            detector_fallback_mock=True,
        )
        det_fb, status_fb, err_fb = build_detector_with_status(fb_cfg)
        self.assertIsInstance(det_fb, MockDetector)
        self.assertEqual(status_fb, "simulation")
        self.assertIsNotNone(err_fb)

        with self.assertRaises(ValueError):
            build_detector_with_status(live_cfg, raise_on_error=True)

    def test_stream_pipeline_factory_isolates_live_vs_synthetic_fallback(self) -> None:
        db_path = self._make_temp_db()
        live_bundle = StreamPipelineFactory.build(
            {"detector": {"model": "nonexistent_detector"}, "reid": {"model": "none"}},
            db_path=db_path,
            camera_id="cam_live",
            source_override=0,
        )
        self.addCleanup(live_bundle.pipeline_bundle.close)
        self.assertIsInstance(live_bundle.detector, EmptyDetector)
        self.assertEqual(live_bundle.pipeline_bundle.detector_status, "unavailable")
        self.assertIsNotNone(live_bundle.pipeline_bundle.detector_error)

        sim_bundle = StreamPipelineFactory.build(
            {"detector": {"model": "nonexistent_detector"}, "reid": {"model": "none"}},
            db_path=db_path,
            camera_id="cam_sim",
            source_override="synthetic",
        )
        self.addCleanup(sim_bundle.pipeline_bundle.close)
        self.assertIsInstance(sim_bundle.detector, MockDetector)
        self.assertEqual(sim_bundle.pipeline_bundle.detector_status, "simulation")

    def test_bundle_module_within_line_budget(self) -> None:
        bundle_path = os.path.join("intelligent_tracker", "pipeline", "bundle.py")
        with open(bundle_path, encoding="utf-8") as handle:
            line_count = sum(1 for _ in handle)
        self.assertLess(line_count, 350)


if __name__ == "__main__":
    unittest.main()
