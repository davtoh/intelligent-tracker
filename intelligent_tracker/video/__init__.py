"""Non-blocking Threaded Video Ingestion Package.

Re-exports 100% of video ingestion sources, synthetic generators, and physical camera
resolvers to preserve backward compatibility across all modules and tests.
"""

from intelligent_tracker.video.capture_guard import CaptureReadGuard, CircuitState
from intelligent_tracker.video.devices import (
    find_first_real_camera,
    find_physical_cameras,
    is_physical_camera,
    resolve_camera_source,
)
from intelligent_tracker.video.source import VideoSource
from intelligent_tracker.video.synthetic import SyntheticFrameGenerator
from intelligent_tracker.video.writers import PipelineVideoWriter

__all__ = [
    "CaptureReadGuard",
    "CircuitState",
    "VideoSource",
    "SyntheticFrameGenerator",
    "PipelineVideoWriter",
    "is_physical_camera",
    "find_physical_cameras",
    "find_first_real_camera",
    "resolve_camera_source",
]

