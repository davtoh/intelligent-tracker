"""
SQLite Connection Coordination & Path-Keyed Locking Registry.

Provides ``SQLiteConnectionCoordinator`` so independent ``TrackerDB`` instances
targeting the same SQLite file share a single re-entrant lock (``RLock``),
consistent WAL/busy-timeout PRAGMA configuration, and reference-counted
``wal_checkpoint(TRUNCATE)`` on last close.
"""

import os
import sqlite3
import threading
from typing import Any


class SQLiteConnectionCoordinator:
    """Thread-safe registry coordinating locks, PRAGMAs, and refcounted closes per DB path."""

    def __init__(self) -> None:
        self._meta_lock = threading.Lock()
        self._path_locks: dict[str, Any] = {}
        self._ref_counts: dict[str, int] = {}

    @staticmethod
    def is_memory_path(db_path: str | os.PathLike[str]) -> bool:
        """Return True if ``db_path`` targets an in-memory SQLite database."""
        raw = os.fspath(db_path).strip()
        return (
            raw == ":memory:"
            or raw.startswith("file::memory:")
            or "mode=memory" in raw
        )

    @classmethod
    def normalize_path(cls, db_path: str | os.PathLike[str]) -> str | None:
        """Return normalized canonical path for file DBs, or None for in-memory DBs."""
        if cls.is_memory_path(db_path):
            return None
        return os.path.normcase(os.path.realpath(os.path.abspath(os.fspath(db_path))))

    def get_path_lock(self, db_path: str | os.PathLike[str]) -> threading.RLock:
        """Return a shared RLock for file DB paths, or an isolated RLock for :memory:."""
        key = self.normalize_path(db_path)
        if key is None:
            return threading.RLock()

        with self._meta_lock:
            lock = self._path_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._path_locks[key] = lock
            return lock

    def get_ref_count(self, db_path: str | os.PathLike[str]) -> int:
        """Return active open connection count for ``db_path`` (0 for in-memory DBs)."""
        key = self.normalize_path(db_path)
        if key is None:
            return 0
        with self._meta_lock:
            return self._ref_counts.get(key, 0)

    def open_connection(
        self,
        db_path: str | os.PathLike[str],
        lock: Any = None,
        busy_timeout_ms: int = 10000,
        timeout: float = 30.0,
    ) -> tuple[sqlite3.Connection, Any]:
        """Open and configure a SQLite connection under the path-keyed lock."""
        raw_path = os.fspath(db_path)
        key = self.normalize_path(raw_path)
        active_lock = lock or self.get_path_lock(raw_path)

        if key is not None:
            db_dir = os.path.dirname(os.path.abspath(raw_path))
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)

        with active_lock:
            conn = sqlite3.connect(
                raw_path,
                check_same_thread=False,
                timeout=timeout,
            )
            conn.row_factory = sqlite3.Row
            try:
                self._configure_pragmas(conn, is_file=(key is not None), busy_timeout_ms=busy_timeout_ms)
            except Exception:
                conn.close()
                raise

            if key is not None:
                with self._meta_lock:
                    self._ref_counts[key] = self._ref_counts.get(key, 0) + 1

        return conn, active_lock

    @staticmethod
    def _configure_pragmas(
        conn: sqlite3.Connection,
        is_file: bool,
        busy_timeout_ms: int,
    ) -> None:
        """Apply foreign-key, WAL, synchronous, and busy_timeout PRAGMAs."""
        cursor = conn.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON;")
            if is_file:
                cursor.execute("PRAGMA journal_mode = WAL;")
                cursor.execute("PRAGMA synchronous = NORMAL;")
            cursor.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)};")
        finally:
            cursor.close()

    def close_connection(
        self,
        db_path: str | os.PathLike[str],
        conn: sqlite3.Connection | None,
        lock: threading.RLock,
    ) -> None:
        """Close ``conn`` safely and checkpoint WAL only when the last reference closes."""
        if conn is None:
            return

        key = self.normalize_path(db_path)
        with lock:
            should_checkpoint = False
            if key is not None:
                with self._meta_lock:
                    current = self._ref_counts.get(key, 0)
                    if current > 1:
                        self._ref_counts[key] = current - 1
                    else:
                        self._ref_counts.pop(key, None)
                        should_checkpoint = True

            if should_checkpoint:
                try:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                except Exception:
                    pass
            try:
                conn.close()
            except Exception:
                pass


_default_coordinator = SQLiteConnectionCoordinator()


def get_connection_coordinator() -> SQLiteConnectionCoordinator:
    """Return the process-wide default ``SQLiteConnectionCoordinator``."""
    return _default_coordinator


__all__ = ["SQLiteConnectionCoordinator", "get_connection_coordinator"]
