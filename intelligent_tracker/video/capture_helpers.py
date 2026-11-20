"""Pure helper utilities for capture backoff, warmup timeouts, and frame geometry."""

from typing import Any
import cv2
import numpy as np


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


def rewind_or_reopen_loop_video(worker: Any, consecutive_empty: int, safe_release_cb: Any) -> tuple[bool, int]:
    """Rewind looping video files and reopen after repeated empty reads."""
    if worker._cap:
        try:
            worker._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        except Exception:
            pass
    consecutive_empty += 1
    if consecutive_empty > 5:
        safe_release_cb(worker._cap, settle_delay=0.0)
        worker._cap = None
        worker._open_capture()
        consecutive_empty = 0
    return not worker._stop_event.wait(timeout=0.02), consecutive_empty


__all__ = [
    "compute_aspect_bounds",
    "compute_reconnect_backoff",
    "probe_capture_dimensions",
    "rewind_or_reopen_loop_video",
]
