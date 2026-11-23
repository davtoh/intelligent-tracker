#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - StreamWorker Fault Isolation & Error Placeholder Helpers.

Provides non-fatal exception isolation, consecutive error tracking, and
dual-buffer (annotated + raw) diagnostic error-card publishing for StreamWorker.
"""

import logging
import sys
import time
from typing import Any

from dashboard.services.async_inference_worker import build_live_step_result, build_worker_step_result
from dashboard.services.cached_replay_provider import reset_bundle_loop_state
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


def step_worker_vs_frame(
    worker: Any,
    vs: Any,
    async_worker: Any,
    processor: Any,
    replay: Any,
    frame_seq: int,
    last_loop_count: int,
    consecutive_empty: int,
    consecutive_errors: int,
) -> tuple[int, int, int, int]:
    """Read one VideoSource frame, handle loop wraps, and step the StreamWorker pipeline."""
    ret, frame = vs.read(timeout=1.0)
    if not ret or frame is None:
        consecutive_empty, _ = worker._handle_empty_frame(vs, consecutive_empty)
        return frame_seq, last_loop_count, consecutive_empty, consecutive_errors
    consecutive_empty, frame_seq = 0, frame_seq + 1
    raw_loops = getattr(vs, "loop_count", 0)
    vs_loops = raw_loops if isinstance(raw_loops, int) and not isinstance(raw_loops, bool) else 0
    if vs_loops > last_loop_count:
        last_loop_count = vs_loops
        if not replay.is_active():
            reset_bundle_loop_state(getattr(processor, "bundle", None), time.time(), reset_tracker=True)
    is_rec = bool(getattr(worker.manager, "is_recording", False))
    sw_mod = sys.modules.get("dashboard.services.stream_worker")
    live_step_fn = getattr(sw_mod, "build_live_step_result", build_live_step_result)
    step_res = build_worker_step_result(
        worker.manager, async_worker, frame, frame_seq, worker._should_run_vision_step(is_rec),
        is_rec, step_fn=live_step_fn,
    )
    if step_res.frame_count % 30 == 1 or consecutive_errors > 0:
        vs_fps = float(getattr(vs, "measured_fps", getattr(vs, "_measured_fps", 0.0)) or 0.0)
        CameraHealthManager().set_online(worker.manager.camera_id, fps=vs_fps if vs_fps > 0 else (step_res.fps or 0.0))
    worker._process_single_frame(step_res)
    return frame_seq, last_loop_count, consecutive_empty, 0
