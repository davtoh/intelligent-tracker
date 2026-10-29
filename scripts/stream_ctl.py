#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker — Terminal Stream & Process Controller (stream_ctl).

Provides operator controls from the command line:
- List all camera channels with live status, FPS, and hibernation state
- Force-evict subscribers or hibernate idle channels on demand
- Inspect Docker container and gateway resource consumption
- View historical system resource metrics and lifecycle audit events
"""

import sys
import json
import time
import argparse
import datetime
import urllib.request
import urllib.error
import urllib.parse


def format_table(rows, headers):
    """Render a clean, aligned ASCII table."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(str(val)))

    header_line = "  ".join(f"{h:<{widths[i]}}" for i, h in enumerate(headers))
    sep_line = "  ".join("-" * widths[i] for i in range(len(headers)))
    data_lines = ["  ".join(f"{str(row[i]):<{widths[i]}}" for i in range(len(headers))) for row in rows]
    return f"{header_line}\n{sep_line}\n" + "\n".join(data_lines)


def cmd_list(app_url: str):
    """List all camera channels with live status and metrics."""
    try:
        req = urllib.request.urlopen(f"{app_url}/api/cameras", timeout=4.0)
        cams = json.loads(req.read().decode("utf-8"))
    except Exception as e:
        print(f"[ERROR] Could not connect to dashboard at {app_url}: {e}")
        sys.exit(1)

    if not cams:
        print("No camera streams registered in pool.")
        return

    rows = []
    for c in cams:
        cid = c.get("id", "-")
        name = c.get("name", cid)
        fps = float(c.get("fps", 0.0))
        res = c.get("resolution", "-")
        tracks = c.get("active_tracks_count", 0)
        source = str(c.get("source", "-"))
        if len(source) > 35:
            source = source[:32] + "..."

        if fps > 0.0:
            status = f"ONLINE ({fps:.1f} FPS)"
        else:
            status = "HIBERNATING (0.0 FPS)"

        rows.append([cid, name, status, res, tracks, source])

    headers = ["CHANNEL ID", "NAME", "LIFECYCLE STATE", "RESOLUTION", "TRACKS", "SOURCE"]
    print("\n" + "=" * 80)
    print("   INTELLIGENT TRACKER — ACTIVE STREAM POOL")
    print("=" * 80)
    print(format_table(rows, headers))
    print("=" * 80 + "\n")


def cmd_evict(app_url: str, camera_id: str):
    """Force-evict subscribers on a channel and force deep hibernation."""
    try:
        url = f"{app_url}/api/system/streams/{camera_id}/evict"
        req = urllib.request.Request(url, data=b"", method="POST")
        resp = urllib.request.urlopen(req, timeout=4.0)
        data = json.loads(resp.read().decode("utf-8"))
        print(f"[OK] Camera channel '{camera_id}' evicted -> {data.get('new_state')} (Evicted: {data.get('evicted_subscribers')} subscribers)")
    except Exception as e:
        print(f"[ERROR] Failed to evict camera '{camera_id}': {e}")
        sys.exit(1)


def cmd_prune(app_url: str):
    """Sweep all registered channels and force-hibernate any with zero active viewers."""
    try:
        url = f"{app_url}/api/system/hibernate_all"
        req = urllib.request.Request(url, data=b"", method="POST")
        resp = urllib.request.urlopen(req, timeout=4.0)
        data = json.loads(resp.read().decode("utf-8"))
        channels = data.get("channels", [])
        ch_str = ", ".join(channels) if channels else "None (all channels already hibernating or active)"
        print(f"[OK] Idle stream sweep complete: {data.get('hibernated_count')} channels hibernated ({ch_str})")
    except Exception as e:
        print(f"[ERROR] Failed to prune idle streams: {e}")
        sys.exit(1)


def cmd_stats(app_url: str):
    """Display live gateway resource metrics and memory telemetry."""
    try:
        req = urllib.request.urlopen(f"{app_url}/api/system/processes", timeout=4.0)
        st = json.loads(req.read().decode("utf-8"))
    except Exception:
        # Fallback to /status if /api/system/processes is loading
        try:
            req = urllib.request.urlopen(f"{app_url}/status", timeout=4.0)
            st = json.loads(req.read().decode("utf-8"))
        except Exception as e:
            print(f"[ERROR] Could not query telemetry from {app_url}: {e}")
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


