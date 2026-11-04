# -*- coding: utf-8 -*-
"""
Intelligent Tracker CLI - Command Line Subsystem & Application Runners.
"""

from intelligent_tracker.cli.arguments import (
    build_argument_parser,
    parse_args,
    load_config,
    parse_resolution,
)
from intelligent_tracker.cli.pipeline_builder import (
    PipelineContext,
    resolve_pipeline_params,
    build_pipeline,
)
from intelligent_tracker.cli.display import (
    CliUiController,
)
from intelligent_tracker.cli.runner import (
    CliAppRunner,
    run_legacy_forms_gui,
    run_cli,
)

main = run_cli

__all__ = [
    "build_argument_parser",
    "parse_args",
    "load_config",
    "parse_resolution",
    "PipelineContext",
    "resolve_pipeline_params",
    "build_pipeline",
    "CliUiController",
    "CliAppRunner",
    "run_legacy_forms_gui",
    "run_cli",
    "main",
]
