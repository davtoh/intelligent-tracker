#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for Milestone 5: Event Dispatching & Alerting System.

Tests:
1. Event Dataclasses & Snapshot Encoding/Decoding.
2. Centralized EventBus (Pub/Sub, async workers, filters, history, error containment).
3. WebhookDispatcher with a live local HTTP echo test server (headers, auth, retry/backoff, snapshots).
4. TelegramDispatcher (formatting, rate-limiting cooldown, snapshots, /status command responder).
5. MqttPublisher (topics, occupancy, sightings, event streams, LWT).
6. QuietHours & AlertRuleEngine (overnight spans, category triggers, intrusion & restricted alerts).
7. End-to-end Pipeline & AnalyticsEngine integration.
"""

from __future__ import division, print_function, absolute_import

import os
import sys
import time
import json
import socket
import unittest
import threading
from datetime import datetime, time as dtime
from http.server import HTTPServer, BaseHTTPRequestHandler

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
    WebhookDispatcher,
    TelegramDispatcher,
    MqttPublisher,
    QuietHours,
    AlertRule,
    AlertRuleEngine,
    frame_to_base64,
    crop_to_base64,
    decode_snapshot_base64,
    setup_event_pipeline,
)
from intelligent_tracker.geometry import ZoneROI, Tripwire
from intelligent_tracker.tracker import Track
from intelligent_tracker.analytics import AnalyticsEngine


# ==============================================================================
# Helper HTTP Echo Server for Webhook Testing
# ==============================================================================

class WebhookTestServerHandler(BaseHTTPRequestHandler):
    """Local HTTP request handler recording POST requests."""

    def log_message(self, format, *args):
        # Silence console log noise during automated test run
        pass

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        # Allow tests to configure simulated error responses
        if getattr(self.server, "fail_next_n", 0) > 0:
            self.server.fail_next_n -= 1
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'{"error": "Internal Server Error"}')
            return

        self.server.received_requests.append({
            "path": self.path,
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "body": json.loads(body.decode("utf-8")),
        })

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "success"}')


class WebhookTestServer(object):
    """Local HTTP Server running on an OS-assigned ephemeral port."""

    def __init__(self):
        self.httpd = HTTPServer(("127.0.0.1", 0), WebhookTestServerHandler)
        self.httpd.received_requests = []
        self.httpd.fail_next_n = 0
        self.port = self.httpd.server_port
        self.url = "http://127.0.0.1:{}/webhook".format(self.port)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2.0)


# ==============================================================================
# Test Cases
# ==============================================================================

class TestEventDataClasses(unittest.TestCase):
    """Test typed event dataclasses and snapshot serialization."""

    def test_base_event_creation_and_json(self):
        ev = BaseEvent(
            event_type="test_event",
            camera_id="cam_east",
            metadata={"source": "unit_test"},
        )
        self.assertEqual(ev.camera_id, "cam_east")
        self.assertEqual(ev.event_type, "test_event")
        self.assertTrue(len(ev.event_id) > 10)

        # JSON serialization
        json_str = ev.to_json()
        parsed = json.loads(json_str)
        self.assertEqual(parsed["event_type"], "test_event")
        self.assertEqual(parsed["camera_id"], "cam_east")

    def test_typed_events(self):
        # 1. ZoneEvent
        ze = ZoneEvent(
            zone_id="storage_room",
            track_id=14,
            action="enter",
            entity_name="Alice",
            entity_category="staff",
        )
        self.assertEqual(ze.event_type, "zone_enter")
        self.assertEqual(ze.zone_id, "storage_room")

        # 2. TripwireCrossEvent
        te = TripwireCrossEvent(
            tripwire_id="perimeter_fence",
            track_id=14,
            direction="in",
        )
        self.assertEqual(te.event_type, "tripwire_cross")
        self.assertEqual(te.direction, "in")

        # 3. IntrusionAlert
        ia = IntrusionAlert(
            zone_id="vault",
            track_id=99,
            severity="critical",
            message="Unauthorized presence",
        )
        self.assertEqual(ia.event_type, "intrusion_alert")
        self.assertEqual(ia.severity, "critical")

        # 4. OccupancyThresholdEvent
        oe = OccupancyThresholdEvent(
            zone_id="lobby",
            current_occupancy=25,
            threshold=20,
            breach_type="exceeded",
        )
        self.assertEqual(oe.event_type, "occupancy_threshold")
        self.assertEqual(oe.breach_type, "exceeded")

        # 5. EntityIdentifiedEvent
        ee = EntityIdentifiedEvent(
            track_id=5,
            entity_id=101,
            name="Bob",
            category="VIP",
            similarity=0.88,
        )
        self.assertEqual(ee.event_type, "entity_identified")
        self.assertEqual(ee.name, "Bob")

        # 6. RestrictedEntityAlert
        re = RestrictedEntityAlert(
            track_id=7,
            name="Suspect #4",
            category="banned",
            message="Blacklisted individual detected",
        )
        self.assertEqual(re.event_type, "restricted_entity_alert")
        self.assertEqual(re.severity, "critical")

    def test_snapshot_encoding_decoding(self):
        # Synthetic test frame (64x64 color gradient)
        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        frame[:, :, 0] = 200  # Blue
        frame[:, :, 2] = 100  # Red

        b64 = frame_to_base64(frame, quality=75)
        self.assertIsNotNone(b64)
        self.assertTrue(isinstance(b64, str))

        # Decode back to frame
        decoded = decode_snapshot_base64(b64)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded.shape, (64, 64, 3))

        # Crop to base64
        crop_b64 = crop_to_base64(frame, bbox=(10, 10, 20, 20), padding=4)
        self.assertIsNotNone(crop_b64)
        decoded_crop = decode_snapshot_base64(crop_b64)
        self.assertIsNotNone(decoded_crop)
        # 20 + 2*4 = 28
        self.assertEqual(decoded_crop.shape[0], 28)
        self.assertEqual(decoded_crop.shape[1], 28)


class TestEventBus(unittest.TestCase):
    """Test publish-subscribe EventBus and worker thread dispatching."""

    def test_sync_publishing_and_filters(self):
        bus = EventBus()
        received_all = []
        received_intrusions = []
        received_filtered = []

        # Universal subscriber
        bus.subscribe(lambda ev: received_all.append(ev))

        # Type-filtered subscriber
        bus.subscribe(lambda ev: received_intrusions.append(ev), event_type=IntrusionAlert)

        # Predicate-filtered subscriber
        bus.subscribe(
            lambda ev: received_filtered.append(ev),
            filter_fn=lambda ev: getattr(ev, "zone_id", None) == "restricted_zone",
        )

        ev1 = ZoneEvent(zone_id="lobby", track_id=1, action="enter")
        ev2 = IntrusionAlert(zone_id="restricted_zone", track_id=2)
        ev3 = ZoneEvent(zone_id="restricted_zone", track_id=3, action="dwell")

        # Publish synchronously
        bus.publish(ev1, sync=True)
        bus.publish(ev2, sync=True)
        bus.publish(ev3, sync=True)

        self.assertEqual(len(received_all), 3)
        self.assertEqual(len(received_intrusions), 1)
        self.assertEqual(received_intrusions[0].track_id, 2)
        self.assertEqual(len(received_filtered), 2)  # ev2 and ev3

        # Test history buffer
        recent = bus.get_recent_events(limit=10)
        self.assertEqual(len(recent), 3)
        recent_intrusions = bus.get_recent_events(limit=10, event_type="intrusion_alert")
        self.assertEqual(len(recent_intrusions), 1)

    def test_async_worker_dispatch_and_drain(self):
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
        bus = EventBus()
        received = []

        def failing_handler(ev):
            raise ValueError("Deliberate test explosion")

        def healthy_handler(ev):
            received.append(ev)

        bus.subscribe(failing_handler)
        bus.subscribe(healthy_handler)

        # Should not raise exception
        bus.publish(BaseEvent(event_type="safe_test"), sync=True)
        self.assertEqual(len(received), 1)


class TestWebhookDispatcher(unittest.TestCase):
    """Test HTTP POST Webhook delivery against a real local echo server."""

    @classmethod
    def setUpClass(cls):
        cls.server = WebhookTestServer()
        cls.server.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def setUp(self):
        self.server.httpd.received_requests = []
        self.server.httpd.fail_next_n = 0

    def test_successful_webhook_post(self):
        dispatcher = WebhookDispatcher(
            url=self.server.url,
            auth_header="secret-token-123",
            include_snapshot=True,
            custom_headers={"X-Test-Source": "unit_test"},
        )

        ev = IntrusionAlert(
            camera_id="cam_front",
            zone_id="perimeter",
            track_id=42,
            severity="critical",
            message="Motion detected after hours",
            snapshot_base64="BASE64_MOCK_IMAGE_DATA",
        )

        success = dispatcher.send(ev)
        self.assertTrue(success)
        self.assertEqual(dispatcher.sent_count, 1)
        self.assertEqual(dispatcher.failed_count, 0)

        # Inspect request received by local echo server
        self.assertEqual(len(self.server.httpd.received_requests), 1)
        req = self.server.httpd.received_requests[0]
        self.assertEqual(req["headers"]["authorization"], "Bearer secret-token-123")
        self.assertEqual(req["headers"]["x-test-source"], "unit_test")
        self.assertEqual(req["body"]["camera_id"], "cam_front")
        self.assertEqual(req["body"]["zone_id"], "perimeter")
        self.assertEqual(req["body"]["event_type"], "intrusion_alert")
        self.assertEqual(req["body"]["snapshot"], "BASE64_MOCK_IMAGE_DATA")

    def test_webhook_retry_and_backoff(self):
        dispatcher = WebhookDispatcher(
            url=self.server.url,
            max_retries=3,
            backoff_factor=0.05,  # fast backoff for tests
        )

        # Tell server to fail first 2 attempts with HTTP 500, then succeed on 3rd
        self.server.httpd.fail_next_n = 2

        ev = ZoneEvent(zone_id="dock", track_id=9, action="enter")
        success = dispatcher.send(ev)

        self.assertTrue(success)
        self.assertEqual(dispatcher.sent_count, 1)
        self.assertEqual(dispatcher.retry_count, 2)
        self.assertEqual(len(self.server.httpd.received_requests), 1)

    def test_webhook_event_type_filter(self):
        dispatcher = WebhookDispatcher(
            url=self.server.url,
            event_types=["intrusion_alert", "restricted_entity_alert"],
        )

        # Standard zone event should be skipped
        ev_skip = ZoneEvent(zone_id="lobby", track_id=1, action="enter")
        sent1 = dispatcher.send(ev_skip)
        self.assertFalse(sent1)
        self.assertEqual(len(self.server.httpd.received_requests), 0)

        # Intrusion alert should be delivered
        ev_send = IntrusionAlert(zone_id="lobby", track_id=2)
        sent2 = dispatcher.send(ev_send)
        self.assertTrue(sent2)
        self.assertEqual(len(self.server.httpd.received_requests), 1)


class TestTelegramDispatcher(unittest.TestCase):
    """Test Telegram notification formatting, cooldown rate limiting, and commands."""

    def test_cooldown_rate_limiting(self):
        tg = TelegramDispatcher(
            token="mock",
            chat_id="12345678",
            cooldown=60.0,
            mock=True,
        )

        ev1 = IntrusionAlert(zone_id="restricted_zone", track_id=1, entity_name="Unknown")
        ev2 = IntrusionAlert(zone_id="restricted_zone", track_id=1, entity_name="Unknown")

        # First alert sent
        t0 = 1000.0
        self.assertFalse(tg.is_cooling_down(ev1, now=t0))
        sent1 = tg.send(ev1)
        self.assertTrue(sent1)
        self.assertEqual(len(tg.sent_messages), 1)

        # Immediate second alert suppressed by cooldown
        sent2 = tg.send(ev2)
        self.assertFalse(sent2)
        self.assertEqual(len(tg.sent_messages), 1)

        # Alert after cooldown passes (t0 + 65s) succeeds
        sent3 = tg.send(ev2)
        # Simulate time jump
        tg._last_alert_time[tg._get_cooldown_key(ev2)] = t0 - 70.0
        sent3 = tg.send(ev2)
        self.assertTrue(sent3)
        self.assertEqual(len(tg.sent_messages), 2)

    def test_message_formatting(self):
        tg = TelegramDispatcher(token="mock", chat_id="12345", mock=True)

        ev = RestrictedEntityAlert(
            camera_id="cam_02",
            zone_id="server_room",
            track_id=88,
            name="Eve",
            category="banned",
            message="Unauthorized access attempt",
        )
        msg = tg.format_message(ev)
        self.assertIn("SECURITY ALERT", msg)
        self.assertIn("cam_02", msg)
        self.assertIn("server_room", msg)
        self.assertIn("Eve", msg)
        self.assertIn("banned", msg)

    def test_bot_status_commands(self):
        tg = TelegramDispatcher(token="mock", chat_id="12345", mock=True)

        analytics = AnalyticsEngine(resolution=(320, 240), heatmap_enabled=False)
        zone = ZoneROI(polygon=[(0, 0), (100, 0), (100, 100), (0, 100)], name="vault")
        analytics.add_zone(zone)
        tw = Tripwire(line_segment=((0, 50), (100, 50)), name="door")
        analytics.add_tripwire(tw)

        bus = EventBus()
        bus.publish(IntrusionAlert(zone_id="vault", track_id=1), sync=True)

        # 1. /status command
        resp_status = tg.handle_command("/status", analytics_engine=analytics, event_bus=bus)
        self.assertIn("INTELLIGENT TRACKER STATUS", resp_status)
        self.assertIn("vault", resp_status)
        self.assertIn("door", resp_status)
        self.assertIn("intrusion_alert", resp_status)

        # 2. /occupancy command
        resp_occ = tg.handle_command("/occupancy", analytics_engine=analytics)
        self.assertIn("vault", resp_occ)

        # 3. /help command
        resp_help = tg.handle_command("/help")
        self.assertIn("Intelligent Tracker Bot Commands", resp_help)


class TestMqttPublisher(unittest.TestCase):
    """Test MQTT publisher topics, telemetry payloads, and Home Assistant compatibility."""

    def test_mqtt_publishing_mock(self):
        mqtt_pub = MqttPublisher(
            broker="localhost",
            port=1883,
            base_topic="tracker_test",
            qos=1,
            mock=True,
        )
        connected = mqtt_pub.connect()
        self.assertTrue(connected)
        self.assertTrue(mqtt_pub.is_connected)

        # 1. Publish occupancy
        ok1 = mqtt_pub.publish_occupancy(
            camera_id="cam_01",
            zone_occupancy={"entry": 2, "exit": 1},
            total_tracks=3,
        )
        self.assertTrue(ok1)

        # 2. Publish event stream
        ev = IntrusionAlert(camera_id="cam_01", zone_id="entry", track_id=5)
        ok2 = mqtt_pub.publish_event(ev)
        self.assertTrue(ok2)

        # 3. Publish sighting
        ok3 = mqtt_pub.publish_sighting(
            camera_id="cam_01",
            entity_id=42,
            name="Alice",
            category="VIP",
            zone_id="vip_lounge",
        )
        self.assertTrue(ok3)

        # Verify messages in published queue
        msgs = mqtt_pub.published_messages
        self.assertEqual(len(msgs), 3)

        # Check occupancy topic & payload
        self.assertEqual(msgs[0]["topic"], "tracker_test/cam_01/occupancy")
        self.assertTrue(msgs[0]["retain"])
        payload_occ = json.loads(msgs[0]["payload"])
        self.assertEqual(payload_occ["total_tracks"], 3)
        self.assertEqual(payload_occ["zones"]["entry"], 2)

        # Check event topic
        self.assertEqual(msgs[1]["topic"], "tracker_test/cam_01/events")
        self.assertFalse(msgs[1]["retain"])

        # Check sighting topic
        self.assertEqual(msgs[2]["topic"], "tracker_test/cam_01/sightings/42")
        self.assertTrue(msgs[2]["retain"])
        payload_sight = json.loads(msgs[2]["payload"])
        self.assertEqual(payload_sight["name"], "Alice")
        self.assertEqual(payload_sight["category"], "VIP")

        # Test disconnect
        mqtt_pub.disconnect()
        self.assertFalse(mqtt_pub.is_connected)


class TestQuietHoursAndRuleEngine(unittest.TestCase):
    """Test time-of-day quiet hours schedules and alert rule matching."""

    def test_quiet_hours_overnight_span(self):
        # 22:00 to 06:00 (spans midnight)
        qh = QuietHours(start_time="22:00", end_time="06:00")

        # 23:30 (Quiet)
        dt_night = datetime(2026, 10, 24, 23, 30, 0)
        self.assertTrue(qh.is_quiet_hour(dt_night))

        # 02:15 (Quiet)
        dt_early = datetime(2026, 10, 25, 2, 15, 0)
        self.assertTrue(qh.is_quiet_hour(dt_early))

        # 06:00 (Boundary - quiet)
        dt_boundary = datetime(2026, 10, 25, 6, 0, 0)
        self.assertTrue(qh.is_quiet_hour(dt_boundary))

        # 12:00 noon (Not quiet)
        dt_noon = datetime(2026, 10, 25, 12, 0, 0)
        self.assertFalse(qh.is_quiet_hour(dt_noon))

    def test_quiet_hours_daytime_span(self):
        # 13:00 to 15:00 (afternoon siesta / lockup)
        qh = QuietHours(start_time="13:00", end_time="15:00")
        self.assertTrue(qh.is_quiet_hour(datetime(2026, 10, 24, 14, 0, 0)))
        self.assertFalse(qh.is_quiet_hour(datetime(2026, 10, 24, 10, 0, 0)))

    def test_alert_rule_matching(self):
        rule = AlertRule(
            name="restricted_area_intrusion",
            zone_id="vault",
            event_types=["zone_enter", "enter"],
            categories=["restricted", "unknown"],
            quiet_hours_only=True,
            quiet_hours=QuietHours("22:00", "06:00"),
            cooldown=30.0,
        )

        dt_night = datetime(2026, 10, 24, 23, 0, 0)
        dt_day = datetime(2026, 10, 24, 14, 0, 0)

        # Match during quiet hours with unknown entity in vault
        ev1 = ZoneEvent(zone_id="vault", track_id=1, action="enter", entity_category="unknown")
        self.assertTrue(rule.matches(ev1, dt=dt_night))

        # Do not match outside quiet hours
        self.assertFalse(rule.matches(ev1, dt=dt_day))

        # Do not match authorized staff even during quiet hours
        ev_staff = ZoneEvent(zone_id="vault", track_id=2, action="enter", entity_category="staff")
        self.assertFalse(rule.matches(ev_staff, dt=dt_night))

    def test_alert_rule_engine_execution(self):
        bus = EventBus()
        engine = AlertRuleEngine(event_bus=bus)

        # Add rule for restricted entity detection
        engine.add_rule(AlertRule(
            name="restricted_entity_spotted",
            categories=["banned", "restricted"],
            severity="critical",
            message="Restricted entity detected in facility",
        ))

        # Trigger event with restricted entity
        ev = EntityIdentifiedEvent(
            camera_id="cam_gate",
            track_id=10,
            entity_id=99,
            name="Suspect X",
            category="banned",
            similarity=0.92,
        )

        test_frame = np.zeros((40, 40, 3), dtype=np.uint8)
        alerts = engine.evaluate(ev, frame=test_frame)

        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertTrue(isinstance(alert, RestrictedEntityAlert))
        self.assertEqual(alert.name, "Suspect X")
        self.assertIsNotNone(alert.snapshot_base64)


class TestFullPipelineIntegration(unittest.TestCase):
    """Test full configuration parsing, AnalyticsEngine integration, and multi-dispatcher broadcasting."""

    @classmethod
    def setUpClass(cls):
        cls.server = WebhookTestServer()
        cls.server.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def test_pipeline_setup_and_analytics_integration(self):
        config = {
            "alerting": {
                "webhooks": [
                    {
                        "url": self.server.url,
                        "auth_token": "pipeline_token",
                    }
                ],
                "telegram": {
                    "enabled": True,
                    "token": "mock",
                    "chat_id": "111222",
                    "mock": True,
                },
                "mqtt": {
                    "enabled": True,
                    "broker": "localhost",
                    "base_topic": "pipeline_tracker",
                    "mock": True,
                },
                "rules": [
                    {
                        "name": "zone_capacity_limit",
                        "zone_id": "checkout",
                        "event_types": ["occupancy_threshold"],
                        "severity": "warning",
                    }
                ],
            }
        }

        pipeline = setup_event_pipeline(config)
        bus = pipeline["event_bus"]
        tg = pipeline["telegram"]
        mqtt_pub = pipeline["mqtt"]
        self.assertIsNotNone(bus)
        self.assertIsNotNone(tg)
        self.assertIsNotNone(mqtt_pub)

        # Initialize AnalyticsEngine wired with this EventBus
        analytics = AnalyticsEngine(
            resolution=(320, 240),
            heatmap_enabled=False,
            event_bus=bus,
            camera_id="cam_main",
        )

        # Create zone with capacity limit = 1
        zone = ZoneROI(
            polygon=[(0, 0), (100, 0), (100, 100), (0, 100)],
            name="checkout",
            capacity_limit=1,
        )
        analytics.add_zone(zone)

        # Create 2 tracks inside the zone (breaching capacity limit of 1)
        t1 = Track(track_id=1, bbox=(40, 40, 20, 20), label="person")
        t2 = Track(track_id=2, bbox=(50, 50, 20, 20), label="person")

        # Update analytics with tracks
        telemetry = analytics.update({1: t1, 2: t2}, timestamp=time.time())
        self.assertEqual(telemetry["zone_occupancy"]["checkout"], 2)

        # Drain bus to ensure async workers finish
        bus.wait_until_empty(timeout=2.0)

        # Verify Telegram received alert message
        self.assertTrue(len(tg.sent_messages) >= 1)

        # Verify MQTT received event
        self.assertTrue(len(mqtt_pub.published_messages) >= 1)

        bus.stop(timeout=1.0)


if __name__ == "__main__":
    unittest.main()
