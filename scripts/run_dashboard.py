#!/usr/bin/env python3
"""Backward-compatible wrapper delegating to dashboard.server."""

import os
import sys
from pathlib import Path

# Ensure repository root is in sys.path and propagated to spawned reloader child processes
REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
_existing_pp = os.environ.get("PYTHONPATH", "")
if REPO_ROOT not in _existing_pp:
    os.environ["PYTHONPATH"] = f"{REPO_ROOT}{os.pathsep}{_existing_pp}" if _existing_pp else REPO_ROOT

from dashboard.server import main, parse_args, preflight_port_check, resolve_config

__all__ = [
    "REPO_ROOT",
    "main",
    "parse_args",
    "preflight_port_check",
    "resolve_config",
]

if __name__ == "__main__":
    main()
