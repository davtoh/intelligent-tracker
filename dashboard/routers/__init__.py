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
- world: World intelligence Q&A, entity confidence, and FTS5 timeline search
"""

from dashboard.routers.alert_rules import router as alert_rules_router
from dashboard.routers.analytics import router as analytics_router
from dashboard.routers.cameras import router as cameras_router
from dashboard.routers.camera_diagnostics import router as camera_diagnostics_router
from dashboard.routers.camera_recording import router as camera_recording_router
from dashboard.routers.categories import router as categories_router
from dashboard.routers.categories_and_collision import router as categories_and_collision_router
from dashboard.routers.events_admin import router as events_admin_router
from dashboard.routers.gallery_health import router as gallery_health_router
from dashboard.routers.learned_classes import router as learned_classes_router
from dashboard.routers.multiview import router as multiview_router
from dashboard.routers.processing_mode import router as processing_mode_router
from dashboard.routers.review import router as review_router
from dashboard.routers.rsac import router as rsac_router
from dashboard.routers.scenarios import router as scenarios_router
from dashboard.routers.streaming import router as streaming_router
from dashboard.routers.system import router as system_router
from dashboard.routers.tagging import router as tagging_router
from dashboard.routers.topology import router as topology_router
from dashboard.routers.videos import router as videos_router
from dashboard.routers.world import router as world_router

__all__ = [
    "alert_rules_router",
    "analytics_router",
    "cameras_router",
    "camera_diagnostics_router",
    "camera_recording_router",
    "categories_router",
    "categories_and_collision_router",
    "events_admin_router",
    "gallery_health_router",
    "learned_classes_router",
    "multiview_router",
    "processing_mode_router",
    "review_router",
    "rsac_router",
    "scenarios_router",
    "streaming_router",
    "system_router",
    "tagging_router",
    "topology_router",
    "videos_router",
    "world_router",
]

