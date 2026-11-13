"""
Spatial Studio and Calibration Repository Mixin.

Manages Scenario Studio zones, tripwires, cross-camera spatial transition links,
and ground-plane homography calibrations.
"""

import json
import time
from typing import Optional, Dict, Any, List, Union, Tuple


class SpatialMixin:
    """Provides spatial zone, tripwire, transition, and homography persistence."""

    def save_zone(
        self,
        camera_id: str,
        name: str,
        polygon: List[Union[List[float], Tuple[float, float]]],
        category_filter: str = "",
        dwell_threshold: float = 5.0,
        capacity_limit: Optional[int] = None,
        color: Union[str, List[int], Tuple[int, ...]] = "",
    ) -> int:
        """Create or update a spatial zone for a camera."""
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        poly_json = json.dumps(polygon)
        color_str = json.dumps(color) if isinstance(color, (list, tuple)) else str(color)
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO spatial_zones (camera_id, name, polygon_json, category_filter, dwell_threshold, capacity_limit, color, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(camera_id, name) DO UPDATE SET
                        polygon_json = excluded.polygon_json,
                        category_filter = excluded.category_filter,
                        dwell_threshold = excluded.dwell_threshold,
                        capacity_limit = excluded.capacity_limit,
                        color = excluded.color,
                        updated_at = excluded.updated_at
                    """,
                    (camera_id, name, poly_json, category_filter, dwell_threshold, capacity_limit, color_str, now, now),
                )
                self._conn.commit()
                return cur.lastrowid
            finally:
                cur.close()

    def get_zones(self, camera_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve spatial zones, optionally filtered by camera_id."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                if camera_id:
                    cur.execute("SELECT * FROM spatial_zones WHERE camera_id = ? ORDER BY name ASC", (camera_id,))
                else:
                    cur.execute("SELECT * FROM spatial_zones ORDER BY camera_id, name ASC")
                rows = cur.fetchall()
                results = []
                for r in rows:
                    d = dict(r)
                    d["polygon"] = json.loads(d["polygon_json"])
                    try:
                        d["color"] = json.loads(d["color"]) if d["color"] else [0, 200, 100]
                    except Exception:
                        d["color"] = [0, 200, 100]
                    results.append(d)
                return results
            finally:
                cur.close()

    def delete_zone(self, camera_id: str, name: str) -> bool:
        """Delete a spatial zone by camera and name."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("DELETE FROM spatial_zones WHERE camera_id = ? AND name = ?", (camera_id, name))
                self._conn.commit()
                return cur.rowcount > 0
            finally:
                cur.close()

    def save_tripwire(
        self,
        camera_id: str,
        name: str,
        line_segment: List[Union[List[float], Tuple[float, float]]],
        bidirectional: bool = True,
        color: Union[str, List[int], Tuple[int, ...]] = "",
    ) -> int:
        """Create or update a spatial tripwire for a camera."""
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        line_json = json.dumps(line_segment)
        color_str = json.dumps(color) if isinstance(color, (list, tuple)) else str(color)
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO spatial_tripwires (camera_id, name, line_segment_json, bidirectional, color, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(camera_id, name) DO UPDATE SET
                        line_segment_json = excluded.line_segment_json,
                        bidirectional = excluded.bidirectional,
                        color = excluded.color,
                        updated_at = excluded.updated_at
                    """,
                    (camera_id, name, line_json, 1 if bidirectional else 0, color_str, now, now),
                )
                self._conn.commit()
                return cur.lastrowid
            finally:
                cur.close()

    def get_tripwires(self, camera_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve spatial tripwires, optionally filtered by camera_id."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                if camera_id:
                    cur.execute("SELECT * FROM spatial_tripwires WHERE camera_id = ? ORDER BY name ASC", (camera_id,))
                else:
                    cur.execute("SELECT * FROM spatial_tripwires ORDER BY camera_id, name ASC")
                rows = cur.fetchall()
                results = []
                for r in rows:
                    d = dict(r)
                    d["line_segment"] = json.loads(d["line_segment_json"])
                    d["bidirectional"] = bool(d["bidirectional"])
                    try:
                        d["color"] = json.loads(d["color"]) if d["color"] else [0, 255, 255]
                    except Exception:
                        d["color"] = [0, 255, 255]
                    results.append(d)
                return results
            finally:
                cur.close()

    def delete_tripwire(self, camera_id: str, name: str) -> bool:
        """Delete a spatial tripwire by camera and name."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("DELETE FROM spatial_tripwires WHERE camera_id = ? AND name = ?", (camera_id, name))
                self._conn.commit()
                return cur.rowcount > 0
            finally:
                cur.close()

    def save_spatial_transition(
        self,
        link_id: str,
        source_camera: str,
        source_zone: str,
        target_camera: str,
        target_zone: str,
        t_min: float = 2.0,
        t_max: float = 15.0,
        prior_boost: float = 0.35,
        bidirectional: bool = False,
        active: bool = True,
    ) -> int:
        """Create or update a cross-camera spatial transition link."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO spatial_transitions (link_id, source_camera, source_zone, target_camera, target_zone, t_min, t_max, prior_boost, bidirectional, active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(link_id) DO UPDATE SET
                        source_camera = excluded.source_camera,
                        source_zone = excluded.source_zone,
                        target_camera = excluded.target_camera,
                        target_zone = excluded.target_zone,
                        t_min = excluded.t_min,
                        t_max = excluded.t_max,
                        prior_boost = excluded.prior_boost,
                        bidirectional = excluded.bidirectional,
                        active = excluded.active
                    """,
                    (link_id, source_camera, source_zone, target_camera, target_zone, t_min, t_max, prior_boost, 1 if bidirectional else 0, 1 if active else 0),
                )
                self._conn.commit()
                return cur.lastrowid
            finally:
                cur.close()

    def get_spatial_transitions(self) -> List[Dict[str, Any]]:
        """Retrieve all cross-camera spatial transition links."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("SELECT * FROM spatial_transitions ORDER BY id ASC")
                rows = cur.fetchall()
                results = []
                for r in rows:
                    d = dict(r)
                    d["bidirectional"] = bool(d["bidirectional"])
                    d["active"] = bool(d["active"])
                    results.append(d)
                return results
            finally:
                cur.close()

    def delete_spatial_transition(self, link_id: str) -> bool:
        """Delete a spatial transition link by link_id."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("DELETE FROM spatial_transitions WHERE link_id = ?", (link_id,))
                self._conn.commit()
                return cur.rowcount > 0
            finally:
                cur.close()

    def save_homography_calibration(
        self,
        camera_id: str,
        src_points: List[Union[List[float], Tuple[float, float]]],
        dst_points: List[Union[List[float], Tuple[float, float]]],
        matrix: List[List[float]],
        metric_width: float = 10.0,
        metric_height: float = 10.0,
    ) -> int:
        """Save 4-point homography calibration for a camera channel."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO homography_calibrations (camera_id, src_points_json, dst_points_json, matrix_json, metric_width, metric_height)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(camera_id) DO UPDATE SET
                        src_points_json = excluded.src_points_json,
                        dst_points_json = excluded.dst_points_json,
                        matrix_json = excluded.matrix_json,
                        metric_width = excluded.metric_width,
                        metric_height = excluded.metric_height
                    """,
                    (camera_id, json.dumps(src_points), json.dumps(dst_points), json.dumps(matrix), metric_width, metric_height),
                )
                self._conn.commit()
                return cur.lastrowid
            finally:
                cur.close()

    def get_homography_calibration(self, camera_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve homography calibration profile for a camera."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("SELECT * FROM homography_calibrations WHERE camera_id = ?", (camera_id,))
                row = cur.fetchone()
                if not row:
                    return None
                d = dict(row)
                d["src_points"] = json.loads(d["src_points_json"])
                d["dst_points"] = json.loads(d["dst_points_json"])
                d["homography_matrix"] = json.loads(d["matrix_json"])
                return d
            finally:
                cur.close()

    def delete_homography_calibration(self, camera_id: str) -> bool:
        """Delete homography calibration profile for a camera."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("DELETE FROM homography_calibrations WHERE camera_id = ?", (camera_id,))
                self._conn.commit()
                return cur.rowcount > 0
            finally:
                cur.close()


def list_homography_camera_ids(db: Any) -> List[str]:
    """Return sorted distinct camera IDs that have stored homography calibrations."""
    lock = getattr(db, "_lock", None)
    conn = getattr(db, "_conn", None)
    if conn is None:
        return []
    if lock is None:
        cur = conn.cursor()
        try:
            cur.execute("SELECT DISTINCT camera_id FROM homography_calibrations ORDER BY camera_id ASC")
            return [str(r[0]) for r in cur.fetchall() if r and r[0]]
        finally:
            cur.close()
    with lock:
        cur = conn.cursor()
        try:
            cur.execute("SELECT DISTINCT camera_id FROM homography_calibrations ORDER BY camera_id ASC")
            return [str(r[0]) for r in cur.fetchall() if r and r[0]]
        finally:
            cur.close()

