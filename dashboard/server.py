#!/usr/bin/env python3
"""Intelligent Tracker — Dashboard ASGI Server Launcher.

Starts the Uvicorn ASGI server with defensive reload configurations:
- Constrains file watching to 'dashboard' and 'intelligent_tracker' source directories.
- Explicitly excludes 'data/*', 'logs/*', and SQLite '*.db*' files from triggering reload loops.
- Supports HOST, PORT, and RELOAD environment variables, or CLI options (--host, --port, --local, --no-reload).
"""

import argparse
import os
from pathlib import Path
from typing import Any
import uvicorn

from dashboard.services import process_supervisor
from dashboard.services.debug_session import prepare_debug_session_env


def _add_debug_args(parser: argparse.ArgumentParser) -> None:
    """Register isolated debug session CLI flags."""
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Run in isolated debug mode (data/debug_session/, DEBUG logs, faulthandler, structured error events).",
    )
    parser.add_argument(
        "--clean-debug",
        action="store_true",
        help="Wipe existing debug session directory before booting in --debug mode.",
    )
    parser.add_argument(
        "--debug-dir",
        type=str,
        default=None,
        help="Custom debug session directory (default: TRACKER_DEBUG_DIR or data/debug_session).",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the dashboard server launcher."""
    parser = argparse.ArgumentParser(
        description="Run the Intelligent Tracker Dashboard ASGI Server."
    )
    parser.add_argument("--host", type=str, default=None, help="Bind interface host (default: HOST env or 0.0.0.0).")
    parser.add_argument("--port", type=int, default=None, help="Bind port (default: PORT env or 8000).")
    parser.add_argument(
        "--local",
        action="store_true",
        help="Bind exclusively to localhost (127.0.0.1) to avoid kernel spinlock deadlocks on secondary NICs.",
    )
    parser.add_argument("--reload", dest="reload", action="store_true", default=None, help="Enable auto-reload.")
    parser.add_argument("--no-reload", dest="reload", action="store_false", help="Disable auto-reload.")
    parser.add_argument("--demo", action="store_true", help="Enable opt-in demo scenarios (configs/alert_demo.yaml).")
    _add_debug_args(parser)
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
    if args.demo:
        os.environ["IT_LOAD_DEMO_SCENARIOS"] = "1"
    debug_active = bool(args.debug or args.clean_debug)
    debug_env: dict[str, str] = {}
    if debug_active:
        debug_dir = Path(args.debug_dir) if args.debug_dir else None
        debug_env = prepare_debug_session_env(debug_dir, clean=bool(args.clean_debug))
    host, port, reload = resolve_config(args)

    print("=== Starting Intelligent Tracker Dashboard ===")
    print(f"  Target: http://{host}:{port}")
    print(f"  Reload: {reload} (directories: dashboard/, intelligent_tracker/)")
    if debug_active:
        print(f"  [DEBUG] Session dir : {debug_env.get('TRACKER_DEBUG_DIR')}")
        print(f"  [DEBUG] Clean start : {bool(args.clean_debug)}")
        print("  [DEBUG] Inspector   : python scripts/debug_inspect.py")

    process_supervisor.assign_to_job_object()
    preflight_port_check(port, host=host)

    uvicorn_kwargs: dict[str, Any] = {
        "host": host,
        "port": port,
        "reload": reload,
        "log_level": "debug" if debug_active else "info",
        "proxy_headers": True,
    }
    forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "").strip()
    if forwarded_allow_ips:
        uvicorn_kwargs["forwarded_allow_ips"] = forwarded_allow_ips
    if reload:
        uvicorn_kwargs["reload_dirs"] = ["dashboard", "intelligent_tracker"]
        uvicorn_kwargs["reload_excludes"] = ["data/*", "logs/*", "*.db*", "*.sqlite*", ".diagnostics/*"]

    uvicorn.run("dashboard.app:app", **uvicorn_kwargs)


if __name__ == "__main__":
    main()
