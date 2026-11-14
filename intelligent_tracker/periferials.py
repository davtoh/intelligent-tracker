#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Deprecated compatibility re-exports for legacy camera wrappers.

.. deprecated::
    Import :class:`intelligent_tracker.video.VideoSource` for modern ingestion,
    or import legacy wrappers directly from
    :mod:`intelligent_tracker.video.legacy_camera` and
    :mod:`intelligent_tracker.video.legacy_sync`.
"""

from intelligent_tracker.video.legacy_camera import (
    CameraError,
    MockVideoCapture,
    PiCamera,
    PiRGBArray,
    UnifiedCamera,
)
from intelligent_tracker.video.legacy_sync import SyncCameras, VideoStream

__all__ = [
    "CameraError",
    "MockVideoCapture",
    "UnifiedCamera",
    "PiRGBArray",
    "PiCamera",
    "VideoStream",
    "SyncCameras",
]
