"""Semantic Memory, Confidence State, and FTS5 Timeline Repository Mixin.

Provides thread-safe persistence for calibrated ``entity_confidence_state``
records and BM25-ranked full-text timeline indexing/search over
``world_timeline_events`` and ``world_timeline_fts``.
"""

import json
import re
import sqlite3
import time
from typing import Any

_FTS_STOPWORDS = frozenset({
    "a", "an", "and", "are", "at", "be", "been", "by", "did", "do",
    "does", "for", "from", "had", "has", "have", "how", "in", "is",
    "of", "on", "or", "the", "to", "was", "were", "what", "when", "where", "who", "with",
})

_UPSERT_CONFIDENCE_SQL = """
INSERT INTO entity_confidence_state (
    entity_id, confidence, face_score, body_score, streak_count, observation_count,
    confirmation_count, rejection_count, ambiguity_penalty, last_camera_id,
    last_zone_id, last_seen_at, evidence_json, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
ON CONFLICT(entity_id) DO UPDATE SET
    confidence = excluded.confidence, face_score = excluded.face_score,
    body_score = excluded.body_score, streak_count = excluded.streak_count,
    observation_count = excluded.observation_count,
    confirmation_count = excluded.confirmation_count,
    rejection_count = excluded.rejection_count,
    ambiguity_penalty = excluded.ambiguity_penalty,
    last_camera_id = excluded.last_camera_id, last_zone_id = excluded.last_zone_id,
    last_seen_at = excluded.last_seen_at, evidence_json = excluded.evidence_json,
    updated_at = CURRENT_TIMESTAMP
"""

_INSERT_TIMELINE_SQL = """
INSERT INTO world_timeline_events (
    event_type, entity_id, entity_name, category, camera_id, zone_id,
    timestamp, confidence, title, summary, tags, metadata_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _parse_json_dict(raw: str | None) -> dict[str, Any]:
    """Safely deserialize a JSON object column into a dictionary."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _build_fts_match_expr(raw_query: str, require_all: bool = False) -> str:
    """Convert arbitrary user text into a safe FTS5 MATCH expression."""
    tokens = re.findall(r"[A-Za-z0-9_]+", raw_query or "")
    if not tokens:
        return ""
    filtered = [tok for tok in tokens if tok.lower() not in _FTS_STOPWORDS]
    terms = filtered or tokens
    joiner = " AND " if require_all else " OR "
    return joiner.join(f'"{tok}"' for tok in terms)


def _hydrate_row(row: sqlite3.Row, json_col: str, out_key: str) -> dict[str, Any]:
    """Convert a SQLite row into a dict and parse its JSON column."""
    data = dict(row)
    data[out_key] = _parse_json_dict(data.get(json_col))
    return data


def _build_timeline_query(
    match_expr: str, entity_id: int | None, camera_id: str | None,
    zone_id: str | None, event_type: str | None,
    start_time: float | None, end_time: float | None, limit: int,
) -> tuple[str, list[Any]]:
    """Build parameterized SQL and bind args for timeline FTS/filter queries."""
    clauses: list[str] = []
    params: list[Any] = []
    if match_expr:
        sql = (
            "SELECT e.*, bm25(world_timeline_fts) AS rank FROM world_timeline_fts "
            "JOIN world_timeline_events e ON e.id = world_timeline_fts.rowid"
        )
        clauses.append("world_timeline_fts MATCH ?")
        params.append(match_expr)
        order_by = "ORDER BY rank ASC, e.timestamp DESC"
    else:
        sql = "SELECT e.*, 0.0 AS rank FROM world_timeline_events e"
        order_by = "ORDER BY e.timestamp DESC"

    filters = (
        ("e.entity_id = ?", int(entity_id) if entity_id is not None else None),
        ("e.camera_id = ?", camera_id.strip() if camera_id else None),
        ("e.zone_id = ?", zone_id.strip() if zone_id else None),
        ("e.event_type = ?", event_type.strip() if event_type else None),
        ("e.timestamp >= ?", float(start_time) if start_time is not None else None),
        ("e.timestamp <= ?", float(end_time) if end_time is not None else None),
    )
    for clause, val in filters:
        if val is not None:
            clauses.append(clause)
            params.append(val)
    where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, int(limit)))
    return f"{sql}{where_sql} {order_by} LIMIT ?", params


