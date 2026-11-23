#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Multi-View Non-Blocking Telemetry & Frame Sender.

Decouples `/ws/multiview` frame/telemetry production from WebSocket I/O using
a single-writer task with per-camera latest-slot coalescing (P3-3) and throttled
JSON telemetry emission (Decision 7 / ADR-05).
"""

import asyncio
from collections import deque
import contextlib
import time
from typing import Any

from fastapi import WebSocketDisconnect


def build_multiview_telemetry(cam_id: str, mgr: Any, seq: int = 0) -> dict[str, Any]:
    """Construct a v1 throttled JSON telemetry payload for one multiview camera."""
    telemetry = mgr.get_latest_telemetry() if hasattr(mgr, "get_latest_telemetry") else {}
    if not isinstance(telemetry, dict):
        telemetry = {}
    tier = str(telemetry.get("priority_tier", "P2"))
    is_hib = bool(getattr(mgr, "is_hibernating", False))
    armed = bool(telemetry.get("armed", getattr(mgr, "is_armed", False)))
    is_armed = bool(telemetry.get("is_armed", armed))
    ai_active = (not is_hib) and tier not in ("PAUSED", "CAPTURE_ONLY", "IDLE")
    vs = getattr(mgr, "video_source", None)
    default_res = [int(getattr(vs, "width", 640) or 640), int(getattr(vs, "height", 480) or 480)]
    src_res = telemetry.get("source_resolution") or default_res
    return {
        "v": 1,
        "type": "telemetry",
        "camera_id": cam_id,
        "seq": int(telemetry.get("frame_seq") or seq or 0),
        "tracks": list(telemetry.get("active_tracks") or []),
        "fps": float(telemetry.get("fps", 0.0) or 0.0),
        "priority_tier": tier,
        "armed": armed,
        "is_armed": is_armed,
        "ai_active": ai_active,
        "source_resolution": list(src_res),
    }


class MultiviewTelemetrySender:
    """Per-camera latest-slot buffer and throttled telemetry writer for MultiviewSession."""

    def __init__(self, telemetry_interval_s: float = 0.2) -> None:
        self._telemetry_interval_s = max(0.05, float(telemetry_interval_s))
        self._pending_frames: dict[str, tuple[int, bytes]] = {}
        self._pending_telemetry: dict[str, dict[str, Any]] = {}
        self._pending_json: deque[dict[str, Any]] = deque(maxlen=64)
        self._last_telemetry_at: dict[str, float] = {}
        self._wake_event: asyncio.Event | None = None

    def bind_loop(self) -> None:
        """Create the writer wakeup event inside the active asyncio loop."""
        self._wake_event = asyncio.Event()

    def clear_camera(self, cam_id: str) -> None:
        """Drop any queued frame and telemetry throttle state for ``cam_id``."""
        self._pending_frames.pop(cam_id, None)
        self._pending_telemetry.pop(cam_id, None)
        self._last_telemetry_at.pop(cam_id, None)

    def enqueue_frame(self, cam_id: str, seq: int, payload: bytes) -> None:
        """Store latest encoded binary frame for ``cam_id`` without blocking."""
        self._pending_frames[cam_id] = (seq, payload)
        if self._wake_event is not None:
            self._wake_event.set()

    def enqueue_json(self, payload: dict[str, Any]) -> None:
        """Queue a JSON payload for single-writer delivery."""
        self._pending_json.append(payload)
        if self._wake_event is not None:
            self._wake_event.set()

    def maybe_enqueue_telemetry(self, cam_id: str, mgr: Any, seq: int = 0) -> None:
        """Emit throttled JSON telemetry for ``cam_id`` when interval has elapsed."""
        now = time.monotonic()
        last = self._last_telemetry_at.get(cam_id)
        if last is not None and (now - last) < self._telemetry_interval_s:
            return
        self._last_telemetry_at[cam_id] = now
        self._pending_telemetry[cam_id] = build_multiview_telemetry(cam_id, mgr, seq=seq)
        if self._wake_event is not None:
            self._wake_event.set()

    async def writer_loop(self, session: Any) -> None:
        """Single-writer loop draining status JSON, latest-slot binary frames, and throttled telemetry."""
        if self._wake_event is None:
            self._wake_event = asyncio.Event()
        while not session._stopped:
            if not self._pending_json and not self._pending_frames and not self._pending_telemetry:
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._wake_event.wait(), timeout=1.0)
                self._wake_event.clear()
                continue
            self._wake_event.clear()
            while self._pending_json and not session._stopped:
                await session._send_json(self._pending_json.popleft())
            if session._stopped or session._paused:
                continue
            for cam_id in list(self._pending_frames):
                if session._stopped or session._paused:
                    break
                entry = self._pending_frames.pop(cam_id, None)
                if entry is not None:
                    await _send_frame_without_cancel(session, cam_id, entry[0], entry[1])
            for cam_id in list(self._pending_telemetry):
                if session._stopped or session._paused:
                    break
                t_msg = self._pending_telemetry.pop(cam_id, None)
                if t_msg is not None:
                    await session._send_json(t_msg)


async def _send_frame_without_cancel(session: Any, cam_id: str, seq: int, payload: bytes) -> None:
    """Send one binary frame without cancelling an in-flight WebSocket write mid-frame."""
    if session._stopped or session._send_lock is None:
        return
    async with session._send_lock:
        task = asyncio.create_task(session._ws.send_bytes(payload))
        try:
            done, _ = await asyncio.wait({task}, timeout=session._limits.send_timeout_s)
            if task not in done:
                session._slow_skips += 1
            await task
            session._last_sent_seq[cam_id] = seq
        except (WebSocketDisconnect, RuntimeError):
            session._stopped = True
        except Exception:
            session._stopped = True
