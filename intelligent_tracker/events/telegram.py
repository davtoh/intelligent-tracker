"""Telegram Bot alert integration with rate limiting and snapshot delivery."""

import base64
from datetime import datetime
import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:
    requests = None

try:
    import urllib.request as urllib_request
except ImportError:
    urllib_request = None

from intelligent_tracker.events.types import (
    BaseEvent,
    EntityIdentifiedEvent,
    IntrusionAlert,
    OccupancyThresholdEvent,
    RestrictedEntityAlert,
)

logger = logging.getLogger(__name__)


class TelegramDispatcher:
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
        return f"{event.event_type}:{zone}:{entity}"

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
            f"• *Event*: `{event.event_type}`",
            f"• *Camera*: `{event.camera_id}`",
            f"• *Time*: `{time_str}`",
        ]

        zone_id = getattr(event, "zone_id", None)
        if zone_id:
            lines.append(f"• *Zone*: `{zone_id}`")

        tripwire_id = getattr(event, "tripwire_id", None)
        if tripwire_id:
            direction = getattr(event, "direction", "")
            lines.append(f"• *Tripwire*: `{tripwire_id}` ({direction})")

        ent_name = getattr(event, "entity_name", None) or getattr(event, "name", None)
        if ent_name:
            cat = getattr(event, "entity_category", getattr(event, "category", "general"))
            lines.append(f"• *Entity*: *{ent_name}* (`{cat}`)")

        track_id = getattr(event, "track_id", None)
        if track_id is not None:
            lines.append(f"• *Track ID*: #{track_id}")

        if isinstance(event, OccupancyThresholdEvent):
            lines.append(f"• *Occupancy*: {event.current_occupancy} / Max {event.threshold}")

        msg = getattr(event, "message", None)
        if msg:
            lines.append(f"• *Note*: _{msg}_")

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
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
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
        url = f"https://api.telegram.org/bot{self.token}/sendPhoto"
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
        event_bus: Optional[Any] = None,
    ) -> str:
        """Compile a concise status report for `/status` Telegram commands."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            "📊 *INTELLIGENT TRACKER STATUS*",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"• *Time*: `{now_str}`",
        ]

        if analytics_engine is not None:
            lines.append(f"• *Total Analyzed Frames*: {getattr(analytics_engine, 'total_frames_analyzed', 0)}")
            zones = getattr(analytics_engine, "zones", {})
            if zones:
                lines.append("\n📍 *Zone Occupancy:*")
                for name, z in zones.items():
                    lines.append(f"  - `{name}`: {z.occupancy} occupants (Total: {z.total_entries})")

            tripwires = getattr(analytics_engine, "tripwires", {})
            if tripwires:
                lines.append("\n⚡ *Tripwire Crossings:*")
                for name, tw in tripwires.items():
                    lines.append(f"  - `{name}`: In: {tw.total_in} | Out: {tw.total_out}")

        if event_bus is not None:
            recent = event_bus.get_recent_events(limit=5)
            if recent:
                lines.append("\n🔔 *Recent Events:*")
                for ev in recent:
                    sub_target = getattr(ev, "zone_id", getattr(ev, "tripwire_id", ""))
                    lines.append(f"  - `{ev.event_type}` ({sub_target})")

        return "\n".join(lines)

    def handle_command(
        self,
        command_text: str,
        analytics_engine: Optional[Any] = None,
        event_bus: Optional[Any] = None,
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
                res.append(f"• *{name}*: `{z.occupancy}` entities")
            return "\n".join(res)
        else:
            return "❓ Unknown command. Send `/help` for available commands."

