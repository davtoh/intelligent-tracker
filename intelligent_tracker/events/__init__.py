"""Event Dispatching, Alerting, and Pub/Sub Subsystem.

Re-exports 100% of event dataclasses, event bus, dispatchers, rule engines,
and snapshot helpers for complete backward compatibility across all modules and tests.
"""

from intelligent_tracker.events.bus import EventBus
from intelligent_tracker.events.mqtt import MqttPublisher
from intelligent_tracker.events.pipeline import setup_event_pipeline
from intelligent_tracker.events.rules import AlertRule, AlertRuleEngine, QuietHours
from intelligent_tracker.events.telegram import TelegramDispatcher
from intelligent_tracker.events.types import (
    BaseEvent,
    EntityIdentifiedEvent,
    IntrusionAlert,
    OccupancyThresholdEvent,
    PetActivityEvent,
    RSACViolationEvent,
    RestrictedEntityAlert,
    ReviewItemQueuedEvent,
    TripwireCrossEvent,
    ZoneEvent,
    crop_to_base64,
    decode_snapshot_base64,
    frame_to_base64,
)
from intelligent_tracker.events.webhooks import WebhookDispatcher

__all__ = [
    # Snapshot Helpers
    "frame_to_base64",
    "crop_to_base64",
    "decode_snapshot_base64",
    # Typed Event Dataclasses
    "BaseEvent",
    "ZoneEvent",
    "TripwireCrossEvent",
    "IntrusionAlert",
    "OccupancyThresholdEvent",
    "EntityIdentifiedEvent",
    "RestrictedEntityAlert",
    "RSACViolationEvent",
    "PetActivityEvent",
    "ReviewItemQueuedEvent",
    # Event Bus
    "EventBus",
    # Dispatchers
    "WebhookDispatcher",
    "TelegramDispatcher",
    "MqttPublisher",
    # Rules & Scheduling
    "QuietHours",
    "AlertRule",
    "AlertRuleEngine",
    # Pipeline Factory
    "setup_event_pipeline",
]

