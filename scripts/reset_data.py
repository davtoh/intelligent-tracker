#!/usr/bin/env python3
"""OS-agnostic CLI to safely back up and reset Intelligent Tracker local or Docker data."""

import argparse
import os
from pathlib import Path
import sys
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dashboard.services.data_reset_service import (
    ResetItem,
    ResetPaths,
    VALID_CATEGORIES,
    build_reset_plan,
    check_running_server,
    create_pre_reset_backup,
    execute_reset_items,
    resolve_reset_paths,
)


def _format_bytes(num_bytes: int) -> str:
    """Format byte count into compact human-readable string."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{num_bytes} B"


def _add_path_args(parser: argparse.ArgumentParser) -> None:
    """Register path override arguments matching env vars."""
    parser.add_argument("--db", default=None, help="Override SQLite DB path (env: TRACKER_DB_PATH / TRACKER_DB)")
    parser.add_argument("--cameras-config", default=None, help="Override cameras.json (env: CAMERAS_CONFIG_PATH)")
    parser.add_argument("--scenarios-config", default=None, help="Override scenarios.yaml (env: SCENARIOS_CONFIG_PATH)")
    parser.add_argument("--crops-dir", default=None, help="Override crops dir (env: TRACKER_CROPS_DIR)")
    parser.add_argument("--reports-dir", default=None, help="Override reports dir (env: TRACKER_REPORTS_DIR)")
    parser.add_argument("--videos-dir", default=None, help="Override videos dir (env: TRACKER_VIDEOS_DIR)")
    parser.add_argument("--debug-dir", default=None, help="Override debug session dir (env: TRACKER_DEBUG_DIR)")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments for reset_data.py."""
    parser = argparse.ArgumentParser(description="Back up and reset Intelligent Tracker dashboard data.")
    parser.add_argument("--target", choices=("local", "docker", "all"), default="local", help="Scope to reset.")
    _add_path_args(parser)
    parser.add_argument("--only", default=None, help=f"Comma-separated subset of: {', '.join(VALID_CATEGORIES)}")
    parser.add_argument("--include-videos", action="store_true", help="Include videos when running with --yes.")
    parser.add_argument("--include-configs", action="store_true", help="Include configs when running with --yes.")
    parser.add_argument("-y", "--yes", action="store_true", help="Non-interactive mode (accept defaults).")
    parser.add_argument("--prompt", action="store_true", help="Force interactive prompts even in headless/non-TTY.")
    parser.add_argument("--no-backup", action="store_true", help="Skip automatic pre-reset zip backup.")
    parser.add_argument("--backup-out", default=None, help="Custom output path for pre-reset zip backup.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting.")
    parser.add_argument("--force", action="store_true", help="Proceed even if dashboard appears to be running on port 8000.")
    return parser.parse_args(argv)


def _parse_only_filter(raw: Optional[str]) -> Optional[set[str]]:
    """Parse and validate --only comma-separated category names."""
    if not raw:
        return None
    chosen = {part.strip() for part in raw.split(",") if part.strip()}
    invalid = sorted(chosen - set(VALID_CATEGORIES))
    if invalid:
        raise ValueError(f"Unknown --only categories: {', '.join(invalid)}. Valid: {', '.join(VALID_CATEGORIES)}")
    return chosen


def _print_plan_header(paths: ResetPaths, plan: list[ResetItem], target: str) -> None:
    """Print resolved paths, active env overrides, and category inventory."""
    print(f"=== Intelligent Tracker Data Reset (target={target}) ===")
    if paths.active_env_vars:
        print("Active env overrides detected:")
        for key, val in sorted(paths.active_env_vars.items()):
            print(f"  {key}={val}")
    print("Categories in scope:")
    for item in plan:
        if item.kind == "docker":
            print(f"  - {item.key:<14}: {item.label}")
        else:
            targets_desc = ", ".join(str(p) for p in item.targets)
            state = f"{item.file_count} files, {_format_bytes(item.total_bytes)}" if item.exists else "empty/missing"
            print(f"  - {item.key:<14}: {item.label} [{state}] ({targets_desc})")


def _prompt_item(item: ResetItem, default_yes: bool) -> bool:
    """Prompt user for one category using [Y/n] or [y/N]."""
    hint = "Y/n" if default_yes else "y/N"
    while True:
        try:
            ans = input(f"Delete '{item.key}' ({item.label})? [{hint}]: ").strip().lower()
        except EOFError:
            return default_yes
        if not ans:
            return default_yes
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        print("  Please answer 'y' or 'n'.")


def _select_items(plan: list[ResetItem], args: argparse.Namespace) -> list[ResetItem]:
    """Resolve which ResetItems are selected based on --yes, --dry-run, flags, and prompts."""
    selected: list[ResetItem] = []
    auto_accept = bool(args.yes or (args.dry_run and not args.prompt))
    for item in plan:
        default_choice = item.default_yes
        if item.key == "videos" and args.include_videos:
            default_choice = True
        if item.key == "configs" and args.include_configs:
            default_choice = True
        if item.kind != "docker" and not item.exists:
            continue
        if auto_accept:
            if default_choice:
                selected.append(item)
        elif _prompt_item(item, default_choice):
            selected.append(item)
    return selected


def _run_backup_if_needed(paths: ResetPaths, args: argparse.Namespace, selected: list[ResetItem]) -> None:
    """Export pre-reset zip backup when local items are selected and backup is enabled."""
    has_local = any(item.kind != "docker" for item in selected)
    if not has_local or args.no_backup or args.dry_run:
        return
    backup_path = create_pre_reset_backup(paths, backup_out=args.backup_out)
    if backup_path is not None:
        print(f"[Backup] Saved pre-reset archive: {backup_path}")
    else:
        print("[Backup] Skipped (no existing DB, crops, or config files).")


def main(argv: Optional[list[str]] = None) -> int:
    """Entrypoint for scripts/reset_data.py."""
    args = parse_args(argv)
    try:
        only_filter = _parse_only_filter(args.only)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    if not args.yes and not args.prompt and not args.dry_run and not sys.stdin.isatty():
        print("[ERROR] Non-interactive stdin detected. Pass --yes, --prompt, or --dry-run.", file=sys.stderr)
        return 2

    paths = resolve_reset_paths(
        repo_root=REPO_ROOT, db_path=args.db, cameras_config=args.cameras_config,
        scenarios_config=args.scenarios_config, crops_dir=args.crops_dir,
        reports_dir=args.reports_dir, videos_dir=args.videos_dir, debug_dir=args.debug_dir,
    )
    plan = build_reset_plan(paths, target=args.target, only=only_filter)
    _print_plan_header(paths, plan, args.target)

    if args.target in ("local", "all") and not args.dry_run and not args.force:
        pids = check_running_server(int(os.getenv("PORT", "8000")))
        if pids:
            print(f"[ABORT] Dashboard running on port 8000 (PIDs: {pids}). Stop it or pass --force.", file=sys.stderr)
            return 1

    selected = _select_items(plan, args)
    if not selected:
        print("Nothing selected to delete.")
        return 0
    _run_backup_if_needed(paths, args, selected)

    result = execute_reset_items(selected, dry_run=args.dry_run, repo_root=REPO_ROOT)
    print("\n=== Reset Summary ===")
    for entry in result["items"]:
        print(f"  - {entry['key']}: {entry['status']}")
    for err in result["errors"]:
        print(f"[ERROR] {err}", file=sys.stderr)
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
