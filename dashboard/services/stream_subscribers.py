"""
Intelligent Tracker Dashboard - Leased Subscriber Registry & Hibernation State.

Encapsulates active viewer tracking (HTTP MJPEG and WebSocket), TTL lease pruning,
heartbeat renewals, and telemetry broadcasting to prevent CPU leaks when streams are idle.
"""

from __future__ import annotations

import time
import uuid
import threading
import logging
from typing import Dict, List, Optional, Any, Callable

logger = logging.getLogger("intelligent_tracker.dashboard.subscribers")


class StreamSubscriberRegistry:
    """
    Manages active client subscriber leases with automatic TTL-based pruning
    and hibernation triggers.
    """

    def __init__(self, resume_callback: Optional[Callable[[], None]] = None, lease_ttl: float = 3.0):
        self._subscribers: Dict[str, float] = {}
        self._ws_subscribers: List[Any] = []
        self._lock = threading.Lock()
        self._is_hibernating = False
        self._resume_callback = resume_callback
        self.lease_ttl = lease_ttl

    def add_subscriber(self, sub_id: Optional[str] = None) -> str:
        """Register an active client subscriber (MJPEG stream or WebSocket) with a leased token."""
        token = str(sub_id) if sub_id else uuid.uuid4().hex
        now = time.time()
        with self._lock:
            self._subscribers[token] = now
        if self._resume_callback:
            try:
                self._resume_callback()
            except Exception as e:
                logger.debug("Subscriber resume callback error: %s", e)
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
        """Register an async WebSocket queue or callback."""
        with self._lock:
            if sub not in self._ws_subscribers:
                self._ws_subscribers.append(sub)
        if self._resume_callback:
            try:
                self._resume_callback()
            except Exception as e:
                logger.debug("WS subscriber resume callback error: %s", e)

    def unregister_ws_subscriber(self, sub: Any) -> None:
        """Unregister an async WebSocket queue or callback."""
        with self._lock:
            if sub in self._ws_subscribers:
                self._ws_subscribers.remove(sub)

    def broadcast_telemetry(self, telemetry: Dict[str, Any]) -> None:
        """Distribute telemetry payload to registered async queues, pruning dead subscribers."""
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

    def evict_all(self, reason: Optional[str] = None) -> int:
        """Force-evict all active leases and WebSocket subscribers."""
        with self._lock:
            count = len(self._subscribers) + len(self._ws_subscribers)
            self._subscribers.clear()
            self._ws_subscribers.clear()
            self._is_hibernating = True
            logger.info("Evicted %d subscribers (reason: %s)", count, reason or "admin action")
            return count

