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
import asyncio
import logging
import os
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import jinja2

from dashboard.camera_pool import CameraPool
from dashboard.dependencies import (
    CROPS_DIR,
    STATIC_DIR,
    TEMPLATES_DIR,
    VIDEOS_DIR,
    _get_active_learning_mgr,
    _get_db,
    _get_enrollment_mgr,
    _get_rsac_mgr,
    _get_scenario_mgr,
    _reload_all_galleries,
    bind_app_state,
    clear_app_state,
    get_active_learning_mgr,
    get_active_stream_manager,
    get_camera_pool,
    get_db,
    get_enrollment_mgr,
    get_lifecycle_manager,
    get_rsac_mgr,
    get_scenario_mgr,
    get_stream_manager,
    get_world_query_engine,
    reload_all_galleries,
    set_shutting_down,
)
from dashboard.routers import (
    analytics_router,
    cameras_router,
    camera_diagnostics_router,
    camera_recording_router,
    categories_router,
    categories_and_collision_router,
    events_admin_router,
    gallery_health_router,
    learned_classes_router,
    multiview_router,
    processing_mode_router,
    review_router,
    rsac_router,
    scenarios_router,
    streaming_router,
    system_router,
    tagging_router,
    topology_router,
    videos_router,
    world_router,
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
    WorldQueryRequest,
    ZoneCreateRequest,
)
from dashboard.services.diagnostic_bridge import (
    DiagnosticTraceMiddleware,
    init_diagnostic_tracer,
)
from dashboard.services.diagnostic_log_handler import (
    install_diagnostic_log_handler,
    remove_diagnostic_log_handler,
)
from dashboard.services.security_config import parse_allowed_origins
from dashboard.services.process_supervisor import (
    set_parent_death_signal,
    start_parent_watchdog,
    stop_parent_watchdog,
)
from dashboard.services.shutdown_handler import (
    GracefulCancellationMiddleware,
    async_shutdown_pool,
    install_shutdown_handlers,
)
from dashboard.services.video_transcoder import VideoTranscodeService
from dashboard.services.windows_resilience import apply_windows_iocp_patch
from dashboard.stream_manager import StreamManager
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.lifecycle import StreamLifecycleManager
from intelligent_tracker.memory import ConfidenceEngine, GeminiSemanticProvider, WorldQueryEngine
from intelligent_tracker.scenarios import ScenarioManager

logger = logging.getLogger("intelligent_tracker.dashboard")

_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader([STATIC_DIR, TEMPLATES_DIR]),
    autoescape=jinja2.select_autoescape(["html", "xml"]),
)

# Apply Windows IOCP Proactor socket resilience for transient drops on startup
apply_windows_iocp_patch()

# Initialize runtime diagnostic trace recorder for structured crash capture
init_diagnostic_tracer()

# Global module references for test fixtures and backward-compatibility
camera_pool: Optional[CameraPool] = None
stream_manager: Optional[StreamManager] = None
scenario_manager: Optional[ScenarioManager] = None
lifecycle_manager: Optional[StreamLifecycleManager] = None

# Backward compatibility alias
_probe_video_file = VideoTranscodeService.probe_video


