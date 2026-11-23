"""
Active Learning and Category Repository Mixin.

Manages active learning candidate queues ("Review & Learn" Inbox) and
role-based custom categories for spatial and access control rules.
"""

import json
import time
from typing import Optional, Dict, Any, List

from intelligent_tracker.repositories.video_schema import expand_video_aliases


_INSERT_REVIEW_SQL = """
INSERT INTO review_queue (
    camera_id, track_id, crop_path, timestamp, suggested_entity_id,
    suggested_name, suggested_category, similarity, status,
    video_filename, media_offset_sec, bbox_json, frame_width, frame_height, run_id
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _serialize_bbox(bbox: Any, raw_json: str = "") -> str:
    """Serialize a 4-element bbox sequence to JSON string."""
    if raw_json:
        return str(raw_json).strip()
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        return json.dumps([int(round(float(v))) for v in bbox])
    return ""


def _parse_bbox_json(raw: str | None) -> list[int] | None:
    """Parse ``bbox_json`` into a 4-int list or None."""
    if not raw:
        return None
    try:
        vals = json.loads(raw)
        if isinstance(vals, list) and len(vals) == 4:
            return [int(v) for v in vals]
    except (TypeError, ValueError):
        pass
    return None


def _bbox_iou(a: list[int] | None, b: list[int] | None) -> float:
    """Compute IoU between two ``[x, y, w, h]`` boxes."""
    if not a or not b:
        return 0.0
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax1 + aw, bx1 + bw), min(ay1 + ah, by1 + bh)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = max(1, aw * ah + bw * bh - inter)
    return inter / union


def _matches_review_candidate(
    row: dict[str, Any],
    track_id: int | None,
    media_offset_sec: float | None,
    target_bbox: list[int] | None,
) -> bool:
    """Return True if a pending ``review_queue`` row matches the Studio/ROI target."""
    if track_id is not None and int(row.get("track_id") or 0) == int(track_id):
        if media_offset_sec is None:
            return True
        row_offset = float(row.get("media_offset_sec") or 0.0)
        return abs(row_offset - float(media_offset_sec)) <= 5.0
    if media_offset_sec is not None:
        row_offset = float(row.get("media_offset_sec") or 0.0)
        if abs(row_offset - float(media_offset_sec)) <= 2.0:
            row_bbox = _parse_bbox_json(row.get("bbox_json"))
            if target_bbox is None or row_bbox is None:
                return True
            return _bbox_iou(row_bbox, target_bbox) >= 0.3
    return False


def _build_review_insert_params(
    camera_id: str, track_id: int, crop_path: str, suggested_entity_id: Optional[int],
    suggested_name: str, suggested_category: str, similarity: float, status: str,
    video_filename: str, media_offset_sec: float, bbox: Any,
    frame_width: int, frame_height: int, run_id: str, kwargs: dict[str, Any],
) -> tuple[Any, ...]:
    """Build parameter tuple for ``_INSERT_REVIEW_SQL``."""
    sim = float(kwargs.get("similarity_score", similarity))
    ent_id = suggested_entity_id if suggested_entity_id is not None else kwargs.get("matched_entity_id")
    s_name = (suggested_name or kwargs.get("matched_entity_name", "")).strip()
    s_cat = (suggested_category or kwargs.get("matched_category", "")).strip()
    bbox_str = _serialize_bbox(bbox, str(kwargs.get("bbox_json", "")))
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    return (
        camera_id, track_id, crop_path.strip(), now, ent_id, s_name, s_cat,
        sim, status.strip(), str(video_filename or "").strip(), float(media_offset_sec or 0.0),
        bbox_str, int(frame_width or 0), int(frame_height or 0), str(run_id or "").strip(),
    )


class LearningMixin:
    """Provides active learning review items and custom category persistence."""

    _conn: Any
    _lock: Any

    def add_review_item(
        self, camera_id: str, track_id: int, crop_path: str,
        suggested_entity_id: Optional[int] = None, suggested_name: str = "",
        suggested_category: str = "", similarity: float = 0.0, status: str = "pending",
        video_filename: str = "", media_offset_sec: float = 0.0, bbox: Any = None,
        frame_width: int = 0, frame_height: int = 0, run_id: str = "", **kwargs,
    ) -> int:
        """Add an ambiguous detection to the active learning review queue."""
        params = _build_review_insert_params(
            camera_id, track_id, crop_path, suggested_entity_id, suggested_name,
            suggested_category, similarity, status, video_filename, media_offset_sec,
            bbox, frame_width, frame_height, run_id, kwargs,
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

    def list_review_items(self, status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """List active learning review items, optionally filtered by status."""
        query = "SELECT * FROM review_queue"
        params: List[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status.strip())
        query += " ORDER BY id DESC"
        if limit > 0:
            query += " LIMIT ?"
            params.append(int(limit))

        with self._lock:
            if self._conn is None:
                return []
            cur = self._conn.cursor()
            try:
                cur.execute(query, params)
                return [dict(r) for r in cur.fetchall()]
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

