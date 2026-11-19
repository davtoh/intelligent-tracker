#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Camera Source Pre-Flight Probe & Bootstrap Service.

Validates file existence and hardware availability before instantiating heavy
StreamManager/YOLOv8/TrackerDB pipelines, isolates initialization failures, and
provides on-demand camera retry orchestration.
"""

import logging
import traceback
from typing import Any, Callable

from dashboard.services.camera_diagnostics import CameraHealthManager
from dashboard.services.diagnostic_bridge import capture_runtime_exception
from intelligent_tracker.camera_device import CameraDeviceHandler
from intelligent_tracker.camera_resolver import CameraPathResolver

logger = logging.getLogger("intelligent_tracker.camera_source_bootstrap")


def probe_source_readiness(
    raw_source: Any,
    device_name: str | None = None,
    resolver: Any = CameraPathResolver,
    active_usb_indices: set[int] | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Resolve a camera source and pre-flight check files and numeric hardware devices."""
    resolved_source, meta = resolver.resolve_camera_source(raw_source, device_name=device_name)
    if meta.get("status") == "error":
        return resolved_source, meta

    if isinstance(resolved_source, int):
        if meta.get("error_code") == "NO_PHYSICAL_CAMERA_AVAILABLE" or meta.get("device_in_registry") is False:
            return resolved_source, {
                **meta,
                "status": "error",
                "error_code": meta.get("error_code") or "DEVICE_UNAVAILABLE",
            }
        if active_usb_indices and resolved_source in active_usb_indices:
            return resolved_source, meta
        if CameraDeviceHandler.probe_device(resolved_source) is None:
            return resolved_source, {
                **meta,
                "status": "error",
                "error_code": "DEVICE_UNAVAILABLE",
            }
    return resolved_source, meta


def _active_usb_indices_for_other_streams(coordinator: Any, exclude_camera_id: str) -> set[int]:
    """Return numeric device indices currently held by other running streams."""
    active: set[int] = set()
    for cid, mgr in (getattr(coordinator, "streams", None) or {}).items():
        if cid == exclude_camera_id or not getattr(mgr, "is_running", False):
            continue
        src = getattr(mgr, "_resolved_source", getattr(mgr, "source_override", None))
        if isinstance(src, int):
            active.add(src)
    return active


def _record_probe_error(camera_id: str, name: str, raw_source: Any, resolved_source: Any, meta: dict[str, Any]) -> None:
    """Persist pre-flight probe failure into CameraHealthManager."""
    err_code = meta.get("error_code", "FILE_NOT_FOUND")
    err_msg = (
        f"Camera device #{resolved_source} unavailable: {raw_source}"
        if err_code == "DEVICE_UNAVAILABLE"
        else f"Source not found: {raw_source}"
    )
    CameraHealthManager().set_error(
        camera_id, err_msg, error_code=err_code, attempted_paths=meta.get("attempted_paths"),
    )
    logger.warning("Camera stream [%s] '%s' registered offline (%s): %s", camera_id, name, err_code, raw_source)


def _construct_manager_safely(
    coordinator: Any, camera_id: str, name: str, raw_source: Any, resolved_source: Any,
    custom_cfg: dict[str, Any] | None, stream_manager_cls: Any,
) -> Any | None:
    """Instantiate StreamManager inside try/except so broken configs do not crash startup."""
    try:
        return stream_manager_cls(
            config_path=coordinator.base_config_path, db_path=coordinator.db_path,
            camera_id=camera_id, name=name, source_override=resolved_source,
            custom_cfg=custom_cfg, world_graph=coordinator.world_graph,
        )
    except Exception as exc:
        capture_runtime_exception(exc, context={"camera_id": camera_id, "source": str(raw_source)})
        CameraHealthManager().set_error(
            camera_id, f"Stream initialization failed: {exc}",
            error_code="INIT_FAILED", traceback_str=traceback.format_exc(),
        )
        logger.exception("Failed to initialize StreamManager for [%s] '%s'", camera_id, name)
        return None


def bootstrap_camera_stream(
    coordinator: Any,
    camera_id: str,
    cfg: dict[str, Any],
    *,
    start: bool = True,
    resolver: Any = CameraPathResolver,
    stream_manager_cls: Any = None,
    custom_cfg_builder: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
    start_stream_fn: Callable[[Any, str, str, Any], None] | None = None,
) -> Any | None:
    """Probe source readiness and safely construct/register a StreamManager."""
    raw_source = cfg.get("source", "synthetic")
    device_name = cfg.get("device_name") or (cfg.get("details") or {}).get("device_name")
    name = cfg.get("name", f"Camera {camera_id.upper()}")
    active_indices = _active_usb_indices_for_other_streams(coordinator, camera_id)

    resolved_source, meta = probe_source_readiness(
        raw_source, device_name=device_name, resolver=resolver, active_usb_indices=active_indices,
    )
    if meta.get("status") == "error":
        _record_probe_error(camera_id, name, raw_source, resolved_source, meta)
        return None
    mgr = _construct_manager_safely(
        coordinator, camera_id, name, raw_source, resolved_source,
        custom_cfg_builder(cfg) if custom_cfg_builder else None, stream_manager_cls,
    )
    if mgr is None:
        return None

    mgr._resolved_source, mgr._source_error = resolved_source, False
    mgr._processing_mode_service, mgr._in_camera_pool = coordinator.processing_mode_service, True
    mgr.is_armed = bool(cfg.get("armed", False))
    with coordinator._lock:
        coordinator.streams[camera_id] = mgr
    if CameraHealthManager().get_health(camera_id).status == "error":
        CameraHealthManager().set_online(camera_id)
    if start and start_stream_fn is not None:
        start_stream_fn(mgr, camera_id, name, raw_source)
    return mgr


def retry_camera_connection(pool: Any, camera_id: str) -> dict[str, Any]:
    """Re-probe a configured camera and restart its stream pipeline if available."""
    with pool._lock:
        cfg = dict(pool.camera_configs.get(camera_id) or {})
    if not cfg:
        raise KeyError(camera_id)

    cfg["enabled"] = True
    with pool._lock:
        pool.camera_configs[camera_id]["enabled"] = True
        pool.save_cameras()

    pool._coordinator.restart_stream(camera_id, cfg)
    mgr = pool.get_stream(camera_id)
    health = CameraHealthManager().get_health(camera_id)
    return {
        "status": "online" if mgr is not None and health.status != "error" else "error",
        "camera_id": camera_id,
        "stream_active": bool(mgr is not None and mgr.is_running),
        "health": health.to_dict(),
    }
