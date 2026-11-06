"""
Descriptor Version History and Rollback Repository Mixin.

Manages historical descriptor versions, continuous learning drift audits,
locked ground-truth anchors, and active descriptor rollbacks.
"""

import time
from typing import Optional, Dict, Any, List
import numpy as np


class DescriptorMixin:
    """Provides historical descriptor snapshotting and signature rollback."""

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
        """
        Record a descriptor version snapshot for historical rollback and drift monitoring.

        :param entity_id: Entity ID.
        :param embedding: Feature vector (or feature_vector).
        :param crop_path: Optional path to thumbnail crop.
        :param source: 'manual_enrollment', 'active_learning', 'ema_update', 'rollback'.
        :param notes: Metadata or operator notes.
        :param version: Explicit version number (optional).
        :param update_reason: Optional alias for notes/source.
        :param is_anchor: Ground truth locked anchor indicator.
        :return: Created version ID.
        """
        vec = feature_vector if feature_vector is not None else embedding
        if vec is None:
            vec = np.zeros(16, dtype=np.float32)
        blob = self.serialize_embedding(vec)
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())

        ver = version if version is not None else version_num
        reason = update_reason or notes or source
        src = source if (source != "manual_enrollment" or not update_reason) else update_reason

        with self._lock:
            cur = self._conn.cursor()
            try:
                if ver is None:
                    cur.execute(
                        "SELECT COALESCE(MAX(version_num), 0) FROM descriptor_versions WHERE entity_id = ?",
                        (entity_id,),
                    )
                    max_ver = cur.fetchone()[0]
                    ver = max_ver + 1

                cur.execute(
                    """
                    INSERT INTO descriptor_versions (entity_id, version_num, embedding, crop_path, source, notes, is_anchor, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (entity_id, ver, blob, crop_path.strip(), src.strip(), reason.strip(), int(is_anchor), now),
                )
                self._conn.commit()
                return cur.lastrowid
            finally:
                cur.close()

    def get_descriptor_versions(self, entity_id: int) -> List[Dict[str, Any]]:
        """Retrieve historical descriptor versions for an entity, sorted descending by version."""
        with self._lock:
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
        """
        Rollback an entity's active descriptor signature to an earlier historical version.

        :param entity_id: Target entity ID.
        :param version: Version number to restore (alias version_num).
        :return: True if successfully restored.
        """
        ver = version if version is not None else version_num
        if ver is None:
            return False

        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    "SELECT embedding, crop_path FROM descriptor_versions WHERE entity_id = ? AND version_num = ?",
                    (entity_id, ver),
                )
                row = cur.fetchone()
                if not row:
                    return False

                blob = row["embedding"]
                crop_path = row["crop_path"]

                # Check if non-anchor signature exists to update
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
                    # Update all or insert rolled back signature
                    cur.execute(
                        "UPDATE entity_signatures SET embedding = ?, crop_path = ?, created_at = ? WHERE entity_id = ?",
                        (blob, crop_path, now, entity_id),
                    )

                # Record rollback event in version history
                cur.execute(
                    "SELECT COALESCE(MAX(version_num), 0) FROM descriptor_versions WHERE entity_id = ?",
                    (entity_id,),
                )
                max_ver = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO descriptor_versions (entity_id, version_num, embedding, crop_path, source, notes, is_anchor, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (entity_id, max_ver + 1, blob, crop_path, f"rollback_to_v{ver}", f"Restored signature from v{ver}", 0, now),
                )
                self._conn.commit()
                return True
            finally:
                cur.close()

