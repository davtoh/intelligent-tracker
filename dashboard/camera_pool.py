#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Dynamic Multi-Stream Orchestrator (CameraPool).

Orchestrates concurrent StreamManager instances across multiple camera channels.
Enables hot-add, edit, toggle, and removal of camera feeds dynamically
at runtime without requiring server restarts.
Handles automatic boot restoration and state persistence via `configs/cameras.json`.
"""

import os
import sys
import time
import json
import logging
import threading
from typing import Dict, List, Optional, Any, Tuple

from dashboard.stream_manager import StreamManager

logger = logging.getLogger("intelligent_tracker.camera_pool")


class CameraPool:
    """
    Thread-safe multi-camera stream pool manager.
    Coordinates active StreamManager instances, camera configurations,
    hot-reloading, and persistent state storage.
    """

    def __init__(
        self,
        config_file: str = "configs/cameras.json",
        db_path: str = "data/tracker.db",
        base_config_path: str = "configs/alert_demo.yaml",
        autostart: bool = True,
    ):
        self.config_file = config_file
        self.db_path = db_path
        self.base_config_path = base_config_path
        self._autostart = autostart

        self._lock = threading.RLock()
        self.camera_configs: Dict[str, Dict[str, Any]] = {}
        self.streams: Dict[str, StreamManager] = {}

        # Auto-restore configured cameras
        self.load_cameras()

    @property
    def primary_stream(self) -> Optional[StreamManager]:
        """
        Returns the primary or first active StreamManager.
        Maintains 100% backward compatibility for single-camera endpoints.
        """
        with self._lock:
            if "cam_01" in self.streams and self.streams["cam_01"].is_running:
                return self.streams["cam_01"]
            for mgr in self.streams.values():
                if mgr.is_running:
                    return mgr
            # Return any existing stream manager even if stopped
            if self.streams:
                return next(iter(self.streams.values()))
            return None

    def load_cameras(self):
        """
        Loads saved camera configurations from `configs/cameras.json`.
        If missing or empty, seeds default primary camera configuration.
        """
        with self._lock:
            configs_loaded = False
            if os.path.exists(self.config_file):
                try:
                    with open(self.config_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            self.camera_configs = {c["id"]: c for c in data if "id" in c}
                            configs_loaded = True
                        elif isinstance(data, dict):
                            self.camera_configs = data
                            configs_loaded = True
                except Exception as e:
                    logger.warning("Failed to load %s: %s", self.config_file, e)

            if not configs_loaded or not self.camera_configs:
                # Seed default primary camera
                default_cam = {
                    "id": "cam_01",
                    "name": "Main Entrance (Synthetic)",
                    "source": "synthetic",
                    "type": "synthetic",
                    "enabled": True,
                    "detector": "mock",
                    "tracker": "centroid",
                }
                self.camera_configs = {"cam_01": default_cam}
                self.save_cameras()

            # Instantiate StreamManagers for enabled cameras
            for cam_id, cfg in list(self.camera_configs.items()):
                if cfg.get("enabled", True):
                    self._create_and_register_stream(cam_id, cfg, start=self._autostart)

    def save_cameras(self):
        """Persists current camera configurations to JSON file."""
        with self._lock:
            os.makedirs(os.path.dirname(self.config_file) or ".", exist_ok=True)
            try:
                with open(self.config_file, "w", encoding="utf-8") as f:
                    json.dump(list(self.camera_configs.values()), f, indent=2)
            except Exception as e:
                logger.error("Failed to save camera configuration to %s: %s", self.config_file, e)

    def _create_and_register_stream(
        self,
        camera_id: str,
        cfg: Dict[str, Any],
        start: bool = True,
    ) -> StreamManager:
        """Internal helper to instantiate and start a StreamManager."""
        source = cfg.get("source", "synthetic")
        name = cfg.get("name", f"Camera {camera_id.upper()}")

        custom_cfg = {}
        if cfg.get("detector"):
            custom_cfg["detector"] = {"model": cfg["detector"]}
        if cfg.get("tracker"):
            custom_cfg["tracker"] = {"type": cfg["tracker"]}

        mgr = StreamManager(
            config_path=self.base_config_path,
            db_path=self.db_path,
            camera_id=camera_id,
            name=name,
            source_override=source,
            custom_cfg=custom_cfg if custom_cfg else None,
        )

        self.streams[camera_id] = mgr
        if start:
            mgr.start()
            logger.info("Started camera stream [%s] '%s' (%s)", camera_id, name, source)
        return mgr

    def add_camera(
        self,
        camera_id: str,
        name: str,
        source: Any,
        cam_type: str = "rtsp",
        detector: Optional[str] = None,
        tracker: Optional[str] = None,
        enabled: bool = True,
        autostart: bool = True,
        details: Optional[Dict[str, Any]] = None,
    ) -> StreamManager:
        """
        Hot-adds a new camera feed dynamically without server restarts.

        Args:
            camera_id: Unique camera channel identifier (e.g. 'cam_02').
            name: Friendly human-readable label.
            source: Source string (RTSP URL, video file path, or USB index).
            cam_type: 'rtsp', 'usb', 'video_file', 'synthetic'.
            detector: Model detector override ('yolov8', 'mock', etc.).
            tracker: Tracker algorithm override ('sort', 'centroid').
            enabled: Whether stream is active immediately.
            autostart: Whether to start worker thread immediately.
            details: Optional extra metadata (ip, port, vendor, etc.).

        Returns:
            The created StreamManager instance.
        """
        with self._lock:
            # If camera already exists, remove/stop it first
            if camera_id in self.streams:
                self.remove_camera(camera_id)

            cam_entry = {
                "id": camera_id,
                "name": name,
                "source": source,
                "type": cam_type,
                "enabled": enabled,
                "detector": detector or "mock",
                "tracker": tracker or "centroid",
                "details": details or {},
                "created_at": time.time(),
            }

            self.camera_configs[camera_id] = cam_entry
            self.save_cameras()

            if enabled:
                mgr = self._create_and_register_stream(camera_id, cam_entry, start=autostart)
            else:
                mgr = StreamManager(
                    config_path=self.base_config_path,
                    db_path=self.db_path,
                    camera_id=camera_id,
                    name=name,
                    source_override=source,
                )
                self.streams[camera_id] = mgr

            return mgr

    def update_camera(
        self,
        camera_id: str,
        name: Optional[str] = None,
        source: Optional[Any] = None,
        cam_type: Optional[str] = None,
        enabled: Optional[bool] = None,
        detector: Optional[str] = None,
        tracker: Optional[str] = None,
    ) -> bool:
        """
        Updates an existing camera configuration dynamically.
        Restarts the background worker if source or enabled status changed.
        """
        with self._lock:
            if camera_id not in self.camera_configs:
                return False

            cfg = self.camera_configs[camera_id]
            source_changed = (source is not None and source != cfg.get("source"))
            enabled_changed = (enabled is not None and enabled != cfg.get("enabled"))

            if name is not None:
                cfg["name"] = name
            if source is not None:
                cfg["source"] = source
            if cam_type is not None:
                cfg["type"] = cam_type
            if enabled is not None:
                cfg["enabled"] = enabled
            if detector is not None:
                cfg["detector"] = detector
            if tracker is not None:
                cfg["tracker"] = tracker

            self.save_cameras()

            # Hot reload stream if necessary
            if source_changed or enabled_changed:
                if camera_id in self.streams:
                    old_mgr = self.streams.pop(camera_id)
                    old_mgr.stop()

                if cfg.get("enabled", True):
                    self._create_and_register_stream(camera_id, cfg, start=True)

            return True

    def remove_camera(self, camera_id: str) -> bool:
        """
        Stops and removes a camera stream dynamically from the pool.
        """
        with self._lock:
            mgr = self.streams.pop(camera_id, None)
            if mgr:
                mgr.stop()

            removed_cfg = self.camera_configs.pop(camera_id, None)
            self.save_cameras()
            logger.info("Removed camera [%s] from pool", camera_id)
            return removed_cfg is not None

    def toggle_camera(self, camera_id: str, enabled: Optional[bool] = None) -> bool:
        """Enables or pauses a camera stream in the pool."""
        with self._lock:
            if camera_id not in self.camera_configs:
                return False

            current_enabled = self.camera_configs[camera_id].get("enabled", True)
            new_state = (not current_enabled) if enabled is None else bool(enabled)
            self.update_camera(camera_id, enabled=new_state)
            return new_state

    def get_stream(self, camera_id: Optional[str] = None) -> Optional[StreamManager]:
        """
        Retrieves StreamManager for given camera ID.
        If camera_id is None, empty, or 'default', returns primary_stream.
        """
        with self._lock:
            if not camera_id or camera_id in ("default", "primary"):
                return self.primary_stream
            return self.streams.get(camera_id)

    def get_latest_frame_jpeg(self, camera_id: Optional[str] = None) -> Optional[bytes]:
        """Gets latest encoded JPEG frame bytes for camera."""
        mgr = self.get_stream(camera_id)
        if mgr:
            return mgr.get_latest_frame_jpeg()
        return None

    def list_cameras(self) -> List[Dict[str, Any]]:
        """
        Returns real-time status and telemetry for all configured cameras.
        """
        result = []
        with self._lock:
            for cam_id, cfg in self.camera_configs.items():
                mgr = self.streams.get(cam_id)
                telemetry = mgr.get_latest_telemetry() if mgr else {}
                is_running = mgr.is_running if mgr else False

                res_str = "640x480"
                is_synth = False
                if mgr and mgr.video_source:
                    res_str = f"{mgr.video_source.width}x{mgr.video_source.height}"
                    is_synth = mgr.video_source.is_synthetic

                result.append({
                    "id": cam_id,
                    "name": cfg.get("name", f"Camera {cam_id}"),
                    "source": str(cfg.get("source", "synthetic")),
                    "type": cfg.get("type", "synthetic" if is_synth else "rtsp"),
                    "enabled": cfg.get("enabled", True),
                    "status": "online" if is_running else ("paused" if not cfg.get("enabled") else "offline"),
                    "fps": round(telemetry.get("fps", 0.0), 1),
                    "resolution": res_str,
                    "active_tracks_count": len(telemetry.get("active_tracks", [])),
                    "source_type": "synthetic" if is_synth else "physical",
                })
        return result

    def start_all(self):
        """Starts all enabled camera streams."""
        with self._lock:
            for cam_id, cfg in self.camera_configs.items():
                if cfg.get("enabled", True):
                    mgr = self.streams.get(cam_id)
                    if not mgr:
                        self._create_and_register_stream(cam_id, cfg, start=True)
                    elif not mgr.is_running:
                        mgr.start()

    def stop_all(self):
        """Stops all active camera streams."""
        with self._lock:
            for mgr in self.streams.values():
                try:
                    mgr.stop()
                except Exception as e:
                    logger.debug("Error stopping manager: %s", e)
            self.streams.clear()
