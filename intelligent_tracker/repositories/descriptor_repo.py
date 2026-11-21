"""
Descriptor Version History and Rollback Repository Mixin.

Manages historical descriptor versions, continuous learning drift audits,
locked ground-truth anchors, and active descriptor rollbacks.
"""

import time
from typing import Optional, Dict, Any, List, Tuple
import numpy as np


def _insert_descriptor_version(
    cur: Any,
    entity_id: int,
    ver: Optional[int],
    blob: bytes,
    crop_path: str,
    src: str,
    reason: str,
    is_anchor: int,
    now: str,
) -> int:
    """Insert a descriptor_versions row, auto-incrementing version_num when None."""
    if ver is None:
        cur.execute(
            "SELECT COALESCE(MAX(version_num), 0) FROM descriptor_versions WHERE entity_id = ?",
            (entity_id,),
        )
        ver = cur.fetchone()[0] + 1
    cur.execute(
        """
        INSERT INTO descriptor_versions (entity_id, version_num, embedding, crop_path, source, notes, is_anchor, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (entity_id, ver, blob, crop_path.strip(), src.strip(), reason.strip(), int(is_anchor), now),
    )
    return cur.lastrowid


def _restore_signature_from_version(
    cur: Any, entity_id: int, ver: int, now: str
) -> Optional[Tuple[bytes, str]]:
    """Apply a historical descriptor version to entity_signatures; return (blob, crop_path) or None."""
    cur.execute(
        "SELECT embedding, crop_path FROM descriptor_versions WHERE entity_id = ? AND version_num = ?",
        (entity_id, ver),
    )
    row = cur.fetchone()
    if not row:
        return None
    blob, crop_path = row["embedding"], row["crop_path"]
    cur.execute(
        "SELECT id FROM entity_signatures WHERE entity_id = ? AND is_anchor = 0 ORDER BY id DESC LIMIT 1",
        (entity_id,),
    )
    dyn_sig = cur.fetchone()
    if dyn_sig:
        cur.execute(
            "UPDATE entity_signatures SET embedding = ?, crop_path = ?, created_at = ? WHERE id = ?",
            (blob, crop_path, now, dyn_sig[0]),
        )
    else:
        cur.execute(
            "UPDATE entity_signatures SET embedding = ?, crop_path = ?, created_at = ? WHERE entity_id = ?",
            (blob, crop_path, now, entity_id),
        )
    return blob, crop_path


class DescriptorMixin:
    """Provides historical descriptor snapshotting and signature rollback."""

    _conn: Any
    _lock: Any
    serialize_embedding: Any
    deserialize_embedding: Any

    def record_descriptor_version(
        self,
        entity_id: int,
        embedding: Optional[np.ndarray] = None,
        feature_vector: Optional[np.ndarray] = None,
        crop_path: str = "",
        source: str = "manual_enrollment",
        notes: str = "",
        version: Optional[int] = None,
        version_num: Optional[int] = None,
        update_reason: str = "",
        is_anchor: int = 0,
        **kwargs,
    ) -> int:
        """Record a descriptor version snapshot for historical rollback and drift monitoring."""
        vec = feature_vector if feature_vector is not None else embedding
        if vec is None:
            vec = np.zeros(16, dtype=np.float32)
        blob = self.serialize_embedding(vec)
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        ver = version if version is not None else version_num
        reason = update_reason or notes or source
        src = source if (source != "manual_enrollment" or not update_reason) else update_reason
        with self._lock:
            if self._conn is None:
                raise RuntimeError("Database connection is closed")
            cur = self._conn.cursor()
            try:
                row_id = _insert_descriptor_version(
                    cur, entity_id, ver, blob, crop_path, src, reason, is_anchor, now
                )
                self._conn.commit()
                return row_id
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def get_descriptor_versions(self, entity_id: int) -> List[Dict[str, Any]]:
        """Retrieve historical descriptor versions for an entity, sorted descending by version."""
        with self._lock:
            if self._conn is None:
                return []
            cur = self._conn.cursor()
            try:
                cur.execute(
                    "SELECT id, entity_id, version_num, embedding, crop_path, source, notes, is_anchor, created_at "
                    "FROM descriptor_versions WHERE entity_id = ? ORDER BY version_num DESC",
                    (entity_id,),
                )
                results = []
                for row in cur.fetchall():
                    item = dict(row)
                    item["version"] = item["version_num"]
                    item["embedding"] = self.deserialize_embedding(item["embedding"])
                    item["feature_vector"] = item["embedding"]
                    item["update_reason"] = item["notes"] or item["source"]
                    results.append(item)
                return results
            finally:
                cur.close()

    def rollback_descriptor(
        self,
        entity_id: int,
        version: Optional[int] = None,
        version_num: Optional[int] = None,
    ) -> bool:
        """Rollback an entity's active descriptor signature to an earlier historical version."""
        ver = version if version is not None else version_num
        if ver is None:
            return False
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        with self._lock:
            if self._conn is None:
                return False
            cur = self._conn.cursor()
            try:
                restored = _restore_signature_from_version(cur, entity_id, ver, now)
                if restored is None:
                    return False
                blob, crop_path = restored
                _insert_descriptor_version(
                    cur, entity_id, None, blob, crop_path,
                    f"rollback_to_v{ver}", f"Restored signature from v{ver}", 0, now,
                )
                self._conn.commit()
                return True
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

