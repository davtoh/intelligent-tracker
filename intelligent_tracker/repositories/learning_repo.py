"""
Active Learning and Category Repository Mixin.

Manages active learning candidate queues ("Review & Learn" Inbox) and
role-based custom categories for spatial and access control rules.
"""

import time
from typing import Optional, Dict, Any, List

from intelligent_tracker.repositories.learning_helpers import (
    _build_review_insert_params,
    _matches_review_candidate,
    _parse_bbox_json,
    _serialize_bbox,
)
from intelligent_tracker.repositories.video_schema import expand_video_aliases


_INSERT_REVIEW_SQL = """
INSERT INTO review_queue (
    camera_id, track_id, crop_path, timestamp, suggested_entity_id,
    suggested_name, suggested_category, similarity, status,
    video_filename, media_offset_sec, bbox_json, frame_width, frame_height, run_id, reason
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


_REVIEW_SORT_SQL = {
    "newest": "id DESC",
    "oldest": "id ASC",
    "sim_desc": "similarity DESC, id DESC",
    "sim_asc": "similarity ASC, id DESC",
}


def _build_review_filter_sql(
    status: Optional[str] = None,
    matched: Optional[str] = None,
    reason: Optional[str] = None,
) -> tuple[str, List[Any]]:
    """Build parameterized WHERE clause for ``review_queue`` triage queries."""
    clauses: List[str] = []
    params: List[Any] = []
    st = (status or "").strip().lower()
    if st and st != "all":
        clauses.append("status = ?")
        params.append(st)
    mt = (matched or "").strip().lower()
    if mt == "matched":
        clauses.append("(suggested_entity_id IS NOT NULL OR TRIM(COALESCE(suggested_name, '')) != '')")
    elif mt == "unmatched":
        clauses.append("(suggested_entity_id IS NULL AND TRIM(COALESCE(suggested_name, '')) = '')")
    rs = (reason or "").strip().lower()
    if rs and rs != "all":
        clauses.append("LOWER(COALESCE(reason, 'borderline')) = ?")
        params.append(rs)
    return (f" WHERE {' AND '.join(clauses)}" if clauses else "", params)


class LearningMixin:
    """Provides active learning review items and custom category persistence."""

    _conn: Any
    _lock: Any

    def add_review_item(
        self, camera_id: str, track_id: int, crop_path: str,
        suggested_entity_id: Optional[int] = None, suggested_name: str = "",
        suggested_category: str = "", similarity: float = 0.0, status: str = "pending",
        video_filename: str = "", media_offset_sec: float = 0.0, bbox: Any = None,
        frame_width: int = 0, frame_height: int = 0, run_id: str = "",
        reason: str = "borderline", **kwargs,
    ) -> int:
        """Add an ambiguous detection to the active learning review queue."""
        params = _build_review_insert_params(
            camera_id, track_id, crop_path, suggested_entity_id, suggested_name,
            suggested_category, similarity, status, video_filename, media_offset_sec,
            bbox, frame_width, frame_height, run_id, reason, kwargs,
        )
        with self._lock:
            if self._conn is None:
                raise RuntimeError("Database connection is closed")
            cur = self._conn.cursor()
            try:
                cur.execute(_INSERT_REVIEW_SQL, params)
                self._conn.commit()
                return cur.lastrowid
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def count_review_items(
        self,
        status: Optional[str] = None,
        matched: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> int:
        """Count active learning review items matching optional triage filters."""
        where_sql, params = _build_review_filter_sql(status=status, matched=matched, reason=reason)
        with self._lock:
            if self._conn is None:
                return 0
            cur = self._conn.cursor()
            try:
                cur.execute(f"SELECT COUNT(*) FROM review_queue{where_sql}", params)
                row = cur.fetchone()
                return int(row[0]) if row else 0
            finally:
                cur.close()

    def list_review_items(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        matched: Optional[str] = None,
        reason: Optional[str] = None,
        sort: str = "newest",
    ) -> List[Dict[str, Any]]:
        """List active learning review items with triage filters, sorting, and pagination."""
        where_sql, params = _build_review_filter_sql(status=status, matched=matched, reason=reason)
        order_sql = _REVIEW_SORT_SQL.get((sort or "newest").strip().lower(), "id DESC")
        query = f"SELECT * FROM review_queue{where_sql} ORDER BY {order_sql}"
        safe_offset = max(0, int(offset or 0))
        if limit > 0:
            query += " LIMIT ? OFFSET ?"
            params.extend([int(limit), safe_offset])
        elif safe_offset > 0:
            query += " LIMIT -1 OFFSET ?"
            params.append(safe_offset)

        with self._lock:
            if self._conn is None:
                return []
            cur = self._conn.cursor()
            try:
                cur.execute(query, params)
                return [dict(r) for r in cur.fetchall()]
            finally:
                cur.close()

    def bulk_dismiss_review_items(
        self,
        item_ids: Optional[List[int]] = None,
        status: str = "pending",
        matched: Optional[str] = None,
        reason: Optional[str] = None,
        reviewed_by: str = "operator",
    ) -> int:
        """Bulk-dismiss review queue items by explicit IDs or triage filter."""
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        reviewer = (reviewed_by or "operator").strip() or "operator"
        if item_ids is not None:
            clean_ids = [int(i) for i in item_ids if i is not None]
            if not clean_ids:
                return 0
            marks = ", ".join("?" for _ in clean_ids)
            st = (status or "").strip().lower()
            where_sql = f" WHERE id IN ({marks})" + (" AND status = ?" if st and st != "all" else "")
            where_params: List[Any] = [*clean_ids, *([st] if st and st != "all" else [])]
        else:
            where_sql, where_params = _build_review_filter_sql(
                status=status or "pending", matched=matched, reason=reason,
            )
        with self._lock:
            if self._conn is None:
                return 0
            cur = self._conn.cursor()
            try:
                cur.execute(
                    f"UPDATE review_queue SET status = 'dismissed', reviewed_at = ?, reviewed_by = ?{where_sql}",
                    [now, reviewer, *where_params],
                )
                self._conn.commit()
                return int(cur.rowcount or 0)
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def get_review_item(self, review_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve single review queue item by ID."""
        with self._lock:
            if self._conn is None:
                return None
            cur = self._conn.cursor()
            try:
                cur.execute("SELECT * FROM review_queue WHERE id = ?", (review_id,))
                row = cur.fetchone()
                return dict(row) if row else None
            finally:
                cur.close()

    def update_review_status(self, review_id: int, status: str, reviewed_by: str = "operator") -> bool:
        """Update status of a review queue candidate ('confirmed', 'reassigned', 'enrolled_new', 'dismissed')."""
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        with self._lock:
            if self._conn is None:
                return False
            cur = self._conn.cursor()
            try:
                cur.execute(
                    "UPDATE review_queue SET status = ?, reviewed_at = ?, reviewed_by = ? WHERE id = ?",
                    (status.strip(), now, reviewed_by.strip(), review_id),
                )
                self._conn.commit()
                return cur.rowcount > 0
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def auto_resolve_matching_review_items(
        self,
        *,
        video_filename: str = "",
        camera_id: str = "",
        track_id: int | None = None,
        media_offset_sec: float | None = None,
        bbox: Any = None,
        status: str = "confirmed",
        reviewed_by: str = "video_studio",
    ) -> list[dict[str, Any]]:
        """Auto-resolve pending ``review_queue`` items matching a Studio/ROI tag."""
        aliases = expand_video_aliases(video_filename) if video_filename else []
        target_bbox = _parse_bbox_json(_serialize_bbox(bbox))
        if not aliases and not (camera_id or "").strip():
            return []
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        with self._lock:
            if self._conn is None:
                return []
            cur = self._conn.cursor()
            try:
                rows = self._fetch_pending_review_candidates(cur, aliases, camera_id)
                matched = [dict(r) for r in rows if _matches_review_candidate(dict(r), track_id, media_offset_sec, target_bbox)]
                if matched:
                    ids = [int(m["id"]) for m in matched]
                    marks = ", ".join("?" for _ in ids)
                    cur.execute(
                        f"UPDATE review_queue SET status = ?, reviewed_at = ?, reviewed_by = ? WHERE id IN ({marks})",
                        [status.strip(), now, reviewed_by.strip(), *ids],
                    )
                    self._conn.commit()
                return matched
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    @staticmethod
    def _fetch_pending_review_candidates(
        cur: Any, aliases: list[str], camera_id: str,
    ) -> list[Any]:
        """Fetch pending review items scoped by video aliases or camera_id."""
        if aliases:
            marks = ", ".join("?" for _ in aliases)
            cur.execute(f"SELECT * FROM review_queue WHERE status = 'pending' AND video_filename IN ({marks})", aliases)
            return cur.fetchall()
        cur.execute("SELECT * FROM review_queue WHERE status = 'pending' AND camera_id = ?", (camera_id.strip(),))
        return cur.fetchall()

    def get_custom_categories(self) -> List[Dict[str, Any]]:
        """List all registered custom categories with color badges."""
        with self._lock:
            if self._conn is None:
                return []
            cur = self._conn.cursor()
            try:
                cur.execute("SELECT * FROM custom_categories ORDER BY id ASC")
                return [dict(r) for r in cur.fetchall()]
            finally:
                cur.close()

    def set_custom_category(
        self,
        cat_id: str,
        name: str,
        color: str = "#3B82F6",
        description: str = "",
        badge_icon: str = "",
    ) -> bool:
        """Register or update custom category badge."""
        with self._lock:
            if self._conn is None:
                return False
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO custom_categories (id, name, color, badge_icon, description)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        color = excluded.color,
                        badge_icon = excluded.badge_icon,
                        description = excluded.description
                    """,
                    (cat_id.strip().lower(), name.strip(), color.strip(), badge_icon.strip(), description.strip()),
                )
                self._conn.commit()
                return True
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def delete_custom_category(self, cat_id: str) -> bool:
        """Delete custom category."""
        with self._lock:
            if self._conn is None:
                return False
            cur = self._conn.cursor()
            try:
                cur.execute("DELETE FROM custom_categories WHERE id = ?", (cat_id.strip().lower(),))
                self._conn.commit()
                return cur.rowcount > 0
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