def _init_runtime_services(application: FastAPI):
    """Initialize CameraPool, ScenarioManager, TrackerDB, and StreamLifecycleManager."""
    cfg_file = os.getenv("CAMERAS_CONFIG_PATH") or "configs/cameras.json"
    db_file = os.getenv("TRACKER_DB_PATH") or "data/tracker.db"
    scen_file = os.getenv("SCENARIOS_CONFIG_PATH") or "configs/scenarios.yaml"
    pool = CameraPool(config_file=cfg_file, db_path=db_file)
    primary_sm = pool.primary_stream
    db = TrackerDB(db_file)
    owned_db: Optional[TrackerDB] = db
    scen_mgr = ScenarioManager(
        config_path=scen_file,
        db=db,
        db_path=db_file,
        world_graph=getattr(pool, "world_graph", None),
        coordinate_mapper=getattr(pool, "coordinate_mapper", None),
    )
    handoff = getattr(pool, "handoff_coordinator", None)
    if handoff is not None:
        handoff.topology, handoff.transition_registry = scen_mgr.topology, scen_mgr.world_transitions
    if getattr(pool, "_coordinator", None) is not None:
        pool._coordinator.scenario_manager = scen_mgr
    lifecycle_mgr = StreamLifecycleManager(db=db, camera_pool=pool)
    world_graph = getattr(pool, "world_graph", None) or getattr(scen_mgr, "world_graph", None)
    event_bus = getattr(pool, "event_bus", None) or getattr(primary_sm, "event_bus", None)
    event_fts_index = getattr(pool, "event_fts_index", None) or getattr(primary_sm, "event_fts_index", None)
    conf_engine = getattr(pool, "confidence_engine", None) or getattr(primary_sm, "confidence_engine", None) or ConfidenceEngine(db=db)
    provider = GeminiSemanticProvider() if os.getenv("WORLD_QUERY_PROVIDER", "").strip().lower() == "gemini" else None
    world_query_engine = WorldQueryEngine(db=db, confidence_engine=conf_engine, world_graph=world_graph, provider=provider)
    bind_app_state(
        application, camera_pool=pool, stream_manager=primary_sm, scenario_manager=scen_mgr,
        lifecycle_manager=lifecycle_mgr, db=db, confidence_engine=conf_engine, world_query_engine=world_query_engine,
        world_graph=world_graph, event_bus=event_bus, event_fts_index=event_fts_index,
    )
    from dashboard.services.camera_pool_queries import snapshot_pool_streams
    for sm in snapshot_pool_streams(pool).values():
        scen_mgr.apply_to_stream_manager(sm)
    try:
        from intelligent_tracker.reid.gallery_reembed import reembed_mismatched_signatures

        reembed_mismatched_signatures(db)
    except Exception as exc:
        logger.warning("Startup gallery re-embed check skipped: %s", exc)
    return pool, primary_sm, lifecycle_mgr, owned_db


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Lifespan context manager starting and stopping the CameraPool, ScenarioManager and pipelines."""
    install_shutdown_handlers()
    set_parent_death_signal()
    start_parent_watchdog()
    log_handler = install_diagnostic_log_handler()
    logger.info("Initializing Intelligent Tracker CameraPool & ScenarioManager...")
    pool, primary_sm, lifecycle_mgr, owned_db = _init_runtime_services(application)

    yield
    logger.info("Shutting down Intelligent Tracker CameraPool...")
    set_shutting_down(True)
    if lifecycle_mgr:
        lifecycle_mgr.stop_sampler()
    if pool:
        await async_shutdown_pool(pool)
    elif primary_sm:
        await asyncio.to_thread(primary_sm.stop)
    if owned_db is not None:
        owned_db.close()
    clear_app_state(application)
    remove_diagnostic_log_handler(log_handler)
    stop_parent_watchdog()


def _attach_static_no_cache(application: FastAPI) -> None:
    """Ensure /static/* assets always revalidate with ETag so JS/CSS edits take effect on reload."""
    @application.middleware("http")
    async def _static_no_cache(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers.setdefault("Cache-Control", "no-cache")
        return response


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
        allow_origins=parse_allowed_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(GracefulCancellationMiddleware)
    application.add_middleware(DiagnosticTraceMiddleware)
    _attach_static_no_cache(application)

    # Mount static assets and crops
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    application.mount("/crops", StaticFiles(directory=CROPS_DIR), name="crops")

    # Mount domain APIRouters
    for router in (
        system_router, cameras_router, camera_diagnostics_router,
        camera_recording_router, categories_router, categories_and_collision_router,
        events_admin_router, gallery_health_router, learned_classes_router, processing_mode_router, multiview_router,
        streaming_router, scenarios_router, review_router, rsac_router, analytics_router,
        tagging_router, videos_router, topology_router, world_router,
    ):
        application.include_router(router)

    return application


app = create_app()


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Serve the modern single-page dashboard."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return HTMLResponse(content=_jinja_env.get_template("index.html").render())
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
    "get_world_query_engine",
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
    "WorldQueryRequest",
]
