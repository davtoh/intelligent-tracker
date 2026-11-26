"""
Negative Exemplar Repository Mixin.

Manages supervised Re-ID negative and false-positive correction exemplars
in SQLite for per-entity and global clutter suppression.
"""

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class NegativeExemplarMixin:
    """Provides CRUD and vectorized matrix loading for negative exemplars."""

    _conn: Any
    _lock: Any

    def add_negative_exemplar(
        self,
        embedding: np.ndarray,
        entity_id: Optional[int] = None,
        label: str = "",
        crop_path: str = "",
        source: str = "",
        notes: str = "",
    ) -> int:
        """Persist a negative or false-positive correction exemplar."""
        arr = np.asarray(embedding, dtype=np.float32).flatten()
        blob = arr.tobytes()
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        with self._lock:
            if self._conn is None:
                raise RuntimeError("Database connection is closed")
            cursor = self._conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO negative_exemplars "
                    "(entity_id, label, embedding, crop_path, source, notes, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        entity_id,
                        str(label or "").strip(),
                        blob,
                        str(crop_path or "").strip(),
                        str(source or "").strip(),
                        str(notes or "").strip(),
                        now,
                    ),
                )
                exemplar_id = int(cursor.lastrowid)
                self._conn.commit()
                return exemplar_id
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cursor.close()

    def get_negative_exemplars(
        self, entity_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """List stored negative exemplars, optionally filtered by entity_id."""
        with self._lock:
            if self._conn is None:
                return []
            cursor = self._conn.cursor()
            try:
                if entity_id is not None:
                    cursor.execute(
                        "SELECT id, entity_id, label, crop_path, source, notes, created_at "
                        "FROM negative_exemplars WHERE entity_id = ? ORDER BY id DESC",
                        (entity_id,),
                    )
                else:
                    cursor.execute(
                        "SELECT id, entity_id, label, crop_path, source, notes, created_at "
                        "FROM negative_exemplars ORDER BY id DESC"
                    )
                return [dict(row) for row in cursor.fetchall()]
            finally:
                cursor.close()

    def get_negative_embeddings(
        self, expected_dim: Optional[int] = None
    ) -> Tuple[np.ndarray, List[Optional[int]], List[str]]:
        """Load L2-normalized negative exemplar matrix and metadata lists."""
        with self._lock:
            if self._conn is None:
                return np.empty((0, 0), dtype=np.float32), [], []
            cursor = self._conn.cursor()
            try:
                cursor.execute(
                    "SELECT entity_id, label, embedding FROM negative_exemplars ORDER BY id ASC"
                )
                rows = cursor.fetchall()
            finally:
                cursor.close()

        vectors: List[np.ndarray] = []
        entity_ids: List[Optional[int]] = []
        labels: List[str] = []
        for row in rows:
            vec = np.frombuffer(row["embedding"], dtype=np.float32).copy()
            if vec.size == 0:
                logger.debug("Skipping empty negative exemplar for entity_id=%s", row["entity_id"])
                continue
            if expected_dim is not None and vec.shape[0] != expected_dim:
                logger.debug("Skipping negative exemplar dim=%d (expected_dim=%d)", vec.shape[0], expected_dim)
                continue
            norm = float(np.linalg.norm(vec))
            if norm > 1e-7:
                vec = vec / norm
            vectors.append(vec)
            entity_ids.append(row["entity_id"])
            labels.append(str(row["label"] or ""))

        if not vectors:
            return np.empty((0, 0), dtype=np.float32), [], []
        return np.vstack(vectors).astype(np.float32), entity_ids, labels

    def delete_negative_exemplar(self, exemplar_id: int) -> bool:
        """Delete a single negative exemplar by ID."""
        with self._lock:
            if self._conn is None:
                return False
            cursor = self._conn.cursor()
            try:
                cursor.execute(
                    "DELETE FROM negative_exemplars WHERE id = ?", (exemplar_id,)
                )
                self._conn.commit()
                return cursor.rowcount > 0
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cursor.close()

    def clear_negative_exemplars(self, entity_id: Optional[int] = None) -> int:
        """Delete negative exemplars for an entity or clear all if entity_id is None."""
        with self._lock:
            if self._conn is None:
                return 0
            cursor = self._conn.cursor()
            try:
                if entity_id is not None:
                    cursor.execute(
                        "DELETE FROM negative_exemplars WHERE entity_id = ?",
                        (entity_id,),
                    )
                else:
                    cursor.execute("DELETE FROM negative_exemplars")
                self._conn.commit()
                return int(cursor.rowcount)
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cursor.close()
