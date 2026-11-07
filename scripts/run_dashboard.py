#!/usr/bin/env python3
"""Intelligent Tracker - Dashboard Launcher Script.

Starts the Uvicorn ASGI server with defensive reload configurations:
- Constrains file watching to 'dashboard' and 'intelligent_tracker' source directories.
- Explicitly excludes 'data/*', 'logs/*', and SQLite '*.db*' files from triggering reload loops.
- Supports HOST, PORT, and RELOAD environment variables.
"""

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

import uvicorn


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", "true").lower() in ("1", "true", "yes")

    print(f"=== Starting Intelligent Tracker Dashboard ===")
    print(f"  Target: http://{host}:{port}")
    print(f"  Reload: {reload} (directories: dashboard/, intelligent_tracker/)")

    if reload:
        uvicorn.run(
            "dashboard.app:app",
            host=host,
            port=port,
            reload=True,
            reload_dirs=["dashboard", "intelligent_tracker"],
            reload_excludes=["data/*", "logs/*", "*.db*", "*.sqlite*", ".diagnostics/*"],
            log_level="info",
        )
    else:
        uvicorn.run(
            "dashboard.app:app",
            host=host,
            port=port,
            reload=False,
            log_level="info",
        )


if __name__ == "__main__":
    main()
