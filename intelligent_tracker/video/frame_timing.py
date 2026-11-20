"""Frame media-timestamp extraction and drift-free pacing helpers."""

import time
from typing import Any, Optional

import cv2


def read_media_time_s(cap: Any, is_file: bool, effective_fps: float) -> Optional[float]:
    """Extract current file media timestamp in seconds from OpenCV capture."""
    if not is_file or cap is None:
        return None
    try:
        pos_ms = float(cap.get(cv2.CAP_PROP_POS_MSEC) or 0.0)
        if pos_ms > 0.0:
            return pos_ms / 1000.0
        pos_f = float(cap.get(cv2.CAP_PROP_POS_FRAMES) or 0.0)
        return max(0.0, pos_f - 1.0) / max(1.0, effective_fps)
    except Exception:
        return None


def resolve_effective_fps(is_file: bool, source_fps: float, fps_limit: Optional[float]) -> float:
    """Resolve target capture FPS, preserving native rate for file sources."""
    if is_file and source_fps > 0:
        return source_fps
    return fps_limit or (source_fps if source_fps > 0 else 30.0)


def advance_frame_deadline(next_deadline: float, min_frame_time: float) -> Optional[float]:
    """Advance monotonic frame deadline without cumulative OS-sleep drift."""
    if min_frame_time <= 0:
        return None
    now_m = time.monotonic()
    if now_m - next_deadline > min_frame_time * 3.0:
        next_deadline = now_m
    return next_deadline + min_frame_time
