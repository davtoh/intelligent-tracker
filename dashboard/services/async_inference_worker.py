"""Intelligent Tracker - Asynchronous Inference Worker.

Decouples heavy FrameProcessor AI stepping from live video capture and MJPEG
encoding using a single-slot latest-frame buffer so slow inference drops
intermediate frames without stalling live video delivery.
"""

import logging
import threading
import time
from typing import Any

import numpy as np

from intelligent_tracker.pipeline import FrameStepResult

logger = logging.getLogger("intelligent_tracker.dashboard.async_inference")


class AsyncInferenceWorker:
    """Single-slot latest-frame background worker for FrameProcessor.step()."""

    def __init__(
        self,
        processor: Any,
        max_dim: int = 1280,
        replay_provider: Any = None,
        scheduler: Any = None,
        camera_id: str = "default",
        is_armed: bool = False,
    ) -> None:
        self._processor = processor
        self._max_dim = max_dim
        self.replay_provider = replay_provider
        self._scheduler = scheduler
        self._camera_id = camera_id
        self._is_armed = bool(is_armed)
        self._lock = threading.Lock()
        self._work_event = threading.Event()
        self._stop_event = threading.Event()
        self._pending: tuple[np.ndarray, float, int] | None = None
        self._latest_result: FrameStepResult | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the background inference thread if not already running."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="async-inference-worker",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        """Signal shutdown and join the inference thread outside locks."""
        self._stop_event.set()
        self._work_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None

    def submit(self, frame: np.ndarray, timestamp: float | None = None, frame_seq: int = 0) -> None:
        """Queue the latest frame for inference, overwriting any unconsumed frame."""
        ts = time.monotonic() if timestamp is None else float(timestamp)
        frame_copy = frame.copy()
        with self._lock:
            self._pending = (frame_copy, ts, int(frame_seq))
        self._work_event.set()

    def clear_latest_result(self) -> None:
        """Clear any cached inference result and pending frame when vision is disabled."""
        with self._lock:
            self._pending = None
            self._latest_result = None

    def get_latest_result(self) -> FrameStepResult | None:
        """Return the most recent completed FrameStepResult, or None."""
        with self._lock:
            return self._latest_result

    def _run_loop(self) -> None:
        """Consume latest pending frame and publish updated FrameStepResult."""
        while not self._stop_event.is_set():
            self._work_event.wait()
            if self._stop_event.is_set():
                break

            with self._lock:
                self._work_event.clear()
                item = self._pending
                self._pending = None

            if item is None:
                continue

            frame, ts, seq = item if len(item) == 3 else (item[0], item[1], 0)
            if self._scheduler is not None:
                self._scheduler.record_inference_start(self._camera_id, now=ts)
            t0 = time.perf_counter()
            try:
                result = self._processor.step(frame, timestamp=ts, max_dim=self._max_dim)
            except Exception:
                logger.exception("AsyncInferenceWorker failed during processor.step")
                continue
            finally:
                if self._scheduler is not None:
                    self._scheduler.record_inference_end(
                        self._camera_id, (time.perf_counter() - t0) * 1000.0, now=ts
                    )
            if result is None:
                continue
            if self._scheduler is not None and self._is_armed:
                if getattr(result, "tracks", None) or (getattr(result, "analytics", None) or {}).get("new_events"):
                    self._scheduler.promote_alarm(self._camera_id, now=ts)

            setattr(result, "inference_frame_seq", int(seq))
            setattr(result, "inference_timestamp", float(ts))
            with self._lock:
                self._latest_result = result


def _stamp_step_provenance(
    res: FrameStepResult,
    inf_seq: int,
    inf_ts: float,
    lag_ms: float,
    decision: Any = None,
) -> FrameStepResult:
    """Attach inference sequence, timestamp, lag, and scheduler metadata."""
    setattr(res, "inference_frame_seq", int(inf_seq))
    setattr(res, "inference_timestamp", float(inf_ts))
    setattr(res, "inference_lag_ms", round(max(0.0, float(lag_ms)), 1))
    if decision is not None:
        tier = getattr(decision.priority_tier, "value", decision.priority_tier)
        shed = getattr(decision.load_shed_stage, "value", decision.load_shed_stage)
        setattr(res, "priority_tier", str(tier))
        setattr(res, "target_fps", float(decision.target_fps))
        setattr(res, "motion_active", bool(decision.motion_active))
        setattr(res, "load_shed_stage", str(shed))
    return res


def _clear_worker_cache(async_worker: Any) -> None:
    """Clear cached inference results when vision stepping is disabled."""
    if hasattr(async_worker, "clear_latest_result"):
        async_worker.clear_latest_result()
    else:
        with getattr(async_worker, "_lock", threading.Lock()):
            async_worker._latest_result = None


def _merge_cached_step_result(
    async_worker: Any,
    frame: np.ndarray,
    now: float,
    frame_seq: int,
    decision: Any,
    scheduler: Any,
    camera_id: str | None,
    is_armed: bool,
) -> FrameStepResult:
    """Merge latest async inference result onto current frame with provenance."""
    cached = async_worker.get_latest_result()
    if cached is not None:
        if scheduler is not None and camera_id and is_armed:
            if cached.tracks or (cached.analytics or {}).get("new_events"):
                scheduler.promote_alarm(camera_id, now=now)
        inf_seq = int(getattr(cached, "inference_frame_seq", getattr(cached, "frame_count", frame_seq)) or frame_seq)
        inf_ts = float(getattr(cached, "inference_timestamp", getattr(cached, "timestamp", now)) or now)
        merged = FrameStepResult(
            frame=frame, tracks=cached.tracks, analytics=cached.analytics,
            identifications=cached.identifications, timestamp=now, fps=cached.fps, frame_count=frame_seq,
        )
        return _stamp_step_provenance(merged, inf_seq, inf_ts, (now - inf_ts) * 1000.0, decision=decision)
    return _stamp_step_provenance(
        FrameStepResult(frame=frame, timestamp=now, fps=0.0, frame_count=frame_seq),
        0, now, 0.0, decision=decision,
    )


def build_live_step_result(
    async_worker: AsyncInferenceWorker, frame: np.ndarray, now: float | None = None, frame_seq: int = 0,
    run_vision: bool = True, replay_provider: Any = None, *, scheduler: Any = None,
    camera_id: str | None = None, mode: str = "focus_only", is_focused: bool = False,
    is_recording: bool = False, is_armed: bool = False, active_tab: str = "live",
    fps: float = 0.0, media_time_s: float | None = None,
) -> FrameStepResult:
    """Submit frame to async AI (or replay provider) when scheduled and stamp provenance."""
    ts = time.monotonic() if now is None else float(now)
    if not run_vision:
        _clear_worker_cache(async_worker)
        return _stamp_step_provenance(
            FrameStepResult(frame=frame, timestamp=ts, fps=0.0, frame_count=frame_seq), frame_seq, ts, 0.0
        )
    provider = replay_provider if replay_provider is not None else getattr(async_worker, "replay_provider", None)
    if provider is not None and hasattr(provider, "build_step_result"):
        try:
            replayed = provider.build_step_result(frame, ts, frame_seq, fps=fps, media_time_s=media_time_s)
        except TypeError:
            replayed = provider.build_step_result(frame, ts, frame_seq)
        if replayed is not None:
            return replayed
    decision = (
        scheduler.should_schedule_frame(
            camera_id, frame, ts, mode=mode, is_focused=is_focused,
            is_recording=is_recording, is_armed=is_armed, active_tab=active_tab,
        )
        if (scheduler is not None and camera_id)
        else None
    )
    if decision is None or decision.should_run:
        try:
            async_worker.submit(frame, ts, frame_seq=frame_seq)
        except TypeError:
            async_worker.submit(frame, ts)
    return _merge_cached_step_result(async_worker, frame, ts, frame_seq, decision, scheduler, camera_id, is_armed)


def build_worker_step_result(
    manager: Any,
    async_worker: AsyncInferenceWorker,
    frame: np.ndarray,
    frame_seq: int,
    run_vision: bool,
    is_rec: bool,
    step_fn: Any = build_live_step_result,
) -> FrameStepResult:
    """Invoke step_fn with AnalyticsScheduler context from StreamManager."""
    now = time.monotonic()
    if step_fn is not build_live_step_result:
        return step_fn(async_worker, frame, now, frame_seq, run_vision)
    svc = getattr(manager, "_processing_mode_service", None)
    scheduler = getattr(svc, "scheduler", None) if svc is not None else None
    mode = getattr(svc, "mode", "focus_only") if svc is not None else "focus_only"
    focused = getattr(svc, "focused_camera_id", None) if svc is not None else None
    active_tab = getattr(svc, "active_tab", "live") if svc is not None else "live"
    vs = getattr(manager, "video_source", None)
    measured_fps = float(getattr(vs, "measured_fps", getattr(vs, "_measured_fps", 0.0)) or 0.0)
    media_time_s = getattr(vs, "last_media_time_s", None)
    return step_fn(
        async_worker, frame, now, frame_seq, run_vision,
        scheduler=scheduler, camera_id=manager.camera_id, mode=mode,
        is_focused=(manager.camera_id == focused), is_recording=is_rec,
        is_armed=bool(getattr(manager, "is_armed", False)), active_tab=active_tab,
        fps=measured_fps, media_time_s=media_time_s,
    )
