#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit tests for time-based QuietHours, AlertRuleEngine, and end-to-end event pipeline.

Tests:
1. QuietHours schedule matching across daytime and midnight-spanning ranges.
2. AlertRule evaluation with criteria, categories, cooldown, and quiet hour gates.
3. Full pipeline wiring with AnalyticsEngine, ZoneROI capacity breaches, and dispatchers.
"""

import time
import unittest
from datetime import datetime
import numpy as np

from intelligent_tracker.events import (
    ZoneEvent,
    EntityIdentifiedEvent,
    RestrictedEntityAlert,
    EventBus,
    QuietHours,
    AlertRule,
    AlertRuleEngine,
    setup_event_pipeline,
)
from intelligent_tracker.geometry import ZoneROI
from intelligent_tracker.tracker import Track
from intelligent_tracker.analytics import AnalyticsEngine
from tests.events_helpers import WebhookTestServer


class TestQuietHoursAndRuleEngine(unittest.TestCase):
    """Test time-of-day quiet hours schedules and alert rule matching."""

    def test_quiet_hours_overnight_span(self):
        """Test overnight quiet hour evaluation across midnight boundary."""
        qh = QuietHours(start_time="22:00", end_time="06:00")
        self.assertTrue(qh.is_quiet_hour(datetime(2026, 10, 24, 23, 30, 0)))
        self.assertTrue(qh.is_quiet_hour(datetime(2026, 10, 25, 2, 15, 0)))
        self.assertTrue(qh.is_quiet_hour(datetime(2026, 10, 25, 6, 0, 0)))
        self.assertFalse(qh.is_quiet_hour(datetime(2026, 10, 25, 12, 0, 0)))

    def test_quiet_hours_daytime_span(self):
        """Test daytime quiet hour window matching."""
        qh = QuietHours(start_time="13:00", end_time="15:00")
        self.assertTrue(qh.is_quiet_hour(datetime(2026, 10, 24, 14, 0, 0)))
        self.assertFalse(qh.is_quiet_hour(datetime(2026, 10, 24, 10, 0, 0)))

    def test_alert_rule_matching(self):
        """Test rule predicate matching with quiet hours and category filtering."""
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

        ev1 = ZoneEvent(zone_id="vault", track_id=1, action="enter", entity_category="unknown")
        self.assertTrue(rule.matches(ev1, dt=dt_night))
        self.assertFalse(rule.matches(ev1, dt=dt_day))

        ev_staff = ZoneEvent(zone_id="vault", track_id=2, action="enter", entity_category="staff")
        self.assertFalse(rule.matches(ev_staff, dt=dt_night))

    def test_alert_rule_engine_execution(self):
        """Test AlertRuleEngine event processing and snapshot injection."""
        bus = EventBus()
        engine = AlertRuleEngine(event_bus=bus)
        engine.add_rule(AlertRule(
            name="restricted_entity_spotted",
            categories=["banned", "restricted"],
            severity="critical",
            message="Restricted entity detected in facility",
        ))

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

    def _build_pipeline_config(self):
        """Generate comprehensive test pipeline configuration dictionary."""
        return {
            "alerting": {
                "webhooks": [{"url": self.server.url, "auth_token": "pipeline_token"}],
                "telegram": {"enabled": True, "token": "mock", "chat_id": "111222", "mock": True},
                "mqtt": {"enabled": True, "broker": "localhost", "base_topic": "pipeline_tracker", "mock": True},
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

    def _simulate_zone_breach(self, bus):
        """Run AnalyticsEngine with tracks breaching zone capacity."""
        analytics = AnalyticsEngine(
            resolution=(320, 240),
            heatmap_enabled=False,
            event_bus=bus,
            camera_id="cam_main",
        )
        zone = ZoneROI(
            polygon=[(0, 0), (100, 0), (100, 100), (0, 100)],
            name="checkout",
            capacity_limit=1,
        )
        analytics.add_zone(zone)
        t1 = Track(track_id=1, bbox=(40, 40, 20, 20), label="person")
        t2 = Track(track_id=2, bbox=(50, 50, 20, 20), label="person")

        telemetry = analytics.update({1: t1, 2: t2}, timestamp=time.time())
        self.assertEqual(telemetry["zone_occupancy"]["checkout"], 2)

    def test_pipeline_setup_and_analytics_integration(self):
        """Test complete pipeline initialization, zone breach detection, and dispatcher delivery."""
        config = self._build_pipeline_config()
        pipeline = setup_event_pipeline(config)
        bus, tg, mqtt_pub = pipeline["event_bus"], pipeline["telegram"], pipeline["mqtt"]

        self.assertIsNotNone(bus)
        self.assertIsNotNone(tg)
        self.assertIsNotNone(mqtt_pub)

        self._simulate_zone_breach(bus)
        bus.wait_until_empty(timeout=2.0)

        self.assertTrue(len(tg.sent_messages) >= 1)
        self.assertTrue(len(mqtt_pub.published_messages) >= 1)
        bus.stop(timeout=1.0)


if __name__ == "__main__":
    unittest.main()

