"""
Analytics and Sightings Repository Mixin.

Manages entity sighting audit trails, occurrence timeline analytics, dwell
time computation, and JSON/CSV summary exports.
"""

import os
import csv
import json
import time
from datetime import datetime
from typing import Optional, Dict, Any, List, Union, Tuple


def _format_sighting_timestamp(timestamp: Optional[Union[float, str, datetime]]) -> str:
    """Normalize sighting timestamps into SQLite UTC string format."""
    if timestamp is None:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    if isinstance(timestamp, (int, float)):
        return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(timestamp))
    if isinstance(timestamp, datetime):
        return timestamp.strftime("%Y-%m-%d %H:%M:%S")
    return str(timestamp)


def _format_sighting_bbox(bbox: Union[str, Tuple[int, int, int, int], List[int]]) -> str:
    """Serialize bounding box tuple/list as JSON string."""
    if isinstance(bbox, (list, tuple)):
        return json.dumps([int(v) for v in bbox])
    return str(bbox)


def _build_sightings_query(
    entity_id: Optional[int],
    source: Optional[str],
    zone_id: Optional[str],
    start_time: Optional[str],
    end_time: Optional[str],
    limit: int,
    video_filename: Optional[str] = None,
) -> tuple[str, list[Any]]:
    """Build parameterized SQL query and args for sightings filtering."""
    query = "SELECT s.*, e.name AS entity_name, e.category AS entity_category FROM sightings s LEFT JOIN entities e ON s.entity_id = e.id"
    filters = [
        ("s.entity_id = ?", entity_id, entity_id is not None),
        ("s.source = ?", source.strip() if source else None, bool(source)),
        ("s.zone_id = ?", zone_id.strip() if zone_id else None, bool(zone_id)),
        ("s.video_filename = ?", video_filename.strip() if video_filename else None, bool(video_filename)),
        ("s.timestamp >= ?", start_time, bool(start_time)),
        ("s.timestamp <= ?", end_time, bool(end_time)),
    ]
    conditions = [sql for sql, _, active in filters if active]
    params = [val for _, val, active in filters if active]
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY s.timestamp DESC"
    if limit > 0:
        query += " LIMIT ?"
        params.append(limit)
    return query, params


def _fetch_entity_analytics_rows(
    cursor: Any, entity_id: int, video_filename: Optional[str] = None
) -> tuple[dict[str, Any], list[str], list[str], list[dict[str, Any]]]:
    """Fetch aggregate stats, sources, zones, and timeline rows for one entity."""
    vf = video_filename.strip() if video_filename else ""
    vf_clause = " AND video_filename = ?" if vf else ""
    base_params: Tuple[Any, ...] = (entity_id, vf) if vf else (entity_id,)
    cursor.execute(
        "SELECT COUNT(*) as total_sightings, MIN(timestamp) as first_seen, MAX(timestamp) as last_seen,"
        " COUNT(DISTINCT source) as distinct_sources, COUNT(DISTINCT zone_id) as distinct_zones"
        f" FROM sightings WHERE entity_id = ?{vf_clause}",
        base_params,
    )
    stats = dict(cursor.fetchone())
    cursor.execute(f"SELECT DISTINCT source FROM sightings WHERE entity_id = ? AND source != ''{vf_clause}", base_params)
    sources = [r[0] for r in cursor.fetchall()]
    cursor.execute(f"SELECT DISTINCT zone_id FROM sightings WHERE entity_id = ? AND zone_id != ''{vf_clause}", base_params)
    zones = [r[0] for r in cursor.fetchall()]
    cursor.execute(
        "SELECT timestamp, source, zone_id, track_id, confidence, video_filename, media_offset_sec"
        f" FROM sightings WHERE entity_id = ?{vf_clause} ORDER BY timestamp ASC",
        base_params,
    )
    return stats, sources, zones, [dict(r) for r in cursor.fetchall()]


def _compute_dwell_seconds(timeline: list[dict[str, Any]], first_seen: Optional[str], last_seen: Optional[str]) -> float:
    """Estimate dwell duration in seconds from first and last sighting timestamps."""
    if len(timeline) < 2 or not first_seen or not last_seen:
        return 0.0
    try:
        t_first = datetime.strptime(first_seen, "%Y-%m-%d %H:%M:%S")
        t_last = datetime.strptime(last_seen, "%Y-%m-%d %H:%M:%S")
        return max(0.0, (t_last - t_first).total_seconds())
    except Exception:
        return 0.0


