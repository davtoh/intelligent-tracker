"""
Local Whitelist and Cloud Hub Offline Cache Repository Mixin.

Manages offline-first credential caches, vehicle license plates, biometric
embeddings, Cloud Hub sync checkpoints, and buffered offline access events.
"""

import json
from typing import Optional, Dict, Any, List, Union
import numpy as np


class WhitelistMixin:
    """Provides local whitelist credentials, cloud sync state, and offline outbox queuing."""

    def get_sync_state(self, sync_key: str = "default") -> Optional[Dict[str, Any]]:
        """Retrieve synchronization state and ETag for Cloud Hub delta sync."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("SELECT * FROM tracker_sync_state WHERE sync_key = ?", (sync_key,))
                row = cur.fetchone()
                if not row:
                    return None
                data = dict(row)
                try:
                    data["metadata"] = json.loads(data.get("metadata_json") or "{}")
                except Exception:
                    data["metadata"] = {}
                return data
            finally:
                cur.close()

    def update_sync_state(
        self,
        sync_key: str = "default",
        last_etag: str = "",
        active_whitelist_count: int = 0,
        status: str = "synced",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Update or insert Cloud Hub synchronization checkpoint state."""
        meta_json = json.dumps(metadata or {})
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO tracker_sync_state (
                        sync_key, last_etag, last_sync_timestamp, active_whitelist_count, status, metadata_json
                    ) VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?, ?)
                    ON CONFLICT(sync_key) DO UPDATE SET
                        last_etag = excluded.last_etag,
                        last_sync_timestamp = CURRENT_TIMESTAMP,
                        active_whitelist_count = excluded.active_whitelist_count,
                        status = excluded.status,
                        metadata_json = excluded.metadata_json
                    """,
                    (sync_key, last_etag, int(active_whitelist_count), str(status), meta_json),
                )
                self._conn.commit()
                return True
            finally:
                cur.close()

    def upsert_whitelist_entry(
        self,
        credential_id: str,
        entity_name: str,
        clearance_tier: str = "VISITOR",
        plate_number: str = "",
        embedding: Optional[Union[np.ndarray, bytes]] = None,
        valid_from: Optional[str] = None,
        valid_until: Optional[str] = None,
        is_banned: bool = False,
        sync_version: int = 1,
    ) -> int:
        """Insert or update an authoritative credential in the local offline whitelist."""
        blob = None
        if embedding is not None:
            if isinstance(embedding, np.ndarray):
                blob = embedding.astype(np.float32).tobytes()
            elif isinstance(embedding, (bytes, bytearray)):
                blob = bytes(embedding)

        norm_plate = plate_number.strip().upper().replace(" ", "").replace("-", "") if plate_number else ""
        tier = clearance_tier.strip().upper()

        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO local_whitelist (
                        credential_id, entity_name, clearance_tier, plate_number,
                        embedding, valid_from, valid_until, is_banned, sync_version, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(credential_id) DO UPDATE SET
                        entity_name = excluded.entity_name,
                        clearance_tier = excluded.clearance_tier,
                        plate_number = excluded.plate_number,
                        embedding = coalesce(excluded.embedding, local_whitelist.embedding),
                        valid_from = excluded.valid_from,
                        valid_until = excluded.valid_until,
                        is_banned = excluded.is_banned,
                        sync_version = excluded.sync_version,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        credential_id.strip(),
                        entity_name.strip(),
                        tier,
                        norm_plate,
                        blob,
                        valid_from,
                        valid_until,
                        1 if is_banned else 0,
                        int(sync_version),
                    ),
                )
                self._conn.commit()
                return cur.lastrowid
            finally:
                cur.close()

    def get_whitelist_entry(self, credential_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single local whitelist entry by credential ID."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("SELECT * FROM local_whitelist WHERE credential_id = ?", (credential_id.strip(),))
                row = cur.fetchone()
                if not row:
                    return None
                data = dict(row)
                if data.get("embedding"):
                    data["embedding_array"] = np.frombuffer(data["embedding"], dtype=np.float32)
                return data
            finally:
                cur.close()

    def list_whitelist(
        self,
        clearance_tier: Optional[str] = None,
        active_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """List local whitelist credentials, optionally filtered by tier or active status."""
        query = "SELECT * FROM local_whitelist WHERE 1=1"
        params: List[Any] = []
        if clearance_tier:
            query += " AND clearance_tier = ?"
            params.append(clearance_tier.strip().upper())
        if active_only:
            query += " AND is_banned = 0 AND (valid_until IS NULL OR valid_until >= CURRENT_TIMESTAMP)"

        query += " ORDER BY updated_at DESC"

        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(query, params)
                return [dict(row) for row in cur.fetchall()]
            finally:
                cur.close()

    def delete_whitelist_entry(self, credential_id: str) -> bool:
        """Remove a credential from local whitelist cache."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("DELETE FROM local_whitelist WHERE credential_id = ?", (credential_id.strip(),))
                self._conn.commit()
                return cur.rowcount > 0
            finally:
                cur.close()

    def enqueue_offline_access(
        self,
        event_uuid: str,
        camera_id: str,
        access_granted: bool,
        credential_id: Optional[str] = None,
        direction: str = "in",
        decision_reason: str = "",
        snapshot_path: str = "",
    ) -> int:
        """Buffer a gate access attempt in the offline outbox queue."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO offline_access_queue (
                        event_uuid, credential_id, camera_id, direction,
                        access_granted, decision_reason, snapshot_path, synced
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        event_uuid.strip(),
                        credential_id.strip() if credential_id else None,
                        camera_id.strip(),
                        direction.strip().lower(),
                        1 if access_granted else 0,
                        decision_reason.strip(),
                        snapshot_path.strip(),
                    ),
                )
                self._conn.commit()
                return cur.lastrowid
            finally:
                cur.close()

    def get_pending_offline_access(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve unsynced access logs waiting to be flushed to Cloud Hub."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    "SELECT * FROM offline_access_queue WHERE synced = 0 ORDER BY occurred_at ASC LIMIT ?",
                    (int(limit),),
                )
                return [dict(r) for r in cur.fetchall()]
            finally:
                cur.close()

    def mark_offline_access_synced(self, event_uuids: List[str]) -> int:
        """Mark successfully transmitted access logs as synced."""
        if not event_uuids:
            return 0
        placeholders = ",".join("?" for _ in event_uuids)
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    f"UPDATE offline_access_queue SET synced = 1, synced_at = CURRENT_TIMESTAMP WHERE event_uuid IN ({placeholders})",
                    event_uuids,
                )
                self._conn.commit()
                return cur.rowcount
            finally:
                cur.close()

