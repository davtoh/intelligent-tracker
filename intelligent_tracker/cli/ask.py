"""Intelligent Tracker CLI - Semantic World Q&A (`ask`) Subcommand."""

import argparse
from datetime import datetime, timezone
import json
import os
import sys
from typing import Any
import urllib.error
import urllib.request

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.memory import (
    ConfidenceEngine,
    GeminiSemanticProvider,
    WorldQueryEngine,
)


def add_ask_arguments(parser: argparse.ArgumentParser, *, include_url: bool = True) -> None:
    """Register arguments for the `ask` semantic world query command."""
    parser.add_argument("query", nargs="+", help="Natural-language or keyword query")
    parser.add_argument("--db", default=None, help="Path to local SQLite TrackerDB (default: data/tracker.db)")
    if include_url:
        parser.add_argument("--url", default=None, help="Remote dashboard base URL (or TRACKER_DASHBOARD_URL / APP_URL)")
    parser.add_argument("--offline", action="store_true", help="Force local TrackerDB query even if a server URL is set")
    parser.add_argument("--entity-id", type=int, default=None, help="Optional entity ID filter")
    parser.add_argument("--camera", dest="camera_id", default=None, help="Optional camera ID filter")
    parser.add_argument("--zone", dest="zone_id", default=None, help="Optional zone ID filter")
    parser.add_argument("--event-type", default=None, help="Optional timeline event type filter")
    parser.add_argument("--limit", type=int, default=15, help="Maximum number of citations to return")
    parser.add_argument("--provider", choices=["local", "gemini"], default=None, help="Optional synthesis provider")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Emit structured JSON output")


def build_ask_parser() -> argparse.ArgumentParser:
    """Construct standalone argument parser for `intelligent-tracker ask`."""
    parser = argparse.ArgumentParser(
        prog="intelligent-tracker ask",
        description="Query timeline events, entity confidence, and world state.",
    )
    add_ask_arguments(parser, include_url=True)
    return parser


def resolve_ask_target(
    *,
    explicit_url: str | None = None,
    explicit_db: str | None = None,
    offline: bool = False,
) -> tuple[str, str]:
    """Return ('remote', base_url) or ('local', db_path) from CLI flags and env vars."""
    if not offline:
        if explicit_url and explicit_url.strip():
            return "remote", explicit_url.strip().rstrip("/")
        if not explicit_db:
            env_url = (os.getenv("TRACKER_DASHBOARD_URL") or os.getenv("APP_URL") or "").strip()
            if env_url:
                return "remote", env_url.rstrip("/")
    db_path = (explicit_db or os.getenv("TRACKER_DB_PATH") or os.path.join("data", "tracker.db")).strip()
    return "local", db_path


