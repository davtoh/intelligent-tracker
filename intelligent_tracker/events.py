#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Event Dispatching & Alerting System.

Provides:
- Typed event dataclasses: `BaseEvent`, `ZoneEvent`, `TripwireCrossEvent`,
  `IntrusionAlert`, `OccupancyThresholdEvent`, `EntityIdentifiedEvent`,
  `RestrictedEntityAlert`.
- `EventBus`: Thread-safe publish/subscribe asynchronous dispatch queue.
- `WebhookDispatcher`: HTTP POST delivery with exponential backoff retries.
- `TelegramDispatcher`: Telegram Bot API notifications with image snapshots,
  rate limiting, and `/status` command handling.
- `MqttPublisher`: Home Assistant / Node-RED compatible MQTT telemetry and
  retained topics.
- `QuietHours` & `AlertRuleEngine`: Time-of-day schedules, entity-specific
  filters, dwell-time rules, and notification cooldowns.
"""

from __future__ import division, print_function, absolute_import

import os
import sys
import time
import json
import uuid
import base64
import logging
import threading
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, time as dtime
from typing import List, Dict, Tuple, Optional, Any, Union, Callable, Set, Type

import cv2
import numpy as np

# Optional dependencies with safe fallbacks
try:
    import requests
except ImportError:
    requests = None

try:
    import urllib.request as urllib_request
    import urllib.error as urllib_error
except ImportError:
    urllib_request = None
    urllib_error = None

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

logger = logging.getLogger(__name__)


# ==============================================================================
# 1. Snapshot Encoding Helpers
# ==============================================================================

def frame_to_base64(
    frame: np.ndarray,
    quality: int = 80,
    max_dimension: Optional[int] = 640,
) -> Optional[str]:
    """
    Encode an OpenCV BGR frame into a base64-encoded JPEG string.

    :param frame: Video frame as NumPy array (H, W, 3).
    :param quality: JPEG quality (1-100).
    :param max_dimension: Optional maximum width/height constraint for downsampling.
    :return: Base64 ASCII string or None if frame is invalid.
    """
    if frame is None or frame.size == 0:
        return None

    h, w = frame.shape[:2]
    if max_dimension and (w > max_dimension or h > max_dimension):
        scale = float(max_dimension) / float(max(w, h))
        target_w = max(1, int(round(w * scale)))
        target_h = max(1, int(round(h * scale)))
        frame = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)

    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), max(10, min(100, int(quality)))]
    success, buffer = cv2.imencode(".jpg", frame, encode_params)
    if not success:
        return None

    return base64.b64encode(buffer).decode("ascii")


def crop_to_base64(
    frame: np.ndarray,
    bbox: Tuple[int, int, int, int],
    quality: int = 85,
    padding: int = 12,
) -> Optional[str]:
    """
    Crop bounding box region from frame with margin padding and encode to base64.

    :param frame: Video frame as NumPy array (H, W, 3).
    :param bbox: (x, y, w, h) in pixels.
    :param quality: JPEG quality (1-100).
    :param padding: Margin in pixels around bbox.
    :return: Base64 JPEG string or None.
    """
    if frame is None or bbox is None:
        return None

    h, w = frame.shape[:2]
    bx, by, bw, bh = bbox
    x0 = max(0, int(bx - padding))
    y0 = max(0, int(by - padding))
    x1 = min(w, int(bx + bw + padding))
    y1 = min(h, int(by + bh + padding))

    if x1 <= x0 or y1 <= y0:
        return None

    crop = frame[y0:y1, x0:x1]
    return frame_to_base64(crop, quality=quality, max_dimension=None)


def decode_snapshot_base64(b64_str: str) -> Optional[np.ndarray]:
    """Decode a base64 JPEG string back into an OpenCV BGR frame."""
    if not b64_str:
        return None
    try:
        raw_bytes = base64.b64decode(b64_str)
        arr = np.frombuffer(raw_bytes, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception as e:
        logger.warning("Failed to decode base64 snapshot: %s", e)
        return None


# ==============================================================================
# 2. Typed Event Data Classes
# ==============================================================================

@dataclass
class BaseEvent:
    """Base event contract for all intelligent tracker telemetry and alerts."""
    event_type: str = "generic_event"
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    camera_id: str = "cam_01"
    snapshot_base64: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self, include_snapshot: bool = True) -> Dict[str, Any]:
        """Convert event to serializable dictionary."""
        d = asdict(self)
        if not include_snapshot:
            d.pop("snapshot_base64", None)
        return d

    def to_json(self, include_snapshot: bool = True, indent: Optional[int] = None) -> str:
        """Convert event to JSON string."""
        return json.dumps(self.to_dict(include_snapshot=include_snapshot), default=str, indent=indent)


@dataclass
class ZoneEvent(BaseEvent):
    """Event emitted when a tracked entity enters, dwells, or exits a ZoneROI."""
    event_type: str = "zone_event"
    zone_id: str = ""
    track_id: int = 0
    action: str = "enter"  # 'enter', 'exit', 'dwell'
    dwell_time: float = 0.0
    centroid: Optional[Tuple[float, float]] = None
    bbox: Optional[Tuple[int, int, int, int]] = None
    entity_id: Optional[int] = None
    entity_name: Optional[str] = None
    entity_category: Optional[str] = None

    def __post_init__(self):
        if self.event_type in ("zone_event", "generic_event", "") or not self.event_type:
            self.event_type = "zone_{}".format(self.action)


@dataclass
class TripwireCrossEvent(BaseEvent):
    """Event emitted when an entity traverses a virtual directional tripwire."""
    event_type: str = "tripwire_cross"
    tripwire_id: str = ""
    track_id: int = 0
    direction: str = "in"  # 'in', 'out', 'A_to_B', 'B_to_A'
    pt1: Optional[Tuple[float, float]] = None
    pt2: Optional[Tuple[float, float]] = None
    centroid: Optional[Tuple[float, float]] = None
    entity_id: Optional[int] = None
    entity_name: Optional[str] = None
    entity_category: Optional[str] = None


@dataclass
class IntrusionAlert(BaseEvent):
    """Security alert emitted on unauthorized zone access or tripwire breach."""
    event_type: str = "intrusion_alert"
    zone_id: str = ""
    track_id: int = 0
    label: str = "person"
    entity_id: Optional[int] = None
    entity_name: Optional[str] = None
    entity_category: Optional[str] = None
    severity: str = "critical"  # "info", "warning", "critical"
    message: str = ""
    dwell_time: float = 0.0


@dataclass
class OccupancyThresholdEvent(BaseEvent):
    """Alert emitted when a zone exceeds or clears its capacity threshold."""
    event_type: str = "occupancy_threshold"
    zone_id: str = ""
    current_occupancy: int = 0
    threshold: int = 0
    breach_type: str = "exceeded"  # "exceeded", "cleared"
    severity: str = "warning"
    message: str = ""


@dataclass
class EntityIdentifiedEvent(BaseEvent):
    """Emitted when visual Re-ID matches a track against the canonical gallery."""
    event_type: str = "entity_identified"
    track_id: int = 0
    entity_id: int = 0
    name: str = ""
    category: str = "general"
    similarity: float = 0.0
    zone_id: Optional[str] = None
    severity: str = "info"
    message: str = ""


@dataclass
class RestrictedEntityAlert(BaseEvent):
    """Alert emitted when a restricted/blacklisted entity is recognized."""
    event_type: str = "restricted_entity_alert"
    zone_id: Optional[str] = None
    track_id: int = 0
    entity_id: Optional[int] = None
    name: str = ""
    category: str = "restricted"
    severity: str = "critical"
    message: str = ""


# ==============================================================================
# 3. Centralized Event Bus (Pub/Sub with Async Queue)
# ==============================================================================

class EventBus(object):
    """
    Thread-safe Publish/Subscribe asynchronous event bus.

    Features:
    - Dedicated background worker threads consuming an internal `Queue`.
    - Zero event loss with synchronous or asynchronous dispatch.
    - Type-based and predicate-based subscriber filtering.
    - Historical ring buffer for telemetry queries and audit inspection.
    - Error isolation: handler exceptions are captured without blocking other handlers.
    """

    def __init__(self, history_limit: int = 500):
        try:
            import queue
        except ImportError:
            import Queue as queue

        self._queue = queue.Queue()
        self._subscribers: List[Tuple[Callable[[BaseEvent], Any], Optional[Callable[[BaseEvent], bool]], Optional[Type]]] = []
        self._sub_lock = threading.Lock()
        self._workers: List[threading.Thread] = []
        self._running = False
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
        while self._running:
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
        self._workers = []
        for i in range(max(1, int(num_workers))):
            t = threading.Thread(
                target=self._worker_loop,
                name="EventBusWorker-{}".format(i + 1),
                daemon=True,
            )
            t.start()
            self._workers.append(t)

    def stop(self, timeout: float = 2.0):
        """Stop background worker threads cleanly."""
        if not self._running:
            return

        self._running = False
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
            time.sleep(0.02)
        try:
            self._queue.join()
            return True
        except Exception:
            return True

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


# ==============================================================================
# 4. Webhook Dispatcher
# ==============================================================================

class WebhookDispatcher(object):
    """
    HTTP POST Webhook Dispatcher with retry logic and exponential backoff.

    Delivers JSON payloads on tripwire crosses, zone intrusions, capacity
    threshold breaches, or tagged entity sightings.
    """

    def __init__(
        self,
        url: str,
        auth_header: Optional[Union[str, Dict[str, str]]] = None,
        timeout: float = 5.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        include_snapshot: bool = True,
        event_types: Optional[List[str]] = None,
        headers: Optional[Dict[str, str]] = None,
        custom_headers: Optional[Dict[str, str]] = None,
    ):
        self.url = str(url)
        self.auth_header = auth_header
        self.timeout = float(timeout)
        self.max_retries = max(1, int(max_retries))
        self.backoff_factor = float(backoff_factor)
        self.include_snapshot = bool(include_snapshot)
        self.event_types = set(event_types) if event_types else None
        self.custom_headers = dict(headers or custom_headers or {})

        # Telemetry metrics
        self.sent_count = 0
        self.failed_count = 0
        self.retry_count = 0
        self.last_status_code = 0
        self.last_error = None
        self.history: List[Dict[str, Any]] = []

    def build_payload(self, event: BaseEvent) -> Dict[str, Any]:
        """Construct standard JSON webhook payload."""
        base_dict = event.to_dict(include_snapshot=False)
        payload = {
            "camera_id": event.camera_id,
            "event_id": event.event_id,
            "event_type": event.event_type,
            "timestamp": event.timestamp,
            "zone_id": getattr(event, "zone_id", None),
            "entity_id": getattr(event, "entity_id", None),
            "entity_name": getattr(event, "entity_name", getattr(event, "name", None)),
            "severity": getattr(event, "severity", "info"),
            "data": base_dict,
        }
        if self.include_snapshot and event.snapshot_base64:
            payload["snapshot"] = event.snapshot_base64

        return payload

    def _prepare_headers(self) -> Dict[str, str]:
        """Prepare request headers including authentication."""
        h = {
            "Content-Type": "application/json",
            "User-Agent": "IntelligentTracker-Webhook/1.0",
        }
        h.update(self.custom_headers)

        if self.auth_header:
            if isinstance(self.auth_header, dict):
                h.update(self.auth_header)
            elif isinstance(self.auth_header, str):
                if self.auth_header.lower().startswith(("bearer ", "token ", "basic ")):
                    h["Authorization"] = self.auth_header
                else:
                    h["Authorization"] = "Bearer {}".format(self.auth_header)
        return h

    def send(self, event: BaseEvent) -> bool:
        """
        Send event via HTTP POST with retries and exponential backoff.

        :param event: BaseEvent to dispatch.
        :return: True if delivered successfully (HTTP 2xx), False otherwise.
        """
        if self.event_types and event.event_type not in self.event_types:
            return False

        payload = self.build_payload(event)
        headers = self._prepare_headers()
        json_data = json.dumps(payload).encode("utf-8")

        for attempt in range(1, self.max_retries + 1):
            try:
                # 1. Try requests if installed
                if requests is not None:
                    resp = requests.post(
                        self.url,
                        data=json_data,
                        headers=headers,
                        timeout=self.timeout,
                    )
                    self.last_status_code = resp.status_code
                    if 200 <= resp.status_code < 300:
                        self.sent_count += 1
                        self.history.append({"event_id": event.event_id, "status": resp.status_code})
                        return True
                    else:
                        raise RuntimeError("HTTP status {}".format(resp.status_code))

                # 2. Standard library urllib fallback
                elif urllib_request is not None:
                    req = urllib_request.Request(self.url, data=json_data, headers=headers, method="POST")
                    with urllib_request.urlopen(req, timeout=self.timeout) as resp:
                        code = resp.getcode()
                        self.last_status_code = code
                        if 200 <= code < 300:
                            self.sent_count += 1
                            self.history.append({"event_id": event.event_id, "status": code})
                            return True
                        else:
                            raise RuntimeError("HTTP status {}".format(code))
                else:
                    raise RuntimeError("Neither requests nor urllib available.")

            except Exception as e:
                self.last_error = str(e)
                if attempt < self.max_retries:
                    self.retry_count += 1
                    sleep_time = self.backoff_factor * (2 ** (attempt - 1))
                    time.sleep(sleep_time)
                else:
                    self.failed_count += 1
                    logger.warning("Webhook failed to %s after %d retries: %s", self.url, attempt, e)

        return False


# ==============================================================================
# 5. Telegram Bot Dispatcher
# ==============================================================================

class TelegramDispatcher(object):
    """
    Telegram Bot alert integration with rate limiting and snapshot delivery.

    Features:
    - Markdown alert banners with status icons (🚨, ⚠️, 👤, 🛑).
    - Image snapshot uploads (JPEG base64 decoded).
    - Rate-limiting cooldown per zone/entity to prevent alert floods.
    - `/status` query responder returning live occupancy and sighting history.
    - Offline mock mode when token is absent or "mock".
    """

    def __init__(
        self,
        token: Optional[str] = None,
        chat_id: Optional[str] = None,
        cooldown: float = 60.0,
        include_snapshot: bool = True,
        enabled: bool = True,
        mock: bool = False,
    ):
        self.token = str(token or "").strip()
        self.chat_id = str(chat_id or "").strip()
        self.cooldown = max(0.0, float(cooldown))
        self.include_snapshot = bool(include_snapshot)
        self.enabled = bool(enabled)
        self.mock = bool(mock) or not self.token or self.token.lower() == "mock"

        self._last_alert_time: Dict[str, float] = {}
        self._lock = threading.Lock()
        self.sent_messages: List[Dict[str, Any]] = []

    def _get_cooldown_key(self, event: BaseEvent) -> str:
        """Compute unique rate limiting key for deduplication."""
        zone = getattr(event, "zone_id", None) or "global"
        entity = getattr(event, "entity_name", None) or getattr(event, "name", None) or getattr(event, "track_id", "")
        return "{}:{}:{}".format(event.event_type, zone, entity)

    def is_cooling_down(self, event: BaseEvent, now: Optional[float] = None) -> bool:
        """Check if an event of this key was sent within the cooldown window."""
        if self.cooldown <= 0.0:
            return False

        t = now if now is not None else time.time()
        key = self._get_cooldown_key(event)
        with self._lock:
            last = self._last_alert_time.get(key, 0.0)
            if (t - last) < self.cooldown:
                return True
            self._last_alert_time[key] = t
            return False

    def format_message(self, event: BaseEvent) -> str:
        """Format an event into a clear, aesthetic Telegram Markdown alert."""
        severity = getattr(event, "severity", "info").upper()
        if severity == "CRITICAL" or isinstance(event, (IntrusionAlert, RestrictedEntityAlert)):
            banner = "🚨 *INTELLIGENT TRACKER: SECURITY ALERT*"
        elif severity == "WARNING" or isinstance(event, OccupancyThresholdEvent):
            banner = "⚠️ *INTELLIGENT TRACKER: CAPACITY WARNING*"
        elif isinstance(event, EntityIdentifiedEvent):
            banner = "👤 *INTELLIGENT TRACKER: RECOGNITION*"
        else:
            banner = "ℹ️ *INTELLIGENT TRACKER: EVENT*"

        time_str = datetime.fromtimestamp(event.timestamp).strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            banner,
            "━━━━━━━━━━━━━━━━━━━━━━",
            "• *Event*: `{}`".format(event.event_type),
            "• *Camera*: `{}`".format(event.camera_id),
            "• *Time*: `{}`".format(time_str),
        ]

        zone_id = getattr(event, "zone_id", None)
        if zone_id:
            lines.append("• *Zone*: `{}`".format(zone_id))

        tripwire_id = getattr(event, "tripwire_id", None)
        if tripwire_id:
            direction = getattr(event, "direction", "")
            lines.append("• *Tripwire*: `{}` ({})".format(tripwire_id, direction))

        ent_name = getattr(event, "entity_name", None) or getattr(event, "name", None)
        if ent_name:
            cat = getattr(event, "entity_category", getattr(event, "category", "general"))
            lines.append("• *Entity*: *{}* (`{}`)".format(ent_name, cat))

        track_id = getattr(event, "track_id", None)
        if track_id is not None:
            lines.append("• *Track ID*: #{}".format(track_id))

        if isinstance(event, OccupancyThresholdEvent):
            lines.append("• *Occupancy*: {} / Max {}".format(event.current_occupancy, event.threshold))

        msg = getattr(event, "message", None)
        if msg:
            lines.append("• *Note*: _{}_".format(msg))

        return "\n".join(lines)

    def send(self, event: BaseEvent) -> bool:
        """
        Deliver event to Telegram chat if enabled and not cooled down.

        :param event: Event instance to send.
        :return: True if delivered or queued in mock mode.
        """
        if not self.enabled:
            return False

        if self.is_cooling_down(event):
            return False

        text = self.format_message(event)
        snapshot_b64 = event.snapshot_base64 if self.include_snapshot else None

        if self.mock:
            self.sent_messages.append({
                "chat_id": self.chat_id,
                "text": text,
                "has_snapshot": bool(snapshot_b64),
                "timestamp": time.time(),
            })
            return True

        # Send via Telegram Bot API HTTP REST endpoints
        try:
            if snapshot_b64:
                return self._send_photo_api(text, snapshot_b64)
            else:
                return self._send_message_api(text)
        except Exception as e:
            logger.warning("Telegram dispatch error: %s", e)
            return False

    def _send_message_api(self, text: str) -> bool:
        """Post message to Telegram API."""
        url = "https://api.telegram.org/bot{}/sendMessage".format(self.token)
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        if requests is not None:
            r = requests.post(url, json=payload, timeout=8.0)
            return 200 <= r.status_code < 300
        elif urllib_request is not None:
            data = json.dumps(payload).encode("utf-8")
            req = urllib_request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
            with urllib_request.urlopen(req, timeout=8.0) as resp:
                return 200 <= resp.getcode() < 300
        return False

    def _send_photo_api(self, caption: str, snapshot_b64: str) -> bool:
        """Upload snapshot JPEG image to Telegram API with caption."""
        url = "https://api.telegram.org/bot{}/sendPhoto".format(self.token)
        raw_bytes = base64.b64decode(snapshot_b64)

        if requests is not None:
            files = {"photo": ("snapshot.jpg", raw_bytes, "image/jpeg")}
            data = {"chat_id": self.chat_id, "caption": caption, "parse_mode": "Markdown"}
            r = requests.post(url, data=data, files=files, timeout=12.0)
            return 200 <= r.status_code < 300
        else:
            return self._send_message_api(caption)

    def get_status_summary(
        self,
        analytics_engine: Optional[Any] = None,
        event_bus: Optional[EventBus] = None,
    ) -> str:
        """Compile a concise status report for `/status` Telegram commands."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            "📊 *INTELLIGENT TRACKER STATUS*",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "• *Time*: `{}`".format(now_str),
        ]

        if analytics_engine is not None:
            lines.append("• *Total Analyzed Frames*: {}".format(getattr(analytics_engine, "total_frames_analyzed", 0)))
            zones = getattr(analytics_engine, "zones", {})
            if zones:
                lines.append("\n📍 *Zone Occupancy:*")
                for name, z in zones.items():
                    lines.append("  - `{}`: {} occupants (Total: {})".format(name, z.occupancy, z.total_entries))

            tripwires = getattr(analytics_engine, "tripwires", {})
            if tripwires:
                lines.append("\n⚡ *Tripwire Crossings:*")
                for name, tw in tripwires.items():
                    lines.append("  - `{}`: In: {} | Out: {}".format(name, tw.total_in, tw.total_out))

        if event_bus is not None:
            recent = event_bus.get_recent_events(limit=5)
            if recent:
                lines.append("\n🔔 *Recent Events:*")
                for ev in recent:
                    lines.append("  - `{}` ({})".format(ev.event_type, getattr(ev, "zone_id", getattr(ev, "tripwire_id", ""))))

        return "\n".join(lines)

    def handle_command(
        self,
        command_text: str,
        analytics_engine: Optional[Any] = None,
        event_bus: Optional[EventBus] = None,
    ) -> str:
        """Handle incoming bot commands like `/status` or `/help`."""
        cmd = command_text.strip().lower()
        if cmd in ("/status", "status"):
            return self.get_status_summary(analytics_engine, event_bus)
        elif cmd in ("/help", "help"):
            return (
                "🤖 *Intelligent Tracker Bot Commands:*\n"
                "• `/status` - Live occupancy count, tripwires & recent alerts.\n"
                "• `/occupancy` - Summary of active zone capacities.\n"
                "• `/help` - Show this guidance menu."
            )
        elif cmd in ("/occupancy", "occupancy"):
            if not analytics_engine or not getattr(analytics_engine, "zones", None):
                return "ℹ️ No active zones registered."
            res = ["🏢 *Current Zone Occupancy:*"]
            for name, z in analytics_engine.zones.items():
                res.append("• *{}*: `{}` entities".format(name, z.occupancy))
            return "\n".join(res)
        else:
            return "❓ Unknown command. Send `/help` for available commands."


