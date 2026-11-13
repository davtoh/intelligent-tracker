#!/usr/bin/env python3
"""Intelligent Tracker — Dashboard ASGI Server Launcher.

Starts the Uvicorn ASGI server with defensive reload configurations:
- Constrains file watching to 'dashboard' and 'intelligent_tracker' source directories.
- Explicitly excludes 'data/*', 'logs/*', and SQLite '*.db*' files from triggering reload loops.
- Supports HOST, PORT, and RELOAD environment variables, or CLI options (--host, --port, --local, --no-reload).
"""

import argparse
import os
import uvicorn

from dashboard.services import process_supervisor


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the dashboard server launcher."""
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
    """Resolve bind host, port, and reload flag from CLI args and environment."""
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


def preflight_port_check(port: int, host: str = "0.0.0.0") -> bool:
    """Verify port availability before launching Uvicorn; auto-reclaim if occupied by stale tracker."""
    if process_supervisor.check_port_available(port, host=host):
        return True

    pids = process_supervisor.find_port_listeners(port)
    pids_desc = f"PID(s): {pids}" if pids else "unknown process"
    print(f"  [Port Pre-Flight] Port {port} is occupied ({pids_desc}). Attempting auto-reclaim...")

    if process_supervisor.reclaim_port(port, force=False):
        print(f"  [Port Pre-Flight] Successfully reclaimed port {port}.")
        return True

    print(f"  [Port Pre-Flight] Warning: Port {port} could not be automatically reclaimed. Startup may fail.")
    return False


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint for intelligent-tracker-server."""
    args = parse_args(argv)
    host, port, reload = resolve_config(args)

    print("=== Starting Intelligent Tracker Dashboard ===")
    print(f"  Target: http://{host}:{port}")
    print(f"  Reload: {reload} (directories: dashboard/, intelligent_tracker/)")

    process_supervisor.assign_to_job_object()
    preflight_port_check(port, host=host)

    uvicorn_kwargs: dict[str, object] = {
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