def cmd_history(app_url: str, camera_id: str = None, limit: int = 20):
    """Display recent stream lifecycle transitions from SQLite audit log."""
    try:
        url = f"{app_url}/api/system/events?limit={limit}"
        if camera_id:
            url += f"&camera_id={camera_id}"
        req = urllib.request.urlopen(url, timeout=4.0)
        events = json.loads(req.read().decode("utf-8"))
    except Exception as e:
        print(f"[ERROR] Could not fetch lifecycle events from {app_url}: {e}")
        sys.exit(1)

    if not events:
        print(f"No lifecycle audit events recorded{' for ' + camera_id if camera_id else ''}.")
        return

    rows = []
    for ev in events:
        ts_str = datetime.datetime.fromtimestamp(ev.get("timestamp", time.time())).strftime("%Y-%m-%d %H:%M:%S")
        cid = ev.get("camera_id", "-")
        etype = ev.get("event_type", "-")
        old_st = ev.get("old_state") or "-"
        new_st = ev.get("new_state") or "-"
        subs = ev.get("subscriber_count", 0)
        details = ev.get("details") or ""
        if len(details) > 35:
            details = details[:32] + "..."
        rows.append([ts_str, cid, etype, f"{old_st} -> {new_st}", subs, details])

    headers = ["TIMESTAMP", "CHANNEL", "EVENT", "TRANSITION", "SUBS", "DETAILS"]
    print("\n" + "=" * 80)
    print("   INTELLIGENT TRACKER — LIFECYCLE AUDIT TRAIL")
    print("=" * 80)
    print(format_table(rows, headers))
    print("=" * 80 + "\n")


def cmd_metrics(app_url: str, limit: int = 15):
    """Display recent system resource telemetry samples from SQLite history."""
    try:
        url = f"{app_url}/api/system/metrics?limit={limit}"
        req = urllib.request.urlopen(url, timeout=4.0)
        metrics = json.loads(req.read().decode("utf-8"))
    except Exception as e:
        print(f"[ERROR] Could not fetch resource metrics from {app_url}: {e}")
        sys.exit(1)

    if not metrics:
        print("No resource metrics sampled yet. (Sampler records every 15s)")
        return

    rows = []
    for m in metrics:
        ts_str = datetime.datetime.fromtimestamp(m.get("timestamp", time.time())).strftime("%H:%M:%S")
        cpu = f"{m.get('cpu_percent', 0.0):.1f}%"
        mem = f"{m.get('memory_mb', 0.0):.1f} MB"
        active = m.get("active_streams", 0)
        hib = m.get("hibernating_streams", 0)
        subs = m.get("total_subscribers", 0)
        rows.append([ts_str, cpu, mem, active, hib, subs])

    headers = ["TIME", "CPU %", "MEMORY", "ACTIVE", "HIBERNATING", "TOTAL SUBS"]
    print("\n" + "=" * 70)
    print("   INTELLIGENT TRACKER — HISTORICAL RESOURCE TELEMETRY")
    print("=" * 70)
    print(format_table(rows, headers))
    print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Intelligent Tracker Stream & Process CLI Controller")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Dashboard base API URL")

    subparsers = parser.add_subparsers(dest="command", help="Management Subcommand")

    # list
    subparsers.add_parser("list", help="List all camera channels and hibernation states")

    # stats
    subparsers.add_parser("stats", help="Show system process memory, CPU, and gateway health")

    # evict
    evict_parser = subparsers.add_parser("evict", help="Force-evict subscribers and hibernate a camera channel")
    evict_parser.add_argument("camera_id", help="Camera channel identifier (e.g. cam_01)")

    # prune
    subparsers.add_parser("prune", help="Audit all streams and force-hibernate any idle channels")

    # history
    history_parser = subparsers.add_parser("history", help="Show recent stream lifecycle events from SQLite")
    history_parser.add_argument("camera_id", nargs="?", default=None, help="Optional camera channel filter")
    history_parser.add_argument("--limit", type=int, default=20, help="Number of records to show")

    # metrics
    metrics_parser = subparsers.add_parser("metrics", help="Show historical system resource telemetry samples")
    metrics_parser.add_argument("--limit", type=int, default=15, help="Number of samples to show")

    args = parser.parse_args()

    if args.command == "list" or not args.command:
        cmd_list(args.url)
    elif args.command == "stats":
        cmd_stats(args.url)
    elif args.command == "evict":
        cmd_evict(args.url, args.camera_id)
    elif args.command == "prune":
        cmd_prune(args.url)
    elif args.command == "history":
        cmd_history(args.url, args.camera_id, args.limit)
    elif args.command == "metrics":
        cmd_metrics(args.url, args.limit)


if __name__ == "__main__":
    main()
