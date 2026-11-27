#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""OS-agnostic reset and pre-reset backup service for Intelligent Tracker data."""

from dataclasses import dataclass, field
from pathlib import Path
import logging
import os
import shutil
import subprocess
import time
from typing import Any, Optional

from intelligent_tracker.backup import BackupManager

logger = logging.getLogger("intelligent_tracker.data_reset")

VALID_CATEGORIES = (
    "db",
    "crops",
    "reports",
    "debug_session",
    "videos",
    "configs",
    "docker_volumes",
)

_DIR_CATEGORIES = {"crops", "reports", "videos"}


@dataclass
class ResetPaths:
    """Resolved filesystem paths and active environment overrides for data reset."""

    repo_root: Path
    db_path: Path
    cameras_config: Path
    scenarios_config: Path
    crops_dir: Path
    reports_dir: Path
    videos_dir: Path
    debug_dir: Path
    active_env_vars: dict[str, str] = field(default_factory=dict)


@dataclass
class ResetItem:
    """Single reset category with resolved targets, size metrics, and prompt default."""

    key: str
    label: str
    default_yes: bool
    kind: str  # "files" | "dir_contents" | "dir_tree" | "docker"
    targets: list[Path] = field(default_factory=list)
    file_count: int = 0
    total_bytes: int = 0
    exists: bool = False


def _pick_path(
    explicit: Optional[str | Path],
    env_keys: tuple[str, ...],
    default_rel: Path,
    repo_root: Path,
    active_env: dict[str, str],
) -> Path:
    """Resolve path with precedence: explicit CLI arg > env var > repo default."""
    if explicit:
        p = Path(explicit)
        return p if p.is_absolute() else (repo_root / p)
    for key in env_keys:
        val = os.getenv(key, "").strip()
        if val:
            active_env[key] = val
            p = Path(val)
            return p if p.is_absolute() else (repo_root / p)
    return repo_root / default_rel


def resolve_reset_paths(
    repo_root: Optional[Path] = None,
    *,
    db_path: Optional[str | Path] = None,
    cameras_config: Optional[str | Path] = None,
    scenarios_config: Optional[str | Path] = None,
    crops_dir: Optional[str | Path] = None,
    reports_dir: Optional[str | Path] = None,
    videos_dir: Optional[str | Path] = None,
    debug_dir: Optional[str | Path] = None,
) -> ResetPaths:
    """Resolve all resettable paths honoring CLI flags, environment variables, and defaults."""
    root = Path(repo_root).resolve() if repo_root else Path.cwd().resolve()
    env_map: dict[str, str] = {}
    return ResetPaths(
        repo_root=root,
        db_path=_pick_path(db_path, ("TRACKER_DB_PATH", "TRACKER_DB"), Path("data/tracker.db"), root, env_map),
        cameras_config=_pick_path(cameras_config, ("CAMERAS_CONFIG_PATH",), Path("configs/cameras.json"), root, env_map),
        scenarios_config=_pick_path(
            scenarios_config, ("SCENARIOS_CONFIG_PATH",), Path("configs/scenarios.yaml"), root, env_map
        ),
        crops_dir=_pick_path(crops_dir, ("TRACKER_CROPS_DIR",), Path("data/crops"), root, env_map),
        reports_dir=_pick_path(reports_dir, ("TRACKER_REPORTS_DIR",), Path("data/reports"), root, env_map),
        videos_dir=_pick_path(videos_dir, ("TRACKER_VIDEOS_DIR",), Path("data/videos"), root, env_map),
        debug_dir=_pick_path(debug_dir, ("TRACKER_DEBUG_DIR",), Path("data/debug_session"), root, env_map),
        active_env_vars=env_map,
    )


def _measure_paths(paths: list[Path], kind: str) -> tuple[int, int, bool]:
    """Return (file_count, total_bytes, exists) across target paths."""
    count = 0
    total = 0
    any_exists = False
    for target in paths:
        if not target.exists():
            continue
        if target.is_file():
            any_exists = True
            count += 1
            total += target.stat().st_size
        elif target.is_dir():
            if kind == "dir_tree":
                any_exists = True
            for entry in target.rglob("*"):
                if entry.is_file():
                    any_exists = True
                    count += 1
                    total += entry.stat().st_size
    return count, total, any_exists


def _make_item(key: str, label: str, default_yes: bool, kind: str, targets: list[Path]) -> ResetItem:
    """Build a populated ResetItem with measured size and existence."""
    if kind == "docker":
        return ResetItem(key=key, label=label, default_yes=default_yes, kind=kind, targets=[], exists=True)
    count, total, exists = _measure_paths(targets, kind)
    return ResetItem(
        key=key,
        label=label,
        default_yes=default_yes,
        kind=kind,
        targets=targets,
        file_count=count,
        total_bytes=total,
        exists=exists,
    )


