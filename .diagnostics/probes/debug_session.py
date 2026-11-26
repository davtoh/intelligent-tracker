#!/usr/bin/env python3
"""Diagnostic Probe: debug_session.

Inspects an isolated IT_DEBUG_MODE session directory (TRACKER_DEBUG_DIR or
data/debug_session) and surfaces user-logged observations correlated with
deduplicated backend warnings, errors, and native crashes.
"""

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _format_probe_summary(target: Path, summary: dict[str, Any]) -> str:
    """Build a compact one-line status summary for the debug_session probe."""
    if not summary["exists"]:
        return f"Debug session clean (directory not created yet): {target}"
    totals = summary["totals"]
    return (
        f"Debug session {target}: CRIT={totals['CRITICAL']} ERR={totals['ERROR']} "
        f"WARN={totals['WARNING']} unique={summary['unique_issues']} obs={summary['observations_count']}"
    )


def run_probe(
    debug_dir: Optional[Path] = None,
    *,
    min_level: str = "WARNING",
    limit: int = 20,
) -> dict[str, Any]:
    """Summarize debug_session issues and correlated user observations."""
    from dashboard.services.debug_session import get_debug_session_dir, summarize_debug_session

    target = Path(debug_dir) if debug_dir else get_debug_session_dir()
    summary = summarize_debug_session(target, min_level=min_level, limit=limit, observation_limit=limit)
    totals = summary["totals"]
    has_error = bool(summary["native_crash_detected"] or totals["CRITICAL"] > 0 or totals["ERROR"] > 0)
    compact_issues = [{k: v for k, v in item.items() if k != "traceback"} for item in summary["issues"]]
    return {
        "status": "error" if has_error else "ok",
        "summary": _format_probe_summary(target, summary),
        "details": {
            "session_dir": summary["session_dir"],
            "exists": summary["exists"],
            "totals": totals,
            "unique_issues": summary["unique_issues"],
            "observations_count": summary["observations_count"],
            "observations": summary["observations"],
            "native_crash_detected": summary["native_crash_detected"],
            "issues": compact_issues,
        },
    }


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the debug_session diagnostic probe.")
    parser.add_argument("--dir", default=None, help="Override debug session directory.")
    parser.add_argument("--min-level", choices=("WARNING", "ERROR", "CRITICAL"), default="WARNING")
    parser.add_argument("--limit", type=int, default=20)
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    res = run_probe(Path(args.dir) if args.dir else None, min_level=args.min_level, limit=args.limit)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    sys.exit(0 if res["status"] == "ok" else 1)
