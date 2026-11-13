#!/usr/bin/env python
"""Backward-compatible wrapper delegating to intelligent_tracker.cli.ctl."""

import sys
from pathlib import Path

REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from intelligent_tracker.cli.ctl import (
    build_parser,
    cmd_evict,
    cmd_history,
    cmd_list,
    cmd_metrics,
    cmd_prune,
    cmd_stats,
    format_table,
    main,
    resolve_dashboard_url,
)

__all__ = [
    "build_parser",
    "cmd_evict",
    "cmd_history",
    "cmd_list",
    "cmd_metrics",
    "cmd_prune",
    "cmd_stats",
    "format_table",
    "main",
    "resolve_dashboard_url",
]

if __name__ == "__main__":
    main()
