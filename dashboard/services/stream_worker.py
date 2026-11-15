"""Intelligent Tracker - Stream Worker Service.

Executes the continuous frame ingestion, FrameProcessor vision stepping,
overlay encoding, and telemetry distribution loop.
"""

import logging
import os
import time
from typing import Any

import cv2
import numpy as np

from dashboard.services.camera_diagnostics import CameraHealthManager
from dashboard.services.stream_telemetry import (
    _build_tripwires_data,
    _build_zones_data,
    _extract_recent_alerts,
    _extract_track_telemetry,
    _resolve_detector_telemetry,
    build_stream_telemetry,
)
from intelligent_tracker.pipeline import (
    FrameProcessor,
    FrameStepResult,
    PipelineBundle,
    PipelineConfig,
)

logger = logging.getLogger("intelligent_tracker.dashboard.worker")


def _diagnose_source_error(vs: Any) -> tuple[str, str]:
    """Diagnose source failure root cause for health manager reporting."""
    if getattr(vs, "is_file", False) and not os.path.exists(str(vs.source)):
        return "FILE_NOT_FOUND", f"Video file not found: {vs.source}"
    if getattr(vs, "is_webcam", False) and not getattr(vs, "_is_connected", False):
        return "DEVICE_LOCKED", f"Camera device #{vs.source} is locked or unavailable"
    if getattr(vs, "is_rtsp", False) and not getattr(vs, "_is_connected", False):
        return "RTSP_TIMEOUT", f"RTSP connection timed out: {vs.source}"
    return "NO_FRAMES_DECODED", "No video frames could be decoded from source"


