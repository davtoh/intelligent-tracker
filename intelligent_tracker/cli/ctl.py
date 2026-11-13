#!/usr/bin/env python3
"""Intelligent Tracker — Terminal Stream & Process Controller.

Provides operator controls from the command line against a running dashboard:
- List all camera channels with live status, FPS, and hibernation state
- Force-evict subscribers or hibernate idle channels on demand
- Inspect gateway resource consumption
- View historical system resource metrics and lifecycle audit events
"""

import argparse
import datetime
import json
import os
import sys
import time
import urllib.parse
import urllib.request


def resolve_dashboard_url(explicit_url: str | None = None) -> str:
    """Resolve the dashboard base URL from CLI flag or environment variables."""
    candidate = (
        explicit_url
        or os.getenv("TRACKER_DASHBOARD_URL")
        or os.getenv("APP_URL")
        or ""
    ).strip()
    if not candidate:
        raise ValueError(
            "Dashboard URL is not configured. Pass --url or set TRACKER_DASHBOARD_URL / APP_URL."
        )
    return candidate.rstrip("/")


def format_table(rows: list[list[object]], headers: list[str]) -> str:
    """Render a clean, aligned ASCII table."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(str(val)))

    header_line = "  ".join(f"{h:<{widths[i]}}" for i, h in enumerate(headers))
    sep_line = "  ".join("-" * widths[i] for i in range(len(headers)))
    data_lines = [
        "  ".join(f"{str(row[i]):<{widths[i]}}" for i in range(len(headers)))
        for row in rows
    ]
    return f"{header_line}\n{sep_line}\n" + "\n".join(data_lines)


def _fetch_json(url: str, method: str = "GET") -> object:
    """Execute an HTTP request and decode its JSON payload."""
    if method == "GET":
        resp = urllib.request.urlopen(url, timeout=4.0)
    else:
        req = urllib.request.Request(url, data=b"", method=method)
        resp = urllib.request.urlopen(req, timeout=4.0)
    with resp:
        return json.loads(resp.read().decode("utf-8"))


def cmd_list(app_url: str) -> None:
    """List all camera channels with live status and metrics."""
    try:
        cams = _fetch_json(f"{app_url}/api/cameras")
    except Exception as exc:
        print(f"[ERROR] Could not connect to dashboard at {app_url}: {exc}")
        sys.exit(1)

    if not cams:
        print("No camera streams registered in pool.")
        return

    rows: list[list[object]] = []
    for cam in cams:
        cid = cam.get("id", "-")
        name = cam.get("name", cid)
        fps = float(cam.get("fps", 0.0))
        res = cam.get("resolution", "-")
        tracks = cam.get("active_tracks_count", 0)
        source = str(cam.get("source", "-"))
        if len(source) > 35:
            source = source[:32] + "..."
        status = f"ONLINE ({fps:.1f} FPS)" if fps > 0.0 else "HIBERNATING (0.0 FPS)"
        rows.append([cid, name, status, res, tracks, source])

    headers = ["CHANNEL ID", "NAME", "LIFECYCLE STATE", "RESOLUTION", "TRACKS", "SOURCE"]
    print("\n" + "=" * 80)
    print("   INTELLIGENT TRACKER — ACTIVE STREAM POOL")
    print("=" * 80)
    print(format_table(rows, headers))
    print("=" * 80 + "\n")


def cmd_evict(app_url: str, camera_id: str) -> None:
    """Force-evict subscribers on a channel and force deep hibernation."""
    encoded_id = urllib.parse.quote(camera_id, safe="")
    try:
        data = _fetch_json(f"{app_url}/api/system/streams/{encoded_id}/evict", method="POST")
        print(
            f"[OK] Camera channel '{camera_id}' evicted -> {data.get('new_state')} "
            f"(Evicted: {data.get('evicted_subscribers')} subscribers)"
        )
    except Exception as exc:
        print(f"[ERROR] Failed to evict camera '{camera_id}': {exc}")
        sys.exit(1)


def cmd_prune(app_url: str) -> None:
    """Sweep all registered channels and force-hibernate any with zero active viewers."""
    try:
        data = _fetch_json(f"{app_url}/api/system/hibernate_all", method="POST")
        channels = data.get("channels", [])
        ch_str = ", ".join(channels) if channels else "None (all channels already hibernating or active)"
        print(f"[OK] Idle stream sweep complete: {data.get('hibernated_count')} channels hibernated ({ch_str})")
    except Exception as exc:
        print(f"[ERROR] Failed to prune idle streams: {exc}")
        sys.exit(1)


def cmd_stats(app_url: str) -> None:
    """Display live gateway resource metrics and memory telemetry."""
    try:
        st = _fetch_json(f"{app_url}/api/system/processes")
    except Exception:
        try:
            st = _fetch_json(f"{app_url}/status")
        except Exception as exc:
            print(f"[ERROR] Could not query telemetry from {app_url}: {exc}")
            sys.exit(1)

    print("\n" + "=" * 60)
    print("   INTELLIGENT TRACKER — RUNTIME PROCESS METRICS")
    print("=" * 60)
    print(f"  PID              : {st.get('pid', 'N/A')}")
    print(f"  Thread Count     : {st.get('thread_count', 'N/A')}")
    print(f"  Process Memory   : {st.get('memory_mb', 'N/A')} MB")
    print(f"  Process CPU %    : {st.get('cpu_percent', 'N/A')}%")
    print(f"  Active Streams   : {st.get('active_streams', 'N/A')}")
    print(f"  Hibernating      : {st.get('hibernating_streams', 'N/A')}")
    print("=" * 60 + "\n")


def cmd_history(app_url: str, camera_id: str | None = None, limit: int = 20) -> None:
    """Display recent stream lifecycle transitions from SQLite audit log."""
    url = f"{app_url}/api/system/events?limit={limit}"
    if camera_id:
        url += f"&camera_id={urllib.parse.quote(camera_id, safe='')}"
    try:
        events = _fetch_json(url)
    except Exception as exc:
        print(f"[ERROR] Could not fetch lifecycle events from {app_url}: {exc}")
        sys.exit(1)

    if not events:
        print(f"No lifecycle audit events recorded{' for ' + camera_id if camera_id else ''}.")
        return

    rows: list[list[object]] = []
    for ev in events:
        ts_str = datetime.datetime.fromtimestamp(ev.get("timestamp", time.time())).strftime("%Y-%m-%d %H:%M:%S")
        details = ev.get("details") or ""
        if len(details) > 35:
            details = details[:32] + "..."
        rows.append([
            ts_str,
            ev.get("camera_id", "-"),
            ev.get("event_type", "-"),
            f"{ev.get('old_state') or '-'} -> {ev.get('new_state') or '-'}",
            ev.get("subscriber_count", 0),
            details,
        ])

    headers = ["TIMESTAMP", "CHANNEL", "EVENT", "TRANSITION", "SUBS", "DETAILS"]
    print("\n" + "=" * 80)
    print("   INTELLIGENT TRACKER — LIFECYCLE AUDIT TRAIL")
    print("=" * 80)
    print(format_table(rows, headers))
    print("=" * 80 + "\n")


def cmd_metrics(app_url: str, limit: int = 15) -> None:
    """Display recent system resource telemetry samples from SQLite history."""
    try:
        metrics = _fetch_json(f"{app_url}/api/system/metrics?limit={limit}")
    except Exception as exc:
        print(f"[ERROR] Could not fetch resource metrics from {app_url}: {exc}")
        sys.exit(1)

    if not metrics:
        print("No resource metrics sampled yet. (Sampler records every 15s)")
        return

    rows: list[list[object]] = []
    for sample in metrics:
        ts_str = datetime.datetime.fromtimestamp(sample.get("timestamp", time.time())).strftime("%H:%M:%S")
        rows.append([
            ts_str,
            f"{sample.get('cpu_percent', 0.0):.1f}%",
            f"{sample.get('memory_mb', 0.0):.1f} MB",
            sample.get("active_streams", 0),
            sample.get("hibernating_streams", 0),
            sample.get("total_subscribers", 0),
        ])

    headers = ["TIME", "CPU %", "MEMORY", "ACTIVE", "HIBERNATING", "TOTAL SUBS"]
    print("\n" + "=" * 70)
    print("   INTELLIGENT TRACKER — HISTORICAL RESOURCE TELEMETRY")
    print("=" * 70)
    print(format_table(rows, headers))
    print("=" * 70 + "\n")


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for intelligent-tracker-ctl."""
    parser = argparse.ArgumentParser(description="Intelligent Tracker Stream & Process CLI Controller")
    parser.add_argument(
        "--url",
        default=None,
        help="Dashboard base API URL (defaults to TRACKER_DASHBOARD_URL or APP_URL env var)",
    )
    subparsers = parser.add_subparsers(dest="command", help="Management Subcommand")
    subparsers.add_parser("list", help="List all camera channels and hibernation states")
    subparsers.add_parser("stats", help="Show system process memory, CPU, and gateway health")

    evict_parser = subparsers.add_parser("evict", help="Force-evict subscribers and hibernate a camera channel")
    evict_parser.add_argument("camera_id", help="Camera channel identifier (e.g. cam_01)")

    subparsers.add_parser("prune", help="Audit all streams and force-hibernate any idle channels")

    history_parser = subparsers.add_parser("history", help="Show recent stream lifecycle events from SQLite")
    history_parser.add_argument("camera_id", nargs="?", default=None, help="Optional camera channel filter")
    history_parser.add_argument("--limit", type=int, default=20, help="Number of records to show")

    metrics_parser = subparsers.add_parser("metrics", help="Show historical system resource telemetry samples")
    metrics_parser.add_argument("--limit", type=int, default=15, help="Number of samples to show")
    return parser


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint for intelligent-tracker-ctl."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        app_url = resolve_dashboard_url(args.url)
    except ValueError as exc:
        print(f"[ERROR] {exc}")
        sys.exit(2)

    if args.command == "list" or not args.command:
        cmd_list(app_url)
    elif args.command == "stats":
        cmd_stats(app_url)
    elif args.command == "evict":
        cmd_evict(app_url, args.camera_id)
    elif args.command == "prune":
        cmd_prune(app_url)
    elif args.command == "history":
        cmd_history(app_url, args.camera_id, args.limit)
    elif args.command == "metrics":
        cmd_metrics(app_url, args.limit)


if __name__ == "__main__":
    main()

