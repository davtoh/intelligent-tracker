"""
Intelligent Tracker - Web Dashboard & Edge Video Management System (VMS).

Slim application factory and entrypoint mounting modular domain APIRouters:
- streaming: MJPEG video, WebSocket telemetry & status
- cameras: Camera CRUD, ONVIF/RTSP discovery, test & presets
- videos: Local recordings, scrubber, upload & H.264 transcoding
- scenarios: Zones, tripwires, 4-point homography & BEV minimap
- topology: Spatial transitions, Markov transit priors & trajectory journeys
- analytics: Occupancy heatmaps, entity CRUD, sightings & click-to-tag
- rsac: Role-Based Spatial Access Control, Active Learning queue & enrollment
- system: Backups, process lifecycle diagnostics, subscriber eviction & metrics
"""

from __future__ import annotations

import os
import logging
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

import dashboard.dependencies as deps
from dashboard.camera_pool import CameraPool
from dashboard.stream_manager import StreamManager
from intelligent_tracker.scenarios import ScenarioManager
from intelligent_tracker.lifecycle import StreamLifecycleManager

# Import Domain Routers
from dashboard.routers import (
    streaming_router,
    cameras_router,
    videos_router,
    scenarios_router,
    topology_router,
    analytics_router,
    rsac_router,
    system_router,
)

# Re-export Schemas for backward compatibility
from dashboard.schemas import *  # noqa: F401, F403
from dashboard.services.video_transcoder import VideoTranscodeService

logger = logging.getLogger("intelligent_tracker.dashboard")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
STATIC_DIR = os.path.join(BASE_DIR, "static")
DATA_DIR = os.path.join(PROJECT_DIR, "data")
CROPS_DIR = os.path.join(DATA_DIR, "crops")
VIDEOS_DIR = os.path.join(DATA_DIR, "videos")

os.makedirs(CROPS_DIR, exist_ok=True)
os.makedirs(VIDEOS_DIR, exist_ok=True)

# -----------------------------------------------------------------------------
# Global Singletons (Delegated to dependencies module for backward compatibility)
# -----------------------------------------------------------------------------
camera_pool: Optional[CameraPool] = None
stream_manager: Optional[StreamManager] = None
scenario_manager: Optional[ScenarioManager] = None
lifecycle_manager: Optional[StreamLifecycleManager] = None


def get_lifecycle_manager() -> StreamLifecycleManager:
    return deps.get_lifecycle_manager()


def get_active_stream_manager(camera_id: Optional[str] = None) -> Optional[StreamManager]:
    # Check local module override first (supports test monkeypatching)
    global stream_manager, camera_pool
    if camera_pool:
        mgr = camera_pool.get_stream(camera_id)
        if mgr:
            return mgr
    if stream_manager:
        return stream_manager
    return deps.get_active_stream_manager(camera_id)


def _get_db():
    return deps.get_db()


def _get_rsac_mgr():
    return deps.get_rsac_mgr()


def _get_active_learning_mgr():
    return deps.get_active_learning_mgr()


def _get_enrollment_mgr():
    return deps.get_enrollment_mgr()


def _reload_all_galleries():
    deps.reload_all_galleries()


def _probe_video_file(path: str):
    return VideoTranscodeService.probe_video_file(path)


# -----------------------------------------------------------------------------
# Lifespan Lifecycle
# -----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager starting and stopping the CameraPool and pipelines."""
    global stream_manager, camera_pool, scenario_manager, lifecycle_manager
    logger.info("Initializing Intelligent Tracker CameraPool & ScenarioManager...")

    if camera_pool is None:
        camera_pool = CameraPool()
    if stream_manager is None:
        stream_manager = camera_pool.primary_stream
    if scenario_manager is None:
        scenario_manager = ScenarioManager()

    db = stream_manager.db if stream_manager else None
    lifecycle_manager = StreamLifecycleManager(db=db, camera_pool=camera_pool)

    # Sync singletons into dependencies module
    deps.set_camera_pool(camera_pool)
    deps.set_stream_manager(stream_manager)
    deps.set_scenario_manager(scenario_manager)
    deps.set_lifecycle_manager(lifecycle_manager)

    # Apply loaded scenarios to active streams
    if camera_pool:
        for sm in camera_pool.streams.values():
            scenario_manager.apply_to_stream_manager(sm)
    elif stream_manager:
        scenario_manager.apply_to_stream_manager(stream_manager)

    yield

    logger.info("Shutting down Intelligent Tracker CameraPool...")
    if lifecycle_manager:
        lifecycle_manager.stop_sampler()
    if camera_pool:
        camera_pool.stop_all()
    elif stream_manager:
        stream_manager.stop()


# -----------------------------------------------------------------------------
# App Construction & Router Mounting
# -----------------------------------------------------------------------------
app = FastAPI(
    title="Intelligent Tracker Web Dashboard & VMS",
    description="Edge AI Retail & Security Analytics Multi-Camera VMS Platform",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static Mounts
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

if os.path.exists(CROPS_DIR):
    app.mount("/crops", StaticFiles(directory=CROPS_DIR), name="crops")

if os.path.exists(VIDEOS_DIR):
    app.mount("/data/videos", StaticFiles(directory=VIDEOS_DIR), name="data_videos")

# Mount Domain APIRouters
app.include_router(streaming_router)
app.include_router(cameras_router)
app.include_router(videos_router)
app.include_router(scenarios_router)
app.include_router(topology_router)
app.include_router(analytics_router)
app.include_router(rsac_router)
app.include_router(system_router)
