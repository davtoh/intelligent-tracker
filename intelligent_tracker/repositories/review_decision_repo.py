"""
Reversible Active Learning Review Decision Repository Mixin.

Persists operator review decisions with created artifact IDs and prior state
snapshots so actions can be audited and cleanly undone without data loss.
"""

import json
import time
from typing import Any


def _hydrate_decision_row(row: Any) -> dict[str, Any]:
    """Convert a SQLite row into a decision dict with parsed ``prior_state``."""
    item = dict(row)
    raw_state = item.get("prior_state_json") or "{}"
    try:
        parsed = json.loads(raw_state)
        item["prior_state"] = parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        item["prior_state"] = {}
    item["undone"] = bool(item.get("undone"))
    return item


_INSERT_DECISION_SQL = """
INSERT INTO review_decisions (
    review_id, action, prior_status, prior_entity_id, new_entity_id,
    created_signature_id, created_descriptor_version_id, created_sighting_id,
    created_negative_exemplar_id, created_entity_id, prior_state_json,
    reviewer, notes, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class ReviewDecisionMixin:
    """Provides CRUD and reversal helpers for ``review_decisions``."""

    _conn: Any
    _lock: Any

    def record_review_decision(
        self,
        review_id: int,
        action: str,
        *,
        prior_status: str = "pending",
        prior_entity_id: int | None = None,
        new_entity_id: int | None = None,
        created_signature_id: int | None = None,
        created_descriptor_version_id: int | None = None,
        created_sighting_id: int | None = None,
        created_negative_exemplar_id: int | None = None,
        created_entity_id: int | None = None,
        prior_state: dict[str, Any] | None = None,
        reviewer: str = "operator",
        notes: str = "",
    ) -> int:
        """Insert a review decision audit row and return its ID."""
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        state_json = json.dumps(prior_state or {}, default=str)
        params = (
            int(review_id), str(action).strip().lower(), str(prior_status or "pending").strip(),
            prior_entity_id, new_entity_id, created_signature_id,
            created_descriptor_version_id, created_sighting_id,
            created_negative_exemplar_id, created_entity_id,
            state_json, str(reviewer or "operator").strip(), str(notes or "").strip(), now,
        )
        with self._lock:
            if self._conn is None:
                raise RuntimeError("Database connection is closed")
            cur = self._conn.cursor()
            try:
                cur.execute(_INSERT_DECISION_SQL, params)
                self._conn.commit()
                return int(cur.lastrowid)
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def get_review_decision(self, decision_id: int) -> dict[str, Any] | None:
        """Fetch a single review decision by ID."""
        with self._lock:
            if self._conn is None:
                return None
            cur = self._conn.cursor()
            try:
                cur.execute("SELECT * FROM review_decisions WHERE id = ?", (int(decision_id),))
                row = cur.fetchone()
                return _hydrate_decision_row(row) if row else None
            finally:
                cur.close()

    def get_latest_decision_for_review(
        self, review_id: int, *, include_undone: bool = False
    ) -> dict[str, Any] | None:
        """Fetch the most recent decision for a given ``review_queue`` item."""
        sql = "SELECT * FROM review_decisions WHERE review_id = ?"
        if not include_undone:
            sql += " AND undone = 0"
        sql += " ORDER BY id DESC LIMIT 1"
        with self._lock:
            if self._conn is None:
                return None
            cur = self._conn.cursor()
            try:
                cur.execute(sql, (int(review_id),))
                row = cur.fetchone()
                return _hydrate_decision_row(row) if row else None
            finally:
                cur.close()

    def list_review_decisions(
        self,
        *,
        review_id: int | None = None,
        include_undone: bool = True,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List review decisions ordered newest-first with optional filters."""
        clauses: list[str] = []
        params: list[Any] = []
        if review_id is not None:
            clauses.append("review_id = ?")
            params.append(int(review_id))
        if not include_undone:
            clauses.append("undone = 0")
        sql = "SELECT * FROM review_decisions"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, min(int(limit), 200)))
        with self._lock:
            if self._conn is None:
                return []
            cur = self._conn.cursor()
            try:
                cur.execute(sql, params)
                return [_hydrate_decision_row(r) for r in cur.fetchall()]
            finally:
                cur.close()

    def mark_decision_undone(self, decision_id: int, undone_by: str = "operator") -> bool:
        """Mark a review decision as undone with timestamp and actor."""
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        with self._lock:
            if self._conn is None:
                return False
            cur = self._conn.cursor()
            try:
                cur.execute(
                    "UPDATE review_decisions SET undone = 1, undone_at = ?, undone_by = ? "
                    "WHERE id = ? AND undone = 0",
                    (now, str(undone_by or "operator").strip(), int(decision_id)),
                )
                self._conn.commit()
                return cur.rowcount > 0
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def get_sighting_by_id(self, sighting_id: int) -> dict[str, Any] | None:
        """Fetch a single sighting row by ID."""
        with self._lock:
            if self._conn is None:
                return None
            cur = self._conn.cursor()
            try:
                cur.execute("SELECT * FROM sightings WHERE id = ?", (int(sighting_id),))
                row = cur.fetchone()
                return dict(row) if row else None
            finally:
                cur.close()

    def delete_sighting_by_id(self, sighting_id: int) -> bool:
        """Delete a single sighting row by ID."""
        with self._lock:
            if self._conn is None:
                return False
            cur = self._conn.cursor()
            try:
                cur.execute("DELETE FROM sightings WHERE id = ?", (int(sighting_id),))
                self._conn.commit()
                return cur.rowcount > 0
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def reassign_sightings_by_provenance(
        self,
        *,
        from_entity_id: int,
        to_entity_id: int | None,
        camera_id: str = "",
        run_id: str = "",
        video_filename: str = "",
        track_id: int | None = None,
    ) -> int:
        """Reassign sightings matching ``from_entity_id`` and provenance filters."""
        clauses = ["entity_id = ?"]
        params: list[Any] = [to_entity_id, int(from_entity_id)]
        for col, val in (("camera_id", camera_id), ("run_id", run_id), ("video_filename", video_filename)):
            if str(val or "").strip():
                clauses.append(f"{col} = ?")
                params.append(str(val).strip())
        if track_id is not None:
            clauses.append("track_id = ?")
            params.append(int(track_id))
        sql = f"UPDATE sightings SET entity_id = ? WHERE {' AND '.join(clauses)}"
        with self._lock:
            if self._conn is None:
                return 0
            cur = self._conn.cursor()
            try:
                cur.execute(sql, params)
                self._conn.commit()
                return int(cur.rowcount)
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def prune_descriptor_version(self, version_id: int) -> bool:
        """Delete a single ``descriptor_versions`` row by ID."""
        with self._lock:
            if self._conn is None:
                return False
            cur = self._conn.cursor()
            try:
                cur.execute("DELETE FROM descriptor_versions WHERE id = ?", (int(version_id),))
                self._conn.commit()
                return cur.rowcount > 0
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()
