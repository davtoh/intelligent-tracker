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


class AnalyticsMixin:
    """Provides sighting audit trail logging, analytics, and export utilities."""

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
    ) -> int:
        """
        Log an entity sighting to the audit trail.

        :return: Created sighting ID.
        """
        if timestamp is None:
            ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        elif isinstance(timestamp, (int, float)):
            ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(timestamp))
        elif isinstance(timestamp, datetime):
            ts_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        else:
            ts_str = str(timestamp)

        if isinstance(bbox, (list, tuple)):
            bbox_str = json.dumps([int(v) for v in bbox])
        else:
            bbox_str = str(bbox)

        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO sightings (
                        entity_id, track_id, source, timestamp, zone_id, bbox, confidence, snapshot_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entity_id,
                        track_id,
                        source.strip(),
                        ts_str,
                        zone_id.strip(),
                        bbox_str,
                        float(confidence),
                        snapshot_path.strip(),
                    ),
                )
                self._conn.commit()
                return cursor.lastrowid
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
    ) -> List[Dict[str, Any]]:
        """Query sightings audit trail with flexible filtering."""
        query = """
            SELECT s.*, e.name AS entity_name, e.category AS entity_category
            FROM sightings s
            LEFT JOIN entities e ON s.entity_id = e.id
        """
        conditions = []
        params = []

        if entity_id is not None:
            conditions.append("s.entity_id = ?")
            params.append(entity_id)
        if source:
            conditions.append("s.source = ?")
            params.append(source.strip())
        if zone_id:
            conditions.append("s.zone_id = ?")
            params.append(zone_id.strip())
        if start_time:
            conditions.append("s.timestamp >= ?")
            params.append(start_time)
        if end_time:
            conditions.append("s.timestamp <= ?")
            params.append(end_time)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY s.timestamp DESC"
        if limit > 0:
            query += " LIMIT ?"
            params.append(limit)

        with self._lock:
            cursor = self._conn.cursor()
            try:
                cursor.execute(query, params)
                return [dict(r) for r in cursor.fetchall()]
            finally:
                cursor.close()

    query_sightings = get_sightings

    def get_entity_analytics(self, entity_id: int) -> Dict[str, Any]:
        """
        Compute occurrence frequency, dwell timeline, and zone journey for an entity.
        """
        entity = self.get_entity(entity_id)
        if not entity:
            return {"error": "Entity not found", "entity_id": entity_id}

        with self._lock:
            cursor = self._conn.cursor()
            try:
                # Count and time bounds
                cursor.execute(
                    """
                    SELECT COUNT(*) as total_sightings,
                           MIN(timestamp) as first_seen,
                           MAX(timestamp) as last_seen,
                           COUNT(DISTINCT source) as distinct_sources,
                           COUNT(DISTINCT zone_id) as distinct_zones
                    FROM sightings
                    WHERE entity_id = ?
                    """,
                    (entity_id,),
                )
                stats = dict(cursor.fetchone())

                # Distinct sources list
                cursor.execute(
                    "SELECT DISTINCT source FROM sightings WHERE entity_id = ? AND source != ''",
                    (entity_id,),
                )
                sources = [r[0] for r in cursor.fetchall()]

                # Distinct zones list
                cursor.execute(
                    "SELECT DISTINCT zone_id FROM sightings WHERE entity_id = ? AND zone_id != ''",
                    (entity_id,),
                )
                zones = [r[0] for r in cursor.fetchall()]

                # Detailed chronological sightings
                cursor.execute(
                    """
                    SELECT timestamp, source, zone_id, track_id, confidence
                    FROM sightings
                    WHERE entity_id = ?
                    ORDER BY timestamp ASC
                    """,
                    (entity_id,),
                )
                timeline = [dict(r) for r in cursor.fetchall()]
            finally:
                cursor.close()

        # Dwell time approximation based on sighting timestamps
        estimated_dwell_seconds = 0.0
        if len(timeline) >= 2:
            try:
                t_first = datetime.strptime(stats["first_seen"], "%Y-%m-%d %H:%M:%S")
                t_last = datetime.strptime(stats["last_seen"], "%Y-%m-%d %H:%M:%S")
                span = (t_last - t_first).total_seconds()
                # If seen across a short window, span is dwell
                estimated_dwell_seconds = max(0.0, span)
            except Exception:
                pass

        return {
            "entity": entity,
            "total_sightings": stats["total_sightings"],
            "first_seen": stats["first_seen"],
            "last_seen": stats["last_seen"],
            "distinct_sources_count": stats["distinct_sources"],
            "sources": sources,
            "distinct_zones_count": stats["distinct_zones"],
            "zones": zones,
            "estimated_dwell_seconds": estimated_dwell_seconds,
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

