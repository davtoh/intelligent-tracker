"""Lightweight 64x36 luma MotionGate for P1 analytics scheduling."""

from dataclasses import dataclass
import threading
import time
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True)
class MotionSample:
    """Result of evaluating a single frame against the 64x36 luma background."""

    motion_active: bool
    score: float
    changed_ratio: float
    first_trigger: bool


@dataclass
class _CameraMotionState:
    """Mutable per-camera running background and hold window."""

    bg_luma: np.ndarray | None = None
    motion_until: float = 0.0
    was_active: bool = False
    last_sample: MotionSample | None = None


def _to_luma_grid(frame: np.ndarray, width: int = 64, height: int = 36) -> np.ndarray:
    """Downscale frame to a 64x36 uint8 luma grid in < 0.2 ms."""
    if frame.ndim == 2:
        gray = frame
    elif frame.ndim == 3 and frame.shape[2] == 1:
        gray = frame[:, :, 0]
    elif frame.ndim == 3 and frame.shape[2] >= 3:
        gray = cv2.cvtColor(frame[:, :, :3], cv2.COLOR_BGR2GRAY)
    else:
        raise ValueError(f"Unsupported frame shape for MotionGate: {frame.shape}")
    if gray.dtype != np.uint8:
        gray = np.clip(gray, 0, 255).astype(np.uint8)
    if gray.shape[1] == width and gray.shape[0] == height:
        return gray
    return cv2.resize(gray, (width, height), interpolation=cv2.INTER_AREA)


class MotionGate:
    """Pure-CPU 64x36 luma frame-differencing gate with hysteresis hold."""

    def __init__(
        self,
        pixel_delta_threshold: int = 18,
        changed_ratio_threshold: float = 0.015,
        ema_alpha: float = 0.15,
        hold_seconds: float = 3.0,
    ) -> None:
        self.pixel_delta_threshold = max(1, int(pixel_delta_threshold))
        self.changed_ratio_threshold = max(0.0, float(changed_ratio_threshold))
        self.ema_alpha = min(1.0, max(0.01, float(ema_alpha)))
        self.hold_seconds = max(0.0, float(hold_seconds))
        self._lock = threading.Lock()
        self._states: dict[str, _CameraMotionState] = {}

    def evaluate(
        self,
        camera_id: str,
        frame: np.ndarray | None,
        now: float | None = None,
    ) -> MotionSample:
        """Evaluate frame motion and return MotionSample with first-trigger flag."""
        ts = time.monotonic() if now is None else float(now)
        if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
            return MotionSample(False, 0.0, 0.0, False)

        luma = _to_luma_grid(frame)
        with self._lock:
            state = self._states.setdefault(camera_id, _CameraMotionState())
            if state.bg_luma is None:
                state.bg_luma = luma.astype(np.float32)
                state.last_sample = MotionSample(False, 0.0, 0.0, False)
                return state.last_sample

            diff = cv2.absdiff(luma, cv2.convertScaleAbs(state.bg_luma))
            changed_ratio = float(np.mean(diff >= self.pixel_delta_threshold))
            score = float(np.mean(diff)) / 255.0
            cv2.accumulateWeighted(luma, state.bg_luma, self.ema_alpha)

            instant_motion = changed_ratio >= self.changed_ratio_threshold
            if instant_motion:
                state.motion_until = max(state.motion_until, ts + self.hold_seconds)
            motion_active = instant_motion or (ts < state.motion_until)
            first_trigger = motion_active and not state.was_active
            state.was_active = motion_active
            sample = MotionSample(motion_active, score, changed_ratio, first_trigger)
            state.last_sample = sample
            return sample

    def is_motion_active(self, camera_id: str, now: float | None = None) -> bool:
        """Return True if camera is currently inside an active motion hold window."""
        ts = time.monotonic() if now is None else float(now)
        with self._lock:
            state = self._states.get(camera_id)
            if state is None:
                return False
            active = ts < state.motion_until
            if not active:
                state.was_active = False
            return active

    def get_state(self, camera_id: str, now: float | None = None) -> dict[str, Any]:
        """Return diagnostic motion state for a single camera."""
        ts = time.monotonic() if now is None else float(now)
        with self._lock:
            state = self._states.get(camera_id)
            if state is None:
                return {"motion_active": False, "hold_remaining_s": 0.0, "score": 0.0}
            remaining = max(0.0, state.motion_until - ts)
            last = state.last_sample
            return {
                "motion_active": remaining > 0.0,
                "hold_remaining_s": round(remaining, 3),
                "score": round(last.score, 4) if last else 0.0,
                "changed_ratio": round(last.changed_ratio, 4) if last else 0.0,
            }

    def reset(self, camera_id: str | None = None) -> None:
        """Clear background model and hold state for one or all cameras."""
        with self._lock:
            if camera_id is None:
                self._states.clear()
            else:
                self._states.pop(camera_id, None)


__all__ = ["MotionGate", "MotionSample"]
