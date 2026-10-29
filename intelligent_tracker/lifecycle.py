#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker — Process & Stream Lifecycle Manager.

Orchestrates live process/thread telemetry, hibernation tracking,
stale subscriber eviction, and historical resource metrics persistence in SQLite.
Exposes control interfaces for superuser admin APIs and terminal tooling.
"""

import os
import sys
import time
import logging
import threading
from typing import Dict, List, Optional, Any

import psutil

from intelligent_tracker.database import TrackerDB

logger = logging.getLogger("intelligent_tracker.lifecycle")


class StreamLifecycleManager:
    """
    Central orchestrator for stream lifecycles, background threads,
    resource telemetry logging, and administrative eviction controls.
    """

    def __init__(
        self,
        db: Optional[TrackerDB] = None,
        camera_pool: Optional[Any] = None,
        sample_interval: float = 15.0,
        autostart_sampler: bool = True,
    ):
        self.db = db
        self.camera_pool = camera_pool
        self.sample_interval = float(sample_interval)
        self._lock = threading.RLock()
        self._running = False
        self._sampler_thread: Optional[threading.Thread] = None

        if autostart_sampler:
            self.start_sampler()

    def set_camera_pool(self, camera_pool: Any):
        """Bind or update the CameraPool instance."""
        with self._lock:
            self.camera_pool = camera_pool

    def start_sampler(self):
        """Start the background telemetry sampling daemon thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._sampler_thread = threading.Thread(
                target=self._sampler_worker,
                name="LifecycleTelemetrySampler",
                daemon=True,
            )
            self._sampler_thread.start()
            logger.info("LifecycleTelemetrySampler daemon started (interval=%.1fs)", self.sample_interval)

    def stop_sampler(self):
        """Stop the background telemetry sampling daemon cleanly."""
        with self._lock:
            self._running = False
            if self._sampler_thread and self._sampler_thread.is_alive():
                self._sampler_thread.join(timeout=2.0)
                self._sampler_thread = None

    def _sampler_worker(self):
        """Periodic background thread that samples CPU, RAM, and stream states into SQLite."""
        while self._running:
            try:
                self.record_sample()
            except Exception as e:
                logger.debug("Telemetry sample error: %s", e)

            # Sleep in small increments for responsive shutdown
            slept = 0.0
            while self._running and slept < self.sample_interval:
                time.sleep(0.5)
                slept += 0.5

    def record_sample(self) -> Optional[int]:
        """Sample current hardware and stream pool status and persist to TrackerDB."""
        if not self.db:
            return None

        try:
            process = psutil.Process(os.getpid())
            mem_mb = process.memory_info().rss / (1024 * 1024)
            cpu_pct = process.cpu_percent(interval=None)
        except Exception:
            mem_mb = 0.0
            cpu_pct = 0.0

        active_streams = 0
        hibernating_streams = 0
        total_subscribers = 0

        with self._lock:
            if self.camera_pool and hasattr(self.camera_pool, "streams"):
                for sm in list(self.camera_pool.streams.values()):
                    subs = getattr(sm, "subscriber_count", 0)
                    total_subscribers += subs
                    if sm.is_hibernating or subs == 0:
                        hibernating_streams += 1
                    else:
                        active_streams += 1

        return self.db.record_resource_metric(
            cpu_percent=cpu_pct,
            memory_mb=mem_mb,
            active_streams=active_streams,
            hibernating_streams=hibernating_streams,
            total_subscribers=total_subscribers,
        )

    def log_event(
        self,
        camera_id: str,
        event_type: str,
        old_state: Optional[str] = None,
        new_state: Optional[str] = None,
        subscriber_count: int = 0,
        details: Optional[str] = None,
    ) -> Optional[int]:
        """Record an explicit stream lifecycle transition in SQLite audit trail."""
        if not self.db:
            return None
        return self.db.record_lifecycle_event(
            camera_id=camera_id,
            event_type=event_type,
            old_state=old_state,
            new_state=new_state,
            subscriber_count=subscriber_count,
            details=details,
        )

    def evict_subscribers(self, camera_id: str, reason: str = "Admin manual eviction") -> Dict[str, Any]:
        """
        Force-evicts all active subscriber leases for a camera channel,
        forcing immediate deep hibernation to protect server resources.
        """
        with self._lock:
            if not self.camera_pool or camera_id not in self.camera_pool.streams:
                return {"success": False, "error": f"Camera stream '{camera_id}' not found"}

            sm = self.camera_pool.streams[camera_id]
            old_count = getattr(sm, "subscriber_count", 0)

            # Evict all leases
            with sm._subscriber_lock:
                sm._subscribers.clear()
                sm._ws_subscribers.clear()

            # Signal hibernation immediately
            if hasattr(sm, "_is_hibernating"):
                sm._is_hibernating = True
            if sm.video_source and hasattr(sm.video_source, "pause"):
                sm.video_source.pause()

            self.log_event(
                camera_id=camera_id,
                event_type="EVICT",
                old_state="ONLINE" if old_count > 0 else "HIBERNATING",
                new_state="HIBERNATING",
                subscriber_count=0,
                details=f"{reason} (evicted {old_count} subscribers)",
            )

            return {
                "success": True,
                "camera_id": camera_id,
                "evicted_subscribers": old_count,
                "new_state": "HIBERNATING",
            }

    def hibernate_all_idle(self) -> Dict[str, Any]:
        """
        Audits all registered camera streams and forces any idle channel
        (zero active subscribers) into verified deep hibernation.
        """
        hibernated = []
        with self._lock:
            if not self.camera_pool:
                return {"success": False, "hibernated_count": 0}

            for cid, sm in list(self.camera_pool.streams.items()):
                if sm.subscriber_count == 0:
                    sm._is_hibernating = True
                    if sm.video_source and hasattr(sm.video_source, "pause"):
                        sm.video_source.pause()
                    hibernated.append(cid)
                    self.log_event(
                        camera_id=cid,
                        event_type="HIBERNATE",
                        old_state="ONLINE",
                        new_state="HIBERNATING",
                        subscriber_count=0,
                        details="Auto-hibernated idle channel by lifecycle sweep",
                    )

        return {
            "success": True,
            "hibernated_count": len(hibernated),
            "channels": hibernated,
        }

    def get_diagnostics(self) -> Dict[str, Any]:
        """Compile a comprehensive live diagnostics dictionary of threads and stream states."""
        try:
            proc = psutil.Process(os.getpid())
            mem_info = proc.memory_info()
            cpu_pct = proc.cpu_percent(interval=None)
            thread_count = proc.num_threads()
        except Exception:
            mem_info = None
            cpu_pct = 0.0
            thread_count = threading.active_count()

        streams_data = []
        with self._lock:
            if self.camera_pool:
                for cid, sm in self.camera_pool.streams.items():
                    telemetry = sm.get_latest_telemetry() if hasattr(sm, "get_latest_telemetry") else {}
                    subs = getattr(sm, "subscriber_count", 0)
                    is_hib = getattr(sm, "is_hibernating", False) or subs == 0
                    streams_data.append({
                        "camera_id": cid,
                        "name": getattr(sm, "name", cid),
                        "state": "HIBERNATING" if is_hib else "ACTIVE",
                        "fps": round(telemetry.get("fps", 0.0), 1),
                        "subscribers": subs,
                        "is_running": sm.is_running,
                        "video_paused": getattr(sm.video_source, "is_paused", False) if sm.video_source else False,
                    })

        return {
            "pid": os.getpid(),
            "cpu_percent": cpu_pct,
            "memory_mb": round(mem_info.rss / (1024 * 1024), 2) if mem_info else 0.0,
            "thread_count": thread_count,
            "total_streams": len(streams_data),
            "active_streams": sum(1 for s in streams_data if s["state"] == "ACTIVE"),
            "hibernating_streams": sum(1 for s in streams_data if s["state"] == "HIBERNATING"),
            "streams": streams_data,
        }

    def get_metrics_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve historical system telemetry samples."""
        if not self.db:
            return []
        return self.db.get_resource_metrics(limit=limit)

    def get_lifecycle_history(self, camera_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve historical stream lifecycle events."""
        if not self.db:
            return []
        return self.db.get_lifecycle_events(camera_id=camera_id, limit=limit)

