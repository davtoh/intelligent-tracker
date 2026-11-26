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


def _print_observations(summary: dict[str, Any]) -> None:
    """Print user-logged observations alongside recent breadcrumbs and correlated issues."""
    obs_list = summary.get("observations") or []
    print(
        f"[DEBUG OBSERVATIONS] {summary['session_dir']} | "
        f"count={summary.get('observations_count', len(obs_list))}"
    )
    if not obs_list:
        print("[OK] No user observations recorded.")
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


def _emit_observations(summary: dict[str, Any], as_json: bool) -> None:
    """Emit user observations either as compact JSON or human-readable lines."""
    if not as_json:
        _print_observations(summary)
        return
    obs_payload = {
        "session_dir": summary["session_dir"],
        "exists": summary["exists"],
        "totals": summary["totals"],
        "observations_count": summary["observations_count"],
        "observations": summary["observations"],
        "native_crash_detected": summary["native_crash_detected"],
    }
    print(json.dumps(obs_payload, indent=2, ensure_ascii=False))


def main(argv: Optional[list[str]] = None) -> int:
    """Entrypoint for scripts/debug_inspect.py."""
    args = parse_args(argv)
    target = Path(args.dir) if args.dir else get_debug_session_dir()

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
        _emit_observations(summary, args.json)
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
