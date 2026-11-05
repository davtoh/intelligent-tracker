#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for event data classes, snapshot encoding, and the centralized EventBus.

Tests:
1. Base and specialized typed event dataclasses.
2. Frame and crop JPEG base64 serialization and deserialization.
3. Synchronous and asynchronous pub/sub event delivery with error isolation.
"""

import json
import unittest
import numpy as np

from intelligent_tracker.events import (
    BaseEvent,
    ZoneEvent,
    TripwireCrossEvent,
    IntrusionAlert,
    OccupancyThresholdEvent,
    EntityIdentifiedEvent,
    RestrictedEntityAlert,
    EventBus,
    frame_to_base64,
    crop_to_base64,
    decode_snapshot_base64,
)


class TestEventDataClasses(unittest.TestCase):
    """Test typed event dataclasses and snapshot serialization."""

    def test_base_event_creation_and_json(self):
        """Test BaseEvent initialization, default fields, and JSON serialization."""
        ev = BaseEvent(
            event_type="test_event",
            camera_id="cam_east",
            metadata={"source": "unit_test"},
        )
        self.assertEqual(ev.camera_id, "cam_east")
        self.assertEqual(ev.event_type, "test_event")
        self.assertTrue(len(ev.event_id) > 10)

        json_str = ev.to_json()
        parsed = json.loads(json_str)
        self.assertEqual(parsed["event_type"], "test_event")
        self.assertEqual(parsed["camera_id"], "cam_east")

    def test_spatial_and_tripwire_events(self):
        """Test ZoneEvent and TripwireCrossEvent initialization."""
        ze = ZoneEvent(
            zone_id="storage_room",
            track_id=14,
            action="enter",
            entity_name="Alice",
            entity_category="staff",
        )
        self.assertEqual(ze.event_type, "zone_enter")
        self.assertEqual(ze.zone_id, "storage_room")

        te = TripwireCrossEvent(
            tripwire_id="perimeter_fence",
            track_id=14,
            direction="in",
        )
        self.assertEqual(te.event_type, "tripwire_cross")
        self.assertEqual(te.direction, "in")

    def test_alert_and_threshold_events(self):
        """Test IntrusionAlert, OccupancyThresholdEvent, and RestrictedEntityAlert."""
        ia = IntrusionAlert(
            zone_id="vault",
            track_id=99,
            severity="critical",
            message="Unauthorized presence",
        )
        self.assertEqual(ia.event_type, "intrusion_alert")
        self.assertEqual(ia.severity, "critical")

        oe = OccupancyThresholdEvent(
            zone_id="lobby",
            current_occupancy=25,
            threshold=20,
            breach_type="exceeded",
        )
        self.assertEqual(oe.event_type, "occupancy_threshold")
        self.assertEqual(oe.breach_type, "exceeded")

        re = RestrictedEntityAlert(
            track_id=7,
            name="Suspect #4",
            category="banned",
            message="Blacklisted individual detected",
        )
        self.assertEqual(re.event_type, "restricted_entity_alert")
        self.assertEqual(re.severity, "critical")

    def test_entity_identified_event(self):
        """Test EntityIdentifiedEvent payload fields and confidence metrics."""
        ee = EntityIdentifiedEvent(
            track_id=5,
            entity_id=101,
            name="Bob",
            category="VIP",
            similarity=0.88,
        )
        self.assertEqual(ee.event_type, "entity_identified")
        self.assertEqual(ee.name, "Bob")

    def test_snapshot_encoding_decoding(self):
        """Test frame and bounding-box crop base64 encoding and decoding."""
        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        frame[:, :, 0] = 200
        frame[:, :, 2] = 100

        b64 = frame_to_base64(frame, quality=75)
        self.assertIsNotNone(b64)
        self.assertTrue(isinstance(b64, str))

        decoded = decode_snapshot_base64(b64)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded.shape, (64, 64, 3))

        crop_b64 = crop_to_base64(frame, bbox=(10, 10, 20, 20), padding=4)
        self.assertIsNotNone(crop_b64)
        decoded_crop = decode_snapshot_base64(crop_b64)
        self.assertIsNotNone(decoded_crop)
        self.assertEqual(decoded_crop.shape[0], 28)
        self.assertEqual(decoded_crop.shape[1], 28)


class TestEventBus(unittest.TestCase):
    """Test publish-subscribe EventBus and worker thread dispatching."""

    def test_sync_publishing_and_filters(self):
        """Test synchronous event dispatching with type and predicate filters."""
        bus = EventBus()
        received_all = []
        received_intrusions = []
        received_filtered = []

        bus.subscribe(lambda ev: received_all.append(ev))
        bus.subscribe(lambda ev: received_intrusions.append(ev), event_type=IntrusionAlert)
        bus.subscribe(
            lambda ev: received_filtered.append(ev),
            filter_fn=lambda ev: getattr(ev, "zone_id", None) == "restricted_zone",
        )

        ev1 = ZoneEvent(zone_id="lobby", track_id=1, action="enter")
        ev2 = IntrusionAlert(zone_id="restricted_zone", track_id=2)
        ev3 = ZoneEvent(zone_id="restricted_zone", track_id=3, action="dwell")

        bus.publish(ev1, sync=True)
        bus.publish(ev2, sync=True)
        bus.publish(ev3, sync=True)

        self.assertEqual(len(received_all), 3)
        self.assertEqual(len(received_intrusions), 1)
        self.assertEqual(received_intrusions[0].track_id, 2)
        self.assertEqual(len(received_filtered), 2)

        recent = bus.get_recent_events(limit=10)
        self.assertEqual(len(recent), 3)
        recent_intrusions = bus.get_recent_events(limit=10, event_type="intrusion_alert")
        self.assertEqual(len(recent_intrusions), 1)

    def test_async_worker_dispatch_and_drain(self):
        """Test asynchronous queueing, multi-worker parallel dispatch, and drain barrier."""
        bus = EventBus()
        received = []
        bus.subscribe(lambda ev: received.append(ev))

        bus.start(num_workers=2)
        for i in range(15):
            bus.publish(ZoneEvent(zone_id="zone_{}".format(i), track_id=i, action="enter"), sync=False)

        drained = bus.wait_until_empty(timeout=3.0)
        self.assertTrue(drained)
        self.assertEqual(len(received), 15)
        bus.stop(timeout=1.0)

    def test_error_isolation_in_subscriber(self):
        """Test exception containment in failing subscriber without crashing pipeline."""
        bus = EventBus()
        received = []

        def failing_handler(ev):
            raise ValueError("Deliberate test explosion")

        def healthy_handler(ev):
            received.append(ev)

        bus.subscribe(failing_handler)
        bus.subscribe(healthy_handler)

        bus.publish(BaseEvent(event_type="safe_test"), sync=True)
        self.assertEqual(len(received), 1)


if __name__ == "__main__":
    unittest.main()

