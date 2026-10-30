"""
Intelligent Tracker Dashboard - Domain APIRouters.
"""

from dashboard.routers.streaming import router as streaming_router
from dashboard.routers.cameras import router as cameras_router
from dashboard.routers.videos import router as videos_router
from dashboard.routers.scenarios import router as scenarios_router
from dashboard.routers.topology import router as topology_router
from dashboard.routers.analytics import router as analytics_router
from dashboard.routers.rsac import router as rsac_router
from dashboard.routers.system import router as system_router

__all__ = [
    "streaming_router",
    "cameras_router",
    "videos_router",
    "scenarios_router",
    "topology_router",
    "analytics_router",
    "rsac_router",
    "system_router",
]
