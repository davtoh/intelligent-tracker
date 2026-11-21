#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Stream Pool Coordinator & Query Mixin.

Owns StreamManager lifecycle orchestration across multi-camera channels,
WorldGraph propagation, lock-free parallel teardown, and telemetry queries.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
import logging
import threading
from typing import Any

from dashboard.services.camera_source_bootstrap import bootstrap_camera_stream
from dashboard.stream_manager import StreamManager
from intelligent_tracker.camera_resolver import CameraPathResolver
from intelligent_tracker.world import WorldGraph

logger = logging.getLogger("intelligent_tracker.stream_pool_coordinator")


def _build_custom_cfg(cfg: dict[str, Any]) -> dict[str, Any] | None:
    """Extract detector and tracker override sections from a camera config entry."""
    custom_cfg: dict[str, Any] = {}
    det_dict = {k: cfg[src] for src, k in (("detector", "model"), ("confidence", "confidence"), ("classes", "classes")) if cfg.get(src) is not None and (src != "detector" or cfg.get(src))}
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


def _sync_manager_hibernation(mgr: Any, should_hib: bool) -> None:
    """Apply immediate pause/resume hibernation state to a StreamManager."""
    vs, telemetry = getattr(mgr, "video_source", None), getattr(mgr, "_latest_telemetry", None)
    lock = getattr(mgr, "_lock", None) or nullcontext()
    if not should_hib and getattr(mgr, "_is_hibernating", False):
        mgr._is_hibernating = False
        if vs is not None and hasattr(vs, "resume"):
            vs.resume()
        if telemetry:
            with lock:
                telemetry["status"] = "online"
    elif should_hib and not getattr(mgr, "_is_hibernating", False) and getattr(mgr, "is_running", False):
        mgr._is_hibernating = True
        if vs is not None and hasattr(vs, "pause"):
            vs.pause()
        if telemetry:
            with lock:
                telemetry.update({"fps": 0.0, "status": "hibernating"})


def _seed_initial_focused_camera(pms: Any, camera_configs: dict[str, dict[str, Any]]) -> None:
    """Seed focused_camera_id from the first enabled camera on cold boot when unset."""
    if pms is not None and pms.focused_camera_id is None:
        first_enabled = next((cid for cid, cfg in camera_configs.items() if cfg.get("enabled", True)), None)
        if first_enabled:
            pms.update(focused_camera_id=first_enabled)


def _start_enabled_streams(coord: Any, camera_configs: dict[str, dict[str, Any]], autostart: bool, reuse_existing: bool) -> None:
    """Register and optionally start all enabled streams outside the coordinator lock."""
    with coord._lock:
        to_start = [
            ((coord.streams.get(cid) if reuse_existing else None) or coord.create_and_register_stream(cid, cfg, start=False),
             cid, cfg.get("name", f"Camera {cid.upper()}"), cfg.get("source", "synthetic"))
            for cid, cfg in list(camera_configs.items()) if cfg.get("enabled", True)
        ]
    if autostart:
        _seed_initial_focused_camera(coord.processing_mode_service, camera_configs)
        for mgr, cam_id, name, raw_source in to_start:
            _start_stream_if_ready(mgr, cam_id, name, raw_source)


class StreamPoolCoordinator:
    """Thread-safe lifecycle coordinator for active StreamManager instances."""

    def __init__(
        self, db_path: str, base_config_path: str, world_graph: WorldGraph,
        lock: Any = None, processing_mode_service: Any = None,
        event_bus: Any = None, confidence_engine: Any = None, event_fts_index: Any = None,
    ) -> None:
        self.db_path, self.base_config_path, self.world_graph = db_path, base_config_path, world_graph
        self.event_bus, self.confidence_engine, self.event_fts_index = event_bus, confidence_engine, event_fts_index
        self._lock = lock or threading.RLock()
        if processing_mode_service is None:
            from dashboard.services.processing_mode_service import get_processing_mode_service
            processing_mode_service = get_processing_mode_service()
        self.processing_mode_service = processing_mode_service
        self.streams: dict[str, StreamManager] = {}

    def create_and_register_stream(
        self, camera_id: str, cfg: dict[str, Any], start: bool = True,
    ) -> StreamManager | None:
        """Probe source readiness and safely instantiate/register a StreamManager."""
        return bootstrap_camera_stream(
            self,
            camera_id,
            cfg,
            start=start,
            resolver=CameraPathResolver,
            stream_manager_cls=StreamManager,
            custom_cfg_builder=_build_custom_cfg,
            start_stream_fn=_start_stream_if_ready,
        )

    def restore_enabled_streams(self, camera_configs: dict[str, dict[str, Any]], autostart: bool = True) -> None:
        """Instantiate streams for all enabled camera entries."""
        _start_enabled_streams(self, camera_configs, autostart=autostart, reuse_existing=False)

    def register_camera_stream(self, camera_id: str, cam_entry: dict[str, Any], enabled: bool = True, autostart: bool = True) -> StreamManager | None:
        """Replace any existing stream for ``camera_id`` and start if enabled."""
        with self._lock:
            old_mgr = self.streams.pop(camera_id, None)
            if enabled:
                mgr = self.create_and_register_stream(camera_id, cam_entry, start=False)
            else:
                mgr = StreamManager(
                    config_path=self.base_config_path, db_path=self.db_path, camera_id=camera_id,
                    name=cam_entry.get("name", f"Camera {camera_id.upper()}"), source_override=cam_entry.get("source", "synthetic"),
                    world_graph=self.world_graph, processing_mode_service=self.processing_mode_service,
                    event_bus=self.event_bus, confidence_engine=self.confidence_engine,
                    event_fts_index=self.event_fts_index,
                )
                mgr._in_camera_pool = True
                self.streams[camera_id] = mgr
        if old_mgr:
            _stop_manager_safely(old_mgr, "add_camera")
        if enabled and autostart and mgr is not None:
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
                focused = getattr(self.processing_mode_service, "focused_camera_id", None)
                if focused and focused in self.streams and self.streams[focused].is_running:
                    return self.streams[focused]
                return next((m for m in self.streams.values() if m.is_running), next(iter(self.streams.values()), None))
            return self.streams.get(camera_id)

    def start_all(self, camera_configs: dict[str, dict[str, Any]]) -> None:
        """Start all enabled camera streams outside ``self._lock``."""
        _start_enabled_streams(self, camera_configs, autostart=True, reuse_existing=True)

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
                for future in as_completed([executor.submit(_stop_manager_safely, m, "stop_all") for m in mgrs]):
                    future.result()
        else:
            for mgr in mgrs:
                _stop_manager_safely(mgr, "stop_all")

    def sync_processing_mode(self, service: Any = None) -> None:
        """Synchronize all registered streams' hibernation state with ProcessingModeService."""
        svc = service or self.processing_mode_service
        with self._lock:
            items = list(self.streams.items())
        for cam_id, mgr in items:
            mgr._processing_mode_service = svc
            mgr._in_camera_pool = True
            should_hib = svc.should_hibernate_camera(
                cam_id, subscriber_count=int(getattr(mgr, "subscriber_count", 0)),
                is_recording=bool(getattr(mgr, "is_recording", False)), in_camera_pool=True,
                is_armed=bool(getattr(mgr, "is_armed", False)),
            )
            _sync_manager_hibernation(mgr, should_hib)
