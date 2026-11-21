#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - System State Persistence, Auto-Restore & Backup Migration.

Provides complete snapshot export and migration capabilities:
1. One-click system snapshot export (`.zip`) containing TrackerDB (SQLite),
   face & object thumbnail crops (`data/crops/`), camera topologies (`configs/cameras.json`),
   and scenario/alert rules (`configs/*.yaml`).
2. Full system import & migration for porting configurations between edge devices
   (e.g., workstation to Raspberry Pi / Intel NUC) with schema validation and hot reload.
3. Automatic boot restoration for persistent VMS multi-stream pipelines.
4. CLI tooling: `python -m intelligent_tracker.backup --export backup.zip` and `--import backup.zip`.
"""

import os
import sys
import stat
import time
import json
import zipfile
import hashlib
import shutil
import sqlite3
import logging
import argparse
from typing import Callable, Dict, List, Optional, Tuple, Any

logger = logging.getLogger("intelligent_tracker.backup")

BACKUP_SCHEMA_VERSION = "1.0.0"


def calculate_sha256(filepath: str) -> str:
    """Calculate SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _add_file_to_zip(
    zipf: zipfile.ZipFile, full_path: str, arcname: str, manifest: Dict[str, Any]
) -> None:
    """Write a single file into the backup archive and record its manifest entry."""
    zipf.write(full_path, arcname=arcname)
    manifest["files"].append({
        "arcname": arcname,
        "size": os.path.getsize(full_path),
        "sha256": calculate_sha256(full_path),
    })


def _collect_dir_to_zip(
    zipf: zipfile.ZipFile,
    base_dir: str,
    arc_prefix: str,
    extensions: Tuple[str, ...],
    manifest: Dict[str, Any],
) -> None:
    """Walk base_dir and add matching files to the zip archive."""
    if not os.path.exists(base_dir):
        return
    for root, _, files in os.walk(base_dir):
        for file in files:
            if file.lower().endswith(extensions):
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, base_dir)
                arcname = f"{arc_prefix}/{rel_path}".replace("\\", "/")
                _add_file_to_zip(zipf, full_path, arcname, manifest)


def _is_unsafe_zip_entry(item: zipfile.ZipInfo) -> bool:
    """Return True if zip entry is a symlink, absolute path, or traversal attempt."""
    mode = (item.external_attr or 0) >> 16
    if stat.S_ISLNK(mode):
        return True
    raw = item.filename or ""
    if raw.startswith(("/", "\\")) or (len(raw) >= 2 and raw[1] == ":"):
        return True
    norm_target = os.path.normpath(raw)
    if norm_target.startswith(("/", "\\", "..")) or ".." in norm_target.split(os.sep):
        return True
    return False


def _remove_sqlite_sidecars(db_path: str) -> None:
    """Remove stale SQLite WAL/SHM sidecar files if present."""
    for suffix in ("-wal", "-shm"):
        sidecar = f"{db_path}{suffix}"
        if os.path.exists(sidecar):
            try:
                os.remove(sidecar)
            except OSError as exc:
                logger.warning("Could not remove SQLite sidecar %s: %s", sidecar, exc)


def _resolve_restore_dest(
    norm_fwd: str, db_path: str, crops_dir: str, configs_dir: str
) -> Optional[str]:
    """Resolve and realpath-verify destination for a backup archive entry."""
    if norm_fwd.startswith("data/crops/") or norm_fwd.startswith("crops/"):
        base_dir = os.path.realpath(crops_dir)
        dest = os.path.join(crops_dir, os.path.basename(norm_fwd))
    elif norm_fwd == "data/tracker.db" or norm_fwd == "tracker.db":
        base_dir = os.path.realpath(os.path.dirname(os.path.abspath(db_path)))
        dest = db_path
    elif norm_fwd.startswith("configs/"):
        base_dir = os.path.realpath(configs_dir)
        rel = norm_fwd.split("configs/", 1)[-1]
        dest = os.path.join(configs_dir, rel)
    else:
        return None
    real_dest = os.path.realpath(dest)
    if real_dest != base_dir and not real_dest.startswith(base_dir + os.sep):
        return None
    return dest