_INSERT_SIGHTING_SQL = """
INSERT INTO sightings (
    entity_id, track_id, source, timestamp, zone_id, bbox,
    confidence, snapshot_path, video_filename, media_offset_sec
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class AnalyticsMixin:
    """Provides sighting audit trail logging, analytics, and export utilities."""

    _conn: Any
    _lock: Any
    get_entity: Any

    def add_sighting(
        self,
        entity_id: Optional[int],
        track_id: Optional[int] = None,
        source: str = "",
        timestamp: Optional[Union[float, str, datetime]] = None,
        zone_id: str = "",
        bbox: Union[str, Tuple[int, int, int, int], List[int]] = "",
        confidence: float = 1.0,
        snapshot_path: str = "",
        video_filename: str = "",
        media_offset_sec: float = 0.0,
    ) -> int:
        """Log an entity sighting to the audit trail and return its ID."""
        params = (
            entity_id, track_id, source.strip(), _format_sighting_timestamp(timestamp),
            zone_id.strip(), _format_sighting_bbox(bbox), float(confidence),
            snapshot_path.strip(), str(video_filename or "").strip(), float(media_offset_sec or 0.0),
        )
        with self._lock:
            if self._conn is None:
                raise RuntimeError("Database connection is closed")
            cursor = self._conn.cursor()
            try:
                cursor.execute(_INSERT_SIGHTING_SQL, params)
                self._conn.commit()
                return cursor.lastrowid
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cursor.close()

    record_sighting = add_sighting

    def get_sightings(
        self,
        entity_id: Optional[int] = None,
        source: Optional[str] = None,
        zone_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100,
        video_filename: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query sightings audit trail with flexible filtering."""
        query, params = _build_sightings_query(
            entity_id, source, zone_id, start_time, end_time, limit, video_filename=video_filename
        )
        with self._lock:
            if self._conn is None:
                return []
            cursor = self._conn.cursor()
            try:
                cursor.execute(query, params)
                return [dict(r) for r in cursor.fetchall()]
            finally:
                cursor.close()

    query_sightings = get_sightings

    def query_sighting_counts(
        self, entity_ids: list[int] | None = None
    ) -> dict[int, int]:
        """Return sighting counts keyed by entity_id using a single GROUP BY query."""
        if entity_ids is not None and len(entity_ids) == 0:
            return {}

        with self._lock:
            if self._conn is None:
                return {}
            cursor = self._conn.cursor()
            try:
                if entity_ids is None:
                    cursor.execute(
                        """
                        SELECT entity_id, COUNT(*) AS sighting_count
                        FROM sightings
                        WHERE entity_id IS NOT NULL
                        GROUP BY entity_id
                        """
                    )
                else:
                    placeholders = ",".join("?" for _ in entity_ids)
                    cursor.execute(
                        f"""
                        SELECT entity_id, COUNT(*) AS sighting_count
                        FROM sightings
                        WHERE entity_id IN ({placeholders})
                        GROUP BY entity_id
                        """,
                        tuple(entity_ids),
                    )
                return {int(row["entity_id"]): int(row["sighting_count"]) for row in cursor.fetchall()}
            finally:
                cursor.close()

    @staticmethod
    def _group_sighting_counts(cursor: Any, column: str) -> dict[str, int]:
        """Return grouped sighting counts for a non-empty column value."""
        if column not in {"source", "zone_id"}:
            raise ValueError(f"Unsupported grouping column: {column}")
        cursor.execute(
            f"SELECT {column}, COUNT(*) AS count FROM sightings "
            f"WHERE {column} != '' GROUP BY {column} ORDER BY count DESC"
        )
        return {row[column]: int(row["count"]) for row in cursor.fetchall()}

    def get_analytics_summary(self) -> dict[str, Any]:
        """Return aggregate entity, signature, and sighting breakdown statistics."""
        with self._lock:
            if self._conn is None:
                return {
                    "total_entities": 0, "total_signatures": 0, "total_sightings": 0,
                    "sightings_by_entity": {}, "sightings_by_source": {}, "sightings_by_zone": {},
                }
            cursor = self._conn.cursor()
            try:
                total_entities = int(cursor.execute("SELECT COUNT(*) FROM entities").fetchone()[0])
                total_signatures = int(
                    cursor.execute("SELECT COUNT(*) FROM entity_signatures").fetchone()[0]
                )
                total_sightings = int(cursor.execute("SELECT COUNT(*) FROM sightings").fetchone()[0])
                by_source = self._group_sighting_counts(cursor, "source")
                by_zone = self._group_sighting_counts(cursor, "zone_id")
                by_entity = self.query_sighting_counts()
            finally:
                cursor.close()

        return {
            "total_entities": total_entities,
            "total_signatures": total_signatures,
            "total_sightings": total_sightings,
            "sightings_by_entity": by_entity,
            "sightings_by_source": by_source,
            "sightings_by_zone": by_zone,
        }

    def get_entity_analytics(
        self, entity_id: int, video_filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """Compute occurrence frequency, dwell timeline, and zone journey for an entity."""
        entity = self.get_entity(entity_id)
        if not entity:
            return {"error": "Entity not found", "entity_id": entity_id}

        with self._lock:
            if self._conn is None:
                return {"error": "Database connection is closed", "entity_id": entity_id}
            cursor = self._conn.cursor()
            try:
                stats, sources, zones, timeline = _fetch_entity_analytics_rows(
                    cursor, entity_id, video_filename=video_filename
                )
            finally:
                cursor.close()

        return {
            "entity": entity,
            "total_sightings": stats["total_sightings"],
            "first_seen": stats["first_seen"],
            "last_seen": stats["last_seen"],
            "distinct_sources_count": stats["distinct_sources"],
            "sources": sources,
            "distinct_zones_count": stats["distinct_zones"],
            "zones": zones,
            "estimated_dwell_seconds": _compute_dwell_seconds(timeline, stats["first_seen"], stats["last_seen"]),
            "timeline": timeline,
        }

    def export_sightings_csv(self, output_path: str, entity_id: Optional[int] = None) -> str:
        """Export sightings to a CSV file."""
        sightings = self.get_sightings(entity_id=entity_id, limit=0)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

        fieldnames = [
            "id", "entity_id", "entity_name", "entity_category", "track_id",
            "source", "timestamp", "zone_id", "bbox", "confidence", "snapshot_path"
        ]
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for s in sightings:
                row = {k: s.get(k, "") for k in fieldnames}
                writer.writerow(row)
        return output_path

    def export_sightings_json(self, output_path: str, entity_id: Optional[int] = None) -> str:
        """Export sightings to a JSON file."""
        sightings = self.get_sightings(entity_id=entity_id, limit=0)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(sightings, f, indent=2, default=str)
        return output_path

