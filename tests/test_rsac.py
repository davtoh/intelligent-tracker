#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Intelligent Tracker - Unit Tests for RSAC & Pet Whitelist Module (Milestone 9).
"""

import os
import tempfile
import unittest
import numpy as np

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.rsac import (
    RSACManager,
    CustomCategory,
    RSACSchedule,
    RSACZoneRule,
    RSACDecision,
    DEFAULT_CUSTOM_CATEGORIES,
    DEFAULT_PET_WHITELIST,
)


class TestRSAC(unittest.TestCase):
    """Test suite for Role-Based Spatial Access Control and pet suppression logic."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_rsac.db")
        self.db = TrackerDB(self.db_path)
        self.rsac = RSACManager(db=self.db)

    def tearDown(self):
        self.db.close()
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_default_categories(self):
        """Verify seeded custom categories and colors."""
        cats = self.rsac.list_categories()
        cat_ids = {c["id"] for c in cats}
        expected = {"person", "family_car", "delivery_truck", "cleaning_crew", "guard_dog", "pet", "vip", "restricted"}
        self.assertTrue(expected.issubset(cat_ids))

        # Check color formatting
        person_cat = self.rsac.get_category("person")
        self.assertIsNotNone(person_cat)
        self.assertTrue(person_cat.color.startswith("#"))

    def test_schedule_evaluation(self):
        """Test time-of-day and day-of-week schedule active checks."""
        # 24/7 wildcard schedule
        all_day = RSACSchedule(days=["*"], start_time="00:00", end_time="23:59")
        self.assertTrue(all_day.is_active())

        # Business hours on weekdays
        biz_hours = RSACSchedule(days=["mon", "tue", "wed", "thu", "fri"], start_time="09:00", end_time="17:00")
        # Fixed Monday 10:00 AM UTC (2026-10-26 10:00:00 was a Monday)
        ts_mon_10am = 1793008800.0
        self.assertTrue(biz_hours.is_active(ts_mon_10am))

        # Fixed Monday 18:30 UTC
        ts_mon_6pm = 1793039400.0
        self.assertFalse(biz_hours.is_active(ts_mon_6pm))

    def test_rsac_zone_rule_allow_deny(self):
        """Test allowed/denied category filtering on zone rules."""
        # Zone where only 'cleaning_crew' and 'staff' are allowed
        rule = self.rsac.set_rule(
            camera_id="cam_01",
            zone_id="vault",
            allowed_categories=["cleaning_crew", "staff"],
            denied_categories=["restricted", "person"],
            alarm_on_breach=True,
        )

        dec_allowed = self.rsac.evaluate_access("cam_01", "vault", "cleaning_crew")
        self.assertTrue(dec_allowed.allowed)
        self.assertEqual(dec_allowed.severity, "info")

        dec_denied = self.rsac.evaluate_access("cam_01", "vault", "person")
        self.assertFalse(dec_denied.allowed)
        self.assertEqual(dec_denied.severity, "critical")

    def test_entity_override(self):
        """Test entity-level grant or denial overriding category rule."""
        # Customer person category is normally denied in server_room
        self.rsac.set_rule(
            camera_id="cam_01",
            zone_id="server_room",
            allowed_categories=["staff"],
            entity_overrides={"42": "allow", "99": "deny"},
        )

        # Entity 42 is explicitly granted access
        dec_override_allow = self.rsac.evaluate_access(
            "cam_01", "server_room", entity_category="person", entity_id=42
        )
        self.assertTrue(dec_override_allow.allowed)

        # Entity 99 is explicitly denied access even if staff
        dec_override_deny = self.rsac.evaluate_access(
            "cam_01", "server_room", entity_category="staff", entity_id=99
        )
        self.assertFalse(dec_override_deny.allowed)

    def test_pet_whitelist_suppression(self):
        """Whitelisted household pets in restricted perimeter zones suppress alarms."""
        # Perimeter zone restricts everything
        self.rsac.set_rule(
            camera_id="cam_01",
            zone_id="perimeter_fence",
            allowed_categories=["vip"],
            alarm_on_breach=True,
        )

        # Domestic pet presence evaluates as allowed with pet suppression
        dec_pet = self.rsac.evaluate_access("cam_01", "perimeter_fence", entity_category="pet")
        self.assertTrue(dec_pet.allowed)
        self.assertTrue(dec_pet.is_pet_suppressed)
        self.assertEqual(dec_pet.severity, "info")

        # Custom pet label addition
        self.rsac.add_pet_whitelist("parrot")
        self.assertIn("parrot", self.rsac.get_pet_whitelist())
        dec_parrot = self.rsac.evaluate_access("cam_01", "perimeter_fence", entity_category="parrot")
        self.assertTrue(dec_parrot.is_pet_suppressed)

        # Removing pet label restores restriction
        self.rsac.remove_pet_whitelist("parrot")
        dec_parrot_denied = self.rsac.evaluate_access("cam_01", "perimeter_fence", entity_category="parrot")
        self.assertFalse(dec_parrot_denied.allowed)

    def test_category_management(self):
        """Test dynamic registration and deletion of custom categories."""
        cat = self.rsac.register_category(
            cat_id="robot_courier",
            name="Autonomous Robot",
            color="#00FFAA",
            badge_icon="cpu",
            description="Automated delivery drone",
        )
        self.assertEqual(cat.id, "robot_courier")
        self.assertIsNotNone(self.rsac.get_category("robot_courier"))

        # Delete category
        del_ok = self.rsac.delete_category("robot_courier")
        self.assertTrue(del_ok)
        self.assertIsNone(self.rsac.get_category("robot_courier"))


if __name__ == "__main__":
    unittest.main()
