#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Multi-View WebSocket Streaming Router.

Exposes ``/ws/multiview`` with Origin/token validation, concurrent session
capping (close 1013), and delegation to ``MultiviewSession``.
"""

from fastapi import APIRouter, WebSocket

from dashboard.dependencies import get_camera_pool, get_shutdown_event, get_stream_manager
from dashboard.services.multiview.limits import get_multiview_limits
from dashboard.services.multiview.session import (
    MultiviewSession,
    release_session_slot,
    try_acquire_session_slot,
)
from dashboard.services.security_config import authorize_websocket

router = APIRouter(tags=["multiview"])


@router.websocket("/ws/multiview")
async def websocket_multiview(websocket: WebSocket) -> None:
    """Serve multiplexed binary thumbnail frames for the multi-camera grid."""
    allowed, reason = authorize_websocket(websocket)
    if not allowed:
        await websocket.close(code=1008, reason=reason)
        return
    limits = get_multiview_limits()
    if not try_acquire_session_slot(limits.max_sessions):
        await websocket.close(code=1013, reason="Session limit reached")
        return
    try:
        session = MultiviewSession(
            websocket,
            pool=get_camera_pool(websocket),
            limits=limits,
            shutdown_event=get_shutdown_event(),
            stream_manager=get_stream_manager(websocket),
        )
        await session.run()
    finally:
        release_session_slot()
