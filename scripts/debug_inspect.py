#!/usr/bin/env python3
"""Token-efficient Jenkins/Sentry-style error and crash inspector for debug sessions."""

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dashboard.services.debug_session import (
    get_debug_session_dir,
    get_issue_context,
    summarize_debug_session,
)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments for debug_inspect.py."""
    parser = argparse.ArgumentParser(
        description="Inspect deduplicated errors, tracebacks, and crashes from an Intelligent Tracker debug session."
    )
    parser.add_argument("--dir", default=None, help="Debug session directory (default: TRACKER_DEBUG_DIR or data/debug_session)")
    parser.add_argument("--min-level", choices=("WARNING", "ERROR", "CRITICAL"), default="WARNING")
    parser.add_argument("--limit", type=int, default=20, help="Max deduplicated issues to display.")
    parser.add_argument("--json", action="store_true", help="Emit compact JSON output for agents/CI.")
    parser.add_argument(
        "--observations",
        action="store_true",
        help="Display user-logged debug observations with breadcrumbs and correlated issues.",
    )
    parser.add_argument(
        "--migrate-observations",
        action="store_true",
        help="Idempotently import legacy OBSERVATION entries from events.jsonl into .diagnostics/observation_catalog.json.",
    )
    parser.add_argument(
        "--workspace",
        default=None,
        help="Target workspace root for .diagnostics/ during --migrate-observations (default: repo root).",
    )
    parser.add_argument("--context", default=None, help="Drill into one issue by #index or fingerprint prefix.")
    parser.add_argument("--lines", type=int, default=15, help="Context lines before/after in debug.log for --context.")
    return parser.parse_args(argv)


def _print_summary(summary: dict[str, Any]) -> None:
    """Print a compact Jenkins-style human & agent readable issue summary."""
    totals = summary["totals"]
    obs_count = summary.get("observations_count", 0)
    print(
        f"[DEBUG SESSION] {summary['session_dir']} | "
        f"CRIT={totals['CRITICAL']} ERR={totals['ERROR']} WARN={totals['WARNING']} | "
        f"unique={summary['unique_issues']} obs={obs_count}"
    )
    if summary["native_crash_detected"]:
        print("[CRIT] NATIVE CRASH DETECTED in faulthandler.log:")
        for line in summary["native_crash_tail"].splitlines():
            print(f"  {line}")
    if not summary["issues"]:
        print("[OK] No issues matching filter.")
    else:
        for issue in summary["issues"]:
            loc = f" @ {issue['top_frames'][-1]}" if issue["top_frames"] else ""
            exc = f"{issue['exc_type']}: " if issue["exc_type"] else ""
            paths = f" routes={','.join(issue['http_paths'])}" if issue["http_paths"] else ""
            msg = " ".join(str(issue["message"]).splitlines())[:120]
            print(
                f"[#{issue['index']} {issue['tag']} x{issue['count']} fp={issue['fingerprint']}] "
                f"{issue['logger']}{loc} -> {exc}{msg}{paths}"
            )
        print("Tip: run `python scripts/debug_inspect.py --context 1` to inspect full traceback + log context.")
    if obs_count:
        print("Tip: run `python scripts/debug_inspect.py --observations` to inspect user observations.")


def _format_breadcrumb(crumb: dict[str, Any]) -> str:
    """Render one client breadcrumb entry as a compact single-line token."""
    kind = str(crumb.get("type") or "event")
    target = str(crumb.get("target") or crumb.get("url") or crumb.get("message") or "").strip()
    status = f" ({crumb['status']})" if crumb.get("status") else ""
    return f"{kind}:{target}{status}" if target else kind


def _print_connector_observations(connector_obs: list[dict[str, Any]]) -> None:
    """Print Wire Contract v1 observations from .diagnostics/observation_catalog.json."""
    print(f"[CONNECTOR OBSERVATIONS] .diagnostics/observation_catalog.json | count={len(connector_obs)}")
    if not connector_obs:
        print("[OK] No active connector observations recorded.")
        return
    for item in connector_obs:
        sel = f" target={item['selector']}" if item.get("selector") else ""
        rec = f" rec={item['recording_id']}({len(item.get('timeline') or [])})" if item.get("recording_id") else ""
        msg = " ".join(str(item.get("message") or "").splitlines())[:180]
        print(f"[{item.get('id', '?')} {item.get('status', 'open')} {item.get('kind', 'note')} path={item.get('page_path') or '/'}{sel}{rec}] {msg}")


def _print_observations(summary: dict[str, Any], connector_obs: Optional[list[dict[str, Any]]] = None) -> None:
    """Print connector observations and legacy user-logged observations with breadcrumbs."""
    _print_connector_observations(connector_obs or [])
    obs_list = summary.get("observations") or []
    print(
        f"[DEBUG OBSERVATIONS] {summary['session_dir']} | "
        f"count={summary.get('observations_count', len(obs_list))}"
    )
    if not obs_list:
        print("[OK] No legacy debug-session observations recorded.")
        return

    for obs in obs_list:
        tab = obs.get("tab") or "-"
        url = obs.get("url") or "-"
        note = " ".join(str(obs.get("note") or "").splitlines())[:180]
        print(f"[OBS #{obs['index']} @ {obs.get('ts', '')} tab={tab} url={url}] {note}")
        crumbs = obs.get("breadcrumbs") or []
        if crumbs:
            tail = " -> ".join(_format_breadcrumb(c) for c in crumbs[-5:] if isinstance(c, dict))
            print(f"  breadcrumbs({len(crumbs)}): {tail}")
        correlated = obs.get("correlated_issues") or []
        if correlated:
            for item in correlated:
                msg = " ".join(str(item.get("message") or "").splitlines())[:100]
                print(
                    f"  correlated: [{item['tag']} fp={item['fingerprint']} "
                    f"dt={item['delta_sec']:+.1f}s x{item['count']}] {msg}"
                )
        else:
            print("  correlated: none within +/-30s")


def _print_context(ctx: dict[str, Any]) -> None:
    """Print full traceback and bounded surrounding debug.log lines for one issue."""
    issue = ctx["issue"]
    print(f"[ISSUE #{issue['index']} {issue['tag']} x{issue['count']} fp={issue['fingerprint']}] {issue['logger']}")
    print(f"Window: {issue['first_seen']} -> {issue['last_seen']}")
    if issue["http_paths"]:
        print(f"HTTP paths: {', '.join(issue['http_paths'])}")
    print(f"Message: {issue['message']}")
    if issue["traceback"]:
        print("\n--- TRACEBACK ---")
        print(issue["traceback"].rstrip())
    if ctx["log_context"]:
        print("\n--- DEBUG.LOG CONTEXT ---")
        for line in ctx["log_context"]:
            print(line)


def _load_connector_observations(workspace: Path, limit: int = 20) -> list[dict[str, Any]]:
    """Read active Wire Contract v1 observations from .diagnostics/observation_catalog.json."""
    store = _load_observation_store()
    if store is None:
        return []
    try:
        return list(store.list_observations(workspace, status="active", limit=limit))
    except OSError:
        return []


def _emit_observations(summary: dict[str, Any], as_json: bool, connector_obs: Optional[list[dict[str, Any]]] = None) -> None:
    """Emit connector and legacy user observations either as JSON or human-readable lines."""
    items = connector_obs if connector_obs is not None else []
    if not as_json:
        _print_observations(summary, connector_obs=items)
        return
    obs_payload = {
        "session_dir": summary["session_dir"],
        "exists": summary["exists"],
        "totals": summary["totals"],
        "observations_count": summary["observations_count"],
        "observations": summary["observations"],
        "connector_observations_count": len(items),
        "connector_observations": items,
        "native_crash_detected": summary["native_crash_detected"],
    }
    print(json.dumps(obs_payload, indent=2, ensure_ascii=False))


def _load_observation_store() -> Any:
    """Resolve and import system-diagnostics observation_store via diagnostic_bridge candidates."""
    from dashboard.services import diagnostic_bridge  # noqa: F401 - populates sys.path

    for cand in diagnostic_bridge._engine_candidates():
        if (cand / "observation_store.py").is_file() and str(cand) not in sys.path:
            sys.path.insert(0, str(cand))
            break
    try:
        import observation_store

        return observation_store
    except ImportError:
        return None


def _legacy_obs_to_record(entry: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Map one legacy events.jsonl OBSERVATION dict to a Wire Contract v1 note record."""
    if str(entry.get("level", "")).upper() != "OBSERVATION":
        return None
    message = str(entry.get("note") or entry.get("message") or "").strip()
    if not message:
        return None
    url = str(entry.get("url") or "").strip()
    tab = str(entry.get("tab") or "").strip()
    page_path = url or (f"/#{tab}" if tab else "/")
    record: dict[str, Any] = {
        "schema": 1,
        "kind": "note",
        "page_path": page_path,
        "message": message,
        "source_url": url,
        "timeline": entry.get("breadcrumbs") if isinstance(entry.get("breadcrumbs"), list) else [],
        "attrs": {
            "legacy_fingerprint": str(entry.get("fingerprint") or ""),
            "tab": tab,
            "viewport": entry.get("viewport") if isinstance(entry.get("viewport"), dict) else {},
            "migrated_from": "debug_session/events.jsonl",
        },
    }
    if entry.get("ts"):
        record["ts"] = str(entry["ts"])
    return record


