"""
Signature Repository Mixin.

Manages Re-ID feature embedding serialization, signature vectors, and gallery
matrices for visual re-identification matching.
"""

import time
from typing import Optional, Dict, Any, Tuple, List
import numpy as np


class SignatureMixin:
    """Provides Re-ID signature embeddings and gallery extraction."""

    _conn: Any
    _lock: Any

    @staticmethod
    def serialize_embedding(embedding: np.ndarray) -> bytes:
        """Serialize a 1D NumPy float vector to bytes."""
        arr = np.asarray(embedding, dtype=np.float32).flatten()
        return arr.tobytes()

    @staticmethod
    def deserialize_embedding(blob: bytes) -> np.ndarray:
        """Deserialize raw bytes back to 1D NumPy float32 array."""
        return np.frombuffer(blob, dtype=np.float32)

    def add_signature(
        self, entity_id: int, embedding: np.ndarray, crop_path: str = "",
        is_anchor: int = 0, locked: int = 0,
    ) -> int:
        """
        Add a feature signature embedding for an entity.

        :param entity_id: Target entity ID.
        :param embedding: 1D NumPy float vector representing the visual embedding.
        :param crop_path: Optional path to saved cropped thumbnail image.
        :param is_anchor: If 1, marks as ground-truth Locked Anchor never modified by continuous learning.
        :param locked: If 1, prevents automatic eviction.
        :return: Created signature ID.
        """
        blob = self.serialize_embedding(embedding)
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())

        with self._lock:
            if self._conn is None:
                raise RuntimeError("Database connection is closed")
            cursor = self._conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO entity_signatures (entity_id, embedding, crop_path, is_anchor, locked, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (entity_id, blob, crop_path.strip(), int(is_anchor), int(locked), now),
                )
                sig_id = cursor.lastrowid
                self._conn.commit()
                return sig_id
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cursor.close()

    def add_entity_signature(
        self,
        entity_id: int,
        embedding: Optional[np.ndarray] = None,
        feature_vector: Optional[np.ndarray] = None,
        crop_path: str = "",
        is_anchor: int = 0,
        locked: int = 0,
    ) -> int:
        """Alias for add_signature accepting either feature_vector or embedding."""
        vec = feature_vector if feature_vector is not None else embedding
        if vec is None:
            raise ValueError("Must provide feature_vector or embedding")
        return self.add_signature(
            entity_id=entity_id,
            embedding=vec,
            crop_path=crop_path,
            is_anchor=is_anchor,
            locked=locked,
        )

    def update_entity_signature(
        self,
        signature_id: int,
        embedding: Optional[np.ndarray] = None,
        feature_vector: Optional[np.ndarray] = None,
        crop_path: Optional[str] = None,
    ) -> bool:
        """Update existing signature feature vector or crop path."""
        vec = feature_vector if feature_vector is not None else embedding
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        with self._lock:
            if self._conn is None:
                return False
            cur = self._conn.cursor()
            try:
                updates = ["created_at = ?"]
                params: List[Any] = [now]
                if vec is not None:
                    updates.append("embedding = ?")
                    params.append(self.serialize_embedding(vec))
                if crop_path is not None:
                    updates.append("crop_path = ?")
                    params.append(crop_path.strip())
                params.append(signature_id)
                cur.execute(f"UPDATE entity_signatures SET {', '.join(updates)} WHERE id = ?", params)
                self._conn.commit()
                return cur.rowcount > 0
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def get_entity_signatures(
        self,
        entity_id: int,
        anchors_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """Retrieve signatures for an entity with feature_vector alias."""
        return self.get_signatures(entity_id=entity_id, anchors_only=anchors_only)

    def get_signatures(
        self,
        entity_id: Optional[int] = None,
        anchors_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve signatures, optionally filtered for a specific entity or locked anchors.

        :param entity_id: Optional entity ID filter.
        :param anchors_only: If True, only returns locked ground-truth anchors.
        :return: List of dicts with deserialized `embedding` arrays.
        """
        query = "SELECT id, entity_id, embedding, crop_path, is_anchor, locked, created_at FROM entity_signatures"
        conditions = []
        params = []
        if entity_id is not None:
            conditions.append("entity_id = ?")
            params.append(entity_id)
        if anchors_only:
            conditions.append("is_anchor = 1")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY id ASC"

        with self._lock:
            if self._conn is None:
                return []
            cursor = self._conn.cursor()
            try:
                cursor.execute(query, params)
                results = []
                for row in cursor.fetchall():
                    item = dict(row)
                    item["embedding"] = self.deserialize_embedding(item["embedding"])
                    item["feature_vector"] = item["embedding"]
                    results.append(item)
                return results
            finally:
                cursor.close()

    def update_signature_embedding(self, sig_id: int, embedding: np.ndarray) -> bool:
        """Update an existing signature's serialized embedding vector in place."""
        blob = self.serialize_embedding(embedding)
        with self._lock:
            if self._conn is None:
                return False
            cursor = self._conn.cursor()
            try:
                cursor.execute(
                    "UPDATE entity_signatures SET embedding = ? WHERE id = ?",
                    (blob, int(sig_id)),
                )
                self._conn.commit()
                return cursor.rowcount > 0
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cursor.close()

    def _build_gallery_matrix(
        self, rows: List[Any], expected_dim: Optional[int]
    ) -> Tuple[np.ndarray, List[int], List[str], List[str]]:
        """Assemble normalized 2D float32 embedding matrix from raw DB rows."""
        vectors, entity_ids, names, categories = [], [], [], []
        target_dim = expected_dim
        skipped = 0
        warned = getattr(self, "_gallery_mismatch_warned_dims", None)
        if warned is None:
            warned = set()
            self._gallery_mismatch_warned_dims = warned
        for row in rows:
            vec = self.deserialize_embedding(row["embedding"])
            if vec is None or vec.size == 0:
                continue
            dim = vec.shape[0] if vec.ndim == 1 else vec.size
            if target_dim is not None and dim != target_dim:
                skipped += 1
                pair = (int(dim), int(target_dim))
                if pair not in warned:
                    warned.add(pair)
                    import logging

                    logging.getLogger(__name__).warning(
                        "Skipping gallery signature with dim=%d (expected_dim=%d).",
                        dim,
                        target_dim,
                    )
                continue
            if target_dim is None:
                target_dim = dim
            vectors.append(vec.ravel())
            entity_ids.append(row["entity_id"])
            names.append(row["name"])
            categories.append(row["category"])
        self._last_gallery_mismatch_count = skipped
        if not vectors:
            out_dim = expected_dim if expected_dim is not None else 0
            return np.empty((0, out_dim), dtype=np.float32), [], [], []
        return np.vstack(vectors).astype(np.float32), entity_ids, names, categories

    def get_gallery_embeddings(
        self, expected_dim: Optional[int] = None
    ) -> Tuple[np.ndarray, List[int], List[str], List[str]]:
        """Fetch all gallery signatures as a unified 2D matrix for vectorized matching."""
        query = """
            SELECT s.embedding, e.id AS entity_id, e.name, e.category
            FROM entity_signatures s
            JOIN entities e ON s.entity_id = e.id
            WHERE e.status = 'active'
            ORDER BY s.id ASC
        """
        with self._lock:
            if self._conn is None:
                out_dim = expected_dim if expected_dim is not None else 0
                return np.empty((0, out_dim), dtype=np.float32), [], [], []
            cursor = self._conn.cursor()
            try:
                cursor.execute(query)
                rows = cursor.fetchall()
            finally:
                cursor.close()

        if not rows:
            return np.empty((0, 0), dtype=np.float32), [], [], []
        return self._build_gallery_matrix(rows, expected_dim)
