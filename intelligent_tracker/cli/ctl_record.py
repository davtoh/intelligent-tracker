"""CLI `record` subcommand for `intelligent-tracker-ctl`."""

import argparse
import json
import os
import sys
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


def add_record_subparser(subparsers: Any) -> None:
    """Register the `record` subcommand on the ctl parser."""
    rec_p = subparsers.add_parser("record", help="Control live camera MP4 recording on a running dashboard")
    rec_p.add_argument("action", choices=["start", "stop", "status"], help="Recording operation")
    rec_p.add_argument("camera_id", nargs="?", default="cam_01", help="Camera channel ID (default: cam_01)")
    rec_p.add_argument("--camera", dest="camera_opt", default=None, help="Explicit camera ID override")
    rec_p.add_argument("--filename", default=None, help="Optional output filename (.mp4) when starting")
    rec_p.add_argument("--fps", type=float, default=None, help="Target recording FPS")
    rec_p.add_argument("--max-frames", type=int, default=None, help="Auto-stop after N frames")
    rec_p.add_argument("--max-duration", type=float, default=None, help="Auto-stop after N seconds")
    rec_p.add_argument("--raw", action="store_true", help="Record raw frames instead of annotated overlays")
    rec_p.add_argument("--url", dest="sub_url", default=None, help="Override dashboard API URL")
    rec_p.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON output")


def _resolve_base_url(explicit_url: str | None) -> str:
    """Resolve remote dashboard URL from --url flag or environment."""
    candidate = (
        explicit_url
        or os.getenv("TRACKER_DASHBOARD_URL")
        or os.getenv("APP_URL")
        or ""
    ).strip()
    if not candidate:
        raise ValueError("Dashboard URL is not configured. Pass --url or set TRACKER_DASHBOARD_URL / APP_URL.")
    return candidate.rstrip("/")


def _http_record_request(url: str, *, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute HTTP GET/POST request against recording REST endpoint."""
    headers: dict[str, str] = {}
    data: bytes | None = None
    if method != "GET":
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        else:
            data = b""
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=8.0) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _build_record_request(args: argparse.Namespace) -> tuple[str, str, dict[str, Any] | None]:
    """Build (method, path, optional JSON body) from parsed CLI arguments."""
    cam_id = urllib.parse.quote(str(getattr(args, "camera_opt", None) or args.camera_id), safe="")
    if args.action == "start":
        body: dict[str, Any] = {"annotated": not bool(getattr(args, "raw", False))}
        for flag, key in (
            ("filename", "filename"),
            ("fps", "fps"),
            ("max_frames", "max_frames"),
            ("max_duration", "max_duration_s"),
        ):
            val = getattr(args, flag, None)
            if val is not None:
                body[key] = val
        return "POST", f"/api/cameras/{cam_id}/record/start", body
    if args.action == "stop":
        return "POST", f"/api/cameras/{cam_id}/record/stop", None
    return "GET", f"/api/cameras/{cam_id}/record/status", None


def execute_record_args(args: argparse.Namespace, *, fallback_url: str | None = None) -> int:
    """Execute the `record` subcommand and return an exit code."""
    try:
        base_url = _resolve_base_url(getattr(args, "sub_url", None) or fallback_url)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    method, suffix, body = _build_record_request(args)
    try:
        payload = _http_record_request(f"{base_url}{suffix}", method=method, payload=body)
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as exc:
        print(f"[ERROR] Recording request failed: {exc}", file=sys.stderr)
        return 1

    if getattr(args, "as_json", False):
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(
            f"Recording [{payload.get('camera_id', args.camera_id)}] "
            f"status={payload.get('status')} active={payload.get('is_recording')} "
            f"frames={payload.get('frames_written', 0)} file={payload.get('output_path') or '-'}"
        )
    return 0
