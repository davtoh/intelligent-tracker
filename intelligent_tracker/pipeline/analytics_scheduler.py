"""Resource-aware P0/P1/P2 analytics scheduler with 3-stage load shedding."""

from collections import deque
from dataclasses import dataclass
from enum import Enum
import os
import threading
import time
from typing import Any, Callable, Protocol

from intelligent_tracker.pipeline.motion_gate import MotionGate, MotionSample


class PriorityTier(str, Enum):
    """Inference scheduling priority tier for a camera stream."""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    REPLAY = "REPLAY"


class LoadShedStage(str, Enum):
    """Global backpressure shedding stage."""

    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class ScheduleDecision:
    """Scheduling outcome for a single frame candidate."""

    should_run: bool
    priority_tier: PriorityTier
    target_fps: float
    load_shed_stage: LoadShedStage
    motion_active: bool
    first_motion_trigger: bool
    alarm_hold_remaining_s: float
    reason: str


class IdleRefinementHook(Protocol):
    """Protocol for Pass-2/3 idle descriptor refinement under spare budget."""

    def run_idle_refinement(self, budget_utilization: float, now: float) -> Any: ...


@dataclass
class _CameraScheduleState:
    """Per-camera scheduler timestamps, alarm hold, and last decision."""

    last_scheduled_at: float | None = None
    alarm_until: float = 0.0
    last_tier: PriorityTier = PriorityTier.P2
    last_target_fps: float = 0.0
    last_motion_active: bool = False
    last_shed_notify_at: float | None = None


def _compute_load_shed_stage(ewma_latency_ms: float, utilization: float) -> LoadShedStage:
    """Determine load-shedding stage from EWMA latency and budget utilization."""
    if ewma_latency_ms > 250.0:
        return LoadShedStage.CRITICAL
    if ewma_latency_ms > 100.0 or utilization > 0.80:
        return LoadShedStage.ELEVATED
    return LoadShedStage.NORMAL


def _compute_tier_and_fps(
    mode: str, is_focused: bool, is_recording: bool, is_armed: bool,
    active_tab: str, alarm_hold_s: float, motion_active: bool, stage: LoadShedStage,
) -> tuple[PriorityTier, float, str]:
    """Resolve priority tier and target FPS for the current camera state."""
    if is_recording or alarm_hold_s > 0.0 or (is_focused and active_tab == "live"):
        fps = 8.0 if stage == LoadShedStage.CRITICAL else 15.0
        reason = "alarm_hold" if alarm_hold_s > 0.0 else ("recording" if is_recording else "focused_live")
        return PriorityTier.P0, fps, reason

    if is_armed:
        if not motion_active:
            return PriorityTier.P1, 1.0, "armed_idle_floor"
        fps = 8.0 if stage == LoadShedStage.NORMAL else (4.0 if stage == LoadShedStage.ELEVATED else 1.0)
        return PriorityTier.P1, max(1.0, fps), "armed_motion_burst"

    if mode == "full_realtime" and stage == LoadShedStage.NORMAL:
        return PriorityTier.P2, 1.0, "background_realtime"
    return PriorityTier.P2, 0.0, "background_shed_or_unfocused"


def _prune_fps_window(window: deque[float], now: float, horizon_s: float = 2.0) -> float:
    """Prune stale timestamps and return rolling inference FPS."""
    cutoff = now - horizon_s
    while window and window[0] < cutoff:
        window.popleft()
    return len(window) / horizon_s


def _can_grant_slot(
    state: _CameraScheduleState, tier: PriorityTier, target_fps: float,
    first_trigger: bool, active_inferences: int, max_concurrent: int, ts: float,
) -> bool:
    """Return True when concurrency and cadence allow scheduling this frame."""
    if target_fps <= 0.0 or active_inferences >= max_concurrent:
        return False
    if tier == PriorityTier.P1 and first_trigger:
        return True
    if state.last_scheduled_at is None:
        return True
    return (ts - state.last_scheduled_at) >= (1.0 / target_fps) - 1e-6


