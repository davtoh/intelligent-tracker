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


ACTIVE_OBSERVATION_STATUSES = frozenset({"open", "triaged", "in_progress"})
DEFAULT_OBSERVATION_CATALOG = REPO_ROOT / ".diagnostics" / "observation_catalog.json"


def _count_open_catalog_observations(catalog_path: Path) -> int:
    """Count active (open/triaged/in_progress) observations in observation_catalog.json."""
    if not catalog_path.is_file():
        return 0
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0
    items = payload.get("observations")
    if isinstance(items, list):
        return sum(
            1
            for item in items
            if isinstance(item, dict) and str(item.get("status", "")).lower() in ACTIVE_OBSERVATION_STATUSES
        )
    summary = payload.get("summary")
    if isinstance(summary, dict):
        return sum(int(summary.get(k, 0) or 0) for k in ACTIVE_OBSERVATION_STATUSES)
    return 0


def _format_probe_summary(target: Path, summary: dict[str, Any], open_obs: int) -> str:
    """Build a compact one-line status summary for the debug_session probe."""
    if not summary["exists"]:
        if open_obs > 0:
            return f"Debug session clean ({target} absent), but {open_obs} active observation(s) pending triage"
        return f"Debug session clean (directory not created yet): {target}"
    totals = summary["totals"]
    return (
        f"Debug session {target}: CRIT={totals['CRITICAL']} ERR={totals['ERROR']} "
        f"WARN={totals['WARNING']} unique={summary['unique_issues']} "
        f"obs={summary['observations_count']} open_obs={open_obs}"
    )


def run_probe(
    debug_dir: Optional[Path] = None,
    *,
    min_level: str = "WARNING",
    limit: int = 20,
    catalog_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Summarize debug_session issues and correlated user observations."""
    from dashboard.services.debug_session import get_debug_session_dir, summarize_debug_session

    target = Path(debug_dir) if debug_dir else get_debug_session_dir()
    obs_catalog = Path(catalog_path) if catalog_path else DEFAULT_OBSERVATION_CATALOG
    summary = summarize_debug_session(target, min_level=min_level, limit=limit, observation_limit=limit)
    open_obs = _count_open_catalog_observations(obs_catalog)
    totals = summary["totals"]
    has_error = bool(summary["native_crash_detected"] or totals["CRITICAL"] > 0 or totals["ERROR"] > 0)
    has_attention = open_obs > 0 or int(summary["observations_count"] or 0) > 0
    status = "error" if has_error else ("warning" if has_attention else "ok")
    compact_issues = [{k: v for k, v in item.items() if k != "traceback"} for item in summary["issues"]]
    return {
        "status": status,
        "summary": _format_probe_summary(target, summary, open_obs),
        "details": {
            "session_dir": summary["session_dir"],
            "exists": summary["exists"],
            "totals": totals,
            "unique_issues": summary["unique_issues"],
            "observations_count": summary["observations_count"],
            "open_observations_count": open_obs,
            "observations": summary["observations"],
            "native_crash_detected": summary["native_crash_detected"],
            "issues": compact_issues,
        },
    }


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the debug_session diagnostic probe.")
    parser.add_argument("--dir", default=None, help="Override debug session directory.")
    parser.add_argument("--catalog", default=None, help="Override observation_catalog.json path.")
    parser.add_argument("--min-level", choices=("WARNING", "ERROR", "CRITICAL"), default="WARNING")
    parser.add_argument("--limit", type=int, default=20)
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    res = run_probe(
        Path(args.dir) if args.dir else None,
        min_level=args.min_level,
        limit=args.limit,
        catalog_path=Path(args.catalog) if args.catalog else None,
    )
    print(json.dumps(res, indent=2, ensure_ascii=False))
    sys.exit(0 if res["status"] in ("ok", "warning") else 1)
