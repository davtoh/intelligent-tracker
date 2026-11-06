"""Quiet hours scheduling and rule evaluation engine for security alerts."""

from dataclasses import dataclass, field
from datetime import datetime, time as dtime
import threading
import time
from typing import Any, Dict, List, Optional

import numpy as np

from intelligent_tracker.events.types import (
    BaseEvent,
    IntrusionAlert,
    RestrictedEntityAlert,
    crop_to_base64,
    frame_to_base64,
)


class QuietHours:
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
        if self.zone_id and getattr(event, "zone_id", None) != self.zone_id:
            return False

        if self.event_types:
            ev_action = getattr(event, "action", None)
            matched = (event.event_type in self.event_types) or (ev_action in self.event_types)
            if not matched:
                return False

        if self.categories:
            ent_cat = getattr(event, "entity_category", getattr(event, "category", None))
            if ent_cat is None:
                ent_cat = "unknown"
            if ent_cat.lower() not in [c.lower() for c in self.categories]:
                return False

        if self.min_dwell_time is not None:
            dwell = getattr(event, "dwell_time", 0.0)
            if dwell < self.min_dwell_time:
                return False

        if self.quiet_hours_only:
            qh = self.quiet_hours
            if qh is None:
                qh = QuietHours("22:00", "06:00")
            if not qh.is_quiet_hour(dt):
                return False

        return True


class AlertRuleEngine:
    """
    Evaluates events against configurable security rules and quiet hours.

    Generates specialized alerts (`IntrusionAlert`, `RestrictedEntityAlert`,
    `OccupancyThresholdEvent`) and enqueues them on the `EventBus`.
    """

    def __init__(
        self,
        rules: Optional[List[AlertRule]] = None,
        event_bus: Optional[Any] = None,
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
        if isinstance(event, (IntrusionAlert, RestrictedEntityAlert)):
            return []

        now_dt = dt or datetime.now()
        now_ts = event.timestamp or time.time()
        generated_alerts: List[BaseEvent] = []

        for rule in self.rules:
            if not rule.matches(event, dt=now_dt):
                continue

            ent_key = getattr(event, "entity_name", None) or getattr(event, "track_id", "")
            rule_key = f"{rule.name}:{getattr(event, 'zone_id', '')}:{ent_key}"

            with self._lock:
                last_time = self._last_trigger.get(rule_key, 0.0)
                if (now_ts - last_time) < rule.cooldown:
                    continue
                self._last_trigger[rule_key] = now_ts

            msg = rule.message_template
            if not msg:
                msg = f"Rule '{rule.name}' triggered on zone '{getattr(event, 'zone_id', 'all')}' by entity '{ent_key}'"

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