def _read_legacy_records(events_path: Path) -> tuple[list[dict[str, Any]], int]:
    """Read valid OBSERVATION records from events.jsonl and return (records, invalid_lines)."""
    records: list[dict[str, Any]] = []
    invalid = 0
    with open(events_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                raw_entry = json.loads(line)
            except ValueError:
                invalid += 1
                continue
            if isinstance(raw_entry, dict):
                record = _legacy_obs_to_record(raw_entry)
                if record is not None:
                    records.append(record)
    return records, invalid


def migrate_legacy_observations(debug_dir: Path, workspace_root: Optional[Path] = None) -> dict[str, Any]:
    """Idempotently import legacy OBSERVATION lines from events.jsonl into .diagnostics/observation_catalog.json."""
    store = _load_observation_store()
    if store is None:
        raise RuntimeError("system-diagnostics observation_store is unavailable")
    ws = Path(workspace_root) if workspace_root else REPO_ROOT
    events_path = Path(debug_dir) / "events.jsonl"
    result: dict[str, Any] = {
        "events_path": str(events_path), "workspace": str(ws),
        "found": 0, "imported": 0, "skipped": 0, "invalid": 0, "ids": [],
    }
    if not events_path.is_file():
        return result

    records, invalid = _read_legacy_records(events_path)
    result["found"], result["invalid"] = len(records), invalid
    existing_fps = {e.get("fingerprint") for e in store.load_catalog(ws).get("observations", [])}
    for record in records:
        sanitized = store.sanitize_record(record)
        fp = store.make_fingerprint(
            sanitized["kind"], sanitized.get("page_path", ""), store._target(sanitized), sanitized["message"]
        )
        if fp in existing_fps:
            result["skipped"] += 1
            continue
        created, _ = store.add_observation(ws, record)
        existing_fps.add(fp)
        result["imported"] += 1
        result["ids"].append(created["id"])
    return result


def _emit_migration_result(result: dict[str, Any], as_json: bool) -> None:
    """Print legacy observation migration summary in JSON or compact human format."""
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    print(
        f"[MIGRATE OBSERVATIONS] {result['events_path']} -> {result['workspace']} | "
        f"found={result['found']} imported={result['imported']} "
        f"skipped={result['skipped']} invalid={result['invalid']}"
    )


def main(argv: Optional[list[str]] = None) -> int:
    """Entrypoint for scripts/debug_inspect.py."""
    args = parse_args(argv)
    target = Path(args.dir) if args.dir else get_debug_session_dir()

    if args.migrate_observations:
        try:
            workspace = Path(args.workspace) if args.workspace else REPO_ROOT
            result = migrate_legacy_observations(target, workspace_root=workspace)
        except RuntimeError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
        _emit_migration_result(result, args.json)
        return 0

    if args.context:
        ctx = get_issue_context(target, args.context, context_lines=args.lines)
        if ctx is None:
            print(f"[ERROR] Issue '{args.context}' not found in {target}", file=sys.stderr)
            return 1
        print(json.dumps(ctx, indent=2, ensure_ascii=False)) if args.json else _print_context(ctx)
        return 0

    summary = summarize_debug_session(
        target,
        min_level=args.min_level,
        limit=args.limit,
        observation_limit=args.limit,
    )
    if args.observations:
        workspace = Path(args.workspace) if args.workspace else REPO_ROOT
        connector_obs = _load_connector_observations(workspace, limit=args.limit)
        _emit_observations(summary, args.json, connector_obs=connector_obs)
        return 0

    if args.json:
        compact = {
            **summary,
            "issues": [{k: v for k, v in item.items() if k != "traceback"} for item in summary["issues"]],
        }
        print(json.dumps(compact, indent=2, ensure_ascii=False))
    else:
        _print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
