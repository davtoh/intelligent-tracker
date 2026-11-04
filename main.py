#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Edge AI Retail & Security Analytics Platform.

Main entrypoint bootstrap module.
"""

from intelligent_tracker.cli import (
    build_argument_parser,
    parse_args,
    load_config,
    parse_resolution,
    run_legacy_forms_gui,
    build_pipeline,
    run_cli,
    main,
)

__all__ = [
    "build_argument_parser",
    "parse_args",
    "load_config",
    "parse_resolution",
    "run_legacy_forms_gui",
    "build_pipeline",
    "run_cli",
    "main",
]

if __name__ == "__main__":
    main()
