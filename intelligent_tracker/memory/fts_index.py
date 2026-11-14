"""EventBus Subscriber Indexing Live Pipeline & World Events into SQLite FTS5."""

import logging
import sqlite3
import threading
import time
from typing import Any

from intelligent_tracker.memory._event_formatters import normalize_event_doc
from intelligent_tracker.world.events import EntityStateChangedEvent

logger = logging.getLogger(__name__)


class EventFTSIndex:
    """Subscribes to EventBus events and indexes timeline documents into TrackerDB FTS5."""

    def __init__(
        self,
        db: Any,
        *,
        event_bus: Any = None,
        state_event_cooldown: float = 0.0,
        auto_attach: bool = True,
    ) -> None:
        self.db = db
        self.state_event_cooldown = max(0.0, float(state_event_cooldown))
        self._lock = threading.Lock()
        self._attached_buses: list[Any] = []
        self._last_state_indexed: dict[str, float] = {}
        if event_bus is not None and auto_attach:
            self.attach(event_bus)

    def attach(self, event_bus: Any) -> bool:
        """Attach subscriber handler to an EventBus instance."""
        if event_bus is None:
            return False
        with self._lock:
            if any(bus is event_bus for bus in self._attached_buses):
                return False
            self._attached_buses.append(event_bus)
        event_bus.subscribe(self.handle_event)
        return True

    def detach(self, event_bus: Any = None) -> None:
        """Detach subscriber handler from one or all attached EventBus instances."""
        with self._lock:
            if event_bus is None:
                targets = list(self._attached_buses)
                self._attached_buses.clear()
            else:
                targets = [bus for bus in self._attached_buses if bus is event_bus]
                self._attached_buses = [bus for bus in self._attached_buses if bus is not event_bus]
        for bus in targets:
            bus.unsubscribe(self.handle_event)

    stop = detach

    def _should_index_state_event(self, event: EntityStateChangedEvent) -> bool:
        """Check per-world-entity cooldown for high-frequency EntityStateChangedEvents."""
        if self.state_event_cooldown <= 0.0 or event.change_type == "added":
            return True
        now = float(event.timestamp or time.time())
        with self._lock:
            prev = self._last_state_indexed.get(event.world_entity_id)
            if prev is not None and (now - prev) < self.state_event_cooldown:
                return False
            self._last_state_indexed[event.world_entity_id] = now
        return True

    def _resolve_entity_meta(
        self, entity_id: int | None, entity_name: str, category: str
    ) -> tuple[str, str]:
        """Resolve missing entity name/category from TrackerDB outside internal locks."""
        if entity_id is None or (entity_name and category) or self.db is None:
            return entity_name, category
        try:
            rec = self.db.get_entity(int(entity_id))
            if rec:
                return entity_name or str(rec.get("name", "")), category or str(rec.get("category", ""))
        except Exception:
            pass
        return entity_name, category

    def _persist_document(self, doc: dict[str, Any]) -> int | None:
        """Persist a normalized document to TrackerDB FTS5 outside locks."""
        if self.db is None:
            return None
        name, cat = self._resolve_entity_meta(doc["entity_id"], doc["entity_name"], doc["category"])
        kwargs = {
            "summary": doc["summary"],
            "event_type": doc["event_type"],
            "entity_id": doc["entity_id"],
            "entity_name": name,
            "category": cat,
            "camera_id": doc["camera_id"],
            "zone_id": doc["zone_id"],
            "timestamp": doc["timestamp"],
            "confidence": doc["confidence"],
            "title": doc["title"],
            "tags": doc["tags"],
            "metadata": doc["metadata"],
        }
        try:
            return int(self.db.index_timeline_event(**kwargs))
        except sqlite3.IntegrityError:
            meta = dict(doc["metadata"])
            meta["unlinked_entity_id"] = doc["entity_id"]
            kwargs["entity_id"] = None
            kwargs["metadata"] = meta
            return int(self.db.index_timeline_event(**kwargs))
        except Exception as exc:
            logger.debug("EventFTSIndex failed indexing %s: %s", doc["event_type"], exc)
            return None

    def handle_event(self, event: Any) -> int | None:
        """Normalize and index an incoming EventBus event outside internal locks."""
        if isinstance(event, EntityStateChangedEvent) and not self._should_index_state_event(event):
            return None
        doc = normalize_event_doc(event)
        if doc is None:
            return None
        return self._persist_document(doc)

    def index_sighting(
        self,
        *,
        entity_id: int | None = None,
        entity_name: str = "",
        category: str = "",
        camera_id: str = "",
        zone_id: str = "",
        confidence: float = 1.0,
        timestamp: float | None = None,
        summary: str = "",
        tags: str = "sighting",
        metadata: dict[str, Any] | None = None,
    ) -> int | None:
        """Explicitly index a sighting observation into the searchable timeline."""
        who = entity_name or (f"Entity {entity_id}" if entity_id is not None else "Unknown entity")
        zone_txt = f" in {zone_id}" if zone_id else ""
        text = summary or f"{who} sighted on {camera_id or 'unknown camera'}{zone_txt} (confidence {confidence:.2f})."
        return self._persist_document({
            "event_type": "sighting",
            "entity_id": entity_id,
            "entity_name": entity_name,
            "category": category,
            "camera_id": camera_id,
            "zone_id": zone_id,
            "timestamp": timestamp if timestamp is not None else time.time(),
            "confidence": float(confidence),
            "title": f"Sighting: {who}",
            "summary": text,
            "tags": tags,
            "metadata": dict(metadata or {}),
        })

    def index_clip_caption(
        self,
        caption: str,
        *,
        camera_id: str = "",
        zone_id: str = "",
        entity_id: int | None = None,
        entity_name: str = "",
        category: str = "",
        timestamp: float | None = None,
        confidence: float = 1.0,
        title: str = "",
        tags: str = "clip,caption",
        metadata: dict[str, Any] | None = None,
    ) -> int | None:
        """Index a semantic clip caption into the searchable timeline."""
        clean_caption = str(caption or "").strip()
        if not clean_caption:
            return None
        return self._persist_document({
            "event_type": "clip_caption",
            "entity_id": entity_id,
            "entity_name": entity_name,
            "category": category,
            "camera_id": camera_id,
            "zone_id": zone_id,
            "timestamp": timestamp if timestamp is not None else time.time(),
            "confidence": float(confidence),
            "title": title or f"Clip caption: {camera_id or 'camera'}",
            "summary": clean_caption,
            "tags": tags,
            "metadata": dict(metadata or {}),
        })
