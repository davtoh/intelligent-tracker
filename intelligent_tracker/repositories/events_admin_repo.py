"""Timeline Event Unread State, Facets, Bulk Clear & Export Repository Mixin."""

import sqlite3
import time
from typing import Any

from intelligent_tracker.repositories._event_filter_sql import (
    build_event_filter_clauses,
    dedupe_normalized_zones,
)
from intelligent_tracker.repositories.memory_repo import _hydrate_row


def _build_admin_filter_where(
    camera_id: str | None = None,
    severity: str | None = None,
    event_type: str | None = None,
    zone_id: str | None = None,
    start_time: float | None = None,
    end_time: float | None = None,
    read_only: bool = False,
    min_severity: str | None = None,
) -> tuple[str, list[Any]]:
    """Build parameterized WHERE clause for timeline admin clear and export queries."""
    clauses, params = build_event_filter_clauses(
        camera_id=camera_id,
        severity=severity,
        min_severity=min_severity,
        event_type=event_type,
        zone_id=zone_id,
        start_time=start_time,
        end_time=end_time,
        read_only=read_only,
    )
    where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return where_sql, params


class EventsAdminMixin:
    """Provides unread counts, filter facets, acknowledgement, clear, and export queries."""

    _conn: Any
    _lock: Any

    def count_unread_timeline_events(self) -> int:
        """Return total count of unread timeline events."""
        with self._lock:
            if self._conn is None:
                return 0
            cur = self._conn.cursor()
            try:
                row = cur.execute(
                    "SELECT COUNT(*) FROM world_timeline_events WHERE COALESCE(is_read, 0) = 0"
                ).fetchone()
                return int(row[0]) if row else 0
            except sqlite3.Error:
                return 0
            finally:
                cur.close()

    def get_timeline_event_facets(self) -> dict[str, list[str]]:
        """Return distinct sorted camera, zone, event_type, and severity values."""
        empty: dict[str, list[str]] = {"cameras": [], "zones": [], "event_types": [], "severities": []}
        with self._lock:
            if self._conn is None:
                return empty
            cur = self._conn.cursor()
            try:
                def _distinct(expr: str) -> list[str]:
                    rows = cur.execute(
                        f"SELECT DISTINCT {expr} AS val FROM world_timeline_events "
                        f"WHERE {expr} IS NOT NULL AND TRIM({expr}) != '' ORDER BY val ASC"
                    ).fetchall()
                    return [str(r[0]) for r in rows if r[0]]

                return {
                    "cameras": _distinct("camera_id"),
                    "zones": dedupe_normalized_zones(_distinct("zone_id")),
                    "event_types": _distinct("event_type"),
                    "severities": _distinct("LOWER(TRIM(json_extract(metadata_json, '$.severity')))"),
                }
            finally:
                cur.close()

    def acknowledge_timeline_events(
        self,
        event_ids: list[int] | None = None,
        mark_all: bool = False,
        is_read: bool = True,
    ) -> int:
        """Mark specific or all timeline events as read or unread."""
        ack_val = 1 if is_read else 0
        ack_ts = time.time() if is_read else None
        with self._lock:
            if self._conn is None:
                return 0
            cur = self._conn.cursor()
            try:
                if mark_all:
                    cur.execute(
                        "UPDATE world_timeline_events SET is_read = ?, acknowledged_at = ? "
                        "WHERE COALESCE(is_read, 0) != ?",
                        (ack_val, ack_ts, ack_val),
                    )
                else:
                    ids = [int(eid) for eid in (event_ids or []) if eid is not None]
                    if not ids:
                        return 0
                    placeholders = ",".join("?" for _ in ids)
                    cur.execute(
                        f"UPDATE world_timeline_events SET is_read = ?, acknowledged_at = ? "
                        f"WHERE id IN ({placeholders})",
                        [ack_val, ack_ts, *ids],
                    )
                self._conn.commit()
                return int(cur.rowcount)
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def clear_timeline_events(
        self,
        camera_id: str | None = None,
        severity: str | None = None,
        event_type: str | None = None,
        zone_id: str | None = None,
        read_only: bool = False,
    ) -> int:
        """Delete timeline events matching optional filters and return deleted row count."""
        where_sql, params = _build_admin_filter_where(
            camera_id=camera_id, severity=severity, event_type=event_type,
            zone_id=zone_id, read_only=read_only,
        )
        with self._lock:
            if self._conn is None:
                return 0
            cur = self._conn.cursor()
            try:
                cur.execute(f"DELETE FROM world_timeline_events{where_sql}", params)
                self._conn.commit()
                return int(cur.rowcount)
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def export_timeline_events(
        self,
        camera_id: str | None = None,
        severity: str | None = None,
        event_type: str | None = None,
        zone_id: str | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Query timeline events ordered by timestamp descending for CSV/JSON export."""
        where_sql, params = _build_admin_filter_where(
            camera_id=camera_id, severity=severity, event_type=event_type,
            zone_id=zone_id, start_time=start_time, end_time=end_time,
        )
        params.append(max(1, min(10000, int(limit))))
        sql = f"SELECT * FROM world_timeline_events{where_sql} ORDER BY timestamp DESC LIMIT ?"
        with self._lock:
            if self._conn is None:
                return []
            cur = self._conn.cursor()
            try:
                rows = cur.execute(sql, params).fetchall()
                return [_hydrate_row(row, "metadata_json", "metadata") for row in rows]
            finally:
                cur.close()
