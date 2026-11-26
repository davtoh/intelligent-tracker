"""SQL query builders and helpers for sightings filtering, counting, and source listing."""

from datetime import datetime
from typing import Any, Optional, Tuple


def _build_sightings_filters(
    entity_id: Optional[int],
    source: Optional[str],
    zone_id: Optional[str],
    start_time: Optional[str],
    end_time: Optional[str],
    video_filename: Optional[str] = None,
) -> tuple[str, list[Any]]:
    """Build parameterized WHERE clause and bind parameters for sightings queries."""
    filters = [
        ("s.entity_id = ?", entity_id, entity_id is not None),
        ("s.source = ?", source.strip() if source else None, bool(source and source.strip())),
        ("s.zone_id = ?", zone_id.strip() if zone_id else None, bool(zone_id and zone_id.strip())),
        (
            "s.video_filename = ?",
            video_filename.strip() if video_filename else None,
            bool(video_filename and video_filename.strip()),
        ),
        ("s.timestamp >= ?", start_time, bool(start_time)),
        ("s.timestamp <= ?", end_time, bool(end_time)),
    ]
    conditions = [sql for sql, _, active in filters if active]
    params = [val for _, val, active in filters if active]
    where_sql = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    return where_sql, params


def build_sightings_query(
    entity_id: Optional[int],
    source: Optional[str],
    zone_id: Optional[str],
    start_time: Optional[str],
    end_time: Optional[str],
    limit: int,
    offset: int = 0,
    video_filename: Optional[str] = None,
) -> tuple[str, list[Any]]:
    """Build parameterized SQL query and args for sightings filtering and pagination."""
    where_sql, params = _build_sightings_filters(
        entity_id, source, zone_id, start_time, end_time, video_filename=video_filename
    )
    query = (
        "SELECT s.*, e.name AS entity_name, e.category AS entity_category "
        "FROM sightings s LEFT JOIN entities e ON s.entity_id = e.id"
        f"{where_sql} ORDER BY s.timestamp DESC, s.id DESC"
    )
    safe_offset = max(0, int(offset or 0))
    safe_limit = int(limit or 0)
    if safe_limit > 0:
        query += " LIMIT ?"
        params.append(safe_limit)
        if safe_offset > 0:
            query += " OFFSET ?"
            params.append(safe_offset)
    elif safe_offset > 0:
        query += " LIMIT -1 OFFSET ?"
        params.append(safe_offset)
    return query, params


def count_sightings_sync(
    cursor: Any,
    entity_id: Optional[int] = None,
    source: Optional[str] = None,
    zone_id: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    video_filename: Optional[str] = None,
) -> int:
    """Count total sightings matching the given filter criteria."""
    where_sql, params = _build_sightings_filters(
        entity_id, source, zone_id, start_time, end_time, video_filename=video_filename
    )
    cursor.execute(f"SELECT COUNT(*) FROM sightings s{where_sql}", params)
    row = cursor.fetchone()
    return int(row[0]) if row else 0


def list_sighting_sources_sync(cursor: Any) -> list[dict[str, Any]]:
    """Return distinct non-empty sighting sources ordered by sighting count descending."""
    cursor.execute(
        "SELECT source, COUNT(*) AS count, "
        "MAX(CASE WHEN video_filename != '' THEN 1 ELSE 0 END) AS has_video "
        "FROM sightings WHERE source != '' GROUP BY source ORDER BY count DESC, source ASC"
    )
    return [
        {
            "source": str(row["source"]),
            "count": int(row["count"]),
            "has_video": bool(row["has_video"]),
        }
        for row in cursor.fetchall()
    ]


def fetch_entity_analytics_rows(
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


def compute_dwell_seconds(timeline: list[dict[str, Any]], first_seen: Optional[str], last_seen: Optional[str]) -> float:
    """Estimate dwell duration in seconds from first and last sighting timestamps."""
    if len(timeline) < 2 or not first_seen or not last_seen:
        return 0.0
    try:
        t_first = datetime.strptime(first_seen, "%Y-%m-%d %H:%M:%S")
        t_last = datetime.strptime(last_seen, "%Y-%m-%d %H:%M:%S")
        return max(0.0, (t_last - t_first).total_seconds())
    except Exception:
        return 0.0
