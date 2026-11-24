"""Atomic SQLite update helpers for Scenario Studio zones and tripwires."""

import json
import time
from typing import Any


class ScenarioNotFoundError(LookupError):
    """Raised when a target zone or tripwire does not exist."""


class ScenarioConflictError(ValueError):
    """Raised when renaming a zone or tripwire collides with an existing name."""


def _require_conn(db: Any) -> Any:
    conn = getattr(db, "_conn", None)
    if conn is None:
        raise RuntimeError("Database connection is closed")
    return conn


def _serialize_color(color: Any, fallback: Any) -> str:
    val = color if color is not None else fallback
    if isinstance(val, (list, tuple)):
        return json.dumps([int(c) for c in val[:3]])
    return str(val)


def _fetch_row_and_check_rename(
    cur: Any, table: str, kind: str, camera_id: str, old_name: str, new_name: str | None
) -> tuple[Any, str]:
    row = cur.execute(f"SELECT * FROM {table} WHERE camera_id = ? AND name = ?", (camera_id, old_name)).fetchone()
    if row is None:
        raise ScenarioNotFoundError(f"{kind} '{old_name}' not found for camera '{camera_id}'")
    resolved_name = str(new_name).strip() if new_name is not None else str(row["name"])
    if resolved_name != old_name:
        clash = cur.execute(
            f"SELECT 1 FROM {table} WHERE camera_id = ? AND name = ?", (camera_id, resolved_name)
        ).fetchone()
        if clash is not None:
            raise ScenarioConflictError(f"{kind} '{resolved_name}' already exists for camera '{camera_id}'")
    return row, resolved_name


def update_spatial_zone_sync(
    db: Any,
    camera_id: str,
    zone_id: str,
    *,
    name: str | None = None,
    polygon: list[list[float]] | list[tuple[float, float]] | None = None,
    category_filter: str | None = None,
    dwell_threshold: float | None = None,
    capacity_limit: int | None = None,
    capacity_limit_set: bool = False,
    color: list[int] | tuple[int, ...] | str | None = None,
) -> dict[str, Any]:
    """Atomically update an existing spatial_zones row without touching historical tables."""
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    with db._lock:
        conn = _require_conn(db)
        cur = conn.cursor()
        try:
            row, new_name = _fetch_row_and_check_rename(cur, "spatial_zones", "Zone", camera_id, zone_id, name)
            poly_json = json.dumps(polygon) if polygon is not None else row["polygon_json"]
            cat = str(category_filter) if category_filter is not None else (row["category_filter"] or "")
            dwell = float(dwell_threshold) if dwell_threshold is not None else float(row["dwell_threshold"])
            cap = capacity_limit if capacity_limit_set else row["capacity_limit"]
            col_str = _serialize_color(color, row["color"])
            cur.execute(
                "UPDATE spatial_zones SET name = ?, polygon_json = ?, category_filter = ?, "
                "dwell_threshold = ?, capacity_limit = ?, color = ?, updated_at = ? WHERE camera_id = ? AND name = ?",
                (new_name, poly_json, cat, dwell, cap, col_str, now, camera_id, zone_id),
            )
            conn.commit()
            return {"camera_id": camera_id, "name": new_name, "polygon": json.loads(poly_json), "category_filter": cat, "dwell_threshold": dwell, "capacity_limit": cap}
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


def update_spatial_tripwire_sync(
    db: Any,
    camera_id: str,
    tripwire_id: str,
    *,
    name: str | None = None,
    line_segment: list[list[float]] | list[tuple[float, float]] | None = None,
    bidirectional: bool | None = None,
    color: list[int] | tuple[int, ...] | str | None = None,
) -> dict[str, Any]:
    """Atomically update an existing spatial_tripwires row without touching historical tables."""
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    with db._lock:
        conn = _require_conn(db)
        cur = conn.cursor()
        try:
            row, new_name = _fetch_row_and_check_rename(cur, "spatial_tripwires", "Tripwire", camera_id, tripwire_id, name)
            line_json = json.dumps(line_segment) if line_segment is not None else row["line_segment_json"]
            bidir = bool(bidirectional) if bidirectional is not None else bool(row["bidirectional"])
            col_str = _serialize_color(color, row["color"])
            cur.execute(
                "UPDATE spatial_tripwires SET name = ?, line_segment_json = ?, bidirectional = ?, "
                "color = ?, updated_at = ? WHERE camera_id = ? AND name = ?",
                (new_name, line_json, 1 if bidir else 0, col_str, now, camera_id, tripwire_id),
            )
            conn.commit()
            return {"camera_id": camera_id, "name": new_name, "line_segment": json.loads(line_json), "bidirectional": bidir}
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