# ==============================================================================
# 6. MQTT Publisher
# ==============================================================================

class MqttPublisher(object):
    """
    Lightweight MQTT Telemetry Publisher for Home Assistant, Node-RED & IoT.

    Topics:
    - `tracker/{camera_id}/occupancy` (JSON with counts, retained=True)
    - `tracker/{camera_id}/events` (JSON event stream, retained=False)
    - `tracker/{camera_id}/sightings/{entity_id}` (JSON entity sighting, retained=True)
    - `tracker/{camera_id}/status` (LWT: 'online' / 'offline', retained=True)
    """

    def __init__(
        self,
        broker: str = "localhost",
        port: int = 1883,
        username: Optional[str] = None,
        password: Optional[str] = None,
        client_id: str = "intelligent_tracker",
        base_topic: str = "tracker",
        qos: int = 1,
        retain_occupancy: bool = True,
        retain_sightings: bool = True,
        mock: bool = False,
    ):
        self.broker = str(broker)
        self.port = int(port)
        self.username = username
        self.password = password
        self.client_id = str(client_id)
        self.base_topic = str(base_topic).rstrip("/")
        self.qos = int(qos)
        self.retain_occupancy = bool(retain_occupancy)
        self.retain_sightings = bool(retain_sightings)
        self.mock = bool(mock) or (mqtt is None)

        self._client = None
        self._connected = False
        self.published_messages: List[Dict[str, Any]] = []

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self, timeout: float = 5.0) -> bool:
        """Establish connection to MQTT broker and configure LWT."""
        if self.mock:
            self._connected = True
            return True

        if mqtt is None:
            self.mock = True
            self._connected = True
            return True

        try:
            if hasattr(mqtt, "CallbackAPIVersion"):
                self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id)
            else:
                self._client = mqtt.Client(client_id=self.client_id)

            if self.username and self.password:
                self._client.username_pw_set(self.username, self.password)

            status_topic = "{}/system/status".format(self.base_topic)
            self._client.will_set(status_topic, payload="offline", qos=self.qos, retain=True)

            def on_connect(client, userdata, flags, rc, *args, **kwargs):
                if rc == 0:
                    self._connected = True
                    client.publish(status_topic, payload="online", qos=self.qos, retain=True)
                else:
                    self._connected = False

            self._client.on_connect = on_connect
            self._client.connect(self.broker, self.port, keepalive=60)
            self._client.loop_start()

            t0 = time.time()
            while not self._connected and (time.time() - t0 < timeout):
                time.sleep(0.05)

            return self._connected

        except Exception as e:
            logger.warning("Could not connect to MQTT broker %s:%d: %s (falling back to mock mode)", self.broker, self.port, e)
            self.mock = True
            self._connected = True
            return True

    def disconnect(self):
        """Publish offline status and disconnect from broker."""
        if self._client and not self.mock:
            try:
                status_topic = "{}/system/status".format(self.base_topic)
                self._client.publish(status_topic, payload="offline", qos=self.qos, retain=True)
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
        self._connected = False

    def publish(self, topic: str, payload: Any, qos: Optional[int] = None, retain: bool = False) -> bool:
        """Publish a message to MQTT topic."""
        q = self.qos if qos is None else qos
        if not isinstance(payload, str):
            payload_str = json.dumps(payload, default=str)
        else:
            payload_str = payload

        self.published_messages.append({
            "topic": topic,
            "payload": payload_str,
            "qos": q,
            "retain": retain,
            "timestamp": time.time(),
        })

        if self.mock or not self._client or not self._connected:
            return True

        try:
            info = self._client.publish(topic, payload=payload_str, qos=q, retain=retain)
            return info.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:
            logger.warning("Failed to publish to MQTT topic %s: %s", topic, e)
            return False

    def publish_occupancy(
        self,
        camera_id: str,
        zone_occupancy: Dict[str, int],
        total_tracks: int,
        timestamp: Optional[float] = None,
    ) -> bool:
        """
        Publish camera occupancy telemetry (Home Assistant compatible).
        Topic: `tracker/{camera_id}/occupancy`
        """
        topic = "{}/{}/occupancy".format(self.base_topic, camera_id)
        payload = {
            "camera_id": camera_id,
            "timestamp": timestamp or time.time(),
            "total_tracks": int(total_tracks),
            "zones": dict(zone_occupancy),
        }
        return self.publish(topic, payload, retain=self.retain_occupancy)

    def publish_event(self, event: BaseEvent) -> bool:
        """
        Publish an event stream message.
        Topic: `tracker/{camera_id}/events`
        """
        topic = "{}/{}/events".format(self.base_topic, event.camera_id)
        payload = event.to_dict(include_snapshot=False)
        return self.publish(topic, payload, retain=False)

    def publish_sighting(
        self,
        camera_id: str,
        entity_id: int,
        name: str,
        category: str,
        zone_id: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> bool:
        """
        Publish last-known location of recognized entity.
        Topic: `tracker/{camera_id}/sightings/{entity_id}`
        """
        topic = "{}/{}/sightings/{}".format(self.base_topic, camera_id, entity_id)
        payload = {
            "camera_id": camera_id,
            "entity_id": int(entity_id),
            "name": str(name),
            "category": str(category),
            "zone_id": zone_id,
            "timestamp": timestamp or time.time(),
        }
        return self.publish(topic, payload, retain=self.retain_sightings)

    def send(self, event: BaseEvent) -> bool:
        """Convenience subscriber method for EventBus."""
        ok = self.publish_event(event)
        if isinstance(event, EntityIdentifiedEvent) and event.entity_id:
            self.publish_sighting(
                camera_id=event.camera_id,
                entity_id=event.entity_id,
                name=event.name,
                category=event.category,
                zone_id=event.zone_id,
                timestamp=event.timestamp,
            )
        return ok


# ==============================================================================
# 7. Quiet Hours & Alert Rule Engine
# ==============================================================================

class QuietHours(object):
    """
    Time-of-day quiet hours schedule evaluation (handles overnight spans).

    Example:
    `QuietHours("22:00", "06:00")` evaluates True between 10:00 PM and 6:00 AM.
    """

    def __init__(
        self,
        start_time: str = "22:00",
        end_time: str = "06:00",
        days: Optional[List[int]] = None,
    ):
        self.start_str = start_time
        self.end_str = end_time
        self.start_t = self._parse_time(start_time)
        self.end_t = self._parse_time(end_time)
        self.days = set(days) if days is not None else set(range(7))

    def _parse_time(self, s: str) -> dtime:
        """Parse HH:MM string to datetime.time."""
        parts = [int(p) for p in str(s).strip().split(":")]
        hour = parts[0]
        minute = parts[1] if len(parts) > 1 else 0
        second = parts[2] if len(parts) > 2 else 0
        return dtime(hour=hour, minute=minute, second=second)

    def is_quiet_hour(self, dt: Optional[datetime] = None) -> bool:
        """Return True if specified datetime falls within quiet hours."""
        now = dt if dt is not None else datetime.now()

        if now.weekday() not in self.days:
            return False

        curr_t = now.time()

        if self.start_t <= self.end_t:
            return self.start_t <= curr_t <= self.end_t
        else:
            return curr_t >= self.start_t or curr_t <= self.end_t


@dataclass
class AlertRule:
    """
    Configurable alerting rule definition.

    Matches events based on zone, event type, entity category, dwell time,
    and quiet hours schedule.
    """
    name: str
    zone_id: Optional[str] = None
    event_types: Optional[List[str]] = None
    categories: Optional[List[str]] = None
    min_dwell_time: Optional[float] = None
    quiet_hours_only: bool = False
    quiet_hours: Optional[QuietHours] = None
    cooldown: float = 60.0
    severity: str = "critical"
    message_template: Optional[str] = None
    message: Optional[str] = None
    actions: List[str] = field(default_factory=lambda: ["webhook", "telegram", "mqtt"])

    def __post_init__(self):
        if not self.message_template and self.message:
            self.message_template = self.message

    def matches(self, event: BaseEvent, dt: Optional[datetime] = None) -> bool:
        """Evaluate if event satisfies rule criteria."""
        # 1. Zone filter
        if self.zone_id and getattr(event, "zone_id", None) != self.zone_id:
            return False

        # 2. Event type filter
        if self.event_types:
            ev_action = getattr(event, "action", None)
            matched = (event.event_type in self.event_types) or (ev_action in self.event_types)
            if not matched:
                return False

        # 3. Category filter
        if self.categories:
            ent_cat = getattr(event, "entity_category", getattr(event, "category", None))
            if ent_cat is None:
                ent_cat = "unknown"
            if ent_cat.lower() not in [c.lower() for c in self.categories]:
                return False

        # 4. Dwell time filter
        if self.min_dwell_time is not None:
            dwell = getattr(event, "dwell_time", 0.0)
            if dwell < self.min_dwell_time:
                return False

        # 5. Quiet hours filter
        if self.quiet_hours_only:
            qh = self.quiet_hours
            if qh is None:
                qh = QuietHours("22:00", "06:00")
            if not qh.is_quiet_hour(dt):
                return False

        return True


class AlertRuleEngine(object):
    """
    Evaluates events against configurable security rules and quiet hours.

    Generates specialized alerts (`IntrusionAlert`, `RestrictedEntityAlert`,
    `OccupancyThresholdEvent`) and enqueues them on the `EventBus`.
    """

    def __init__(
        self,
        rules: Optional[List[AlertRule]] = None,
        event_bus: Optional[EventBus] = None,
    ):
        self.rules: List[AlertRule] = list(rules or [])
        self.event_bus = event_bus
        self._last_trigger: Dict[str, float] = {}
        self._lock = threading.Lock()

    def add_rule(self, rule: AlertRule):
        self.rules.append(rule)

    def evaluate(
        self,
        event: BaseEvent,
        frame: Optional[np.ndarray] = None,
        dt: Optional[datetime] = None,
    ) -> List[BaseEvent]:
        """
        Evaluate an event against all active rules.

        :param event: Incoming event (ZoneEvent, TripwireCrossEvent, EntityIdentifiedEvent).
        :param frame: Video frame for snapshot attachment.
        :param dt: Optional datetime override for quiet hours test verification.
        :return: List of generated derived alert events.
        """
        # Avoid recursion on derived alerts
        if isinstance(event, (IntrusionAlert, RestrictedEntityAlert)):
            return []

        now_dt = dt or datetime.now()
        now_ts = event.timestamp or time.time()
        generated_alerts: List[BaseEvent] = []

        for rule in self.rules:
            if not rule.matches(event, dt=now_dt):
                continue

            ent_key = getattr(event, "entity_name", None) or getattr(event, "track_id", "")
            rule_key = "{}:{}:{}".format(rule.name, getattr(event, "zone_id", ""), ent_key)

            with self._lock:
                last_time = self._last_trigger.get(rule_key, 0.0)
                if (now_ts - last_time) < rule.cooldown:
                    continue
                self._last_trigger[rule_key] = now_ts

            msg = rule.message_template
            if not msg:
                msg = "Rule '{}' triggered on zone '{}' by entity '{}'".format(
                    rule.name, getattr(event, "zone_id", "all"), ent_key
                )

            snapshot_b64 = event.snapshot_base64
            if not snapshot_b64 and frame is not None:
                bbox = getattr(event, "bbox", None)
                if bbox is not None:
                    snapshot_b64 = crop_to_base64(frame, bbox)
                else:
                    snapshot_b64 = frame_to_base64(frame)

            raw_cat = getattr(event, "entity_category", getattr(event, "category", None)) or ""
            ent_cat = str(raw_cat).lower()
            if ent_cat in ("restricted", "banned", "blacklisted"):
                alert = RestrictedEntityAlert(
                    camera_id=event.camera_id,
                    zone_id=getattr(event, "zone_id", None),
                    track_id=getattr(event, "track_id", 0),
                    entity_id=getattr(event, "entity_id", None),
                    name=str(getattr(event, "entity_name", getattr(event, "name", "Restricted Entity"))),
                    category=ent_cat,
                    severity=rule.severity,
                    message=msg,
                    snapshot_base64=snapshot_b64,
                )
            else:
                alert = IntrusionAlert(
                    camera_id=event.camera_id,
                    zone_id=getattr(event, "zone_id", ""),
                    track_id=getattr(event, "track_id", 0),
                    label=str(getattr(event, "label", "person")),
                    entity_id=getattr(event, "entity_id", None),
                    entity_name=getattr(event, "entity_name", None),
                    entity_category=ent_cat or None,
                    severity=rule.severity,
                    message=msg,
                    dwell_time=getattr(event, "dwell_time", 0.0),
                    snapshot_base64=snapshot_b64,
                )

            generated_alerts.append(alert)
            if self.event_bus is not None:
                self.event_bus.publish(alert)

        return generated_alerts


# ==============================================================================
# 8. Dispatcher Pipeline Setup Helper
# ==============================================================================

def setup_event_pipeline(
    config: Dict[str, Any],
    event_bus: Optional[EventBus] = None,
) -> Dict[str, Any]:
    """
    Parse configuration dictionary and initialize event bus, dispatchers, and rules.

    :param config: Dictionary loaded from YAML (e.g. `configs/alert_demo.yaml`).
    :param event_bus: Optional existing EventBus instance.
    :return: Dictionary containing initialized components.
    """
    bus = event_bus or EventBus()
    alert_cfg = config.get("alerting", config.get("events", {}))

    dispatchers: Dict[str, Any] = {
        "event_bus": bus,
        "webhooks": [],
        "telegram": None,
        "mqtt": None,
        "rule_engine": None,
    }

    # 1. Setup Webhooks
    for wh in alert_cfg.get("webhooks", []):
        url = wh.get("url")
        if url:
            dispatcher = WebhookDispatcher(
                url=url,
                auth_header=wh.get("auth_header") or wh.get("auth_token"),
                timeout=wh.get("timeout", 5.0),
                max_retries=wh.get("max_retries", 3),
                backoff_factor=wh.get("backoff_factor", 0.5),
                include_snapshot=wh.get("include_snapshot", True),
                event_types=wh.get("event_types"),
                headers=wh.get("headers"),
            )
            bus.subscribe(dispatcher.send)
            dispatchers["webhooks"].append(dispatcher)

    # 2. Setup Telegram Bot
    tg_cfg = alert_cfg.get("telegram")
    if tg_cfg and tg_cfg.get("enabled", True):
        tg = TelegramDispatcher(
            token=tg_cfg.get("token"),
            chat_id=tg_cfg.get("chat_id"),
            cooldown=tg_cfg.get("cooldown", 60.0),
            include_snapshot=tg_cfg.get("include_snapshot", True),
            mock=tg_cfg.get("mock", False),
        )
        bus.subscribe(tg.send)
        dispatchers["telegram"] = tg

    # 3. Setup MQTT Publisher
    mqtt_cfg = alert_cfg.get("mqtt")
    if mqtt_cfg and mqtt_cfg.get("enabled", True):
        mqtt_pub = MqttPublisher(
            broker=mqtt_cfg.get("broker", "localhost"),
            port=mqtt_cfg.get("port", 1883),
            username=mqtt_cfg.get("username"),
            password=mqtt_cfg.get("password"),
            client_id=mqtt_cfg.get("client_id", "intelligent_tracker"),
            base_topic=mqtt_cfg.get("base_topic", "tracker"),
            qos=mqtt_cfg.get("qos", 1),
            retain_occupancy=mqtt_cfg.get("retain_occupancy", True),
            retain_sightings=mqtt_cfg.get("retain_sightings", True),
            mock=mqtt_cfg.get("mock", False),
        )
        mqtt_pub.connect()
        bus.subscribe(mqtt_pub.send)
        dispatchers["mqtt"] = mqtt_pub

    # 4. Setup Alert Rules
    rules_cfg = alert_cfg.get("rules", [])
    if rules_cfg:
        rule_objs = []
        for r in rules_cfg:
            qh = None
            qh_cfg = r.get("quiet_hours")
            if qh_cfg:
                qh = QuietHours(
                    start_time=qh_cfg.get("start", "22:00"),
                    end_time=qh_cfg.get("end", "06:00"),
                    days=qh_cfg.get("days"),
                )

            rule_objs.append(
                AlertRule(
                    name=r.get("name", "unnamed_rule"),
                    zone_id=r.get("zone_id"),
                    event_types=r.get("event_types"),
                    categories=r.get("categories"),
                    min_dwell_time=r.get("min_dwell_time"),
                    quiet_hours_only=r.get("quiet_hours_only", False) or (qh is not None),
                    quiet_hours=qh,
                    cooldown=r.get("cooldown", 60.0),
                    severity=r.get("severity", "critical"),
                    message_template=r.get("message"),
                    actions=r.get("actions", ["webhook", "telegram", "mqtt"]),
                )
            )

        rule_engine = AlertRuleEngine(rules=rule_objs, event_bus=bus)
        bus.subscribe(lambda ev: rule_engine.evaluate(ev))
        dispatchers["rule_engine"] = rule_engine

    # Start event bus async workers
    bus.start()
    return dispatchers
