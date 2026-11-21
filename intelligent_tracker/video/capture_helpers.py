"""Pure helper utilities for capture backoff, warmup timeouts, and frame geometry."""

from typing import Any
import cv2
import numpy as np

from intelligent_tracker.video.frame_timing import resolve_effective_fps


def compute_capture_timing(worker: Any) -> tuple[float, float]:
    """Compute (effective_fps, min_frame_time) from current worker source_fps and limits."""
    effective_fps = resolve_effective_fps(worker.is_file, worker.source_fps, worker.fps_limit)
    min_frame_time = (1.0 / effective_fps) if (worker.is_file or worker.fps_limit) else 0.0
    return effective_fps, min_frame_time


def compute_reconnect_backoff(
    attempt: int,
    base_delay: float = 1.0,
    max_backoff: float = 30.0,
) -> float:
    """Compute capped exponential reconnection delay in seconds."""
    safe_attempt = max(1, int(attempt))
    exponent = min(safe_attempt - 1, 5)
    return min(float(max_backoff), float(base_delay) * (2 ** exponent))


def compute_aspect_bounds(
    width: int,
    height: int,
    target_width: int,
    target_height: int,
) -> tuple[int, int]:
    """Compute even-aligned target dimensions preserving source aspect ratio."""
    src_ratio = width / float(height)
    target_ratio = target_width / float(target_height)
    if src_ratio >= target_ratio:
        adj_w = target_width
        adj_h = int(round(target_width / src_ratio))
    else:
        adj_h = target_height
        adj_w = int(round(target_height * src_ratio))
    even_w = adj_w if adj_w % 2 == 0 else adj_w - 1
    even_h = adj_h if adj_h % 2 == 0 else adj_h - 1
    return even_w, even_h


def probe_capture_dimensions(
    cap: Any,
    target_width: int | None,
    target_height: int | None,
) -> tuple[int | None, int | None, float | None]:
    """Configure requested bounds and read back actual capture dimensions and FPS."""
    if target_width and target_height:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(target_width))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(target_height))

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    valid_fps = fps if (fps > 0 and not np.isnan(fps)) else None

    if w > 0 and h > 0:
        if target_width and target_height:
            adj_w, adj_h = compute_aspect_bounds(w, h, target_width, target_height)
            return adj_w, adj_h, valid_fps
        return w, h, valid_fps
    return (w if w > 0 else None), (h if h > 0 else None), valid_fps


def handle_file_eof(worker: Any) -> None:
    """Mark non-looping file source at EOF and push None sentinel."""
    worker._eof = True
    worker._running = False
    worker._is_connected = False
    q = getattr(worker, "_queue", None)
    if q is not None:
        if q.full():
            try:
                q.get_nowait()
            except Exception:
                pass
        try:
            q.put_nowait(None)
        except Exception:
            pass


def rewind_or_reopen_loop_video(worker: Any, consecutive_empty: int, safe_release_cb: Any) -> tuple[bool, int]:
    """Rewind looping video files and reopen immediately on seek failure."""
    rewound = False
    if worker._cap:
        try:
            rewound = bool(worker._cap.set(cv2.CAP_PROP_POS_FRAMES, 0))
        except Exception:
            rewound = False
    if rewound and consecutive_empty == 0:
        worker._loop_count = int(getattr(worker, "_loop_count", 0)) + 1
    if not rewound or consecutive_empty > 5:
        if worker._cap:
            safe_release_cb(worker._cap, settle_delay=0.0)
            worker._cap = None
        if worker._open_capture():
            worker._loop_count = int(getattr(worker, "_loop_count", 0)) + 1
            consecutive_empty = 0
            return not worker._stop_event.wait(timeout=0.02), consecutive_empty
    consecutive_empty += 1
    return not worker._stop_event.wait(timeout=0.02), consecutive_empty


def handle_read_failure_helper(
    worker: Any, guard: Any, consecutive_empty: int, reconnect_attempts: int, safe_release_cb: Any
) -> tuple[bool, int, int]:
    """Handle failed/timed-out frame read with driver severing or empty-frame fallback."""
    if not worker._running:
        return False, consecutive_empty, reconnect_attempts
    is_severed = getattr(guard, "last_read_timed_out", False)
    if is_severed or (guard.is_reconnecting and worker.auto_reconnect and not worker.is_file):
        guard.safe_driver_unbind(worker._cap)
        worker._cap, worker._is_connected = None, False
        if worker.is_file:
            if worker._stop_event.wait(timeout=0.05) or not worker._open_capture():
                return False, consecutive_empty, reconnect_attempts
            guard.reset()
            return True, 0, reconnect_attempts
        if worker.auto_reconnect:
            should_continue, reconnect_attempts = worker._handle_reconnection(reconnect_attempts)
            if not should_continue:
                return False, consecutive_empty, reconnect_attempts
            guard.reset()
            return True, consecutive_empty, reconnect_attempts
        return False, consecutive_empty, reconnect_attempts
    return worker._handle_empty_frame(consecutive_empty, reconnect_attempts)


__all__ = [
    "compute_aspect_bounds",
    "compute_capture_timing",
    "compute_reconnect_backoff",
    "handle_file_eof",
    "handle_read_failure_helper",
    "probe_capture_dimensions",
    "rewind_or_reopen_loop_video",
]
