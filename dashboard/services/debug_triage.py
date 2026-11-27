#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Token-efficient JSONL error deduplication and debug.log context extractor."""

from collections import deque
import json
from pathlib import Path
from typing import Any, Optional

_SEVERITY_RANK = {"CRITICAL": 4, "FATAL": 4, "ERROR": 3, "WARNING": 2, "WARN": 2, "INFO": 1, "DEBUG": 0}
_SEVERITY_TAG = {"CRITICAL": "CRIT", "FATAL": "CRIT", "ERROR": "ERR", "WARNING": "WARN", "WARN": "WARN"}


def _read_jsonl_records(
    events_path: Path,
    min_rank: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Read events.jsonl separating severity-ranked issues from user observations."""
    totals = {"CRITICAL": 0, "ERROR": 0, "WARNING": 0}
    events: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    if not events_path.is_file():
        return events, observations, totals
    with open(events_path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            lvl = str(ev.get("level", "INFO")).upper()
            if lvl == "OBSERVATION":
                observations.append(ev)
                continue
            rank = _SEVERITY_RANK.get(lvl, 1)
            bucket = "CRITICAL" if rank >= 4 else ("ERROR" if rank == 3 else ("WARNING" if rank == 2 else ""))
            if bucket:
                totals[bucket] += 1
            if rank >= min_rank:
                events.append(ev)
    return events, observations, totals


def read_jsonl_events(events_path: Path, min_rank: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Read events.jsonl and compute per-severity totals (excluding OBSERVATION records)."""
    events, _observations, totals = _read_jsonl_records(events_path, min_rank)
    return events, totals


def _update_grouped_entry(grouped: dict[str, dict[str, Any]], ev: dict[str, Any]) -> None:
    """Merge a single parsed event into the fingerprint-keyed summary map."""
    fp = str(ev.get("fingerprint") or "unknown")
    lvl = str(ev.get("level", "WARNING")).upper()
    rank = _SEVERITY_RANK.get(lvl, 2)
    entry = grouped.get(fp)
    if entry is None:
        entry = {
            "fingerprint": fp, "level": lvl, "tag": _SEVERITY_TAG.get(lvl, lvl[:4]),
            "severity_rank": rank, "count": 0,
            "first_seen": ev.get("ts", ""), "last_seen": ev.get("ts", ""),
            "logger": ev.get("logger", ""), "exc_type": ev.get("exc_type", ""),
            "message": ev.get("message", ""), "top_frames": ev.get("top_frames") or [],
            "http_paths": [], "traceback": ev.get("traceback", ""),
        }
        grouped[fp] = entry
    entry["count"] += 1
    entry["last_seen"] = ev.get("ts", entry["last_seen"])
    if rank > entry["severity_rank"]:
        entry.update({"severity_rank": rank, "level": lvl, "tag": _SEVERITY_TAG.get(lvl, lvl[:4])})
    if ev.get("traceback"):
        entry["traceback"] = ev.get("traceback")
    hp = ev.get("http_path")
    if hp and hp not in entry["http_paths"]:
        entry["http_paths"].append(hp)


def group_events(events: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Deduplicate events by fingerprint and rank by severity, count, and recency."""
    grouped: dict[str, dict[str, Any]] = {}
    for ev in events:
        _update_grouped_entry(grouped, ev)
    ordered = sorted(
        grouped.values(),
        key=lambda item: (item["severity_rank"], item["count"], item["last_seen"]),
        reverse=True,
    )[:limit]
    for idx, item in enumerate(ordered, start=1):
        item["index"] = idx
    return ordered


def _correlate_observation_issues(
    obs_epoch: Optional[float],
    raw_events: list[dict[str, Any]],
    window_sec: float = 30.0,
) -> list[dict[str, Any]]:
    """Find deduplicated issues occurring within +/- window_sec of an observation."""
    if obs_epoch is None:
        return []
    seen: dict[str, dict[str, Any]] = {}
    for ev in raw_events:
        ev_epoch = ev.get("epoch")
        if not isinstance(ev_epoch, (int, float)):
            continue
        delta = round(float(ev_epoch) - float(obs_epoch), 3)
        if abs(delta) > window_sec:
            continue
        fp = str(ev.get("fingerprint") or "unknown")
        if fp in seen:
            seen[fp]["count"] += 1
            continue
        lvl = str(ev.get("level", "WARNING")).upper()
        seen[fp] = {
            "fingerprint": fp,
            "level": lvl,
            "tag": _SEVERITY_TAG.get(lvl, lvl[:4]),
            "message": str(ev.get("message", ""))[:160],
            "delta_sec": delta,
            "count": 1,
        }
    return list(seen.values())


def build_observation_summaries(
    observations: list[dict[str, Any]],
    raw_events: list[dict[str, Any]],
    *,
    limit: int = 20,
    window_sec: float = 30.0,
) -> list[dict[str, Any]]:
    """Return newest-first user observations correlated with nearby warning/error events."""
    recent = list(reversed(observations[-limit:])) if limit > 0 else []
    summaries: list[dict[str, Any]] = []
    for idx, obs in enumerate(recent, start=1):
        obs_epoch = obs.get("epoch") if isinstance(obs.get("epoch"), (int, float)) else None
        correlated = _correlate_observation_issues(obs_epoch, raw_events, window_sec=window_sec)
        summaries.append({
            "index": idx,
            "ts": obs.get("ts", ""),
            "epoch": obs_epoch,
            "fingerprint": obs.get("fingerprint", ""),
            "note": obs.get("note") or obs.get("message", ""),
            "tab": obs.get("tab", ""),
            "url": obs.get("url", ""),
            "breadcrumbs": obs.get("breadcrumbs") or [],
            "viewport": obs.get("viewport") or {},
            "window_sec": window_sec,
            "correlated_issues": correlated,
        })
    return summaries


def summarize_debug_session(
    debug_dir: Optional[Path] = None,
    *,
    min_level: str = "WARNING",
    limit: int = 20,
    observation_limit: int = 20,
    correlation_window_sec: float = 30.0,
) -> dict[str, Any]:
    """Return a compact, deduplicated summary of errors/warnings, observations, and native crashes."""
    from dashboard.services.debug_session import get_debug_session_dir

    target = Path(debug_dir) if debug_dir else get_debug_session_dir()
    min_rank = _SEVERITY_RANK.get(min_level.strip().upper(), 2)
    events, raw_observations, totals = _read_jsonl_records(target / "events.jsonl", min_rank)
    issues = group_events(events, limit)
    observations = build_observation_summaries(
        raw_observations,
        events,
        limit=observation_limit,
        window_sec=correlation_window_sec,
    )

    fault_path = target / "faulthandler.log"
    fault_tail = ""
    if fault_path.is_file() and fault_path.stat().st_size > 0:
        lines = fault_path.read_text(encoding="utf-8", errors="replace").splitlines()
        fault_tail = "\n".join(lines[-20:])

    return {
        "session_dir": str(target),
        "exists": target.is_dir(),
        "totals": totals,
        "unique_issues": len(issues),
        "observations_count": len(raw_observations),
        "observations": observations,
        "native_crash_detected": bool(fault_tail.strip()),
        "native_crash_tail": fault_tail,
        "issues": issues,
    }


def _find_log_context(debug_log: Path, needle: str, context_lines: int) -> list[str]:
    """Return bounded surrounding lines around the last occurrence of needle in debug.log."""
    if not debug_log.is_file() or not needle:
        return []
    ring: deque[str] = deque(maxlen=max(1, context_lines))
    captured: list[str] = []
    remaining_after = -1
    with open(debug_log, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\r\n")
            if remaining_after >= 0:
                captured.append(line)
                remaining_after -= 1
                if remaining_after < 0:
                    continue
            if needle in line:
                captured = list(ring) + [line]
                remaining_after = context_lines
            ring.append(line)
    return captured


def get_issue_context(
    debug_dir: Optional[Path],
    identifier: str,
    *,
    context_lines: int = 15,
) -> Optional[dict[str, Any]]:
    """Return full traceback and bounded debug.log context for one issue (#index or fingerprint)."""
    from dashboard.services.debug_session import get_debug_session_dir

    target = Path(debug_dir) if debug_dir else get_debug_session_dir()
    summary = summarize_debug_session(target, min_level="WARNING", limit=200)
    ident = str(identifier).strip().lstrip("#")
    match: Optional[dict[str, Any]] = None
    for issue in summary["issues"]:
        if (ident.isdigit() and issue["index"] == int(ident)) or issue["fingerprint"].startswith(ident):
            match = issue
            break
    if match is None:
        return None

    needle = (match.get("message") or "").splitlines()[0][:80]
    log_ctx = _find_log_context(target / "debug.log", needle, context_lines)
    return {"issue": match, "log_context": log_ctx}