class BackupManager:
    """
    Manages complete system state serialization, archive creation,
    and cross-platform migration extraction.
    """

    def __init__(
        self,
        db_path: str = "data/tracker.db",
        crops_dir: str = "data/crops",
        configs_dir: str = "configs",
        hot_reload_callbacks: Optional[List[Callable[[], Any]]] = None,
    ):
        self.db_path = db_path
        self.crops_dir = crops_dir
        self.configs_dir = configs_dir
        self._hot_reload_callbacks: List[Callable[[], Any]] = list(hot_reload_callbacks or [])

    def register_hot_reload_callback(self, callback: Callable[[], Any]) -> None:
        """Register a callback invoked when restore_backup(hot_reload=True) finishes."""
        if callback not in self._hot_reload_callbacks:
            self._hot_reload_callbacks.append(callback)

    def get_database_summary(self) -> Dict[str, int]:
        """Queries entity and sighting record statistics from the SQLite database."""
        stats = {"entities": 0, "signatures": 0, "sightings": 0}
        if not os.path.exists(self.db_path):
            return stats

        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM entities")
            stats["entities"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM entity_signatures")
            stats["signatures"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM sightings")
            stats["sightings"] = cur.fetchone()[0]
            conn.close()
        except Exception as e:
            logger.warning("Could not read database summary: %s", e)
        return stats

    def create_backup(
        self,
        output_path: Optional[str] = None,
        include_crops: bool = True,
    ) -> str:
        """Create a versioned, portable system backup `.zip` archive."""
        if not output_path:
            output_path = f"intelligent_tracker_backup_{time.strftime('%Y%m%d_%H%M%S')}.zip"
        output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        compression = zipfile.ZIP_DEFLATED
        try:
            import zlib  # noqa: F401
        except ImportError:
            compression = zipfile.ZIP_STORED

        manifest: Dict[str, Any] = {
            "version": BACKUP_SCHEMA_VERSION,
            "created_at": time.time(),
            "created_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "platform": sys.platform,
            "database_stats": self.get_database_summary(),
            "files": [],
        }
        with zipfile.ZipFile(output_path, "w", compression=compression) as zipf:
            self._package_database(zipf, manifest)
            _collect_dir_to_zip(
                zipf, self.configs_dir, "configs", (".yaml", ".yml", ".json", ".ini", ".conf"), manifest
            )
            if include_crops:
                _collect_dir_to_zip(
                    zipf, self.crops_dir, "data/crops", (".jpg", ".jpeg", ".png", ".webp"), manifest
                )
            zipf.writestr("manifest.json", json.dumps(manifest, indent=2))
        logger.info("Created system backup archive at: %s (%d files)", output_path, len(manifest["files"]))
        return output_path

    def _package_database(self, zipf: zipfile.ZipFile, manifest: Dict[str, Any]) -> None:
        """Checkpoint SQLite WAL and package tracker.db into zipf."""
        if not os.path.exists(self.db_path):
            return
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA wal_checkpoint(FULL)")
            conn.close()
        except Exception:
            pass
        _add_file_to_zip(zipf, self.db_path, "data/tracker.db", manifest)

    def inspect_backup(self, zip_path: str) -> Dict[str, Any]:
        """Reads metadata manifest and file list from a backup archive without extraction."""
        if not os.path.exists(zip_path):
            raise FileNotFoundError(f"Backup archive not found: {zip_path}")

        with zipfile.ZipFile(zip_path, "r") as zipf:
            if "manifest.json" not in zipf.namelist():
                raise ValueError("Invalid backup archive: missing 'manifest.json'")
            manifest_data = zipf.read("manifest.json").decode("utf-8")
            return json.loads(manifest_data)

    def restore_backup(self, zip_path: str, hot_reload: bool = True) -> Dict[str, Any]:
        """Validate, extract, and restore database, crops, and configs from an archive."""
        if not os.path.exists(zip_path):
            raise FileNotFoundError(f"Backup archive not found: {zip_path}")
        manifest = self.inspect_backup(zip_path)
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        os.makedirs(self.crops_dir, exist_ok=True)
        os.makedirs(self.configs_dir, exist_ok=True)

        restored_files, db_restored = self._extract_archive_entries(zip_path)
        if db_restored:
            _remove_sqlite_sidecars(self.db_path)
        reloaded_count = self._invoke_hot_reload() if hot_reload else 0
        result = {
            "success": True,
            "version": manifest.get("version"),
            "backup_date": manifest.get("created_iso"),
            "restored_files_count": restored_files,
            "hot_reloaded": reloaded_count,
            "database_stats": self.get_database_summary(),
        }
        logger.info("Successfully restored system state from %s (%d files)", zip_path, restored_files)
        return result

    def _extract_archive_entries(self, zip_path: str) -> Tuple[int, bool]:
        """Extract validated entries from zip_path into configured target directories."""
        restored_files = 0
        db_restored = False
        with zipfile.ZipFile(zip_path, "r") as zipf:
            for item in zipf.infolist():
                if item.filename == "manifest.json" or item.is_dir():
                    continue
                if _is_unsafe_zip_entry(item):
                    logger.warning("Skipping potentially unsafe zip entry: %s", item.filename)
                    continue
                norm_fwd = os.path.normpath(item.filename).replace("\\", "/")
                dest = _resolve_restore_dest(norm_fwd, self.db_path, self.crops_dir, self.configs_dir)
                if dest is None:
                    logger.warning("Skipping unrecognized or escaping zip entry: %s", item.filename)
                    continue
                if dest == self.db_path:
                    self._prepare_db_overwrite()
                    db_restored = True
                os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
                with open(dest, "wb") as f_out:
                    f_out.write(zipf.read(item.filename))
                restored_files += 1
        return restored_files, db_restored

    def _prepare_db_overwrite(self) -> None:
        """Back up existing DB and remove stale WAL/SHM sidecars before restore."""
        if os.path.exists(self.db_path):
            try:
                shutil.copy2(self.db_path, f"{self.db_path}.pre_restore.bak")
            except Exception:
                pass
        _remove_sqlite_sidecars(self.db_path)

    def _invoke_hot_reload(self) -> int:
        """Execute registered hot-reload callbacks after backup restoration."""
        count = 0
        for cb in list(self._hot_reload_callbacks):
            try:
                cb()
                count += 1
            except Exception as exc:
                logger.warning("Backup hot_reload callback failed: %s", exc)
        return count


def _run_cli_action(args: argparse.Namespace, manager: BackupManager) -> None:
    """Execute the selected CLI backup/restore/inspect action."""
    if args.export:
        out = manager.create_backup(output_path=args.export, include_crops=not args.no_crops)
        print(f"[OK] System state snapshot exported successfully to: {out}")
    elif args.import_file:
        res = manager.restore_backup(zip_path=args.import_file)
        print(f"[OK] System state restored successfully from: {args.import_file}")
        print(f"     Restored files: {res['restored_files_count']}")
        print(f"     Entities: {res['database_stats'].get('entities', 0)}")
        print(f"     Sightings: {res['database_stats'].get('sightings', 0)}")
    elif args.info:
        info = manager.inspect_backup(args.info)
        db_stats = info.get("database_stats", {})
        print("=== INTELLIGENT TRACKER BACKUP MANIFEST ===")
        print(f"Version:      {info.get('version')}\nCreated:      {info.get('created_iso')}")
        print(f"Platform:     {info.get('platform')}\nFiles count:  {len(info.get('files', []))}")
        print(f"DB Entities:  {db_stats.get('entities', 0)}\nDB Sightings: {db_stats.get('sightings', 0)}")


def main():
    """Command-line interface for backup export, import, and inspection."""
    parser = argparse.ArgumentParser(
        description="Intelligent Tracker - State Persistence, Backup & Migration Tool"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--export", metavar="FILE.ZIP", help="Export system snapshot to portable zip archive")
    group.add_argument("--import", dest="import_file", metavar="FILE.ZIP", help="Import & restore system state from zip archive")
    group.add_argument("--info", metavar="FILE.ZIP", help="Inspect backup archive manifest and statistics")
    parser.add_argument("--db", default="data/tracker.db", help="SQLite database path")
    parser.add_argument("--crops", default="data/crops", help="Crops directory")
    parser.add_argument("--configs", default="configs", help="Configurations directory")
    parser.add_argument("--no-crops", action="store_true", help="Exclude image crops from export to reduce size")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    manager = BackupManager(db_path=args.db, crops_dir=args.crops, configs_dir=args.configs)
    _run_cli_action(args, manager)


if __name__ == "__main__":
    main()
