#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - StreamWorker Fault Isolation & Error Placeholder Helpers.

Provides non-fatal exception isolation, consecutive error tracking, and
dual-buffer (annotated + raw) diagnostic error-card publishing for StreamWorker.
"""

import logging
from typing import Any

from dashboard.services.camera_diagnostics import CameraHealthManager
from dashboard.services.diagnostic_bridge import capture_runtime_exception

logger = logging.getLogger("intelligent_tracker.dashboard.worker.recovery")


def publish_error_placeholders(
    manager: Any,
    err_code: str,
    err_msg: str,
    *,
    force: bool = False,
) -> None:
    """Publish diagnostic error placeholder JPEG to both annotated and raw buffers."""
    health_mgr = CameraHealthManager()
    with manager._lock:
        telemetry = getattr(manager, "_latest_telemetry", None)
        already_error = bool(telemetry and telemetry.get("status") == "error")
        need_ann = force or getattr(manager, "_latest_jpeg", None) is None or not already_error
        need_raw = force or getattr(manager, "_latest_raw_jpeg", None) is None or not already_error

    placeholder: bytes | None = None
    if need_ann or need_raw:
        placeholder = health_mgr.create_error_placeholder_jpeg(
            manager.camera_id,
            name=getattr(manager, "name", manager.camera_id),
            width=int(getattr(manager, "width", 640) or 640),
            height=int(getattr(manager, "height", 480) or 480),
        )

    with manager._lock:
        if placeholder:
            if need_ann:
                manager._latest_jpeg = placeholder
            if need_raw:
                manager._latest_raw_jpeg = placeholder
        if getattr(manager, "_latest_telemetry", None):
            manager._latest_telemetry["status"] = "error"
            manager._latest_telemetry["fps"] = 0.0
            manager._latest_telemetry["error_code"] = err_code
            manager._latest_telemetry["error_msg"] = err_msg


def handle_worker_exception(
    manager: Any,
    exc: BaseException,
    consecutive_errors: int,
    *,
    stage: str = "frame_loop",
    error_threshold: int = 10,
) -> int:
    """Record a transient worker exception without crashing the StreamWorker thread."""
    consecutive_errors += 1
    camera_id = getattr(manager, "camera_id", "unknown")
    capture_runtime_exception(
        exc,
        context={"thread_name": "StreamManagerWorker", "camera_id": camera_id, "stage": stage},
    )
    err_msg = f"Pipeline {stage} error: {exc}"
    logger.warning(
        "StreamWorker [%s] transient error #%d (%s): %s",
        camera_id, consecutive_errors, stage, exc,
    )
    CameraHealthManager().set_error(camera_id, err_msg, error_code="PIPELINE_ERROR")
    if consecutive_errors > error_threshold or getattr(manager, "_latest_jpeg", None) is None:
        publish_error_placeholders(
            manager, "PIPELINE_ERROR", err_msg, force=(consecutive_errors == error_threshold + 1)
        )
    manager._stop_event.wait(timeout=0.05)
    return consecutive_errors
