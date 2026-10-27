#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Role-Based Spatial Access Control (RSAC) & Pet Whitelisting Module.

Provides:
- ``CustomCategory``: Custom semantic entity classification badges with tailored HEX/RGB colors.
- ``RSACSchedule``: Time-of-day and day-of-week active interval schedules.
- ``RSACZoneRule``: Granular per-zone permissions (allowed/denied categories, schedules, entity overrides).
- ``RSACDecision``: Access evaluation result with severity and pet suppression telemetry.
- ``RSACManager``: Multi-camera permission evaluator and synchronization manager with TrackerDB.
"""

import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any, Set, Tuple

from intelligent_tracker.database import TrackerDB


DEFAULT_CUSTOM_CATEGORIES: List[Dict[str, str]] = [
    {"id": "person", "name": "Person", "color": "#3B82F6", "badge_icon": "user", "description": "General human person"},
    {"id": "family_car", "name": "Family Car", "color": "#10B981", "badge_icon": "car", "description": "Whitelisted resident family vehicle"},
    {"id": "delivery_truck", "name": "Delivery Truck", "color": "#F59E0B", "badge_icon": "truck", "description": "Courier or logistics vehicle"},
    {"id": "cleaning_crew", "name": "Cleaning Crew", "color": "#8B5CF6", "badge_icon": "sparkles", "description": "Authorized maintenance crew"},
    {"id": "guard_dog", "name": "Guard Dog", "color": "#EC4899", "badge_icon": "shield", "description": "Authorized security canine"},
    {"id": "pet", "name": "Household Pet", "color": "#06B6D4", "badge_icon": "paw", "description": "Whitelisted domestic pet"},
    {"id": "vip", "name": "VIP Resident", "color": "#6366F1", "badge_icon": "star", "description": "High priority resident or guest"},
    {"id": "restricted", "name": "Restricted / Watchlist", "color": "#EF4444", "badge_icon": "alert-triangle", "description": "Watchlist or unauthorized presence"},
]

DEFAULT_PET_WHITELIST: Set[str] = {"dog", "cat", "pet", "guard_dog"}


@dataclass
class CustomCategory:
    """Semantic category with display color and metadata."""
    id: str
    name: str
    color: str = "#3B82F6"
    badge_icon: str = ""
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RSACSchedule:
    """
    Time schedule window for spatial access rules.
    Days: lowercase 3-letter codes ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] or ['*'].
    Times: 'HH:MM' 24-hour format.
    """
    days: List[str] = field(default_factory=lambda: ["*"])
    start_time: str = "00:00"
    end_time: str = "23:59"

    def is_active(self, timestamp: Optional[float] = None) -> bool:
        """Check if given timestamp falls within schedule interval."""
        ts = timestamp if timestamp is not None else time.time()
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)

        # Day of week check
        day_map = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}
        cur_day = day_map.get(dt.weekday(), "")
        allowed_days = [d.lower().strip() for d in self.days]
        if "*" not in allowed_days and cur_day not in allowed_days:
            return False

        # Time of day check (HH:MM)
        cur_minute = dt.hour * 60 + dt.minute
        try:
            sh, sm = [int(v) for v in self.start_time.split(":")]
            eh, em = [int(v) for v in self.end_time.split(":")]
            start_minute = sh * 60 + sm
            end_minute = eh * 60 + em
        except Exception:
            return True

        if start_minute <= end_minute:
            return start_minute <= cur_minute <= end_minute
        else:
            # Spans overnight / midnight
            return cur_minute >= start_minute or cur_minute <= end_minute

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RSACDecision:
    """Outcome of access control rule evaluation for a tracked entity."""
    allowed: bool
    reason: str
    severity: str = "info"  # 'info', 'warning', 'critical'
    is_pet_suppressed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RSACZoneRule:
    """
    Role-Based Spatial Access Control rule configured for a specific camera Zone.
    """
    camera_id: str
    zone_id: str
    allowed_categories: List[str] = field(default_factory=list)
    denied_categories: List[str] = field(default_factory=list)
    schedules: List[RSACSchedule] = field(default_factory=list)
    entity_overrides: Dict[str, str] = field(default_factory=dict)
    alarm_on_breach: bool = True

    def evaluate_access(
        self,
        entity_category: str,
        entity_id: Optional[int] = None,
        timestamp: Optional[float] = None,
    ) -> RSACDecision:
        """
        Evaluate access permission for an entity category in this zone.

        Priority order:
        1. Entity-specific override ('allow' or 'deny')
        2. Explicitly denied categories -> Deny (critical)
        3. Schedule checks: if schedules defined, current time must match an active schedule
        4. Explicitly allowed categories -> Allow
        5. If allowed_categories is specified and entity_category not present -> Deny (warning)
        6. Default -> Allow (info)
        """
        cat_clean = str(entity_category or "unknown").strip().lower()

        # 1. Entity-specific override
        if entity_id is not None:
            override = self.entity_overrides.get(str(entity_id)) or self.entity_overrides.get(entity_id)
            if override:
                override_clean = str(override).lower().strip()
                if override_clean == "allow":
                    return RSACDecision(
                        allowed=True,
                        reason=f"Entity #{entity_id} has explicit access clearance override",
                        severity="info",
                    )
                elif override_clean == "deny":
                    return RSACDecision(
                        allowed=False,
                        reason=f"Entity #{entity_id} has explicit access restriction override",
                        severity="critical" if self.alarm_on_breach else "warning",
                    )

        # 2. Denied categories
        denied_clean = [c.lower().strip() for c in self.denied_categories]
        if cat_clean in denied_clean or "*" in denied_clean:
            return RSACDecision(
                allowed=False,
                reason=f"Category '{entity_category}' is explicitly denied in zone '{self.zone_id}'",
                severity="critical" if self.alarm_on_breach else "warning",
            )

        # 3. Schedule check
        if self.schedules:
            in_schedule = any(s.is_active(timestamp) for s in self.schedules)
            if not in_schedule:
                return RSACDecision(
                    allowed=False,
                    reason=f"Access outside configured operating hours in zone '{self.zone_id}'",
                    severity="warning",
                )

        # 4. Allowed categories
        allowed_clean = [c.lower().strip() for c in self.allowed_categories]
        if "*" in allowed_clean or cat_clean in allowed_clean:
            return RSACDecision(
                allowed=True,
                reason=f"Category '{entity_category}' is whitelisted in zone '{self.zone_id}'",
                severity="info",
            )

        # 5. Non-empty whitelist rejection
        if self.allowed_categories:
            return RSACDecision(
                allowed=False,
                reason=f"Category '{entity_category}' is not whitelisted for zone '{self.zone_id}'",
                severity="warning" if not self.alarm_on_breach else "critical",
            )

        # 6. Default open
        return RSACDecision(
            allowed=True,
            reason=f"Zone '{self.zone_id}' has open access policy",
            severity="info",
        )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["schedules"] = [s.to_dict() if hasattr(s, "to_dict") else s for s in self.schedules]
        return d


class RSACManager:
    """
    Manager for Role-Based Spatial Access Control rules, custom category definitions,
    and pet alarm suppression.
    """

    def __init__(self, db: Optional[TrackerDB] = None):
        self.db = db
        self.categories: Dict[str, CustomCategory] = {}
        self.rules: Dict[Tuple[str, str], RSACZoneRule] = {}
        self.pet_whitelist: Set[str] = set(DEFAULT_PET_WHITELIST)

        # Populate default categories
        for c in DEFAULT_CUSTOM_CATEGORIES:
            self.categories[c["id"]] = CustomCategory(**c)

        if self.db is not None:
            self.reload()

    def reload(self):
        """Reload categories, rules, and pet whitelist from database."""
        if self.db is None:
            return

        # Load custom categories
        for row in self.db.get_custom_categories():
            self.categories[row["id"]] = CustomCategory(
                id=row["id"],
                name=row["name"],
                color=row.get("color", "#3B82F6"),
                badge_icon=row.get("badge_icon", ""),
                description=row.get("description", ""),
            )

        # Load RSAC zone rules
        self.rules.clear()
        for r in self.db.get_rsac_rules():
            schedules = [RSACSchedule(**s) for s in r.get("schedules", [])]
            rule = RSACZoneRule(
                camera_id=r["camera_id"],
                zone_id=r["zone_id"],
                allowed_categories=r.get("allowed_categories", []),
                denied_categories=r.get("denied_categories", []),
                schedules=schedules,
                entity_overrides=r.get("entity_overrides", {}),
                alarm_on_breach=r.get("alarm_on_breach", True),
            )
            self.rules[(rule.camera_id, rule.zone_id)] = rule

        # Load pet whitelist
        stored_pets = self.db.get_pet_whitelist()
        if stored_pets:
            self.pet_whitelist = set(s.lower().strip() for s in stored_pets)

    def evaluate_access(
        self,
        camera_id: str,
        zone_id: str,
        entity_category: str,
        entity_id: Optional[int] = None,
        timestamp: Optional[float] = None,
    ) -> RSACDecision:
        """
        Evaluate access permission for an entity in a zone.
        Automatically checks pet whitelist to suppress perimeter alarms.
        """
        cat_clean = str(entity_category or "unknown").strip().lower()

        # Check pet whitelist: family pets never trigger intrusion alarms
        if cat_clean in self.pet_whitelist:
            return RSACDecision(
                allowed=True,
                reason=f"Whitelisted pet activity ('{entity_category}') recorded; perimeter alarms suppressed",
                severity="info",
                is_pet_suppressed=True,
            )

        key = (camera_id, zone_id)
        rule = self.rules.get(key)
        if not rule:
            # Default allow if no specific RSAC rule is configured for zone
            return RSACDecision(
                allowed=True,
                reason=f"No RSAC restrictions configured for zone '{zone_id}'",
                severity="info",
            )

        return rule.evaluate_access(
            entity_category=entity_category,
            entity_id=entity_id,
            timestamp=timestamp,
        )

    def set_rule(
        self,
        camera_id: str,
        zone_id: str,
        allowed_categories: List[str],
        denied_categories: Optional[List[str]] = None,
        schedules: Optional[List[Dict[str, Any]]] = None,
        entity_overrides: Optional[Dict[str, str]] = None,
        alarm_on_breach: bool = True,
    ) -> RSACZoneRule:
        """Create or update an RSAC rule for a camera zone."""
        sched_objs = [RSACSchedule(**s) for s in (schedules or [])]
        rule = RSACZoneRule(
            camera_id=camera_id,
            zone_id=zone_id,
            allowed_categories=allowed_categories or [],
            denied_categories=denied_categories or [],
            schedules=sched_objs,
            entity_overrides=entity_overrides or {},
            alarm_on_breach=alarm_on_breach,
        )
        self.rules[(camera_id, zone_id)] = rule

        if self.db is not None:
            self.db.set_rsac_rule(
                camera_id=camera_id,
                zone_id=zone_id,
                allowed_categories=allowed_categories,
                denied_categories=denied_categories,
                schedules=schedules,
                entity_overrides=entity_overrides,
                alarm_on_breach=alarm_on_breach,
            )
        return rule

    def delete_rule(self, camera_id: str, zone_id: str) -> bool:
        """Delete RSAC rule for a zone."""
        self.rules.pop((camera_id, zone_id), None)
        if self.db is not None:
            return self.db.delete_rsac_rule(camera_id, zone_id)
        return True

    def get_rule(self, camera_id: str, zone_id: str) -> Optional[RSACZoneRule]:
        """Get RSAC rule for a zone."""
        return self.rules.get((camera_id, zone_id))

    def list_rules(self, camera_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all RSAC zone rules."""
        results = []
        for (cam, zid), r in self.rules.items():
            if camera_id is None or cam == camera_id:
                results.append(r.to_dict())
        return results

    def add_pet_whitelist(self, label: str, notes: str = "") -> bool:
        """Add label to pet whitelist."""
        clean = label.strip().lower()
        self.pet_whitelist.add(clean)
        if self.db is not None:
            return self.db.add_pet_whitelist(clean, notes=notes)
        return True

    def remove_pet_whitelist(self, label: str) -> bool:
        """Remove label from pet whitelist."""
        clean = label.strip().lower()
        self.pet_whitelist.discard(clean)
        if self.db is not None:
            return self.db.remove_pet_whitelist(clean)
        return True

    def get_pet_whitelist(self) -> List[str]:
        """Get list of whitelisted pet labels."""
        return sorted(list(self.pet_whitelist))

    def register_category(
        self,
        cat_id: str,
        name: str,
        color: str = "#3B82F6",
        badge_icon: str = "",
        description: str = "",
    ) -> CustomCategory:
        """Register or update custom category."""
        clean_id = cat_id.strip().lower()
        cat = CustomCategory(
            id=clean_id,
            name=name.strip(),
            color=color.strip(),
            badge_icon=badge_icon.strip(),
            description=description.strip(),
        )
        self.categories[clean_id] = cat
        if self.db is not None:
            self.db.set_custom_category(
                cat_id=clean_id,
                name=name,
                color=color,
                badge_icon=badge_icon,
                description=description,
            )
        return cat

    def list_categories(self) -> List[Dict[str, Any]]:
        """List all custom categories with colors."""
        return [c.to_dict() for c in self.categories.values()]

    def get_category(self, cat_id: str) -> Optional[CustomCategory]:
        """Get custom category by identifier."""
        return self.categories.get(str(cat_id).strip().lower())

    def delete_category(self, cat_id: str) -> bool:
        """Delete custom category."""
        clean = str(cat_id).strip().lower()
        self.categories.pop(clean, None)
        if self.db is not None:
            return self.db.delete_custom_category(clean)
        return True
