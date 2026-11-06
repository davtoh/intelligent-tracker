"""
Active Learning and Category Repository Mixin.

Manages active learning candidate queues ("Review & Learn" Inbox) and
role-based custom categories for spatial and access control rules.
"""

import time
from typing import Optional, Dict, Any, List


class LearningMixin:
    """Provides active learning review items and custom category persistence."""

    def add_review_item(
        self,
        camera_id: str,
        track_id: int,
        crop_path: str,
        suggested_entity_id: Optional[int] = None,
        suggested_name: str = "",
        suggested_category: str = "",
        similarity: float = 0.0,
        status: str = "pending",
        **kwargs,
    ) -> int:
        """Add an ambiguous detection to the active learning review queue."""
        if "similarity_score" in kwargs:
            similarity = kwargs["similarity_score"]
        if "matched_entity_id" in kwargs and suggested_entity_id is None:
            suggested_entity_id = kwargs["matched_entity_id"]
        if "matched_entity_name" in kwargs and not suggested_name:
            suggested_name = kwargs["matched_entity_name"]
        if "matched_category" in kwargs and not suggested_category:
            suggested_category = kwargs["matched_category"]

        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO review_queue (
                        camera_id, track_id, crop_path, timestamp, suggested_entity_id,
                        suggested_name, suggested_category, similarity, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        camera_id,
                        track_id,
                        crop_path.strip(),
                        now,
                        suggested_entity_id,
                        suggested_name.strip(),
                        suggested_category.strip(),
                        float(similarity),
                        status.strip(),
                    ),
                )
                self._conn.commit()
                return cur.lastrowid
            finally:
                cur.close()

    def list_review_items(self, status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """List active learning review items, optionally filtered by status."""
        query = "SELECT * FROM review_queue"
        params = []
        if status:
            query += " WHERE status = ?"
            params.append(status.strip())
        query += " ORDER BY id DESC"
        if limit > 0:
            query += " LIMIT ?"
            params.append(int(limit))

        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(query, params)
                return [dict(r) for r in cur.fetchall()]
            finally:
                cur.close()

    def get_review_item(self, review_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve single review queue item by ID."""
        with self._lock:
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
            cur = self._conn.cursor()
            try:
                cur.execute(
                    "UPDATE review_queue SET status = ?, reviewed_at = ?, reviewed_by = ? WHERE id = ?",
                    (status.strip(), now, reviewed_by.strip(), review_id),
                )
                self._conn.commit()
                return cur.rowcount > 0
            finally:
                cur.close()

    def get_custom_categories(self) -> List[Dict[str, Any]]:
        """List all registered custom categories with color badges."""
        with self._lock:
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
            finally:
                cur.close()

    def delete_custom_category(self, cat_id: str) -> bool:
        """Delete custom category."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("DELETE FROM custom_categories WHERE id = ?", (cat_id.strip().lower(),))
                self._conn.commit()
                return cur.rowcount > 0
            finally:
                cur.close()

