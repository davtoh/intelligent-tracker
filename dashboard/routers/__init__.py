#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Dashboard API Routers Package.

Exports the 8 domain APIRouters:
- system: Diagnostics, lifecycle process management, and backup export/import
- cameras: Camera pool CRUD, discovery, telemetry, and overlays
- streaming: Real-time MJPEG live stream and WebSockets
- scenarios: Zones, tripwires, 4-point homography calibration, and BEV minimap
- rsac: Role-Based Spatial Access Control, Active Learning queue, and enrollment
- analytics: Heatmap, entities, sightings, and event alerts
- videos: Video file management, uploads, transcoding, and scrubber serving
- topology: Spatial transitions and multi-camera trajectory journey search
"""

from __future__ import annotations

from dashboard.routers.analytics import router as analytics_router
from dashboard.routers.cameras import router as cameras_router
from dashboard.routers.camera_diagnostics import router as camera_diagnostics_router
from dashboard.routers.rsac import router as rsac_router
from dashboard.routers.scenarios import router as scenarios_router
from dashboard.routers.streaming import router as streaming_router
from dashboard.routers.system import router as system_router
from dashboard.routers.topology import router as topology_router
from dashboard.routers.videos import router as videos_router

__all__ = [
    "analytics_router",
    "cameras_router",
    "camera_diagnostics_router",
    "rsac_router",
    "scenarios_router",
    "streaming_router",
    "system_router",
    "topology_router",
    "videos_router",
]