class MemoryMixin:
    """Provides confidence state persistence and FTS5 timeline operations."""

    def get_schema_version(self) -> int:
        """Return the SQLite ``PRAGMA user_version`` integer."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                row = cur.execute("PRAGMA user_version;").fetchone()
                return int(row[0]) if row else 0
            finally:
                cur.close()

    def upsert_entity_confidence(
        self, entity_id: int, confidence: float, face_score: float = 0.0, body_score: float = 0.0,
        streak_count: int = 0, observation_count: int = 0, confirmation_count: int = 0,
        rejection_count: int = 0, ambiguity_penalty: float = 0.0, last_camera_id: str = "",
        last_zone_id: str = "", last_seen_at: float | None = None, evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Insert or update calibrated confidence state for ``entity_id``."""
        seen_ts = float(last_seen_at) if last_seen_at is not None else time.time()
        clamped = max(0.0, min(1.0, float(confidence)))
        values = (
            int(entity_id), clamped, float(face_score), float(body_score),
            int(streak_count), int(observation_count), int(confirmation_count),
            int(rejection_count), float(ambiguity_penalty),
            str(last_camera_id), str(last_zone_id), seen_ts, json.dumps(evidence or {}, sort_keys=True),
        )
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(_UPSERT_CONFIDENCE_SQL, values)
                self._conn.commit()
            finally:
                cur.close()
        return self.get_entity_confidence(int(entity_id)) or {}

    def get_entity_confidence(self, entity_id: int) -> dict[str, Any] | None:
        """Retrieve persisted confidence state for ``entity_id`` or None."""
        sql = (
            "SELECT c.*, e.name AS entity_name, e.category AS category "
            "FROM entity_confidence_state c LEFT JOIN entities e ON e.id = c.entity_id WHERE c.entity_id = ?"
        )
        with self._lock:
            cur = self._conn.cursor()
            try:
                row = cur.execute(sql, (int(entity_id),)).fetchone()
                return _hydrate_row(row, "evidence_json", "evidence") if row else None
            finally:
                cur.close()

    def _fetch_hydrated_rows(self, sql: str, params: list[Any], json_col: str, out_key: str) -> list[dict[str, Any]]:
        """Execute a SELECT under lock and hydrate JSON column on each row."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                rows = cur.execute(sql, params).fetchall()
                return [_hydrate_row(row, json_col, out_key) for row in rows]
            finally:
                cur.close()

    def list_entity_confidences(self, min_confidence: float | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """List entity confidence states ordered by confidence descending."""
        sql = "SELECT c.*, e.name AS entity_name, e.category AS category FROM entity_confidence_state c LEFT JOIN entities e ON e.id = c.entity_id"
        params: list[Any] = []
        if min_confidence is not None:
            sql += " WHERE c.confidence >= ?"
            params.append(float(min_confidence))
        sql += " ORDER BY c.confidence DESC, c.last_seen_at DESC LIMIT ?"
        params.append(max(1, int(limit)))
        return self._fetch_hydrated_rows(sql, params, "evidence_json", "evidence")

    def index_timeline_event(
        self, summary: str, event_type: str = "sighting", entity_id: int | None = None,
        entity_name: str = "", category: str = "", camera_id: str = "", zone_id: str = "",
        timestamp: float | None = None, confidence: float = 1.0, title: str = "",
        tags: str = "", metadata: dict[str, Any] | None = None,
    ) -> int:
        """Insert a timeline event and automatically index it into ``world_timeline_fts``."""
        ts = float(timestamp) if timestamp is not None else time.time()
        values = (
            event_type.strip(), entity_id, entity_name.strip(), category.strip(),
            camera_id.strip(), zone_id.strip(), ts, float(confidence),
            title.strip(), summary.strip(), tags.strip(), json.dumps(metadata or {}, sort_keys=True),
        )
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(_INSERT_TIMELINE_SQL, values)
                self._conn.commit()
                return int(cur.lastrowid)
            finally:
                cur.close()

    def get_timeline_event(self, event_id: int) -> dict[str, Any] | None:
        """Retrieve a single timeline event by ID."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                row = cur.execute("SELECT * FROM world_timeline_events WHERE id = ?", (int(event_id),)).fetchone()
                return _hydrate_row(row, "metadata_json", "metadata") if row else None
            finally:
                cur.close()

    def delete_timeline_event(self, event_id: int) -> bool:
        """Delete a timeline event and remove its entry from ``world_timeline_fts``."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("DELETE FROM world_timeline_events WHERE id = ?", (int(event_id),))
                self._conn.commit()
                return cur.rowcount > 0
            finally:
                cur.close()

    def search_timeline_events(
        self, query: str = "", entity_id: int | None = None, camera_id: str | None = None,
        zone_id: str | None = None, event_type: str | None = None,
        start_time: float | None = None, end_time: float | None = None,
        limit: int = 25, require_all: bool = False,
    ) -> list[dict[str, Any]]:
        """Search timeline events using FTS5 BM25 ranking plus structured filters."""
        match_expr = _build_fts_match_expr(query, require_all=require_all)
        sql, params = _build_timeline_query(
            match_expr, entity_id, camera_id, zone_id, event_type, start_time, end_time, limit
        )
        return self._fetch_hydrated_rows(sql, params, "metadata_json", "metadata")
