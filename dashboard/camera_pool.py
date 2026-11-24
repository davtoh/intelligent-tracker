#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Dynamic Multi-Stream Orchestrator (CameraPool).

Thin public facade coordinating CameraConfigStore, StreamPoolCoordinator,
and shared WorldGraph across multi-camera channels.
"""

import logging
import threading
from typing import Any

from dashboard.services.base_config_resolver import resolve_base_config_path
from dashboard.services.camera_config_store import CameraConfigStore
from dashboard.services.camera_pool_queries import (
    CameraPoolQueryMixin,
    CameraPoolStateMixin,
)
from dashboard.services.stream_pool_coordinator import StreamPoolCoordinator
from dashboard.stream_manager import StreamManager
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.events import EventBus
from intelligent_tracker.memory import ConfidenceEngine, EventFTSIndex
from intelligent_tracker.world import (
    GlobalCoordinateMapper,
    MultiCameraHandoffCoordinator,
    WorldGraph,
)

logger = logging.getLogger("intelligent_tracker.camera_pool")


class CameraPool(CameraPoolStateMixin, CameraPoolQueryMixin):
    """
    Thread-safe multi-camera stream pool facade.
    Delegates configuration persistence to CameraConfigStore and stream
    lifecycle transitions to StreamPoolCoordinator while preserving public contracts.
    """

    def __init__(
        self,
        config_file: str = "configs/cameras.json",
        db_path: str = "data/tracker.db",
        base_config_path: str | None = None,
        autostart: bool = True,
    ) -> None:
        resolved_base_config = resolve_base_config_path(base_config_path)
        self.config_file = config_file
        self.db_path = db_path
        self.base_config_path = resolved_base_config
        self._autostart = autostart

        self._lock = threading.RLock()
        self.event_bus = EventBus(capacity=500)
        self.event_bus.start()
        self.coordinate_mapper = GlobalCoordinateMapper()
        self.world_graph = WorldGraph(coordinate_mapper=self.coordinate_mapper, event_bus=self.event_bus)
        self.handoff_coordinator = MultiCameraHandoffCoordinator(
            self.world_graph,
            coordinate_mapper=self.coordinate_mapper,
        )
        self.world_graph.handoff_coordinator = self.handoff_coordinator
        self._db = TrackerDB(db_path) if db_path else None
        self._confidence_engine = ConfidenceEngine(db=self._db, event_bus=self.event_bus)
        self.event_fts_index = (
            EventFTSIndex(db=self._db, event_bus=self.event_bus, auto_attach=True) if self._db is not None else None
        )
        self._config_store = CameraConfigStore(config_file=config_file, lock=self._lock)
        self._coordinator = StreamPoolCoordinator(
            db_path=db_path,
            base_config_path=resolved_base_config,
            world_graph=self.world_graph,
            lock=self._lock,
            event_bus=self.event_bus,
            confidence_engine=self._confidence_engine,
            event_fts_index=self.event_fts_index,
        )

        # Auto-restore configured cameras
        self.load_cameras()

    def load_cameras(self) -> None:
        """Load saved camera configurations and instantiate enabled streams."""
        configs, seeded = self._config_store.load_cameras()
        if seeded:
            self.save_cameras()
        self._coordinator.restore_enabled_streams(configs, autostart=self._autostart)

    def save_cameras(self) -> None:
        """Persist current camera configurations to JSON file."""
        self._config_store.save_cameras()

    def add_camera(
        self,
        camera_id: str,
        name: str,
        source: Any,
        cam_type: str = "rtsp",
        detector: str | None = None,
        tracker: str | None = None,
        confidence: float | None = None,
        classes: list[str] | None = None,
        tracked_categories: list[str] | None = None,
        enabled: bool = True,
        autostart: bool = True,
        details: dict[str, Any] | None = None,
        device_name: str | None = None,
        armed: bool = False,
    ) -> StreamManager:
        """Hot-add a new camera feed dynamically without server restarts."""
        with self._lock:
            cam_entry = self._config_store.build_and_store_entry(
                camera_id=camera_id, name=name, source=source, cam_type=cam_type,
                detector=detector, tracker=tracker, confidence=confidence,
                classes=classes, tracked_categories=tracked_categories,
                enabled=enabled, details=details, device_name=device_name, armed=armed,
            )
        self.save_cameras()
        return self._coordinator.register_camera_stream(
            camera_id=camera_id,
            cam_entry=cam_entry,
            enabled=enabled,
            autostart=autostart,
        )

    def update_camera(
        self,
        camera_id: str,
        name: str | None = None,
        source: Any | None = None,
        cam_type: str | None = None,
        enabled: bool | None = None,
        detector: str | None = None,
        tracker: str | None = None,
        confidence: float | None = None,
        classes: list[str] | None = None,
        tracked_categories: list[str] | None = None,
        device_name: str | None = None,
        details: dict[str, Any] | None = None,
        armed: bool | None = None,
    ) -> bool:
        """Update an existing camera configuration and hot-reload its stream if needed."""
        with self._lock:
            found, needs_restart, cfg = self._config_store.update_entry(
                camera_id, name=name, source=source, cam_type=cam_type, enabled=enabled,
                detector=detector, tracker=tracker, confidence=confidence, classes=classes,
                tracked_categories=tracked_categories, device_name=device_name, details=details, armed=armed,
            )
            if not found or cfg is None:
                return False
        self.save_cameras()

        if armed is not None:
            with self._lock:
                stream_mgr = self._coordinator.streams.get(camera_id)
            if stream_mgr is not None:
                if hasattr(stream_mgr, "set_armed"):
                    stream_mgr.set_armed(bool(armed))
                else:
                    stream_mgr.is_armed = bool(armed)
                self._coordinator.sync_processing_mode()
        if needs_restart:
            self._coordinator.restart_stream(camera_id, cfg)
        return True

    def remove_camera(self, camera_id: str) -> bool:
        """Stop and remove a camera stream dynamically from the pool."""
        with self._lock:
            removed_cfg = self._config_store.remove_entry(camera_id)
        self.save_cameras()
        self._coordinator.remove_stream(camera_id)
        logger.info("Removed camera [%s] from pool", camera_id)
        return removed_cfg is not None

    def toggle_camera(self, camera_id: str, enabled: bool | None = None) -> bool:
        """Enable or pause a camera stream in the pool."""
        with self._lock:
            if camera_id not in self.camera_configs:
                return False
            current_enabled = self.camera_configs[camera_id].get("enabled", True)
            new_state = (not current_enabled) if enabled is None else bool(enabled)
        self.update_camera(camera_id, enabled=new_state)
        return new_state

    def start_all(self) -> None:
        """Start all enabled camera streams."""
        self._coordinator.start_all(self.camera_configs)

    def signal_stop_all(self) -> None:
        """Immediately broadcast stop signal to all active streams without blocking."""
        self._coordinator.signal_stop_all()

    def stop_all(self, parallel: bool = True) -> None:
        """Stop all active camera streams concurrently in parallel."""
        self._coordinator.stop_all(parallel=parallel)
        if getattr(self, "event_fts_index", None) is not None:
            self.event_fts_index.detach()
        if getattr(self, "event_bus", None) is not None:
            self.event_bus.stop(timeout=0.2)
        if getattr(self, "_db", None) is not None:
            self._db.close()
