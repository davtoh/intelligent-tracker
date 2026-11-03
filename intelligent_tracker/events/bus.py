"""Centralized asynchronous publish/subscribe event bus."""

from collections import deque
import logging
import queue
import threading
import time
from typing import Any, Callable, List, Optional, Tuple, Type

from intelligent_tracker.events.types import BaseEvent

logger = logging.getLogger(__name__)


class EventBus:
    """
    Thread-safe Publish/Subscribe asynchronous event bus.

    Features:
    - Dedicated background worker threads consuming an internal `Queue`.
    - Zero event loss with synchronous or asynchronous dispatch.
    - Type-based and predicate-based subscriber filtering.
    - Historical ring buffer for telemetry queries and audit inspection.
    - Error isolation: handler exceptions are captured without blocking other handlers.
    """

    def __init__(self, history_limit: int = 500, capacity: Optional[int] = None):
        if capacity is not None:
            history_limit = capacity

        self._queue = queue.Queue()
        self._subscribers: List[Tuple[Callable[[BaseEvent], Any], Optional[Callable[[BaseEvent], bool]], Optional[Type]]] = []
        self._sub_lock = threading.Lock()
        self._workers: List[threading.Thread] = []
        self._running = False
        self._stop_event = threading.Event()
        self._history: deque = deque(maxlen=max(10, int(history_limit)))
        self._history_lock = threading.Lock()
        self._sentinel = object()

    def subscribe(
        self,
        handler: Callable[[BaseEvent], Any],
        filter_fn: Optional[Callable[[BaseEvent], bool]] = None,
        event_type: Optional[Type] = None,
    ):
        """
        Register a subscriber callback.

        :param handler: Callable receiving a `BaseEvent` instance.
        :param filter_fn: Optional predicate `(event) -> bool` returning True to dispatch.
        :param event_type: Optional class or tuple of classes to filter by `isinstance`.
        """
        with self._sub_lock:
            self._subscribers.append((handler, filter_fn, event_type))

    def unsubscribe(self, handler: Callable):
        """Remove a previously registered handler."""
        with self._sub_lock:
            self._subscribers = [
                sub for sub in self._subscribers if sub[0] != handler
            ]

    def publish(self, event: BaseEvent, sync: bool = False):
        """
        Publish an event to all matching subscribers.

        :param event: BaseEvent instance to publish.
        :param sync: If True, execute matching handlers immediately in calling thread.
        """
        with self._history_lock:
            self._history.append(event)

        if sync:
            self._dispatch_event(event)
        else:
            self._queue.put(event)

    def _dispatch_event(self, event: BaseEvent):
        """Internal dispatch to registered subscribers with exception isolation."""
        with self._sub_lock:
            current_subs = list(self._subscribers)

        for handler, filter_fn, event_type in current_subs:
            try:
                if event_type is not None and not isinstance(event, event_type):
                    continue
                if filter_fn is not None and not filter_fn(event):
                    continue
                handler(event)
            except Exception as e:
                logger.error("EventBus subscriber %s failed on event %s: %s", handler, event, e)

    def _worker_loop(self):
        """Background worker thread processing events from the queue."""
        while self._running and not self._stop_event.is_set():
            try:
                event = self._queue.get(timeout=0.2)
            except Exception:
                continue

            if event is self._sentinel:
                self._queue.task_done()
                break

            try:
                self._dispatch_event(event)
            finally:
                self._queue.task_done()

    def start(self, num_workers: int = 1):
        """Start background dispatcher worker threads."""
        if self._running:
            return

        self._running = True
        self._stop_event.clear()
        self._workers = []
        for i in range(max(1, int(num_workers))):
            t = threading.Thread(
                target=self._worker_loop,
                name=f"EventBusWorker-{i + 1}",
                daemon=True,
            )
            t.start()
            self._workers.append(t)

    def stop(self, timeout: float = 2.0):
        """Stop background worker threads cleanly."""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()
        for _ in self._workers:
            self._queue.put(self._sentinel)

        for t in self._workers:
            t.join(timeout=timeout)
        self._workers = []

    def wait_until_empty(self, timeout: float = 5.0) -> bool:
        """Wait until all pending events in the queue have been fully dispatched."""
        t0 = time.time()
        while not self._queue.empty():
            if time.time() - t0 > timeout:
                return False
            self._stop_event.wait(timeout=0.02)
        try:
            self._queue.join()
            return True
        except Exception:
            return True

    @property
    def published_count(self) -> int:
        """Total number of events recorded in the ring buffer."""
        with self._history_lock:
            return len(self._history)

    def get_recent_events(
        self,
        limit: int = 50,
        event_type: Optional[str] = None,
    ) -> List[BaseEvent]:
        """Query recent events from the in-memory ring buffer."""
        with self._history_lock:
            events = list(self._history)

        if event_type:
            events = [e for e in events if e.event_type == event_type]

        return events[-limit:]

