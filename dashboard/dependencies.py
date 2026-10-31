#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Dashboard Dependencies & Bidirectional Proxy Bridge.

Provides typed dependency providers and proxy accessors for CameraPool,
StreamManager, ScenarioManager, and StreamLifecycleManager.
Supports runtime synchronization and monkeypatching compatibility for test fixtures.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

from dashboard.camera_pool import CameraPool
from dashboard.stream_manager import StreamManager
from intelligent_tracker.active_learning import ActiveLearningManager
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.enrollment import UniversalEnrollmentManager
from intelligent_tracker.lifecycle import StreamLifecycleManager
from intelligent_tracker.rsac import RSACManager
from intelligent_tracker.scenarios import ScenarioManager

logger = logging.getLogger("intelligent_tracker.dashboard.dependencies")

# File and directory paths
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
VIDEOS_DIR = os.path.join("data", "videos")
CROPS_DIR = os.path.join("data", "crops")

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(VIDEOS_DIR, exist_ok=True)
os.makedirs(CROPS_DIR, exist_ok=True)

# Internal module singletons
_camera_pool: Optional[CameraPool] = None
_stream_manager: Optional[StreamManager] = None
_scenario_manager: Optional[ScenarioManager] = None
_lifecycle_manager: Optional[StreamLifecycleManager] = None


def get_camera_pool() -> Optional[CameraPool]:
    """Resolve CameraPool, prioritizing app module overrides for test isolation."""
    try:
        app_mod = sys.modules.get("dashboard.app")
        if app_mod and getattr(app_mod, "camera_pool", None) is not None:
            return app_mod.camera_pool
    except Exception:
        pass
    return _camera_pool


def set_camera_pool(pool: Optional[CameraPool]) -> None:
    """Set active CameraPool and synchronize with app module globals."""
    global _camera_pool
    _camera_pool = pool
    try:
        app_mod = sys.modules.get("dashboard.app")
        if app_mod:
            app_mod.camera_pool = pool
    except Exception:
        pass


def get_stream_manager() -> Optional[StreamManager]:
    """Resolve StreamManager, checking app module override first."""
    try:
        app_mod = sys.modules.get("dashboard.app")
        if app_mod and getattr(app_mod, "stream_manager", None) is not None:
            return app_mod.stream_manager
    except Exception:
        pass
    return _stream_manager


def set_stream_manager(mgr: Optional[StreamManager]) -> None:
    """Set active StreamManager and synchronize with app module globals."""
    global _stream_manager
    _stream_manager = mgr
    try:
        app_mod = sys.modules.get("dashboard.app")
        if app_mod:
            app_mod.stream_manager = mgr
    except Exception:
        pass


def get_scenario_manager() -> Optional[ScenarioManager]:
    """Resolve ScenarioManager, checking app module override first."""
    try:
        app_mod = sys.modules.get("dashboard.app")
        if app_mod and getattr(app_mod, "scenario_manager", None) is not None:
            return app_mod.scenario_manager
    except Exception:
        pass
    return _scenario_manager


def set_scenario_manager(mgr: Optional[ScenarioManager]) -> None:
    """Set active ScenarioManager and synchronize with app module globals."""
    global _scenario_manager
    _scenario_manager = mgr
    try:
        app_mod = sys.modules.get("dashboard.app")
        if app_mod:
            app_mod.scenario_manager = mgr
    except Exception:
        pass


def get_scenario_mgr() -> ScenarioManager:
    """Ensure and return active ScenarioManager singleton."""
    mgr = get_scenario_manager()
    if mgr is None:
        mgr = ScenarioManager()
        set_scenario_manager(mgr)
    return mgr


def get_lifecycle_manager() -> StreamLifecycleManager:
    """Ensure and return active StreamLifecycleManager instance."""
    global _lifecycle_manager
    try:
        app_mod = sys.modules.get("dashboard.app")
        if app_mod and getattr(app_mod, "lifecycle_manager", None) is not None:
            return app_mod.lifecycle_manager
    except Exception:
        pass

    if _lifecycle_manager is None:
        sm = get_stream_manager()
        pool = get_camera_pool()
        db = sm.db if sm else None
        _lifecycle_manager = StreamLifecycleManager(
            db=db, camera_pool=pool, autostart_sampler=False
        )

    pool = get_camera_pool()
    if pool and _lifecycle_manager.camera_pool is None:
        _lifecycle_manager.set_camera_pool(pool)

    return _lifecycle_manager


def set_lifecycle_manager(lm: Optional[StreamLifecycleManager]) -> None:
    """Set active StreamLifecycleManager and synchronize with app module."""
    global _lifecycle_manager
    _lifecycle_manager = lm
    try:
        app_mod = sys.modules.get("dashboard.app")
        if app_mod:
            app_mod.lifecycle_manager = lm
    except Exception:
        pass


def get_active_stream_manager(camera_id: Optional[str] = None) -> Optional[StreamManager]:
    """Resolve active StreamManager for a camera ID or default primary channel."""
    pool = get_camera_pool()
    sm = get_stream_manager()
    if pool:
        mgr = pool.get_stream(camera_id)
        if mgr:
            return mgr
    if sm:
        if not camera_id or sm.camera_id == camera_id:
            return sm
    if pool:
        return pool.primary_stream
    return sm


def get_db() -> TrackerDB:
    """Retrieve TrackerDB instance from active stream or create fallback."""
    mgr = get_active_stream_manager()
    if mgr and mgr.db:
        return mgr.db
    return TrackerDB()


def get_rsac_mgr() -> RSACManager:
    """Retrieve RSACManager from camera pool, stream, or initialize new."""
    pool = get_camera_pool()
    if pool and pool.rsac_manager:
        return pool.rsac_manager
    mgr = get_active_stream_manager()
    if mgr and mgr.rsac_manager:
        return mgr.rsac_manager
    return RSACManager(db=get_db())


def get_active_learning_mgr() -> ActiveLearningManager:
    """Retrieve ActiveLearningManager from camera pool, stream, or initialize."""
    pool = get_camera_pool()
    if pool and pool.active_learning:
        return pool.active_learning
    mgr = get_active_stream_manager()
    if mgr and mgr.active_learning:
        return mgr.active_learning
    return ActiveLearningManager(db=get_db())


def get_enrollment_mgr() -> UniversalEnrollmentManager:
    """Retrieve UniversalEnrollmentManager from camera pool, stream, or initialize."""
    pool = get_camera_pool()
    if pool and pool.enrollment_manager:
        return pool.enrollment_manager
    mgr = get_active_stream_manager()
    if mgr and mgr.enrollment_manager:
        return mgr.enrollment_manager
    return UniversalEnrollmentManager(db=get_db())


def reload_all_galleries() -> None:
    """Reload visual Re-ID matchers and RSAC categories across all active streams."""
    pool = get_camera_pool()
    if pool:
        pool.reload_all_galleries()
    else:
        mgr = get_active_stream_manager()
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

