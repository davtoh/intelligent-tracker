#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Multi-View WebSocket Session Manager.

Manages one `/ws/multiview` connection: replace-set subscriptions, StreamManager
subscriber leases (`annotated=False`), frame-waiter wakeups, latest-frame-wins
binary delivery with `SEND_TIMEOUT` slow-client skipping, `source_status`
change detection, pause/resume, and clean shutdown-event teardown.
"""

import asyncio
import contextlib
import threading
import time
from typing import Any
import uuid

from fastapi import WebSocket, WebSocketDisconnect

from dashboard.services.camera_diagnostics import CameraHealthManager
from dashboard.services.multiview.limits import MultiviewLimits, get_multiview_limits
from dashboard.services.multiview.protocol import (
    PROTOCOL_VERSION,
    ProtocolError,
    pack_frame,
    parse_control_message,
)
from dashboard.services.multiview.telemetry_sender import MultiviewTelemetrySender

_session_lock = threading.Lock()
_active_sessions = 0


def try_acquire_session_slot(max_sessions: int) -> bool:
    """Atomically reserve a concurrent session slot if below ``max_sessions``."""
    global _active_sessions
    with _session_lock:
        if _active_sessions >= max(0, int(max_sessions)):
            return False
        _active_sessions += 1
        return True


def release_session_slot() -> None:
    """Release a previously acquired concurrent session slot."""
    global _active_sessions
    with _session_lock:
        if _active_sessions > 0:
            _active_sessions -= 1


def get_active_session_count() -> int:
    """Return current number of active multiview WebSocket sessions."""
    with _session_lock:
        return _active_sessions


def resolve_camera_status(camera_id: str, mgr: Any, pool: Any = None) -> str:
    """Resolve canonical multiview status for ``camera_id``."""
    if pool is not None:
        cfg = getattr(pool, "camera_configs", {}).get(camera_id)
        if isinstance(cfg, dict) and not cfg.get("enabled", True):
            return "disabled"
    if getattr(mgr, "is_hibernating", False):
        return "hibernating"
    health = CameraHealthManager().get_health(camera_id)
    if getattr(mgr, "_source_error", False) or health.status == "error":
        return "error"
    if health.status in ("reconnecting", "hibernating", "disabled", "offline"):
        return health.status
    if getattr(mgr, "is_running", False) or health.status == "online":
        return "online"
    return "offline"


def _resolve_stream(camera_id: str, pool: Any, stream_manager: Any) -> tuple[Any | None, str]:
    """Look up StreamManager for ``camera_id`` without aliasing primary_stream."""
    if pool is not None:
        mgr = pool.get_stream(camera_id)
        if mgr is not None:
            return mgr, ""
        cfg = getattr(pool, "camera_configs", {}).get(camera_id)
        if isinstance(cfg, dict) and not cfg.get("enabled", True):
            return None, "disabled"
        return None, "unknown_camera"
    if stream_manager is not None and getattr(stream_manager, "camera_id", None) == camera_id:
        return stream_manager, ""
    return None, "unknown_camera"


def _build_hello_payload(limits: MultiviewLimits) -> dict[str, Any]:
    """Construct the initial server->client ``hello`` control message."""
    return {
        "v": 1,
        "type": "hello",
        "protocol": PROTOCOL_VERSION,
        "limits": {
            "max_subscriptions": limits.max_subscriptions,
            "max_sessions": limits.max_sessions,
            "send_timeout_s": limits.send_timeout_s,
        },
        "layouts": {
            k: {"max_fps": v[0], "max_width": v[1]}
            for k, v in limits.layout_caps.items()
        },
    }


def _rebind_stream_leases(session: Any, cam_id: str, old_mgr: Any, new_mgr: Any) -> Any:
    """Migrate subscriber lease and frame waiter from a restarted StreamManager to ``new_mgr``."""
    width = session._desired[2] if session._desired else 640
    fps = session._desired[1] if session._desired else 15
    if getattr(old_mgr, "thumbnail_cache", None) is not None:
        old_mgr.thumbnail_cache.release_lease(session._session_id)
    if session._loop is not None and session._frame_event is not None:
        with contextlib.suppress(Exception):
            old_mgr.unregister_frame_waiter(session._loop, session._frame_event)
    with contextlib.suppress(Exception):
        old_mgr.remove_subscriber(session._sub_id(cam_id))
    tier = width
    if getattr(new_mgr, "thumbnail_cache", None) is not None:
        tier = new_mgr.thumbnail_cache.acquire_lease(session._session_id, width, fps)
    new_mgr.add_subscriber(session._sub_id(cam_id), annotated=False)
    if session._loop is not None and session._frame_event is not None:
        new_mgr.register_frame_waiter(session._loop, session._frame_event)
    session._active[cam_id] = (new_mgr, tier)
    session._last_sent_seq.pop(cam_id, None)
    session._sender.clear_camera(cam_id)
    return new_mgr


class MultiviewSession:
    """Async WebSocket session driving multiplexed camera thumbnail delivery."""

    def __init__(
        self,
        websocket: WebSocket,
        pool: Any = None,
        limits: MultiviewLimits | None = None,
        shutdown_event: asyncio.Event | None = None,
        session_id: str | None = None,
        stream_manager: Any = None,
    ) -> None:
        self._ws = websocket
        self._pool = pool
        self._stream_manager = stream_manager
        self._limits = limits or get_multiview_limits()
        self._shutdown_event = shutdown_event
        self._session_id = session_id or f"mv_{uuid.uuid4().hex[:12]}"
        self._active: dict[str, tuple[Any, int]] = {}
        self._desired: tuple[list[str], int, int] | None = None
        self._last_sent_seq: dict[str, int] = {}
        self._last_status: dict[str, str] = {}
        self._paused = False
        self._stopped = False
        self._slow_skips = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._frame_event: asyncio.Event | None = None
        self._send_lock: asyncio.Lock | None = None
        self._sender = MultiviewTelemetrySender()

    def _sub_id(self, camera_id: str) -> str:
        return f"{self._session_id}:{camera_id}"

    async def run(self) -> None:
        """Accept the WebSocket and run receive/send loops until disconnect or shutdown."""
        self._loop = asyncio.get_running_loop()
        self._frame_event = asyncio.Event()
        self._send_lock = asyncio.Lock()
        self._sender.bind_loop()
        await self._ws.accept()
        await self._send_json(_build_hello_payload(self._limits))

        tasks: set[asyncio.Task[Any]] = {
            asyncio.create_task(self._receive_loop()),
            asyncio.create_task(self._sender_loop()),
            asyncio.create_task(self._sender.writer_loop(self)),
        }
        shutdown_task: asyncio.Task[Any] | None = None
        if self._shutdown_event is not None:
            shutdown_task = asyncio.create_task(self._shutdown_event.wait())
            tasks.add(shutdown_task)

        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if shutdown_task is not None and shutdown_task in done:
                with contextlib.suppress(Exception):
                    await self._ws.close(code=1001, reason="Server shutting down")
            for task in pending:
                task.cancel()
            for task in pending:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        finally:
            self._stopped = True
            self._release_all_leases()

    async def _send_json(self, payload: dict[str, Any]) -> None:
        if self._stopped or self._send_lock is None:
            return
        async with self._send_lock:
            with contextlib.suppress(WebSocketDisconnect, RuntimeError):
                await asyncio.wait_for(
                    self._ws.send_json(payload),
                    timeout=self._limits.send_timeout_s,
                )

    async def _receive_loop(self) -> None:
        while not self._stopped:
            try:
                raw = await self._ws.receive_text()
            except (WebSocketDisconnect, RuntimeError):
                break
            try:
                msg = parse_control_message(raw, self._limits)
            except ProtocolError as exc:
                await self._send_json({"v": 1, "type": "error", "code": exc.code, "message": exc.message})
                continue
            await self._handle_control(msg)

    async def _handle_control(self, msg: dict[str, Any]) -> None:
        action = msg["action"]
        if action == "ping":
            await self._send_json({"v": 1, "type": "pong", "ts": time.time()})
        elif action == "unsubscribe_all":
            self._desired = None
            self._release_all_leases()
        elif action == "pause":
            self._paused = True
            self._release_all_leases()
        elif action == "resume":
            self._paused = False
            if self._desired is not None:
                cams, fps, width = self._desired
                self._apply_subscriptions(cams, fps, width)
        elif action == "subscribe":
            cams = msg["cameras"]
            fps = msg["max_fps"]
            width = msg["max_width"]
            self._desired = (cams, fps, width)
            accepted, rejected = self._apply_subscriptions(cams, fps, width)
            await self._send_json({
                "v": 1,
                "type": "subscribed",
                "accepted": accepted,
                "rejected": rejected,
                "layout": msg["layout"],
                "fps": fps,
                "width": width,
            })

    def _apply_subscriptions(self, cameras: list[str], fps: int, width: int) -> tuple[list[str], dict[str, str]]:
        """Replace active subscriptions with ``cameras`` and update thumbnail/subscriber leases."""
        target = set(cameras)
        for cam_id in list(self._active):
            if cam_id not in target:
                self._release_camera(cam_id)

        accepted: list[str] = []
        rejected: dict[str, str] = {}
        for cam_id in cameras:
            mgr, reason = _resolve_stream(cam_id, self._pool, self._stream_manager)
            if mgr is None:
                rejected[cam_id] = reason
                continue
            accepted.append(cam_id)
            if self._paused:
                continue
            tier = width
            cache = getattr(mgr, "thumbnail_cache", None)
            if cache is not None:
                tier = cache.acquire_lease(self._session_id, width, fps)
            if cam_id not in self._active:
                mgr.add_subscriber(self._sub_id(cam_id), annotated=False)
                if self._loop is not None and self._frame_event is not None:
                    mgr.register_frame_waiter(self._loop, self._frame_event)
            self._active[cam_id] = (mgr, tier)

        if self._frame_event is not None and not self._paused:
            self._frame_event.set()
        return accepted, rejected

    def _release_camera(self, cam_id: str) -> None:
        entry = self._active.pop(cam_id, None)
        self._last_sent_seq.pop(cam_id, None)
        self._sender.clear_camera(cam_id)
        if entry is None:
            return
        mgr, _tier = entry
        cache = getattr(mgr, "thumbnail_cache", None)
        if cache is not None:
            cache.release_lease(self._session_id)
        if self._loop is not None and self._frame_event is not None:
            with contextlib.suppress(Exception):
                mgr.unregister_frame_waiter(self._loop, self._frame_event)
        with contextlib.suppress(Exception):
            mgr.remove_subscriber(self._sub_id(cam_id))

    def _release_all_leases(self) -> None:
        for cam_id in list(self._active):
            self._release_camera(cam_id)

    async def _sender_loop(self) -> None:
        assert self._frame_event is not None
        while not self._stopped:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._frame_event.wait(), timeout=1.0)
            self._frame_event.clear()
            if self._stopped or self._paused:
                continue
            for cam_id, (mgr, tier) in list(self._active.items()):
                await self._flush_camera(cam_id, mgr, tier)

    async def _flush_camera(self, cam_id: str, mgr: Any, tier: int) -> None:
        """Emit status/rebind updates, throttled telemetry, and latest unseen thumbnail."""
        resolved, _ = _resolve_stream(cam_id, self._pool, self._stream_manager)
        if resolved is None:
            if self._last_status.get(cam_id) != "offline":
                self._last_status[cam_id] = "offline"
                self._sender.enqueue_json({"v": 1, "type": "source_status", "camera_id": cam_id, "status": "offline", "reason": "removed"})
            self._release_camera(cam_id)
            return

        rebound = resolved is not mgr
        if rebound:
            mgr = _rebind_stream_leases(self, cam_id, mgr, resolved)
            tier = self._active[cam_id][1]
        with contextlib.suppress(Exception):
            mgr.heartbeat_subscriber(self._sub_id(cam_id))

        status = resolve_camera_status(cam_id, mgr, self._pool)
        if rebound or status != self._last_status.get(cam_id):
            self._last_status[cam_id] = status
            self._sender.enqueue_json({
                "v": 1, "type": "source_status", "camera_id": cam_id,
                "status": status, "reason": "rebound" if rebound else "",
            })

        cache = getattr(mgr, "thumbnail_cache", None)
        slot = cache.get_latest(tier) if cache is not None else None
        if slot is None or slot.seq == self._last_sent_seq.get(cam_id):
            return
        self._sender.enqueue_frame(cam_id, slot.seq, pack_frame(cam_id, slot.seq, slot.ts_ms, slot.data))
        self._sender.maybe_enqueue_telemetry(cam_id, mgr, seq=slot.seq)
