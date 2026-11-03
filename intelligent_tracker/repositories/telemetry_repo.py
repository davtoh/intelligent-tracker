"""
Hardware Resource and Stream Lifecycle Telemetry Repository Mixin.

Manages recording and chronological querying of system telemetry metrics
(CPU %, RAM MB, active stream counts) and stream state transitions.
"""

import time
from typing import Optional, Dict, Any, List


class TelemetryMixin:
    """Provides system resource telemetry and stream lifecycle event persistence."""

    def record_resource_metric(
        self,
        cpu_percent: float,
        memory_mb: float,
        active_streams: int,
        hibernating_streams: int,
        total_subscribers: int,
        timestamp: Optional[float] = None,
    ) -> int:
        """Record a periodic system resource telemetry sample."""
        ts = timestamp if timestamp is not None else time.time()
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO system_resource_metrics (
                        timestamp, cpu_percent, memory_mb, active_streams, hibernating_streams, total_subscribers
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (ts, float(cpu_percent), float(memory_mb), int(active_streams), int(hibernating_streams), int(total_subscribers)),
                )
                self._conn.commit()
                return cur.lastrowid
            finally:
                cur.close()

    def get_resource_metrics(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve recent system resource telemetry samples in chronological order."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    SELECT * FROM (
                        SELECT * FROM system_resource_metrics ORDER BY timestamp DESC LIMIT ?
                    ) ORDER BY timestamp ASC
                    """,
                    (int(limit),),
                )
                return [dict(r) for r in cur.fetchall()]
            finally:
                cur.close()

    def record_lifecycle_event(
        self,
        camera_id: str,
        event_type: str,
        old_state: Optional[str] = None,
        new_state: Optional[str] = None,
        subscriber_count: int = 0,
        details: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> int:
        """Log a stream lifecycle transition (e.g. START, HIBERNATE, RESUME, EVICT, STOP)."""
        ts = timestamp if timestamp is not None else time.time()
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO stream_lifecycle_events (
                        timestamp, camera_id, event_type, old_state, new_state, subscriber_count, details
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (ts, str(camera_id), str(event_type).upper(), old_state, new_state, int(subscriber_count), details),
                )
                self._conn.commit()
                return cur.lastrowid
            finally:
                cur.close()

    def get_lifecycle_events(
        self,
        camera_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Retrieve historical stream lifecycle events."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                if camera_id:
                    cur.execute(
                        """
                        SELECT * FROM stream_lifecycle_events
                        WHERE camera_id = ?
                        ORDER BY timestamp DESC LIMIT ?
                        """,
                        (str(camera_id), int(limit)),
                    )
                else:
                    cur.execute(
                        """
                        SELECT * FROM stream_lifecycle_events
                        ORDER BY timestamp DESC LIMIT ?
                        """,
                        (int(limit),),
                    )
                return [dict(r) for r in cur.fetchall()]
            finally:
                cur.close()