def query_local_world(
    db_path: str,
    query: str,
    *,
    entity_id: int | None = None,
    camera_id: str | None = None,
    zone_id: str | None = None,
    event_type: str | None = None,
    limit: int = 15,
    provider_name: str | None = None,
) -> dict[str, Any]:
    """Execute a semantic world query directly against a local SQLite TrackerDB."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database file not found: {db_path}")
    db = TrackerDB(db_path)
    try:
        conf_engine = ConfidenceEngine(db=db)
        selected = (provider_name or os.getenv("WORLD_QUERY_PROVIDER", "")).strip().lower()
        provider = GeminiSemanticProvider() if selected == "gemini" else None
        engine = WorldQueryEngine(db=db, confidence_engine=conf_engine, provider=provider)
        result = engine.ask(
            query,
            entity_id=entity_id,
            camera_id=camera_id,
            zone_id=zone_id,
            event_type=event_type,
            limit=max(1, int(limit)),
        )
        return result.to_dict()
    finally:
        db.close()


def query_remote_world(
    base_url: str,
    query: str,
    *,
    entity_id: int | None = None,
    camera_id: str | None = None,
    zone_id: str | None = None,
    event_type: str | None = None,
    limit: int = 15,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    """Execute a semantic world query against a running dashboard `/api/world/query` API."""
    payload = {
        "query": query,
        "entity_id": entity_id,
        "camera_id": camera_id,
        "zone_id": zone_id,
        "event_type": event_type,
        "limit": max(1, int(limit)),
    }
    body = json.dumps({k: v for k, v in payload.items() if v is not None}).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/world/query",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fmt_ts(ts: float | int | None) -> str:
    """Format a UNIX timestamp into readable UTC text."""
    if not ts:
        return "unknown-time"
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def format_ask_output(payload: dict[str, Any], *, as_json: bool = False) -> str:
    """Format a WorldQueryResult payload for JSON or human-readable terminal output."""
    if as_json:
        return json.dumps(payload, indent=2, default=str)
    lines = [
        f"Answer   : {payload.get('answer', '')}",
        f"Intent   : {payload.get('intent', 'timeline')} (provider: {payload.get('provider', 'local_deterministic')})",
    ]
    if payload.get("fallback_used"):
        lines.append(f"Fallback : {payload.get('fallback_reason') or 'active'}")
    entities = payload.get("entities") or []
    if entities:
        lines.append("Entities :")
        for ent in entities[:5]:
            name = ent.get("entity_name") or ent.get("name") or f"Entity {ent.get('entity_id')}"
            conf = ent.get("confidence")
            conf_str = f"{float(conf):.2f}" if conf is not None else "n/a"
            cam = ent.get("last_camera_id") or "-"
            zone = ent.get("last_zone_id") or "-"
            lines.append(f"  - {name} (id={ent.get('entity_id')}, conf={conf_str}, last={cam}/{zone})")
    citations = payload.get("citations") or []
    if citations:
        lines.append(f"Citations ({len(citations)}):")
        for cit in citations[:10]:
            loc = "/".join(p for p in (cit.get("camera_id", ""), cit.get("zone_id", "")) if p) or "-"
            lines.append(f"  - [{_fmt_ts(cit.get('timestamp'))}] ({cit.get('event_type', '')} @ {loc}) {cit.get('summary', '')}")
    return "\n".join(lines)


def _dispatch_ask_query(mode: str, target: str, query: str, args: argparse.Namespace) -> dict[str, Any]:
    """Dispatch parsed ask parameters to either remote API or local TrackerDB."""
    common = {
        "entity_id": getattr(args, "entity_id", None),
        "camera_id": getattr(args, "camera_id", None),
        "zone_id": getattr(args, "zone_id", None),
        "event_type": getattr(args, "event_type", None),
        "limit": int(getattr(args, "limit", 15)),
    }
    if mode == "remote":
        return query_remote_world(target, query, **common)
    return query_local_world(target, query, provider_name=getattr(args, "provider", None), **common)


def execute_ask_args(args: argparse.Namespace, *, fallback_url: str | None = None) -> int:
    """Execute parsed `ask` arguments, printing output and returning an exit code."""
    raw_query = " ".join(args.query) if isinstance(args.query, (list, tuple)) else str(args.query or "")
    query = raw_query.strip()
    if not query:
        print("[ERROR] Query text must not be empty.", file=sys.stderr)
        return 2

    explicit_url = getattr(args, "ask_url", None) or getattr(args, "url", None) or fallback_url
    mode, target = resolve_ask_target(
        explicit_url=explicit_url,
        explicit_db=getattr(args, "db", None),
        offline=bool(getattr(args, "offline", False)),
    )
    try:
        result = _dispatch_ask_query(mode, target, query, args)
    except (FileNotFoundError, urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as exc:
        print(f"[ERROR] World query failed ({mode}: {target}): {exc}", file=sys.stderr)
        return 1

    print(format_ask_output(result, as_json=bool(getattr(args, "as_json", False))))
    return 0


def run_ask_cli(argv: list[str] | None = None) -> int:
    """Parse arguments for `intelligent-tracker ask` and execute query."""
    parser = build_ask_parser()
    args = parser.parse_args(argv)
    return execute_ask_args(args)
