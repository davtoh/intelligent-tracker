#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Dashboard FastAPI Dependencies & App State Providers.

Resolves CameraPool, StreamManager, ScenarioManager, StreamLifecycleManager,
TrackerDB, and vision managers from FastAPI ``app.state`` (supporting
``app.dependency_overrides``) with standalone module fallbacks for non-request
background and signal-handler callers.
"""

import asyncio
import logging
import os
from typing import Any, Optional

from fastapi import FastAPI
from fastapi.requests import HTTPConnection

from dashboard.camera_pool import CameraPool
from dashboard.stream_manager import StreamManager
from intelligent_tracker.active_learning import ActiveLearningManager
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.enrollment import UniversalEnrollmentManager
from intelligent_tracker.lifecycle import StreamLifecycleManager
from intelligent_tracker.rsac import RSACManager
from intelligent_tracker.scenarios import ScenarioManager

logger = logging.getLogger("intelligent_tracker.dashboard.dependencies")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
VIDEOS_DIR = os.path.join("data", "videos")
CROPS_DIR = os.path.join("data", "crops")

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(VIDEOS_DIR, exist_ok=True)
os.makedirs(CROPS_DIR, exist_ok=True)

_camera_pool: Optional[CameraPool] = None
_stream_manager: Optional[StreamManager] = None
_scenario_manager: Optional[ScenarioManager] = None
_lifecycle_manager: Optional[StreamLifecycleManager] = None
_shutdown_event: Optional[asyncio.Event] = None
_is_shutting_down: bool = False


def _from_app_state(conn: Optional[HTTPConnection], attr: str, fallback: Any) -> Any:
    """Resolve an attribute from ``conn.app.state`` before falling back to module state."""
    if conn is not None:
        val = getattr(conn.app.state, attr, None)
        if val is not None:
            return val
    return fallback


def bind_app_state(
    app: FastAPI,
    *,
    camera_pool: Optional[CameraPool] = None,
    stream_manager: Optional[StreamManager] = None,
    scenario_manager: Optional[ScenarioManager] = None,
    lifecycle_manager: Optional[StreamLifecycleManager] = None,
    db: Optional[TrackerDB] = None,
) -> None:
    """Bind core runtime services to ``app.state`` and sync standalone fallbacks."""
    global _camera_pool, _stream_manager, _scenario_manager, _lifecycle_manager
    app.state.camera_pool = camera_pool
    app.state.stream_manager = stream_manager
    app.state.scenario_manager = scenario_manager
    app.state.lifecycle_manager = lifecycle_manager
    app.state.db = db
    _camera_pool = camera_pool
    _stream_manager = stream_manager
    _scenario_manager = scenario_manager
    _lifecycle_manager = lifecycle_manager


def clear_app_state(app: FastAPI) -> None:
    """Clear all runtime service references from ``app.state`` and module fallbacks."""
    bind_app_state(app)


def get_shutdown_event() -> asyncio.Event:
    """Retrieve or initialize the application-wide asyncio shutdown event for active loop."""
    global _shutdown_event
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if _shutdown_event is None:
        _shutdown_event = asyncio.Event()
    elif current_loop is not None and getattr(_shutdown_event, "_loop", None) is not None:
        if _shutdown_event._loop is not current_loop:
            _shutdown_event = asyncio.Event()

    if _is_shutting_down and not _shutdown_event.is_set():
        _shutdown_event.set()

    return _shutdown_event


def is_shutting_down() -> bool:
    """Return True if the dashboard service is currently shutting down."""
    return _is_shutting_down


def set_shutting_down(shutting_down: bool = True) -> None:
    """Signal all active video streaming generators and WebSocket channels to disconnect."""
    global _is_shutting_down
    _is_shutting_down = shutting_down
    if _shutdown_event is not None:
        try:
            loop = getattr(_shutdown_event, "_loop", None)
            if loop and loop.is_running():
                cb = _shutdown_event.set if shutting_down else _shutdown_event.clear
                loop.call_soon_threadsafe(cb)
            elif shutting_down:
                _shutdown_event.set()
            else:
                _shutdown_event.clear()
        except Exception:
            pass


def get_camera_pool(conn: HTTPConnection = None) -> Optional[CameraPool]:
    """Resolve active CameraPool from ``app.state`` or standalone fallback."""
    return _from_app_state(conn, "camera_pool", _camera_pool)


def set_camera_pool(pool: Optional[CameraPool], app: Optional[FastAPI] = None) -> None:
    """Set active CameraPool fallback and optionally bind ``app.state``."""
    global _camera_pool
    _camera_pool = pool
    if app is not None:
        app.state.camera_pool = pool


def get_stream_manager(conn: HTTPConnection = None) -> Optional[StreamManager]:
    """Resolve active StreamManager from ``app.state`` or standalone fallback."""
    return _from_app_state(conn, "stream_manager", _stream_manager)


def set_stream_manager(mgr: Optional[StreamManager], app: Optional[FastAPI] = None) -> None:
    """Set active StreamManager fallback and optionally bind ``app.state``."""
    global _stream_manager
    _stream_manager = mgr
    if app is not None:
        app.state.stream_manager = mgr


def get_scenario_manager(conn: HTTPConnection = None) -> Optional[ScenarioManager]:
    """Resolve ScenarioManager from ``app.state`` or standalone fallback."""
    return _from_app_state(conn, "scenario_manager", _scenario_manager)


def set_scenario_manager(mgr: Optional[ScenarioManager], app: Optional[FastAPI] = None) -> None:
    """Set active ScenarioManager fallback and optionally bind ``app.state``."""
    global _scenario_manager
    _scenario_manager = mgr
    if app is not None:
        app.state.scenario_manager = mgr


def get_scenario_mgr(conn: HTTPConnection = None) -> ScenarioManager:
    """Ensure and return active ScenarioManager singleton."""
    global _scenario_manager
    mgr = get_scenario_manager(conn)
    if mgr is None:
        mgr = ScenarioManager()
        _scenario_manager = mgr
        if conn is not None:
            conn.app.state.scenario_manager = mgr
    return mgr


def get_lifecycle_manager(conn: HTTPConnection = None) -> StreamLifecycleManager:
    """Ensure and return active StreamLifecycleManager instance."""
    global _lifecycle_manager
    lm = _from_app_state(conn, "lifecycle_manager", _lifecycle_manager)
    pool = get_camera_pool(conn)
    if lm is None:
        sm = get_stream_manager(conn)
        lm = StreamLifecycleManager(
            db=sm.db if sm else None,
            camera_pool=pool,
            autostart_sampler=False,
        )
        _lifecycle_manager = lm
        if conn is not None:
            conn.app.state.lifecycle_manager = lm

    if pool and lm.camera_pool is None:
        lm.set_camera_pool(pool)
    return lm


def set_lifecycle_manager(
    lm: Optional[StreamLifecycleManager],
    app: Optional[FastAPI] = None,
) -> None:
    """Set active StreamLifecycleManager fallback and optionally bind ``app.state``."""
    global _lifecycle_manager
    _lifecycle_manager = lm
    if app is not None:
        app.state.lifecycle_manager = lm


def resolve_stream_manager(
    camera_id: Optional[str] = None,
    pool: Optional[CameraPool] = None,
    sm: Optional[StreamManager] = None,
) -> Optional[StreamManager]:
    """Resolve active StreamManager for ``camera_id`` from supplied pool/stream."""
    if pool:
        mgr = pool.get_stream(camera_id)
        if mgr:
            return mgr
    if sm and (not camera_id or sm.camera_id == camera_id):
        return sm
    if pool:
        return pool.primary_stream
    return sm


def get_active_stream_manager(
    camera_id: Optional[str] = None,
    conn: HTTPConnection = None,
) -> Optional[StreamManager]:
    """Resolve active StreamManager for a camera ID or default primary channel."""
    return resolve_stream_manager(
        camera_id=camera_id,
        pool=get_camera_pool(conn),
        sm=get_stream_manager(conn),
    )


def get_db(conn: HTTPConnection = None) -> TrackerDB:
    """Retrieve TrackerDB instance from active stream, ``app.state``, or fallback."""
    mgr = get_active_stream_manager(conn=conn)
    if mgr and mgr.db and getattr(mgr.db, "_conn", None) is not None:
        return mgr.db
    state_db = getattr(conn.app.state, "db", None) if conn is not None else None
    if state_db is not None and getattr(state_db, "_conn", None) is not None:
        return state_db
    return TrackerDB()


def get_rsac_mgr(conn: HTTPConnection = None) -> RSACManager:
    """Retrieve RSACManager from camera pool, stream, or initialize new."""
    pool = get_camera_pool(conn)
    if pool and pool.rsac_manager:
        return pool.rsac_manager
    mgr = get_active_stream_manager(conn=conn)
    if mgr and mgr.rsac_manager:
        return mgr.rsac_manager
    return RSACManager(db=get_db(conn))


def get_active_learning_mgr(conn: HTTPConnection = None) -> ActiveLearningManager:
    """Retrieve ActiveLearningManager from camera pool, stream, or initialize."""
    pool = get_camera_pool(conn)
    if pool and pool.active_learning:
        return pool.active_learning
    mgr = get_active_stream_manager(conn=conn)
    if mgr and mgr.active_learning:
        return mgr.active_learning
    return ActiveLearningManager(db=get_db(conn))


def get_enrollment_mgr(conn: HTTPConnection = None) -> UniversalEnrollmentManager:
    """Retrieve UniversalEnrollmentManager from camera pool, stream, or initialize."""
    pool = get_camera_pool(conn)
    if pool and pool.enrollment_manager:
        return pool.enrollment_manager
    mgr = get_active_stream_manager(conn=conn)
    if mgr and mgr.enrollment_manager:
        return mgr.enrollment_manager
    return UniversalEnrollmentManager(db=get_db(conn))


def reload_all_galleries(conn: HTTPConnection = None) -> None:
    """Reload visual Re-ID matchers and RSAC categories across all active streams."""
    pool = get_camera_pool(conn)
    if pool:
        pool.reload_all_galleries()
        return
    mgr = get_active_stream_manager(conn=conn)
    if mgr and mgr.gallery_matcher:
        mgr.gallery_matcher.reload_gallery()
    if mgr and mgr.rsac_manager:
        mgr.rsac_manager.reload()


# Legacy aliases preserving backwards compatibility
_get_db = get_db
_get_rsac_mgr = get_rsac_mgr
_get_active_learning_mgr = get_active_learning_mgr
_get_enrollment_mgr = get_enrollment_mgr
_get_scenario_mgr = get_scenario_mgr
_reload_all_galleries = reload_all_galleries
