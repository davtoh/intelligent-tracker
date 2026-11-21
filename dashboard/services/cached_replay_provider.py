"""Zero-GPU CachedReplayProvider with live post-detection governance.

Replays pre-indexed TrackerDB detection streams for ``video_file`` cameras
without consuming GPU/YOLO scheduler slots, while running live zone, tripwire,
RSAC, pet-whitelist, EventBus, and WorldEntityBridge governance and resetting
per-track dwell/crossing state cleanly on video loop wrap-around.
"""

from contextlib import nullcontext
import threading
import time
from typing import Any

from dashboard.services.file_detection_replay import FileDetectionReplayProvider, ReplayTrack
from intelligent_tracker.pipeline import FrameStepResult
from intelligent_tracker.pipeline.post_detection_governance import (
    evaluate_tracks_governance,
    resolve_camera_id,
)


def reset_bundle_loop_state(bundle: Any, now: float, *, reset_tracker: bool = False) -> None:
    """Clear per-track zone dwell, tripwire centroid, and optional tracker state on loop wrap."""
    if bundle is None:
        return
    lock = getattr(bundle, "_governance_lock", None)
    with lock if lock is not None else nullcontext():
        if reset_tracker:
            tracker = getattr(bundle, "tracker", None)
            if tracker is not None:
                if hasattr(tracker, "reset") and callable(tracker.reset):
                    tracker.reset()
                elif isinstance(getattr(tracker, "tracks", None), dict):
                    tracker.tracks.clear()
        analytics = getattr(bundle, "analytics", None)
        if analytics is not None:
            prev = getattr(analytics, "_prev_centroids", None)
            if isinstance(prev, dict):
                prev.clear()
            for zone in getattr(analytics, "zones", {}).values():
                occ = getattr(zone, "current_occupants", None)
                if isinstance(occ, dict):
                    occ.clear()
        bridge = getattr(bundle, "world_bridge", None)
        if bridge is not None and hasattr(bridge, "prune_stale_tracks"):
            bridge.prune_stale_tracks(
                camera_id=resolve_camera_id(bundle), active_track_ids=set(), timestamp=now
            )


class CachedReplayProvider:
    """Zero-GPU replay provider executing live rule governance on cached tracks."""

    def __init__(
        self,
        db: Any,
        video_source: Any,
        processor: Any = None,
        *,
        bundle: Any = None,
        topology: Any = None,
        world_bridge: Any = None,
        replay_provider: FileDetectionReplayProvider | None = None,
        run_id: str | None = None,
        tolerance_s: float = 0.45,
        run_reid: bool = False,
    ) -> None:
        self._processor = processor
        self._bundle = bundle
        self._topology = topology
        self._world_bridge = world_bridge
        self._run_reid = bool(run_reid)
        self.replay = replay_provider or FileDetectionReplayProvider(
            db, video_source, run_id=run_id, tolerance_s=tolerance_s
        )
        self._last_media_time_s: float | None = None
        self._last_frame_seq: int | None = None
        self.loop_reset_count: int = 0

    def is_active(self) -> bool:
        """Return True when a completed pre-indexed detection stream is available."""
        return bool(self.replay.ensure_loaded())

    def _resolve_context(self) -> tuple[Any, Any, Any]:
        """Resolve active (bundle, topology, world_bridge) from processor or overrides."""
        bundle = self._bundle if self._bundle is not None else getattr(self._processor, "bundle", None)
        topology = self._topology if self._topology is not None else getattr(self._processor, "topology", None)
        bridge = self._world_bridge if self._world_bridge is not None else getattr(self._processor, "world_bridge", None)
        return bundle, topology, bridge

    def _detect_loop_wrap(self, frame_seq: int, media_time_s: float) -> bool:
        """Return True when video playback wrapped back to the start of the clip."""
        if self._last_frame_seq is None:
            return False
        if frame_seq < self._last_frame_seq:
            return True
        if frame_seq == 0 and self._last_frame_seq != 0:
            return True
        if self._last_media_time_s is not None and (media_time_s + 0.05) < self._last_media_time_s:
            return True
        return False

    def reset_loop_state(self, bundle: Any, now: float) -> None:
        """Clear per-track zone dwell and tripwire centroid state on video loop wrap."""
        self.loop_reset_count += 1
        reset_bundle_loop_state(bundle, now, reset_tracker=False)
        if bundle is None:
            return
        bridge = self._world_bridge or getattr(self._processor, "world_bridge", None)
        if bridge is not None and bridge is not getattr(bundle, "world_bridge", None) and hasattr(bridge, "prune_stale_tracks"):
            bridge.prune_stale_tracks(
                camera_id=resolve_camera_id(bundle), active_track_ids=set(), timestamp=now
            )

    def build_step_result(
        self,
        frame: Any,
        now: float | None,
        frame_seq: int,
        fps: float = 0.0,
        *,
        media_time_s: float | None = None,
    ) -> FrameStepResult | None:
        """Return zero-GPU FrameStepResult with live rule governance, or None if unindexed."""
        if not self.replay.ensure_loaded():
            return None
        wall_now = time.time() if now is None else float(now)
        t_start = time.perf_counter()
        resolved_t = self.replay.resolve_media_time(frame_seq, media_time_s=media_time_s)
        bundle, topology, bridge = self._resolve_context()
        if bundle is not None and getattr(bundle, "_governance_lock", None) is None:
            bundle._governance_lock = threading.Lock()
        if self._detect_loop_wrap(frame_seq, resolved_t):
            self.reset_loop_state(bundle, wall_now)
        self._last_media_time_s, self._last_frame_seq = resolved_t, int(frame_seq)
        tracks: dict[int, ReplayTrack] = self.replay.lookup_tracks(frame_seq, frame.shape, media_time_s=resolved_t) or {}
        analytics_res, identifications = ({}, [])
        if bundle is not None:
            lock = getattr(bundle, "_governance_lock", None)
            with lock if lock is not None else nullcontext():
                analytics_res, identifications = evaluate_tracks_governance(
                    bundle, frame, tracks, wall_now, topology=topology, world_bridge=bridge, run_reid=self._run_reid
                )
        elapsed_ms = max(0.0, (time.perf_counter() - t_start) * 1000.0)
        resolved_fps = float(fps) if float(fps or 0.0) > 0 else float(getattr(self.replay, "_source_fps", 0.0) or 0.0)
        res = FrameStepResult(
            frame=frame, tracks=tracks, analytics=analytics_res, identifications=identifications,
            timestamp=wall_now, fps=resolved_fps, frame_count=frame_seq, processing_ms=elapsed_ms,
        )
        return _stamp_replay_result(res, frame_seq=frame_seq, now=wall_now)


def _stamp_replay_result(res: FrameStepResult, *, frame_seq: int, now: float) -> FrameStepResult:
    """Attach zero-GPU replay provenance and priority metadata."""
    setattr(res, "inference_frame_seq", int(frame_seq))
    setattr(res, "inference_timestamp", float(now))
    setattr(res, "inference_lag_ms", 0.0)
    setattr(res, "replay_active", True)
    setattr(res, "priority_tier", "REPLAY")
    return res
