#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Stream Pool Coordinator & Query Mixin.

Owns StreamManager lifecycle orchestration across multi-camera channels,
WorldGraph propagation, lock-free parallel teardown, and telemetry queries.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import threading
from typing import Any

from dashboard.services.camera_diagnostics import CameraHealthManager
from dashboard.stream_manager import StreamManager
from intelligent_tracker.camera_resolver import CameraPathResolver
from intelligent_tracker.world import WorldGraph

logger = logging.getLogger("intelligent_tracker.stream_pool_coordinator")


def _build_custom_cfg(cfg: dict[str, Any]) -> dict[str, Any] | None:
    """Extract detector and tracker override sections from a camera config entry."""
    custom_cfg: dict[str, Any] = {}
    det_dict: dict[str, Any] = {}
    if cfg.get("detector"):
        det_dict["model"] = cfg["detector"]
    if cfg.get("confidence") is not None:
        det_dict["confidence"] = cfg["confidence"]
    if cfg.get("classes") is not None:
        det_dict["classes"] = cfg["classes"]
    if det_dict:
        custom_cfg["detector"] = det_dict
    if cfg.get("tracker"):
        custom_cfg["tracker"] = {"type": cfg["tracker"]}
    return custom_cfg or None


def _stagger_if_hardware(source: Any) -> None:
    """Stagger physical USB/DirectShow starts to prevent MSMF lockups on Windows."""
    if isinstance(source, int) or (isinstance(source, str) and str(source).isdigit()):
        threading.Event().wait(0.15)


def _stop_manager_safely(mgr: Any, context: str) -> None:
    """Stop a StreamManager outside locks without propagating teardown exceptions."""
    try:
        mgr.stop()
    except Exception as exc:
        logger.debug("Error stopping manager (%s): %s", context, exc)


def _start_stream_if_ready(mgr: StreamManager | None, camera_id: str, name: str, raw_source: Any) -> None:
    """Start a registered StreamManager outside locks if source resolution succeeded."""
    if not mgr or mgr.is_running or getattr(mgr, "_source_error", False):
        return
    resolved = getattr(mgr, "_resolved_source", raw_source)
    _stagger_if_hardware(resolved)
    mgr.start()
    logger.info("Started camera stream [%s] '%s' (%s -> %s)", camera_id, name, raw_source, resolved)


