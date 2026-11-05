#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Stream Subscriber Registry Service.
Manages viewer leases, TTL-based eviction, WebSocket push distribution,
and deep video source hibernation callbacks.
"""

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional
import uuid

logger = logging.getLogger(__name__)


class StreamSubscriberRegistry:
    """
    Self-healing leased subscriber registry for active camera streams.
    Tracks HTTP MJPEG viewers and WebSocket telemetry subscribers with
    time-to-live leases to prevent orphaned stream processing.
    """

    def __init__(
        self,
        resume_callback: Optional[Callable[[], None]] = None,
        lease_ttl: float = 3.0,
    ) -> None:
        self._subscribers: Dict[str, float] = {}
        self._ws_subscribers: List[Any] = []
        self._lock = threading.Lock()
        self._is_hibernating: bool = False
        self.resume_callback = resume_callback
        self.lease_ttl = lease_ttl

    def add_subscriber(self, sub_id: Optional[str] = None) -> str:
        """Register an active client subscriber (MJPEG stream or WebSocket) with a leased token."""
        token = str(sub_id) if sub_id else uuid.uuid4().hex
        now = time.time()
        with self._lock:
            self._subscribers[token] = now

        if self.resume_callback is not None:
            try:
                self.resume_callback()
            except Exception as e:
                logger.debug("Subscriber resume callback failed: %s", e)
        return token

    def heartbeat_subscriber(self, sub_id: str) -> None:
        """Update last-seen timestamp for an active leased subscriber."""
        with self._lock:
            if sub_id in self._subscribers:
                self._subscribers[sub_id] = time.time()

    def remove_subscriber(self, sub_id: Optional[str] = None) -> int:
        """Unregister an active client subscriber by token or pop one."""
        with self._lock:
            if sub_id:
                self._subscribers.pop(str(sub_id), None)
            elif self._subscribers:
                self._subscribers.pop(next(iter(self._subscribers)))
            return self._active_subscriber_count_unlocked()

    def _active_subscriber_count_unlocked(self) -> int:
        """Internal helper to prune expired subscriber leases and count active viewers."""
        now = time.time()
        expired = [sid for sid, last_seen in self._subscribers.items() if (now - last_seen) > self.lease_ttl]
        for sid in expired:
            self._subscribers.pop(sid, None)
        return len(self._subscribers) + len(self._ws_subscribers)

    @property
    def subscriber_count(self) -> int:
        """Current number of active, non-expired subscribers."""
        with self._lock:
            return self._active_subscriber_count_unlocked()

    @property
    def is_hibernating(self) -> bool:
        """Returns True if the stream is currently hibernating due to zero subscribers."""
        return self._is_hibernating

    @is_hibernating.setter
    def is_hibernating(self, val: bool) -> None:
        self._is_hibernating = bool(val)

    def register_ws_subscriber(self, sub: Any) -> None:
        """Register an active WebSocket subscriber queue."""
        with self._lock:
            if sub not in self._ws_subscribers:
                self._ws_subscribers.append(sub)

        if self.resume_callback is not None:
            try:
                self.resume_callback()
            except Exception as e:
                logger.debug("WebSocket resume callback failed: %s", e)

    def unregister_ws_subscriber(self, sub: Any) -> None:
        """Unregister an active WebSocket subscriber."""
        with self._lock:
            if sub in self._ws_subscribers:
                self._ws_subscribers.remove(sub)

    def broadcast_telemetry(self, telemetry: Dict[str, Any]) -> None:
        """Distribute telemetry to registered async queues, pruning dead subscribers."""
        with self._lock:
            subs = list(self._ws_subscribers)
        dead = []
        for sub in subs:
            try:
                if hasattr(sub, "put_nowait"):
                    sub.put_nowait(telemetry)
                elif callable(sub):
                    sub(telemetry)
            except Exception:
                dead.append(sub)
        if dead:
            with self._lock:
                for d in dead:
                    if d in self._ws_subscribers:
                        self._ws_subscribers.remove(d)


class StreamSubscriberMixin:
    """Mixin delegating subscriber lifecycle and telemetry distribution to _subscriber_registry."""

    def add_subscriber(self, sub_id: Optional[str] = None) -> str:
        """Register an active client subscriber with a leased token."""
        return self._subscriber_registry.add_subscriber(sub_id)

    def heartbeat_subscriber(self, sub_id: str) -> None:
        """Update last-seen timestamp for an active leased subscriber."""
        self._subscriber_registry.heartbeat_subscriber(sub_id)

    def remove_subscriber(self, sub_id: Optional[str] = None) -> int:
        """Unregister an active client subscriber by token or pop one."""
        return self._subscriber_registry.remove_subscriber(sub_id)

    def _active_subscriber_count_unlocked(self) -> int:
        """Internal helper to prune expired subscriber leases and count active viewers."""
        return self._subscriber_registry._active_subscriber_count_unlocked()

    @property
    def subscriber_count(self) -> int:
        """Current number of active, non-expired subscribers."""
        return self._subscriber_registry.subscriber_count

    @property
    def is_hibernating(self) -> bool:
        """Returns True if the stream is currently hibernating due to zero subscribers."""
        return self._subscriber_registry.is_hibernating

    @is_hibernating.setter
    def is_hibernating(self, val: bool) -> None:
        self._subscriber_registry.is_hibernating = val

    _is_hibernating = is_hibernating

    def register_ws_subscriber(self, sub: Any) -> None:
        """Register an active WebSocket subscriber queue."""
        self._subscriber_registry.register_ws_subscriber(sub)

    def unregister_ws_subscriber(self, sub: Any) -> None:
        """Unregister an active WebSocket subscriber."""
        self._subscriber_registry.unregister_ws_subscriber(sub)

    def _broadcast_telemetry(self, telemetry: Dict[str, Any]) -> None:
        """Distribute telemetry to registered async queues."""
        self._subscriber_registry.broadcast_telemetry(telemetry)
