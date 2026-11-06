#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for external notification dispatchers: Webhook, Telegram, and MQTT.

Tests:
1. WebhookDispatcher HTTP POST delivery, bearer auth, HMAC signatures, and retry backoff.
2. TelegramDispatcher formatting, cooldown suppression, and bot command handlers.
3. MqttPublisher occupancy payloads, event streams, sightings, and LWT state.
"""

import json
import hmac
import hashlib
import os
import threading
import time
import unittest

from intelligent_tracker.events import (
    IntrusionAlert,
    ZoneEvent,
    RestrictedEntityAlert,
    WebhookDispatcher,
    TelegramDispatcher,
    MqttPublisher,
    EventBus,
)
from intelligent_tracker.geometry import ZoneROI, Tripwire
from intelligent_tracker.analytics import AnalyticsEngine
from tests.events_helpers import WebhookTestServer


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
        """Test standard HTTP POST with bearer authorization and custom headers."""
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

        self.assertEqual(len(self.server.httpd.received_requests), 1)
        req = self.server.httpd.received_requests[0]
        self.assertEqual(req["headers"]["authorization"], "Bearer secret-token-123")
        self.assertEqual(req["headers"]["x-test-source"], "unit_test")
        self.assertEqual(req["body"]["camera_id"], "cam_front")
        self.assertEqual(req["body"]["zone_id"], "perimeter")
        self.assertEqual(req["body"]["event_type"], "intrusion_alert")
        self.assertEqual(req["body"]["snapshot"], "BASE64_MOCK_IMAGE_DATA")

    def test_webhook_retry_and_backoff(self):
        """Test exponential retry backoff on upstream 500 error."""
        dispatcher = WebhookDispatcher(
            url=self.server.url,
            max_retries=3,
            backoff_factor=0.05,
        )
        self.server.httpd.fail_next_n = 2
        ev = ZoneEvent(zone_id="dock", track_id=9, action="enter")
        success = dispatcher.send(ev)

        self.assertTrue(success)
        self.assertEqual(dispatcher.sent_count, 1)
        self.assertEqual(dispatcher.retry_count, 2)
        self.assertEqual(len(self.server.httpd.received_requests), 1)

    def test_webhook_event_type_filter(self):
        """Test client-side event filtering before network dispatch."""
        dispatcher = WebhookDispatcher(
            url=self.server.url,
            event_types=["intrusion_alert", "restricted_entity_alert"],
        )
        ev_skip = ZoneEvent(zone_id="lobby", track_id=1, action="enter")
        self.assertFalse(dispatcher.send(ev_skip))
        self.assertEqual(len(self.server.httpd.received_requests), 0)

        ev_send = IntrusionAlert(zone_id="lobby", track_id=2)
        self.assertTrue(dispatcher.send(ev_send))
        self.assertEqual(len(self.server.httpd.received_requests), 1)

    def test_webhook_hmac_signature(self):
        """Test SHA-256 HMAC payload signature calculation."""
        secret = "enterprise_shared_secret_987"
        dispatcher = WebhookDispatcher(url=self.server.url, secret_key=secret)
        ev = IntrusionAlert(zone_id="vault", track_id=7, message="Breach detected")

        self.assertTrue(dispatcher.send(ev))
        self.assertEqual(len(self.server.httpd.received_requests), 1)
        req = self.server.httpd.received_requests[0]
        self.assertIn("x-tracker-signature", req["headers"])

        expected_sig = hmac.new(secret.encode("utf-8"), req["raw_body"], hashlib.sha256).hexdigest()
        self.assertEqual(req["headers"]["x-tracker-signature"], expected_sig)
        self.assertIn("timestamp", req["body"])
        self.assertIn("timestamp_epoch", req["body"])

    def test_webhook_cancellation_with_stop_event(self):
        """Test pre-flight and mid-backoff cancellation via stop_event / close()."""
        dispatcher = WebhookDispatcher(
            url=self.server.url,
            max_retries=5,
            backoff_factor=2.0,
        )
        self.server.httpd.fail_next_n = 5
        ev = ZoneEvent(zone_id="dock", track_id=99, action="enter")

        timer = threading.Timer(0.04, dispatcher.close)
        timer.start()
        t0 = time.time()
        success = dispatcher.send(ev)
        elapsed = time.time() - t0
        timer.cancel()

        self.assertFalse(success)
        self.assertEqual(dispatcher.retry_count, 1)
        self.assertLess(elapsed, 0.5, f"Expected mid-backoff abort in <500ms, took {elapsed:.3f}s")


class TestTelegramDispatcher(unittest.TestCase):
    """Test Telegram notification formatting, cooldown rate limiting, and commands."""

    def test_cooldown_rate_limiting(self):
        """Test cooldown suppression of repeated alert messages."""
        tg = TelegramDispatcher(token="mock", chat_id="12345678", cooldown=60.0, mock=True)
        ev1 = IntrusionAlert(zone_id="restricted_zone", track_id=1, entity_name="Unknown")
        ev2 = IntrusionAlert(zone_id="restricted_zone", track_id=1, entity_name="Unknown")

        t0 = 1000.0
        self.assertFalse(tg.is_cooling_down(ev1, now=t0))
        self.assertTrue(tg.send(ev1))
        self.assertEqual(len(tg.sent_messages), 1)

        self.assertFalse(tg.send(ev2))
        self.assertEqual(len(tg.sent_messages), 1)

        tg._last_alert_time[tg._get_cooldown_key(ev2)] = t0 - 70.0
        self.assertTrue(tg.send(ev2))
        self.assertEqual(len(tg.sent_messages), 2)

    def test_message_formatting(self):
        """Test Markdown-escaped security alert formatting."""
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
        for expected in ("SECURITY ALERT", "cam_02", "server_room", "Eve", "banned"):
            self.assertIn(expected, msg)

    def test_bot_status_commands(self):
        """Test /status, /occupancy, and /help interactive bot command processing."""
        tg = TelegramDispatcher(token="mock", chat_id="12345", mock=True)
        analytics = AnalyticsEngine(resolution=(320, 240), heatmap_enabled=False)
        analytics.add_zone(ZoneROI(polygon=[(0, 0), (100, 0), (100, 100), (0, 100)], name="vault"))
        analytics.add_tripwire(Tripwire(line_segment=((0, 50), (100, 50)), name="door"))

        bus = EventBus()
        bus.publish(IntrusionAlert(zone_id="vault", track_id=1), sync=True)

        resp_status = tg.handle_command("/status", analytics_engine=analytics, event_bus=bus)
        for token in ("INTELLIGENT TRACKER STATUS", "vault", "door", "intrusion_alert"):
            self.assertIn(token, resp_status)

        resp_occ = tg.handle_command("/occupancy", analytics_engine=analytics)
        self.assertIn("vault", resp_occ)

        resp_help = tg.handle_command("/help")
        self.assertIn("Intelligent Tracker Bot Commands", resp_help)


class TestMqttPublisher(unittest.TestCase):
    """Test MQTT publisher topics, telemetry payloads, and Home Assistant compatibility."""

    def _verify_mqtt_messages(self, msgs):
        """Validate topic structure and JSON content of emitted MQTT messages."""
        self.assertEqual(len(msgs), 3)
        self.assertEqual(msgs[0]["topic"], "tracker_test/cam_01/occupancy")
        self.assertTrue(msgs[0]["retain"])
        payload_occ = json.loads(msgs[0]["payload"])
        self.assertEqual(payload_occ["total_tracks"], 3)
        self.assertEqual(payload_occ["zones"]["entry"], 2)

        self.assertEqual(msgs[1]["topic"], "tracker_test/cam_01/events")
        self.assertFalse(msgs[1]["retain"])

        self.assertEqual(msgs[2]["topic"], "tracker_test/cam_01/sightings/42")
        self.assertTrue(msgs[2]["retain"])
        payload_sight = json.loads(msgs[2]["payload"])
        self.assertEqual(payload_sight["name"], "Alice")
        self.assertEqual(payload_sight["category"], "VIP")

    def test_mqtt_publishing_mock(self):
        """Test MQTT topic tree generation and message publication."""
        mqtt_pub = MqttPublisher(
            broker="localhost",
            port=1883,
            base_topic="tracker_test",
            qos=1,
            mock=True,
        )
        self.assertTrue(mqtt_pub.connect())
        self.assertTrue(mqtt_pub.is_connected)

        self.assertTrue(mqtt_pub.publish_occupancy(
            camera_id="cam_01",
            zone_occupancy={"entry": 2, "exit": 1},
            total_tracks=3,
        ))
        ev = IntrusionAlert(camera_id="cam_01", zone_id="entry", track_id=5)
        self.assertTrue(mqtt_pub.publish_event(ev))
        self.assertTrue(mqtt_pub.publish_sighting(
            camera_id="cam_01",
            entity_id=42,
            name="Alice",
            category="VIP",
            zone_id="vip_lounge",
        ))

        self._verify_mqtt_messages(mqtt_pub.published_messages)
        mqtt_pub.disconnect()
        self.assertFalse(mqtt_pub.is_connected)

    def test_mqtt_broker_env_variable(self):
        """Test that MqttPublisher resolves broker from MQTT_BROKER env variable."""
        original = os.environ.get("MQTT_BROKER")
        try:
            os.environ["MQTT_BROKER"] = "192.168.1.100"
            pub = MqttPublisher(mock=True)
            self.assertEqual(pub.broker, "192.168.1.100")

            pub_explicit = MqttPublisher(broker="custom.broker.local", mock=True)
            self.assertEqual(pub_explicit.broker, "custom.broker.local")

            from intelligent_tracker.events.pipeline import setup_event_pipeline
            disps = setup_event_pipeline({"alerting": {"mqtt": {"enabled": True, "mock": True}}})
            self.assertEqual(disps["mqtt"].broker, "192.168.1.100")
        finally:
            if original is not None:
                os.environ["MQTT_BROKER"] = original
            else:
                os.environ.pop("MQTT_BROKER", None)


if __name__ == "__main__":
    unittest.main()

