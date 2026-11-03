#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Modern Web Dashboard Application & Multi-Camera VMS.

Modular FastAPI Application Factory providing:
- Multi-Camera VMS & Dynamic Stream Pool
- Real-Time Live MJPEG Streaming & Telemetry WebSockets
- Scenario Studio (Zones, Tripwires, Homography, BEV Minimap)
- Role-Based Spatial Access Control (RSAC) & Active Learning
- Analytics, Heatmap Density & Sighting Timeline
- Local Video Recording Studio & Scrubber
- System State Persistence, Diagnostics & One-Click Backup
- Single-page web UI served at GET /
"""

from contextlib import asynccontextmanager
import logging
import os
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from dashboard.camera_pool import CameraPool
from dashboard.dependencies import (
    CROPS_DIR,
    STATIC_DIR,
    VIDEOS_DIR,
    _get_active_learning_mgr,
    _get_db,
    _get_enrollment_mgr,
    _get_rsac_mgr,
    _get_scenario_mgr,
    _reload_all_galleries,
    get_active_learning_mgr,
    get_active_stream_manager,
    get_camera_pool,
    get_db,
    get_enrollment_mgr,
    get_lifecycle_manager,
    get_rsac_mgr,
    get_scenario_manager,
    get_scenario_mgr,
    get_stream_manager,
    reload_all_galleries,
    set_camera_pool,
    set_lifecycle_manager,
    set_scenario_manager,
    set_shutting_down,
    set_stream_manager,
)
from dashboard.routers import (
    analytics_router,
    cameras_router,
    camera_diagnostics_router,
    rsac_router,
    scenarios_router,
    streaming_router,
    system_router,
    topology_router,
    videos_router,
)
from dashboard.schemas import (
    CameraAddRequest,
    CameraTestRequest,
    CameraUpdateRequest,
    CustomCategoryCreateRequest,
    EnrollmentRequest,
    EntityCreateRequest,
    EntityUpdateRequest,
    HomographyCalibrationRequest,
    JourneyExportRequest,
    OverlayUpdateRequest,
    PetWhitelistRequest,
    ReviewConfirmRequest,
    ReviewDismissRequest,
    ReviewEnrollNewRequest,
    ReviewReassignRequest,
    RollbackRequest,
    RSACRuleCreateRequest,
    SpatialTransitionRequest,
    TagRequest,
    TripwireCreateRequest,
    ZoneCreateRequest,
)
from dashboard.services.video_transcoder import VideoTranscodeService
from dashboard.stream_manager import StreamManager
from intelligent_tracker.lifecycle import StreamLifecycleManager
from intelligent_tracker.scenarios import ScenarioManager

logger = logging.getLogger("intelligent_tracker.dashboard")

# Global module references for test fixtures and backward-compatibility
camera_pool: Optional[CameraPool] = None
stream_manager: Optional[StreamManager] = None
scenario_manager: Optional[ScenarioManager] = None
lifecycle_manager: Optional[StreamLifecycleManager] = None

# Backward compatibility alias
_probe_video_file = VideoTranscodeService.probe_video


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager starting and stopping the CameraPool, ScenarioManager and pipelines."""
    global stream_manager, camera_pool, scenario_manager, lifecycle_manager
    logger.info("Initializing Intelligent Tracker CameraPool & ScenarioManager...")
    camera_pool = CameraPool()
    set_camera_pool(camera_pool)
    stream_manager = camera_pool.primary_stream
    set_stream_manager(stream_manager)
    scenario_manager = ScenarioManager()
    set_scenario_manager(scenario_manager)
    db = stream_manager.db if stream_manager else None
    lifecycle_manager = StreamLifecycleManager(db=db, camera_pool=camera_pool)
    set_lifecycle_manager(lifecycle_manager)

    # Apply loaded scenarios to active streams
    if camera_pool:
        for sm in camera_pool.streams.values():
            scenario_manager.apply_to_stream_manager(sm)
    elif stream_manager:
        scenario_manager.apply_to_stream_manager(stream_manager)

    yield
    logger.info("Shutting down Intelligent Tracker CameraPool...")
    set_shutting_down(True)
    if lifecycle_manager:
        lifecycle_manager.stop_sampler()
    if camera_pool:
        camera_pool.stop_all()
    elif stream_manager:
        stream_manager.stop()


def create_app() -> FastAPI:
    """FastAPI Application Factory mounting routers, static assets, and middleware."""
    application = FastAPI(
        title="Intelligent Tracker Web Dashboard & VMS",
        description="Edge AI Retail & Security Analytics Multi-Camera VMS Platform",
        version="1.2.0",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount static assets and crops
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    application.mount("/crops", StaticFiles(directory=CROPS_DIR), name="crops")

    # Mount domain APIRouters
    application.include_router(system_router)
    application.include_router(cameras_router)
    application.include_router(camera_diagnostics_router)
    application.include_router(streaming_router)
    application.include_router(scenarios_router)
    application.include_router(rsac_router)
    application.include_router(analytics_router)
    application.include_router(videos_router)
    application.include_router(topology_router)

    return application


app = create_app()


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Serve the modern single-page dashboard."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Intelligent Tracker Dashboard Initializing...</h1>")


__all__ = [
    "app",
    "create_app",
    "camera_pool",
    "stream_manager",
    "scenario_manager",
    "lifecycle_manager",
    "get_active_stream_manager",
    "get_camera_pool",
    "get_stream_manager",
    "get_scenario_mgr",
    "get_lifecycle_manager",
    "get_db",
    "get_rsac_mgr",
    "get_active_learning_mgr",
    "get_enrollment_mgr",
    "reload_all_galleries",
    "_get_db",
    "_get_rsac_mgr",
    "_get_active_learning_mgr",
    "_get_enrollment_mgr",
    "_get_scenario_mgr",
    "_reload_all_galleries",
    "_probe_video_file",
    "STATIC_DIR",
    "VIDEOS_DIR",
    "CROPS_DIR",
    "CameraAddRequest",
    "CameraUpdateRequest",
    "CameraTestRequest",
    "ZoneCreateRequest",
    "TripwireCreateRequest",
    "HomographyCalibrationRequest",
    "SpatialTransitionRequest",
    "OverlayUpdateRequest",
    "JourneyExportRequest",
    "EnrollmentRequest",
    "ReviewConfirmRequest",
    "ReviewReassignRequest",
    "ReviewEnrollNewRequest",
    "ReviewDismissRequest",
    "CustomCategoryCreateRequest",
    "RSACRuleCreateRequest",
    "PetWhitelistRequest",
    "RollbackRequest",
    "EntityCreateRequest",
    "EntityUpdateRequest",
    "TagRequest",
]
