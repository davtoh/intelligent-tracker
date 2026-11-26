"""Repository mixin for exemplar learned classes and per-camera COCO overrides."""

import re
import sqlite3
from typing import Any

import numpy as np


def _slugify_class_name(name: str) -> str:
    """Normalize a learned class name into a URL-safe lowercase slug."""
    cleaned = re.sub(r"[^a-z0-9]+", "_", str(name or "").strip().lower()).strip("_")
    return cleaned or "learned_class"


class LearnedClassMixin:
    """SQLite persistence for learned_classes, learned_class_exemplars, and camera_class_overrides."""

    _conn: Any
    _lock: Any

    def create_learned_class(
        self,
        name: str,
        slug: str = "",
        parent_coco_class: str = "",
        color: str = "#06B6D4",
        threshold: float = 0.65,
        description: str = "",
    ) -> dict[str, Any]:
        """Insert a new learned class and return its persisted record."""
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("Learned class name is required")
        clean_slug = _slugify_class_name(slug or clean_name)
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute(
                    """INSERT INTO learned_classes (name, slug, parent_coco_class, color, threshold, description)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (clean_name, clean_slug, str(parent_coco_class or "").strip(), str(color or "#06B6D4"), float(threshold), str(description or "")),
                )
                class_id = int(cursor.lastrowid)
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cursor.close()
        return self.get_learned_class(class_id) or {"id": class_id, "name": clean_name, "slug": clean_slug}

    def list_learned_classes(self) -> list[dict[str, Any]]:
        """Return all learned classes with exemplar counts and sample crop paths."""
        with self._lock:
            rows = self._conn.execute(
                """SELECT lc.id, lc.name, lc.slug, lc.parent_coco_class, lc.color,
                          lc.threshold, lc.description, lc.created_at, lc.updated_at,
                          COUNT(lce.id) AS exemplar_count,
                          COALESCE(MAX(NULLIF(lce.crop_path, '')), '') AS sample_crop_path
                   FROM learned_classes lc
                   LEFT JOIN learned_class_exemplars lce ON lce.class_id = lc.id
                   GROUP BY lc.id
                   ORDER BY lc.name ASC"""
            ).fetchall()
        return [dict(row) for row in rows]

    def get_learned_class(self, class_id: int) -> dict[str, Any] | None:
        """Return a single learned class record by primary key."""
        with self._lock:
            row = self._conn.execute(
                """SELECT lc.id, lc.name, lc.slug, lc.parent_coco_class, lc.color,
                          lc.threshold, lc.description, lc.created_at, lc.updated_at,
                          COUNT(lce.id) AS exemplar_count,
                          COALESCE(MAX(NULLIF(lce.crop_path, '')), '') AS sample_crop_path
                   FROM learned_classes lc
                   LEFT JOIN learned_class_exemplars lce ON lce.class_id = lc.id
                   WHERE lc.id = ?
                   GROUP BY lc.id""",
                (int(class_id),),
            ).fetchone()
        return dict(row) if row is not None else None

    def update_learned_class(self, class_id: int, **fields: Any) -> dict[str, Any] | None:
        """Update mutable fields on a learned class and return the updated record."""
        allowed = {"name", "slug", "parent_coco_class", "color", "threshold", "description"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return self.get_learned_class(class_id)
        if "slug" in updates:
            updates["slug"] = _slugify_class_name(updates["slug"])
        set_clause = ", ".join(f"{col} = ?" for col in updates)
        params = list(updates.values()) + [int(class_id)]
        with self._lock:
            try:
                self._conn.execute(
                    f"UPDATE learned_classes SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    params,
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return self.get_learned_class(class_id)

    def delete_learned_class(self, class_id: int) -> bool:
        """Delete a learned class and cascade-remove its exemplars."""
        with self._lock:
            try:
                cur = self._conn.execute("DELETE FROM learned_classes WHERE id = ?", (int(class_id),))
                self._conn.commit()
                return cur.rowcount > 0
            except Exception:
                self._conn.rollback()
                raise

    def add_learned_class_exemplar(
        self,
        class_id: int,
        embedding: np.ndarray,
        crop_path: str = "",
        source_camera_id: str = "",
        notes: str = "",
    ) -> int:
        """Store a normalized float32 exemplar embedding for a learned class."""
        vec = np.asarray(embedding, dtype=np.float32).reshape(-1)
        if vec.size == 0:
            raise ValueError("Exemplar embedding cannot be empty")
        blob = sqlite3.Binary(vec.tobytes())
        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute(
                    """INSERT INTO learned_class_exemplars (class_id, embedding, crop_path, source_camera_id, notes)
                    VALUES (?, ?, ?, ?, ?)""",
                    (int(class_id), blob, str(crop_path or ""), str(source_camera_id or ""), str(notes or "")),
                )
                exemplar_id = int(cursor.lastrowid)
                self._conn.commit()
                return exemplar_id
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cursor.close()

    def list_learned_class_exemplars(self, class_id: int | None = None) -> list[dict[str, Any]]:
        """List exemplar records with deserialized float32 embeddings."""
        sql = (
            "SELECT lce.id, lce.class_id, lc.name AS class_name, lc.slug, lc.threshold, "
            "lc.parent_coco_class, lc.color, lce.embedding, lce.crop_path, lce.source_camera_id, "
            "lce.notes, lce.created_at "
            "FROM learned_class_exemplars lce "
            "JOIN learned_classes lc ON lc.id = lce.class_id"
        )
        params: tuple[Any, ...] = ()
        if class_id is not None:
            sql += " WHERE lce.class_id = ?"
            params = (int(class_id),)
        sql += " ORDER BY lce.id ASC"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            blob = item.get("embedding")
            item["embedding"] = np.frombuffer(blob, dtype=np.float32).copy() if blob else np.empty(0, dtype=np.float32)
            results.append(item)
        return results

    def delete_learned_class_exemplar(self, exemplar_id: int) -> bool:
        """Delete a single exemplar by ID."""
        with self._lock:
            try:
                cur = self._conn.execute("DELETE FROM learned_class_exemplars WHERE id = ?", (int(exemplar_id),))
                self._conn.commit()
                return cur.rowcount > 0
            except Exception:
                self._conn.rollback()
                raise

    def get_camera_class_overrides(self, camera_id: str) -> list[dict[str, Any]]:
        """Return all per-camera COCO class suppress/relabel rules for camera_id."""
        with self._lock:
            rows = self._conn.execute(
                """SELECT id, camera_id, coco_class, action, relabel_to, updated_at
                   FROM camera_class_overrides
                   WHERE camera_id = ?
                   ORDER BY coco_class ASC""",
                (str(camera_id or "").strip(),),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_camera_class_override(
        self,
        camera_id: str,
        coco_class: str,
        action: str = "suppress",
        relabel_to: str = "",
    ) -> dict[str, Any]:
        """Upsert a per-camera COCO class override ('suppress' or 'relabel')."""
        cam = str(camera_id or "").strip()
        cls_name = str(coco_class or "").strip().lower()
        act = str(action or "suppress").strip().lower()
        if not cam or not cls_name:
            raise ValueError("camera_id and coco_class are required")
        if act not in ("suppress", "relabel"):
            raise ValueError("action must be 'suppress' or 'relabel'")
        relabel = str(relabel_to or "").strip()
        if act == "relabel" and not relabel:
            raise ValueError("relabel_to is required when action is 'relabel'")
        with self._lock:
            try:
                self._conn.execute(
                    """INSERT INTO camera_class_overrides (camera_id, coco_class, action, relabel_to, updated_at)
                       VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                       ON CONFLICT(camera_id, coco_class) DO UPDATE SET
                         action = excluded.action,
                         relabel_to = excluded.relabel_to,
                         updated_at = CURRENT_TIMESTAMP""",
                    (cam, cls_name, act, relabel),
                )
                self._conn.commit()
                row = self._conn.execute(
                    """SELECT id, camera_id, coco_class, action, relabel_to, updated_at
                       FROM camera_class_overrides WHERE camera_id = ? AND coco_class = ?""",
                    (cam, cls_name),
                ).fetchone()
            except Exception:
                self._conn.rollback()
                raise
        return dict(row) if row is not None else {"camera_id": cam, "coco_class": cls_name, "action": act, "relabel_to": relabel}

    def delete_camera_class_override(self, camera_id: str, coco_class: str) -> bool:
        """Remove a per-camera COCO class override."""
        with self._lock:
            try:
                cur = self._conn.execute(
                    "DELETE FROM camera_class_overrides WHERE camera_id = ? AND coco_class = ?",
                    (str(camera_id or "").strip(), str(coco_class or "").strip().lower()),
                )
                self._conn.commit()
                return cur.rowcount > 0
            except Exception:
                self._conn.rollback()
                raise
