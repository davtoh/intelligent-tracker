"""
Intelligent Tracker Dashboard - Dependency Injection & Runtime Singletons.

Provides centralized typed accessors for the CameraPool, StreamManager,
ScenarioManager, StreamLifecycleManager, and database repositories across
FastAPI APIRouters.
"""

from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from dashboard.camera_pool import CameraPool
    from dashboard.stream_manager import StreamManager
    from intelligent_tracker.scenarios import ScenarioManager
    from intelligent_tracker.lifecycle import StreamLifecycleManager
    from intelligent_tracker.database import TrackerDB
    from intelligent_tracker.rsac import RSACManager
    from intelligent_tracker.active_learning import ActiveLearningManager
    from intelligent_tracker.enrollment import UniversalEnrollmentManager

logger = logging.getLogger("intelligent_tracker.dashboard.dependencies")

# Shared runtime singletons
_camera_pool: Optional[CameraPool] = None
_stream_manager: Optional[StreamManager] = None
_scenario_manager: Optional[ScenarioManager] = None
_lifecycle_manager: Optional[StreamLifecycleManager] = None


def get_camera_pool() -> Optional[CameraPool]:
    """Get the active CameraPool instance (checking app module override first)."""
    try:
        import dashboard.app as app_mod
        if getattr(app_mod, "camera_pool", None) is not None:
            return app_mod.camera_pool
    except Exception:
        pass
    return _camera_pool


def set_camera_pool(pool: Optional[CameraPool]) -> None:
    """Set the active CameraPool instance."""
    global _camera_pool
    _camera_pool = pool
    try:
        import dashboard.app as app_mod
        app_mod.camera_pool = pool
    except Exception:
        pass


def get_stream_manager() -> Optional[StreamManager]:
    """Get the primary fallback StreamManager instance (checking app module override first)."""
    try:
        import dashboard.app as app_mod
        if getattr(app_mod, "stream_manager", None) is not None:
            return app_mod.stream_manager
    except Exception:
        pass
    return _stream_manager


def set_stream_manager(mgr: Optional[StreamManager]) -> None:
    """Set the primary fallback StreamManager instance."""
    global _stream_manager
    _stream_manager = mgr
    try:
        import dashboard.app as app_mod
        app_mod.stream_manager = mgr
    except Exception:
        pass


def get_scenario_manager() -> ScenarioManager:
    """Get or initialize the active ScenarioManager instance."""
    try:
        import dashboard.app as app_mod
        if getattr(app_mod, "scenario_manager", None) is not None:
            return app_mod.scenario_manager
    except Exception:
        pass
    global _scenario_manager
    if _scenario_manager is None:
        from intelligent_tracker.scenarios import ScenarioManager
        _scenario_manager = ScenarioManager()
    return _scenario_manager


def set_scenario_manager(mgr: Optional[ScenarioManager]) -> None:
    """Set the active ScenarioManager instance."""
    global _scenario_manager
    _scenario_manager = mgr
    try:
        import dashboard.app as app_mod
        app_mod.scenario_manager = mgr
    except Exception:
        pass


def get_lifecycle_manager() -> StreamLifecycleManager:
    """Resolves or initializes the StreamLifecycleManager."""
    try:
        import dashboard.app as app_mod
        if getattr(app_mod, "lifecycle_manager", None) is not None:
            return app_mod.lifecycle_manager
    except Exception:
        pass
    global _lifecycle_manager
    if _lifecycle_manager is None:
        from intelligent_tracker.lifecycle import StreamLifecycleManager
        sm = get_stream_manager()
        pool = get_camera_pool()
        db = sm.db if sm else None
        _lifecycle_manager = StreamLifecycleManager(db=db, camera_pool=pool, autostart_sampler=False)
    pool = get_camera_pool()
    if pool and _lifecycle_manager.camera_pool is None:
        _lifecycle_manager.set_camera_pool(pool)
    return _lifecycle_manager


def set_lifecycle_manager(mgr: Optional[StreamLifecycleManager]) -> None:
    """Set the active StreamLifecycleManager instance."""
    global _lifecycle_manager
    _lifecycle_manager = mgr
    try:
        import dashboard.app as app_mod
        app_mod.lifecycle_manager = mgr
    except Exception:
        pass


def get_active_stream_manager(camera_id: Optional[str] = None) -> Optional[StreamManager]:
    """Resolves the appropriate StreamManager instance for a camera ID or active default."""
    pool = get_camera_pool()
    if pool:
        mgr = pool.get_stream(camera_id)
        if mgr:
            return mgr
    sm = get_stream_manager()
    if sm:
        return sm
    if pool:
        return pool.primary_stream
    return None


def get_db() -> TrackerDB:
    """Resolves the active TrackerDB instance."""
    mgr = get_active_stream_manager()
    if mgr and mgr.db:
        return mgr.db
    from intelligent_tracker.database import TrackerDB
    return TrackerDB()


def get_rsac_mgr() -> RSACManager:
    """Resolves the active RSACManager instance."""
    if _camera_pool and _camera_pool.rsac_manager:
        return _camera_pool.rsac_manager
    mgr = get_active_stream_manager()
    if mgr and mgr.rsac_manager:
        return mgr.rsac_manager
    from intelligent_tracker.rsac import RSACManager
    return RSACManager(db=get_db())


def get_active_learning_mgr() -> ActiveLearningManager:
    """Resolves the active ActiveLearningManager instance."""
    if _camera_pool and _camera_pool.active_learning:
        return _camera_pool.active_learning
    mgr = get_active_stream_manager()
    if mgr and mgr.active_learning:
        return mgr.active_learning
    from intelligent_tracker.active_learning import ActiveLearningManager
    return ActiveLearningManager(db=get_db())


def get_enrollment_mgr() -> UniversalEnrollmentManager:
    """Resolves the active UniversalEnrollmentManager instance."""
    if _camera_pool and _camera_pool.enrollment_manager:
        return _camera_pool.enrollment_manager
    mgr = get_active_stream_manager()
    if mgr and mgr.enrollment_manager:
        return mgr.enrollment_manager
    from intelligent_tracker.enrollment import UniversalEnrollmentManager
    return UniversalEnrollmentManager(db=get_db())


def reload_all_galleries() -> None:
    """Reloads visual identity galleries across all active camera streams."""
    if _camera_pool:
        _camera_pool.reload_all_galleries()
    else:
        mgr = get_active_stream_manager()
        if mgr and mgr.gallery_matcher:
            mgr.gallery_matcher.reload_gallery()
        if mgr and mgr.rsac_manager:
            mgr.rsac_manager.reload()