def build_reset_plan(
    paths: ResetPaths,
    target: str = "local",
    only: Optional[set[str]] = None,
) -> list[ResetItem]:
    """Build ordered reset plan filtered by target (local|docker|all) and optional category filter."""
    items: list[ResetItem] = []
    if target in ("local", "all"):
        db_targets = [paths.db_path, Path(f"{paths.db_path}-wal"), Path(f"{paths.db_path}-shm")]
        items.extend([
            _make_item("db", "SQLite database & WAL sidecars", True, "files", db_targets),
            _make_item("crops", "Enrolled & auto-saved crops", True, "dir_contents", [paths.crops_dir]),
            _make_item("reports", "Report & detection artifacts", True, "dir_contents", [paths.reports_dir]),
            _make_item("debug_session", "Debug session data & logs", True, "dir_tree", [paths.debug_dir]),
            _make_item("videos", "Uploaded & recorded videos", False, "dir_contents", [paths.videos_dir]),
            _make_item(
                "configs",
                "Camera & scenario configs",
                False,
                "files",
                [paths.cameras_config, paths.scenarios_config],
            ),
        ])
    if target in ("docker", "all"):
        items.append(_make_item("docker_volumes", "Docker Compose volumes (down -v)", True, "docker", []))

    if only is not None:
        return [item for item in items if item.key in only]
    return items


def _has_backup_payload(paths: ResetPaths) -> bool:
    """Return True if any local DB, crop, or config file exists to back up."""
    if paths.db_path.is_file() or paths.cameras_config.is_file() or paths.scenarios_config.is_file():
        return True
    if paths.crops_dir.is_dir() and any(paths.crops_dir.rglob("*")):
        return True
    return False


def create_pre_reset_backup(
    paths: ResetPaths,
    backup_out: Optional[str | Path] = None,
) -> Optional[Path]:
    """Export a pre-reset zip archive via BackupManager; returns path or None if nothing to back up."""
    if not _has_backup_payload(paths):
        return None
    if backup_out:
        out_path = Path(backup_out)
        if not out_path.is_absolute():
            out_path = paths.repo_root / out_path
    else:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        out_path = paths.repo_root / "data" / "backups" / f"pre_reset_{stamp}.zip"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    mgr = BackupManager(
        db_path=str(paths.db_path),
        crops_dir=str(paths.crops_dir),
        configs_dir=str(paths.cameras_config.parent),
    )
    created = mgr.create_backup(output_path=str(out_path), include_crops=True)
    return Path(created)


def check_running_server(port: int = 8000) -> list[int]:
    """Return PIDs listening on the dashboard port, or empty list on failure."""
    try:
        from dashboard.services.process_supervisor import find_port_listeners

        return find_port_listeners(port)
    except Exception:
        return []


def wipe_debug_session(debug_dir: Path) -> bool:
    """Delete an existing debug session directory and recreate its base layout."""
    removed = False
    if debug_dir.exists():
        shutil.rmtree(debug_dir)
        removed = True
    (debug_dir / "crops").mkdir(parents=True, exist_ok=True)
    (debug_dir / "reports").mkdir(parents=True, exist_ok=True)
    (debug_dir / "recordings").mkdir(parents=True, exist_ok=True)
    return removed


def _delete_local_item(item: ResetItem) -> tuple[int, list[str]]:
    """Delete files or directory contents for one local ResetItem."""
    removed_files = 0
    errors: list[str] = []
    for target in item.targets:
        if not target.exists():
            continue
        try:
            if item.kind == "files":
                if target.is_file():
                    target.unlink()
                    removed_files += 1
            elif item.kind == "dir_contents":
                if target.is_dir():
                    removed_files += sum(1 for p in target.rglob("*") if p.is_file())
                    shutil.rmtree(target)
                    target.mkdir(parents=True, exist_ok=True)
            elif item.kind == "dir_tree":
                if target.is_dir():
                    removed_files += sum(1 for p in target.rglob("*") if p.is_file())
                    shutil.rmtree(target)
        except OSError as exc:
            errors.append(f"{target}: {exc}")
    return removed_files, errors


def _run_docker_compose_down(repo_root: Path) -> tuple[bool, str]:
    """Run `docker compose down -v` in repo_root without invoking a shell."""
    docker_bin = shutil.which("docker")
    if not docker_bin:
        return False, "docker executable not found on PATH"
    proc = subprocess.run(
        [docker_bin, "compose", "down", "-v"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    return proc.returncode == 0, output


def execute_reset_items(
    selected_items: list[ResetItem],
    *,
    dry_run: bool = False,
    repo_root: Optional[Path] = None,
) -> dict[str, Any]:
    """Execute or simulate deletion across selected ResetItems."""
    root = Path(repo_root).resolve() if repo_root else Path.cwd().resolve()
    summary: dict[str, Any] = {"dry_run": dry_run, "items": [], "errors": []}
    for item in selected_items:
        if dry_run:
            summary["items"].append({"key": item.key, "status": "would_delete", "files": item.file_count})
            continue
        if item.kind == "docker":
            ok, msg = _run_docker_compose_down(root)
            status = "deleted" if ok else "failed"
            summary["items"].append({"key": item.key, "status": status, "detail": msg})
            if not ok:
                summary["errors"].append(f"docker_volumes: {msg}")
            continue
        removed, errs = _delete_local_item(item)
        summary["items"].append({"key": item.key, "status": "deleted", "files_removed": removed})
        summary["errors"].extend(errs)
    return summary