class StreamWorker:
    """Collaborator executing continuous background video pipeline loop."""

    def __init__(self, manager: Any) -> None:
        self.manager = manager
        self._processor: FrameProcessor | None = None

    def _get_processor(self) -> FrameProcessor:
        """Lazily build and synchronize the canonical FrameProcessor."""
        if self._processor is None:
            bundle = getattr(self.manager, "_pipeline_bundle", None)
            if bundle is None:
                bundle = PipelineBundle(
                    config=PipelineConfig(camera_id=getattr(self.manager, "camera_id", "default")),
                    db=getattr(self.manager, "db", None),
                    video_source=getattr(self.manager, "video_source", None),
                    detector=getattr(self.manager, "detector", None),
                    tracker=getattr(self.manager, "tracker", None),
                    analytics=getattr(self.manager, "analytics", None),
                    reid_extractor=getattr(self.manager, "reid_extractor", None),
                    gallery_matcher=getattr(self.manager, "gallery_matcher", None),
                    rsac_manager=getattr(self.manager, "rsac_manager", None),
                    active_learning=getattr(self.manager, "active_learning", None),
                    enrollment_manager=getattr(self.manager, "enrollment_manager", None),
                    event_bus=getattr(self.manager, "event_bus", None),
                    event_pipeline=getattr(self.manager, "event_pipeline", None),
                    world_graph=getattr(self.manager, "world_graph", None),
                    world_bridge=getattr(self.manager, "world_bridge", None),
                    world_rule_engine=getattr(self.manager, "world_rule_engine", None),
                    confidence_engine=getattr(self.manager, "confidence_engine", None),
                )
            self._processor = FrameProcessor(bundle, topology=getattr(self.manager, "topology", None))

        self._processor.topology = getattr(self.manager, "topology", None)
        bundle = self._processor.bundle
        bundle.detector = getattr(self.manager, "detector", bundle.detector)
        bundle.tracker = getattr(self.manager, "tracker", bundle.tracker)
        bundle.analytics = getattr(self.manager, "analytics", bundle.analytics)
        bundle.gallery_matcher = getattr(self.manager, "gallery_matcher", bundle.gallery_matcher)
        bundle.event_bus = getattr(self.manager, "event_bus", bundle.event_bus)
        bundle.world_bridge = getattr(self.manager, "world_bridge", bundle.world_bridge)
        return self._processor

    def run(self) -> None:
        """Continuous pipeline loop executing FrameProcessor, overlays, and telemetry."""
        if not self.manager.video_source:
            return

        processor = self._get_processor()
        consecutive_empty = 0

        with self.manager.video_source as vs:
            while self.manager._running and not self.manager._stop_event.is_set():
                if self._handle_hibernation(vs, processor.frame_count):
                    continue

                ret, frame = vs.read(timeout=1.0)
                if not ret or frame is None:
                    consecutive_empty, should_skip = self._handle_empty_frame(vs, consecutive_empty)
                    if should_skip:
                        continue

                consecutive_empty = 0
                step_res = processor.step(frame, timestamp=time.time(), max_dim=1280)
                if step_res.frame_count % 30 == 1:
                    CameraHealthManager().set_online(self.manager.camera_id, fps=step_res.fps)

                self._process_single_frame(step_res)

    def _process_single_frame(self, step_res: FrameStepResult) -> None:
        """Store raw frame, encode needed overlays, and broadcast telemetry."""
        with self.manager._lock:
            self.manager._latest_raw_frame = step_res.frame.copy()
            raw_missing = getattr(self.manager, "_latest_raw_jpeg", None) is None
            ann_missing = getattr(self.manager, "_latest_jpeg", None) is None

        if getattr(self.manager, "has_raw_subscribers", True) or raw_missing:
            self._encode_raw_frame(step_res.frame)

        recorder = getattr(self.manager, "_recording_controller", None)
        is_rec = bool(recorder is not None and recorder.is_recording)
        if getattr(self.manager, "has_annotated_subscribers", True) or is_rec or ann_missing:
            annotated = self._encode_annotated_frame(step_res.frame, step_res.tracks, step_res.fps)
            if is_rec:
                recorder.write_frame(step_res.frame, annotated, step_res=step_res)

        telemetry = self._build_telemetry(
            step_res.tracks, step_res.timestamp, step_res.fps,
            step_res.frame.shape, step_res.frame_count,
        )
        with self.manager._lock:
            self.manager._latest_telemetry = telemetry

        self.manager._broadcast_telemetry(telemetry)
        self.manager._stop_event.wait(timeout=0.01)

    def _handle_hibernation(self, vs: Any, frame_count: int) -> bool:
        """Pause video capture if zero viewers are connected to conserve compute."""
        is_recording = getattr(self.manager, "is_recording", False)
        if self.manager.subscriber_count <= 0 and not is_recording and frame_count > 0:
            if not self.manager._is_hibernating:
                self.manager._is_hibernating = True
                if hasattr(vs, "pause"):
                    vs.pause()
                with self.manager._lock:
                    if self.manager._latest_telemetry:
                        self.manager._latest_telemetry["fps"] = 0.0
                        self.manager._latest_telemetry["status"] = "hibernating"
            self.manager._stop_event.wait(timeout=0.2)
            return True

        if self.manager._is_hibernating:
            self.manager._is_hibernating = False
            if hasattr(vs, "resume"):
                vs.resume()
            with self.manager._lock:
                if self.manager._latest_telemetry:
                    self.manager._latest_telemetry["status"] = "online"
        return False

    def _handle_empty_frame(self, vs: Any, consecutive_empty: int) -> tuple[int, bool]:
        """Handle missing frames, report diagnostics errors, and generate placeholders."""
        consecutive_empty += 1
        if consecutive_empty >= 4:
            err_code, err_msg = _diagnose_source_error(vs)
            CameraHealthManager().set_error(self.manager.camera_id, err_msg, error_code=err_code)
            with self.manager._lock:
                if self.manager._latest_jpeg is None or (
                    self.manager._latest_telemetry and self.manager._latest_telemetry.get("status") != "error"
                ):
                    self.manager._latest_jpeg = CameraHealthManager().create_error_placeholder_jpeg(
                        self.manager.camera_id,
                        name=self.manager.name,
                        width=self.manager.width,
                        height=self.manager.height,
                    )
                if self.manager._latest_telemetry:
                    self.manager._latest_telemetry["status"] = "error"
                    self.manager._latest_telemetry["fps"] = 0.0
                    self.manager._latest_telemetry["error_code"] = err_code
                    self.manager._latest_telemetry["error_msg"] = err_msg
            self.manager._stop_event.wait(timeout=0.5)
            return consecutive_empty, True

        self.manager._stop_event.wait(timeout=0.04)
        return consecutive_empty, True

    def _process_vision_pipeline(self, frame: np.ndarray, curr_t: float) -> dict[int, Any]:
        """Delegate single-frame CV stepping to canonical FrameProcessor."""
        return self._get_processor().step(frame, timestamp=curr_t, max_dim=1280).tracks

    def _encode_raw_frame(self, frame: np.ndarray) -> None:
        """Compress clean un-annotated frame to JPEG for client-side canvas viewports."""
        ret, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if ret:
            with self.manager._lock:
                self.manager._latest_raw_jpeg = buf.tobytes()

    def _encode_annotated_frame(
        self,
        frame: np.ndarray,
        tracks: dict[int, Any],
        measured_fps: float,
    ) -> np.ndarray:
        """Render floating overlays and compress annotated frame to JPEG."""
        annotated = self.manager._overlay_renderer.render(
            frame=frame,
            tracks=tracks,
            overlays=self.manager.overlays,
            camera_id=self.manager.camera_id,
            measured_fps=measured_fps,
            start_time=self.manager.start_time,
            analytics=self.manager.analytics,
            rsac_manager=self.manager.rsac_manager,
            homography=self.manager.homography,
            draw_heatmap=self.manager.draw_heatmap,
        )
        ret, buf = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if ret:
            with self.manager._lock:
                self.manager._latest_jpeg = buf.tobytes()
        return annotated

    def _build_telemetry(
        self,
        tracks: dict[int, Any],
        curr_t: float,
        measured_fps: float,
        shape: tuple[int, ...],
        frame_count: int,
    ) -> dict[str, Any]:
        """Construct comprehensive telemetry payload with ground plane projections."""
        return build_stream_telemetry(
            self.manager, tracks, curr_t, measured_fps, shape, frame_count
        )
