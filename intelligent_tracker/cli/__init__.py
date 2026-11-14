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
from intelligent_tracker.cli.ask import (
    build_ask_parser,
    execute_ask_args,
    query_local_world,
    query_remote_world,
    run_ask_cli,
)
from intelligent_tracker.cli.benchmark import (
    BenchmarkCollector,
    format_benchmark_report,
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
    "build_ask_parser",
    "execute_ask_args",
    "query_local_world",
    "query_remote_world",
    "run_ask_cli",
    "PipelineContext",
    "BenchmarkCollector",
    "format_benchmark_report",
    "resolve_pipeline_params",
    "build_pipeline",
    "CliUiController",
    "CliAppRunner",
    "run_legacy_forms_gui",
    "run_cli",
    "main",
]