class StreamPoolCoordinator:
    """Thread-safe lifecycle coordinator for active StreamManager instances."""

    def __init__(
        self,
        db_path: str,
        base_config_path: str,
        world_graph: WorldGraph,
        lock: Any = None,
    ) -> None:
        self.db_path = db_path
        self.base_config_path = base_config_path
        self.world_graph = world_graph
        self._lock = lock or threading.RLock()
        self.streams: dict[str, StreamManager] = {}

    def create_and_register_stream(
        self,
        camera_id: str,
        cfg: dict[str, Any],
        start: bool = True,
    ) -> StreamManager:
        """Instantiate and register a StreamManager for ``camera_id``."""
        raw_source = cfg.get("source", "synthetic")
        device_name = cfg.get("device_name") or (cfg.get("details") or {}).get("device_name")
        name = cfg.get("name", f"Camera {camera_id.upper()}")
        resolved_source, meta = CameraPathResolver.resolve_camera_source(raw_source, device_name=device_name)

        mgr = StreamManager(
            config_path=self.base_config_path,
            db_path=self.db_path,
            camera_id=camera_id,
            name=name,
            source_override=resolved_source,
            custom_cfg=_build_custom_cfg(cfg),
            world_graph=self.world_graph,
        )
        mgr._resolved_source = resolved_source
        mgr._source_error = meta.get("status") == "error"
        with self._lock:
            self.streams[camera_id] = mgr

        if mgr._source_error:
            CameraHealthManager().set_error(
                camera_id,
                f"Source not found: {raw_source}",
                error_code=meta.get("error_code", "FILE_NOT_FOUND"),
                attempted_paths=meta.get("attempted_paths"),
            )
            logger.warning("Camera stream [%s] '%s' registered offline: source not found (%s)", camera_id, name, raw_source)
        elif start:
            _start_stream_if_ready(mgr, camera_id, name, raw_source)
        return mgr

    def restore_enabled_streams(self, camera_configs: dict[str, dict[str, Any]], autostart: bool = True) -> None:
        """Instantiate streams for all enabled camera entries."""
        to_start: list[tuple[StreamManager, str, str, Any]] = []
        with self._lock:
            for cam_id, cfg in list(camera_configs.items()):
                if cfg.get("enabled", True):
                    mgr = self.create_and_register_stream(cam_id, cfg, start=False)
                    to_start.append((mgr, cam_id, cfg.get("name", f"Camera {cam_id.upper()}"), cfg.get("source", "synthetic")))
        if autostart:
            for mgr, cam_id, name, raw_source in to_start:
                _start_stream_if_ready(mgr, cam_id, name, raw_source)

    def register_camera_stream(
        self,
        camera_id: str,
        cam_entry: dict[str, Any],
        enabled: bool = True,
        autostart: bool = True,
    ) -> StreamManager:
        """Replace any existing stream for ``camera_id`` and start if enabled."""
        with self._lock:
            old_mgr = self.streams.pop(camera_id, None)
            if enabled:
                mgr = self.create_and_register_stream(camera_id, cam_entry, start=False)
            else:
                mgr = StreamManager(
                    config_path=self.base_config_path,
                    db_path=self.db_path,
                    camera_id=camera_id,
                    name=cam_entry.get("name", f"Camera {camera_id.upper()}"),
                    source_override=cam_entry.get("source", "synthetic"),
                    world_graph=self.world_graph,
                )
                self.streams[camera_id] = mgr

        if old_mgr:
            _stop_manager_safely(old_mgr, "add_camera")

        if enabled and autostart:
            _start_stream_if_ready(mgr, camera_id, cam_entry.get("name", f"Camera {camera_id.upper()}"), cam_entry.get("source", ""))
        return mgr

    def restart_stream(self, camera_id: str, cfg: dict[str, Any]) -> None:
        """Stop any existing stream outside the lock and start a fresh one if enabled."""
        with self._lock:
            old_mgr = self.streams.pop(camera_id, None)
            new_mgr = self.create_and_register_stream(camera_id, cfg, start=False) if cfg.get("enabled", True) else None

        if old_mgr:
            _stop_manager_safely(old_mgr, "update_camera")

        if cfg.get("enabled", True) and new_mgr:
            _start_stream_if_ready(new_mgr, camera_id, cfg.get("name", f"Camera {camera_id.upper()}"), cfg.get("source", ""))

    def remove_stream(self, camera_id: str) -> None:
        """Pop and stop a camera stream outside the lock, then prune WorldGraph."""
        with self._lock:
            mgr = self.streams.pop(camera_id, None)
        if mgr:
            _stop_manager_safely(mgr, "remove_camera")
        self.world_graph.remove_camera(camera_id)

    def get_stream(self, camera_id: str | None = None) -> StreamManager | None:
        """Resolve a StreamManager by ID or return the primary active fallback."""
        with self._lock:
            if not camera_id or camera_id in ("default", "primary"):
                if "cam_01" in self.streams and self.streams["cam_01"].is_running:
                    return self.streams["cam_01"]
                for mgr in self.streams.values():
                    if mgr.is_running:
                        return mgr
                return next(iter(self.streams.values()), None)
            return self.streams.get(camera_id)

    def start_all(self, camera_configs: dict[str, dict[str, Any]]) -> None:
        """Start all enabled camera streams outside ``self._lock``."""
        to_start: list[tuple[StreamManager, str, str, Any]] = []
        with self._lock:
            for cam_id, cfg in camera_configs.items():
                if cfg.get("enabled", True):
                    mgr = self.streams.get(cam_id) or self.create_and_register_stream(cam_id, cfg, start=False)
                    to_start.append((mgr, cam_id, cfg.get("name", f"Camera {cam_id.upper()}"), cfg.get("source", "synthetic")))
        for mgr, cam_id, name, raw_source in to_start:
            _start_stream_if_ready(mgr, cam_id, name, raw_source)

    def signal_stop_all(self) -> None:
        """Immediately broadcast stop signal to all active streams without blocking."""
        with self._lock:
            for mgr in self.streams.values():
                if hasattr(mgr, "signal_stop"):
                    try:
                        mgr.signal_stop()
                    except Exception as exc:
                        logger.debug("Error signaling stop on manager: %s", exc)

    def stop_all(self, parallel: bool = True) -> None:
        """Stop all active camera streams concurrently outside ``self._lock``."""
        with self._lock:
            self.signal_stop_all()
            mgrs = list(self.streams.values())
            self.streams.clear()

        if parallel and mgrs:
            with ThreadPoolExecutor(max_workers=min(8, len(mgrs))) as executor:
                futures = [executor.submit(_stop_manager_safely, m, "stop_all") for m in mgrs]
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception:
                        pass
        else:
            for mgr in mgrs:
                _stop_manager_safely(mgr, "stop_all")
