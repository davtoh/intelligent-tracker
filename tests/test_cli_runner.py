"""Headless CLI integration tests for build_pipeline, CliAppRunner, and main.py."""

import os
import tempfile
import unittest

import main as root_main
from intelligent_tracker.cli import (
    CliAppRunner,
    PipelineContext,
    build_pipeline,
    parse_args,
    resolve_pipeline_params,
    run_cli,
)
from intelligent_tracker.pipeline import FrameProcessor


class TestCliRunnerIntegration(unittest.TestCase):
    """Verify headless CLI pipeline assembly, execution, and teardown."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.db_path = os.path.join(self.tmpdir.name, "cli_test.db")

    def test_build_pipeline_and_runner_headless_five_frames(self) -> None:
        """Exercise build_pipeline and CliAppRunner.run() for 5 synthetic frames."""
        args = parse_args([
            "--headless",
            "--frames", "5",
            "--detector", "mock",
            "--source", "synthetic",
            "--resolution", "640x480",
            "--reid", "color",
            "--db", self.db_path,
        ])
        ctx = build_pipeline(args, {})
        self.assertIsInstance(ctx, PipelineContext)
        self.assertIsNotNone(ctx.bundle)

        runner = CliAppRunner(ctx)
        self.assertIsInstance(runner.processor, FrameProcessor)
        runner.run()

        self.assertEqual(runner.frame_count, 5)
        self.assertGreater(runner.measured_fps, 0.0)
        self.assertTrue(ctx.bundle._closed)

    def test_cli_governance_flag_wires_governance_subsystems(self) -> None:
        """Verify --governance enables RSAC, ActiveLearning, and Enrollment."""
        args = parse_args([
            "--headless",
            "--frames", "2",
            "--detector", "mock",
            "--source", "synthetic",
            "--db", self.db_path,
            "--governance",
        ])
        params = resolve_pipeline_params(args, {})
        self.assertTrue(params["governance"])

        ctx = build_pipeline(args, {})
        try:
            self.assertIsNotNone(ctx.bundle)
            self.assertIsNotNone(ctx.bundle.rsac_manager)
            self.assertIsNotNone(ctx.bundle.active_learning)
            self.assertIsNotNone(ctx.bundle.enrollment_manager)
        finally:
            if ctx.bundle is not None:
                ctx.bundle.close()

    def test_main_module_backward_compatibility_and_run_cli(self) -> None:
        """Verify root main.py exports and run_cli() headless execution."""
        for attr in (
            "build_argument_parser",
            "parse_args",
            "load_config",
            "parse_resolution",
            "run_legacy_forms_gui",
            "build_pipeline",
            "run_cli",
            "main",
        ):
            self.assertTrue(hasattr(root_main, attr), f"Missing export {attr} on main.py")

        args = root_main.parse_args([
            "--headless",
            "--frames", "5",
            "--detector", "mock",
            "--source", "synthetic",
            "--reid", "none",
            "--db", self.db_path,
        ])
        run_cli(args)

    def test_resolve_pipeline_params_skips_hardware_probe_by_default(self) -> None:
        """Dry CLI parameter resolution must not probe physical camera hardware."""
        from unittest.mock import patch

        with patch("intelligent_tracker.pipeline.config.resolve_camera_source") as mock_probe:
            params = resolve_pipeline_params(parse_args([]), {})
        mock_probe.assert_not_called()
        self.assertEqual(params["source"], "0")


if __name__ == "__main__":
    unittest.main()

