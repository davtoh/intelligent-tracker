"""Canonical per-frame CV execution engine shared by CLI and Dashboard."""

from collections import deque
from dataclasses import dataclass, field
import logging
import time
from typing import Any

import cv2
import numpy as np

from intelligent_tracker.pipeline.bundle import PipelineBundle
from intelligent_tracker.pipeline.post_detection_governance import evaluate_tracks_governance

logger = logging.getLogger("intelligent_tracker.pipeline.frame_processor")


@dataclass
class FrameStepResult:
    """Structured output produced by a single FrameProcessor.step() call."""

    frame: np.ndarray
    detections: list[Any] = field(default_factory=list)
    tracks: dict[int, Any] = field(default_factory=dict)
    analytics: dict[str, Any] = field(default_factory=dict)
    identifications: list[Any] = field(default_factory=list)
    timestamp: float = 0.0
    fps: float = 0.0
    frame_count: int = 0
    processing_ms: float = 0.0


def prepare_frame(
    frame: np.ndarray,
    *,
    target_size: tuple[int, int] | None = None,
    max_dim: int | None = None,
) -> np.ndarray:
    """Validate and resize an input frame to target_size and/or max_dim bounds."""
    if frame is None or not hasattr(frame, "shape") or frame.size == 0:
        raise ValueError("Frame cannot be None or empty")

    out = frame
    if target_size is not None:
        tw, th = int(target_size[0]), int(target_size[1])
        if tw > 0 and th > 0 and (out.shape[1] != tw or out.shape[0] != th):
            out = cv2.resize(out, (tw, th))

    if max_dim is not None and max_dim > 0:
        h, w = out.shape[:2]
        longest = max(h, w)
        if longest > max_dim:
            scale = max_dim / float(longest)
            out = cv2.resize(out, (max(1, int(w * scale)), max(1, int(h * scale))))

    return out


def _rescale_tracks_and_detections(
    tracks: dict[int, Any], detections: list[Any], src_shape: tuple[int, ...], proc_shape: tuple[int, ...]
) -> None:
    """Rescale track coordinates back to original frame dimensions."""
    orig_h, orig_w = int(src_shape[0]), int(src_shape[1])
    proc_h, proc_w = int(proc_shape[0]), int(proc_shape[1])
    if orig_h <= 0 or orig_w <= 0 or proc_h <= 0 or proc_w <= 0 or (orig_h == proc_h and orig_w == proc_w):
        return
    sx, sy = orig_w / float(proc_w), orig_h / float(proc_h)
    for trk in tracks.values():
        bbox = getattr(trk, "bbox", None)
        if bbox is not None and len(bbox) >= 4:
            trk.bbox = (int(round(bbox[0] * sx)), int(round(bbox[1] * sy)), max(1, int(round(bbox[2] * sx))), max(1, int(round(bbox[3] * sy))))
        c = getattr(trk, "centroid", None)
        if c is not None and len(c) >= 2:
            trk.centroid = (float(c[0]) * sx, float(c[1]) * sy)
        v = getattr(trk, "velocity", None)
        if v is not None and len(v) >= 2:
            trk.velocity = (float(v[0]) * sx, float(v[1]) * sy)


class FrameProcessor:
    """Executes detection, tracking, analytics, topology, and Re-ID per frame."""

    def __init__(
        self,
        bundle: PipelineBundle,
        *,
        topology: Any = None,
        world_bridge: Any = None,
        fps_window: int = 30,
    ) -> None:
        self.bundle = bundle
        self.topology = topology
        self._world_bridge = world_bridge
        self.frame_count = 0
        self.measured_fps = 0.0
        self._fps_history: deque[float] = deque(maxlen=max(1, int(fps_window)))

    @property
    def world_bridge(self) -> Any:
        """Return explicit or bundle-owned WorldEntityBridge."""
        return self._world_bridge if self._world_bridge is not None else self.bundle.world_bridge

    @world_bridge.setter
    def world_bridge(self, value: Any) -> None:
        self._world_bridge = value

    def reset_fps(self) -> None:
        """Clear accumulated frame count and rolling FPS history."""
        self.frame_count = 0
        self.measured_fps = 0.0
        self._fps_history.clear()

    def step(
        self,
        frame: np.ndarray,
        timestamp: float | None = None,
        max_dim: int | None = None,
        target_size: tuple[int, int] | None = None,
    ) -> FrameStepResult:
        """Run one canonical CV pipeline step on a single BGR frame."""
        t_perf = time.perf_counter()
        now = float(timestamp) if timestamp is not None else time.time()
        processed = prepare_frame(frame, target_size=target_size, max_dim=max_dim)

        detections = self._run_detector(processed)
        tracks = self._run_tracker(detections, now)
        _rescale_tracks_and_detections(tracks, detections, frame.shape, processed.shape)
        analytics_res, identifications = evaluate_tracks_governance(
            self.bundle, frame, tracks, now,
            topology=self.topology, world_bridge=self.world_bridge, run_reid=True,
        )

        elapsed_s = max(time.perf_counter() - t_perf, 1e-6)
        self.frame_count += 1
        self._fps_history.append(1.0 / elapsed_s)
        self.measured_fps = sum(self._fps_history) / len(self._fps_history)

        return FrameStepResult(
            frame=processed,
            detections=detections,
            tracks=tracks,
            analytics=analytics_res,
            identifications=identifications,
            timestamp=now,
            fps=self.measured_fps,
            frame_count=self.frame_count,
            processing_ms=elapsed_s * 1000.0,
        )

    def _run_detector(self, frame: np.ndarray) -> list[Any]:
        """Run object detector on the prepared frame."""
        detector = self.bundle.detector
        if detector is None:
            return []
        try:
            return list(detector.detect(frame) or [])
        except Exception as exc:
            logger.debug("Detector error: %s", exc)
            return []

    def _run_tracker(self, detections: list[Any], timestamp: float) -> dict[int, Any]:
        """Update multi-object tracker using detections and timestamp."""
        tracker = self.bundle.tracker
        if tracker is None:
            return {}
        try:
            return dict(tracker.update(detections, timestamp=timestamp) or {})
        except Exception as exc:
            logger.debug("Tracker error: %s", exc)
            return {}

