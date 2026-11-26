"""
World Pose Repository Mixin for Persistent Camera World-Coordinate Poses.

Stores rigid 2D/BEV camera world poses (origin_x, origin_y, yaw_deg, scale,
fov_deg, range_m) in ``camera_world_poses`` for hydration into ``WorldGraph``.
"""

from typing import Any, Dict, List, Optional

_UPSERT_WORLD_POSE_SQL = """
INSERT INTO camera_world_poses (
    camera_id, origin_x, origin_y, yaw_deg, scale, fov_deg, range_m, updated_at
)
VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
ON CONFLICT(camera_id) DO UPDATE SET
    origin_x = excluded.origin_x,
    origin_y = excluded.origin_y,
    yaw_deg = excluded.yaw_deg,
    scale = excluded.scale,
    fov_deg = excluded.fov_deg,
    range_m = excluded.range_m,
    updated_at = CURRENT_TIMESTAMP
"""


class WorldPoseMixin:
    """Mixin for persistent camera world-pose CRUD in TrackerDB."""

    _conn: Any
    _lock: Any

    def save_world_pose(
        self,
        camera_id: str,
        origin_x: float = 0.0,
        origin_y: float = 0.0,
        yaw_deg: float = 0.0,
        scale: float = 1.0,
        fov_deg: float = 75.0,
        range_m: float = 12.0,
    ) -> int:
        """Upsert a camera's world-coordinate pose and return affected row count."""
        params = (
            camera_id, float(origin_x), float(origin_y), float(yaw_deg),
            float(scale), float(fov_deg), float(range_m),
        )
        with self._lock:
            if self._conn is None:
                raise RuntimeError("Database connection is closed")
            cur = self._conn.cursor()
            try:
                cur.execute(_UPSERT_WORLD_POSE_SQL, params)
                self._conn.commit()
                return int(cur.rowcount or 1)
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def get_world_pose(self, camera_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single camera's persisted world pose, or None if unset."""
        with self._lock:
            if self._conn is None:
                return None
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    SELECT camera_id, origin_x, origin_y, yaw_deg, scale,
                           fov_deg, range_m, updated_at
                    FROM camera_world_poses
                    WHERE camera_id = ?
                    """,
                    (camera_id,),
                )
                row = cur.fetchone()
                return dict(row) if row is not None else None
            finally:
                cur.close()

    def list_world_poses(self) -> List[Dict[str, Any]]:
        """List all persisted camera world poses ordered by camera_id."""
        with self._lock:
            if self._conn is None:
                return []
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    SELECT camera_id, origin_x, origin_y, yaw_deg, scale,
                           fov_deg, range_m, updated_at
                    FROM camera_world_poses
                    ORDER BY camera_id ASC
                    """
                )
                return [dict(row) for row in cur.fetchall()]
            finally:
                cur.close()

    def delete_world_pose(self, camera_id: str) -> bool:
        """Delete a persisted camera world pose by camera_id."""
        with self._lock:
            if self._conn is None:
                return False
            cur = self._conn.cursor()
            try:
                cur.execute("DELETE FROM camera_world_poses WHERE camera_id = ?", (camera_id,))
                self._conn.commit()
                return cur.rowcount > 0
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()
