"""Canonical per-frame CV execution engine shared by CLI and Dashboard."""

from collections import deque
from dataclasses import dataclass, field
import logging
import time
from typing import Any

import cv2
import numpy as np

from intelligent_tracker.events import EntityIdentifiedEvent, RestrictedEntityAlert, crop_to_base64
from intelligent_tracker.pipeline.bundle import PipelineBundle

logger = logging.getLogger("intelligent_tracker.pipeline.frame_processor")

_RESTRICTED_CATEGORIES = frozenset({"restricted", "banned", "blacklisted"})


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


class FrameProcessor:
    """Executes detection, tracking, analytics, topology, and Re-ID per frame."""

    def __init__(
        self,
        bundle: PipelineBundle,
        *,
        topology: Any = None,
        fps_window: int = 30,
    ) -> None:
        self.bundle = bundle
        self.topology = topology
        self.frame_count = 0
        self.measured_fps = 0.0
        self._fps_history: deque[float] = deque(maxlen=max(1, int(fps_window)))

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
        analytics_res = self._run_analytics(processed, tracks, now)
        self._handle_zone_exits(analytics_res, tracks, now)
        identifications = self._run_reid(processed, tracks, now)

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

    def _run_analytics(
        self,
        frame: np.ndarray,
        tracks: dict[int, Any],
        timestamp: float,
    ) -> dict[str, Any]:
        """Step spatial analytics (zones, tripwires, heatmaps, RSAC)."""
        analytics = self.bundle.analytics
        if analytics is None:
            return {}
        try:
            res = analytics.update(tracks, timestamp=timestamp, current_frame=frame)
            return dict(res) if isinstance(res, dict) else {}
        except Exception as exc:
            logger.warning("Analytics error: %s", exc, exc_info=True)
            return {}

    def _handle_zone_exits(
        self,
        analytics_res: dict[str, Any],
        tracks: dict[int, Any],
        timestamp: float,
    ) -> None:
        """Forward zone exit events to optional cross-camera topology."""
        if self.topology is None or not analytics_res:
            return
        camera_id = self.bundle.config.camera_id
        for ev in analytics_res.get("new_events", []):
            action = ev.get("action") or ev.get("event_type")
            if action not in ("exit", "zone_exit"):
                continue
            tid = ev.get("track_id")
            trk = tracks.get(tid)
            ent_id = getattr(trk, "entity_id", None) if trk else None
            ent_name = (
                getattr(trk, "entity_name", getattr(trk, "identity_label", f"Track #{tid}"))
                if trk
                else f"Track #{tid}"
            )
            self.topology.record_zone_exit(
                camera_id=camera_id,
                zone_name=ev.get("zone_id"),
                entity_name=ent_name,
                entity_id=ent_id,
                timestamp=timestamp,
            )

    def _run_reid(
        self,
        frame: np.ndarray,
        tracks: dict[int, Any],
        timestamp: float,
    ) -> list[Any]:
        """Run Re-ID gallery matching and publish identification/restricted events."""
        matcher = self.bundle.gallery_matcher
        if matcher is None or not tracks:
            return []
        try:
            if self.topology is not None and getattr(matcher, "topology", None) is None:
                matcher.topology = self.topology
            events = list(
                matcher.match_tracks(
                    tracks=tracks,
                    frame=frame,
                    source=str(self.bundle.config.source),
                    timestamp=timestamp,
                )
                or []
            )
            self._publish_id_events(frame, tracks, events, timestamp)
            return events
        except Exception as exc:
            logger.debug("Re-ID matching error: %s", exc)
            return []

    def _publish_id_events(
        self,
        frame: np.ndarray,
        tracks: dict[int, Any],
        events: list[Any],
        timestamp: float,
    ) -> None:
        """Publish EntityIdentifiedEvent and RestrictedEntityAlert to EventBus."""
        bus = self.bundle.event_bus
        if bus is None or not events:
            return
        camera_id = (
            getattr(self.bundle.analytics, "camera_id", None)
            or self.bundle.config.camera_id
        )
        for ev in events:
            try:
                trk = tracks.get(ev.track_id)
                snap_b64 = getattr(ev, "snapshot_base64", None)
                if snap_b64 is None and trk is not None and getattr(trk, "bbox", None) is not None:
                    snap_b64 = crop_to_base64(frame, trk.bbox)

                if isinstance(ev, EntityIdentifiedEvent):
                    if not ev.camera_id:
                        ev.camera_id = camera_id
                    if ev.snapshot_base64 is None:
                        ev.snapshot_base64 = snap_b64
                    bus.publish(ev)
                else:
                    bus.publish(EntityIdentifiedEvent(
                        camera_id=camera_id,
                        track_id=ev.track_id,
                        entity_id=getattr(ev, "entity_id", 0),
                        name=ev.name,
                        category=ev.category,
                        similarity=ev.similarity,
                        snapshot_base64=snap_b64,
                        timestamp=timestamp,
                    ))

                if str(getattr(ev, "category", "")).lower() in _RESTRICTED_CATEGORIES:
                    bus.publish(RestrictedEntityAlert(
                        camera_id=camera_id,
                        track_id=ev.track_id,
                        entity_id=getattr(ev, "entity_id", 0),
                        name=ev.name,
                        category=ev.category,
                        severity="critical",
                        message=f"Restricted entity '{ev.name}' detected",
                        snapshot_base64=snap_b64,
                        timestamp=timestamp,
                    ))
            except Exception as exc:
                logger.debug("Event publish error: %s", exc)