class AnalyticsScheduler:
    """Central P0/P1/P2 arbiter enforcing global CPU/GPU budgets and <=2.0s alarm SLA."""

    def __init__(
        self,
        motion_gate: MotionGate | None = None,
        max_concurrent_inferences: int | None = None,
        global_fps_budget: float | None = None,
        deferred_indexing_cb: Callable[[str, str], None] | None = None,
        idle_refinement_hook: IdleRefinementHook | None = None,
    ) -> None:
        self.motion_gate = motion_gate if motion_gate is not None else MotionGate()
        env_conc = int(os.getenv("SCHEDULER_MAX_CONCURRENT_INFERENCES", "2"))
        env_fps = float(os.getenv("SCHEDULER_GLOBAL_FPS_BUDGET", "30.0"))
        raw_conc = env_conc if max_concurrent_inferences is None else max_concurrent_inferences
        raw_fps = env_fps if global_fps_budget is None else global_fps_budget
        self.max_concurrent_inferences = max(1, int(raw_conc))
        self.global_fps_budget = max(1.0, float(raw_fps))
        self._deferred_indexing_cb = deferred_indexing_cb
        self._idle_refinement_hook = idle_refinement_hook

        self._lock = threading.Lock()
        self._cameras: dict[str, _CameraScheduleState] = {}
        self._inference_timestamps: deque[float] = deque()
        self._active_inferences: int = 0
        self._ewma_latency_ms: float = 0.0
        self._last_refinement_at: float | None = None

    def promote_alarm(self, camera_id: str, duration_s: float = 15.0, now: float | None = None) -> float:
        """Promote camera to P0 follow-up cadence for duration_s seconds."""
        ts = time.monotonic() if now is None else float(now)
        until = ts + max(0.0, float(duration_s))
        with self._lock:
            state = self._cameras.setdefault(camera_id, _CameraScheduleState())
            state.alarm_until = max(state.alarm_until, until)
            if state.alarm_until > ts:
                state.last_tier = PriorityTier.P0
            return state.alarm_until - ts

    def should_schedule_frame(
        self, camera_id: str, frame: Any = None, now: float | None = None, *,
        mode: str = "focus_only", is_focused: bool = False, is_recording: bool = False,
        is_armed: bool = False, active_tab: str = "live", is_replay: bool = False,
    ) -> ScheduleDecision:
        """Decide whether a camera frame should enter AI inference now."""
        ts = time.monotonic() if now is None else float(now)
        if is_replay:
            with self._lock:
                self._cameras.setdefault(camera_id, _CameraScheduleState()).last_tier = PriorityTier.REPLAY
            return ScheduleDecision(True, PriorityTier.REPLAY, 0.0, self.get_load_shed_stage(), False, False, 0.0, "zero_gpu_replay")
        if mode in ("paused", "capture_only"):
            with self._lock:
                state = self._cameras.setdefault(camera_id, _CameraScheduleState())
                state.last_tier = PriorityTier.P2
                state.last_target_fps = 0.0
                state.last_motion_active = False
                rolling_fps = _prune_fps_window(self._inference_timestamps, ts)
                util = max(rolling_fps / self.global_fps_budget, self._active_inferences / self.max_concurrent_inferences)
                stage = _compute_load_shed_stage(self._ewma_latency_ms, util)
            return ScheduleDecision(False, PriorityTier.P2, 0.0, stage, False, False, 0.0, f"mode_{mode}")

        motion = (
            self.motion_gate.evaluate(camera_id, frame, now=ts) if (is_armed and frame is not None)
            else MotionSample(self.motion_gate.is_motion_active(camera_id, now=ts) if is_armed else False, 0.0, 0.0, False)
        )
        deferred_reason: str | None = None
        with self._lock:
            state = self._cameras.setdefault(camera_id, _CameraScheduleState())
            alarm_rem = max(0.0, state.alarm_until - ts)
            rolling_fps = _prune_fps_window(self._inference_timestamps, ts)
            util = max(rolling_fps / self.global_fps_budget, self._active_inferences / self.max_concurrent_inferences)
            stage = _compute_load_shed_stage(self._ewma_latency_ms, util)
            tier, target_fps, reason = _compute_tier_and_fps(
                mode, is_focused, is_recording, is_armed, active_tab, alarm_rem, motion.motion_active, stage
            )
            should_run = _can_grant_slot(
                state, tier, target_fps, motion.first_trigger, self._active_inferences, self.max_concurrent_inferences, ts
            )
            if should_run:
                state.last_scheduled_at = ts
            if stage == LoadShedStage.CRITICAL and tier == PriorityTier.P1 and motion.motion_active and self._deferred_indexing_cb is not None:
                if state.last_shed_notify_at is None or (ts - state.last_shed_notify_at) >= 10.0:
                    state.last_shed_notify_at, deferred_reason = ts, "critical_p1_motion_shed"
            state.last_tier, state.last_target_fps, state.last_motion_active = tier, target_fps, motion.motion_active
        if deferred_reason is not None and self._deferred_indexing_cb is not None:
            self._deferred_indexing_cb(camera_id, deferred_reason)
        return ScheduleDecision(should_run, tier, target_fps, stage, motion.motion_active, motion.first_trigger, alarm_rem, reason)

    def record_inference_start(self, camera_id: str, now: float | None = None) -> None:
        """Record start of an active inference call against global concurrency budget."""
        ts = time.monotonic() if now is None else float(now)
        with self._lock:
            self._cameras.setdefault(camera_id, _CameraScheduleState())
            self._active_inferences += 1
            self._inference_timestamps.append(ts)
            _prune_fps_window(self._inference_timestamps, ts)

    def record_inference_end(self, camera_id: str, latency_ms: float, now: float | None = None) -> None:
        """Record completion and update EWMA inference latency."""
        with self._lock:
            self._cameras.setdefault(camera_id, _CameraScheduleState())
            self._active_inferences = max(0, self._active_inferences - 1)
            lat = max(0.0, float(latency_ms))
            self._ewma_latency_ms = lat if self._ewma_latency_ms <= 0.0 else (0.3 * lat + 0.7 * self._ewma_latency_ms)

    def get_load_shed_stage(self) -> LoadShedStage:
        """Return the current global load-shedding stage."""
        with self._lock:
            rolling_fps = _prune_fps_window(self._inference_timestamps, time.monotonic())
            util = max(rolling_fps / self.global_fps_budget, self._active_inferences / self.max_concurrent_inferences)
            return _compute_load_shed_stage(self._ewma_latency_ms, util)

    def get_camera_summary(self, camera_id: str, now: float | None = None) -> dict[str, Any]:
        """Return scheduler telemetry snapshot for a single camera."""
        ts = time.monotonic() if now is None else float(now)
        with self._lock:
            state = self._cameras.get(camera_id)
            rolling_fps = _prune_fps_window(self._inference_timestamps, ts)
            util = max(rolling_fps / self.global_fps_budget, self._active_inferences / self.max_concurrent_inferences)
            stage = _compute_load_shed_stage(self._ewma_latency_ms, util)
            if state is None:
                return {"priority_tier": PriorityTier.P2.value, "target_fps": 0.0, "motion_active": False, "alarm_hold_s": 0.0, "load_shed_stage": stage.value}
            return {"priority_tier": state.last_tier.value, "target_fps": state.last_target_fps, "motion_active": state.last_motion_active, "alarm_hold_s": round(max(0.0, state.alarm_until - ts), 2), "load_shed_stage": stage.value}

    def get_summary(self, now: float | None = None) -> dict[str, Any]:
        """Return global scheduler budget, latency, and load-shedding summary."""
        ts = time.monotonic() if now is None else float(now)
        with self._lock:
            rolling_fps = _prune_fps_window(self._inference_timestamps, ts)
            util = max(rolling_fps / self.global_fps_budget, self._active_inferences / self.max_concurrent_inferences)
            stage = _compute_load_shed_stage(self._ewma_latency_ms, util)
            return {
                "load_shed_stage": stage.value, "rolling_fps": round(rolling_fps, 2),
                "global_fps_budget": self.global_fps_budget, "active_inferences": self._active_inferences,
                "max_concurrent_inferences": self.max_concurrent_inferences,
                "ewma_latency_ms": round(self._ewma_latency_ms, 2), "budget_utilization": round(min(1.5, util), 3),
            }

    def maybe_run_idle_refinement(self, now: float | None = None) -> bool:
        """Invoke IdleRefinementHook when budget utilization is below 40%."""
        if self._idle_refinement_hook is None:
            return False
        ts = time.monotonic() if now is None else float(now)
        with self._lock:
            rolling_fps = _prune_fps_window(self._inference_timestamps, ts)
            util = max(rolling_fps / self.global_fps_budget, self._active_inferences / self.max_concurrent_inferences)
            stage = _compute_load_shed_stage(self._ewma_latency_ms, util)
            too_soon = self._last_refinement_at is not None and (ts - self._last_refinement_at) < 1.0
            if stage != LoadShedStage.NORMAL or util >= 0.40 or too_soon:
                return False
            self._last_refinement_at = ts
        self._idle_refinement_hook.run_idle_refinement(util, ts)
        return True

    def reset(self, camera_id: str | None = None) -> None:
        """Reset scheduler and motion-gate state for one or all cameras."""
        self.motion_gate.reset(camera_id)
        with self._lock:
            if camera_id is None:
                self._cameras.clear()
                self._inference_timestamps.clear()
                self._active_inferences, self._ewma_latency_ms, self._last_refinement_at = 0, 0.0, None
            else:
                self._cameras.pop(camera_id, None)


__all__ = ["AnalyticsScheduler", "IdleRefinementHook", "LoadShedStage", "PriorityTier", "ScheduleDecision"]
