#!/usr/bin/env python3
"""Intelligent Tracker - Dashboard Launcher Script.

Starts the Uvicorn ASGI server with defensive reload configurations:
- Constrains file watching to 'dashboard' and 'intelligent_tracker' source directories.
- Explicitly excludes 'data/*', 'logs/*', and SQLite '*.db*' files from triggering reload loops.
- Supports HOST, PORT, and RELOAD environment variables, or CLI options (--host, --port, --local, --no-reload).
"""

import argparse
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Intelligent Tracker Dashboard ASGI Server."
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Bind interface host (default: from HOST env var, or 0.0.0.0).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Bind port (default: from PORT env var, or 8000).",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Bind exclusively to localhost (127.0.0.1) to avoid kernel spinlock deadlocks on secondary NICs.",
    )
    parser.add_argument(
        "--reload",
        dest="reload",
        action="store_true",
        default=None,
        help="Enable auto-reload on source code changes.",
    )
    parser.add_argument(
        "--no-reload",
        dest="reload",
        action="store_false",
        help="Disable auto-reload.",
    )
    return parser.parse_args(argv)


def resolve_config(args: argparse.Namespace) -> tuple[str, int, bool]:
    if args.local:
        host = "127.0.0.1"
    elif args.host:
        host = args.host
    else:
        host = os.getenv("HOST", "0.0.0.0")

    if args.port is not None:
        port = args.port
    else:
        port = int(os.getenv("PORT", "8000"))

    if args.reload is not None:
        reload = args.reload
    else:
        reload = os.getenv("RELOAD", "true").lower() in ("1", "true", "yes")

    return host, port, reload


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    host, port, reload = resolve_config(args)

    print(f"=== Starting Intelligent Tracker Dashboard ===")
    print(f"  Target: http://{host}:{port}")
    print(f"  Reload: {reload} (directories: dashboard/, intelligent_tracker/)")

    uvicorn_kwargs = {
        "host": host,
        "port": port,
        "reload": reload,
        "log_level": "info",
    }
    if reload:
        uvicorn_kwargs["reload_dirs"] = ["dashboard", "intelligent_tracker"]
        uvicorn_kwargs["reload_excludes"] = ["data/*", "logs/*", "*.db*", "*.sqlite*", ".diagnostics/*"]

    uvicorn.run("dashboard.app:app", **uvicorn_kwargs)


if __name__ == "__main__":
    main()
