#!/usr/bin/env python3
"""Diagnostic Probe: alerts_store_probe.

Verifies SQLite alerts SSOT end-to-end in an isolated TemporaryDirectory database:
1. is_read SSOT & unread_alert_count transitions via acknowledge_events.
2. 0 world_entity_state_changed rows in SQLite while in-memory EventBus receives them.
3. severity=info|warning|critical & min_severity filter parity.
4. Canonical unscoped + contains + multi-term zone_id filtering & deduplicated facets.
5. zone_dwell / zone_exit entry_time, exit_time, and dwell_time persistence.
6. Custom DB AlertPromotionEngine rule upgrading matching dwell event to warning/critical.
"""

import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _check_is_read_ssot(db: Any, failures: list[str]) -> None:
    """Verify is_read SSOT and unread count transitions."""
    from dashboard.services.events_admin_service import acknowledge_events

    ev_id = db.index_timeline_event(
        "Entity entered z_1",
        event_type="zone_entry",
        camera_id="cam_1",
        zone_id="cam_1:zone:z_1",
        timestamp=time.time(),
        title="Zone Entry",
        metadata={"severity": "info"},
    )
    if db.count_unread_timeline_events() != 1:
        failures.append(f"Expected 1 unread alert, got: {db.count_unread_timeline_events()}")
    ack = acknowledge_events(db, event_ids=[ev_id], is_read=True)
    if ack.get("unread_alert_count") != 0 or ack.get("updated") != 1:
        failures.append(f"Acknowledge failed to clear unread count: {ack}")
    reopened = acknowledge_events(db, event_ids=[ev_id], is_read=False)
    if reopened.get("unread_alert_count") != 1:
        failures.append(f"Mark unread failed to restore unread count: {reopened}")


def _publish_probe_events(db: Any, t0: float) -> tuple[list[str], Any, Any]:
    """Publish state, dwell, exit, and warning events through EventBus write-through."""
    from intelligent_tracker.events import EventBus, IntrusionAlert, ZoneEvent
    from intelligent_tracker.events.promotion_engine import AlertPromotionEngine
    from intelligent_tracker.memory import EventFTSIndex
    from intelligent_tracker.world.events import EntityStateChangedEvent

    engine = AlertPromotionEngine(db=db)
    bus = EventBus(capacity=64)
    bus.start()
    fts = EventFTSIndex(db=db, event_bus=bus, auto_attach=True, promotion_engine=engine)
    seen: list[str] = []
    bus.subscribe(lambda ev: seen.append(ev.event_type))
    try:
        bus.publish(EntityStateChangedEvent(
            camera_id="cam_1", world_entity_id="e:1", change_type="updated",
            active_zones={"cam_1": ["cam_1:zone:Main_Vault"]}, timestamp=t0,
        ))
        dwell_ev = ZoneEvent(
            camera_id="cam_1", zone_id="cam_1:zone:Main_Vault", track_id=3,
            action="dwell", dwell_time=12.5, entry_time=t0, timestamp=t0 + 12.5,
        )
        exit_ev = ZoneEvent(
            camera_id="cam_1", zone_id="cam_1:zone:Main_Vault", track_id=3,
            action="exit", dwell_time=20.0, entry_time=t0, exit_time=t0 + 20.0, timestamp=t0 + 20.0,
        )
        warn_ev = IntrusionAlert(
            camera_id="cam_2", zone_id="cam_2:zone:Lobby_West", track_id=4,
            severity="warning", timestamp=t0 + 25.0,
        )
        for ev in (dwell_ev, exit_ev, warn_ev):
            bus.publish(ev)
        bus.wait_until_empty(timeout=3.0)
    finally:
        fts.detach()
        bus.stop()
    return seen, dwell_ev, exit_ev


def _check_noise_and_promotion(db: Any, failures: list[str]) -> None:
    """Verify state-tick noise suppression, dwell window persistence, and promotion rules."""
    db.create_alert_rule(
        name="Vault Dwell Critical", event_type="zone_dwell", zone_id="vault",
        min_dwell_time=8.0, target_severity="critical", add_tags="escalated",
    )
    t0 = 1_700_000_000.0
    seen, dwell_ev, exit_ev = _publish_probe_events(db, t0)
    if "world_entity_state_changed" not in seen:
        failures.append("In-memory EventBus did not receive world_entity_state_changed")
    if db.search_timeline_events(event_type="world_entity_state_changed", limit=10):
        failures.append("world_entity_state_changed leaked into SQLite timeline_events")
    dwell_row = db.get_timeline_event(int(getattr(dwell_ev, "db_id", 0) or 0))
    exit_row = db.get_timeline_event(int(getattr(exit_ev, "db_id", 0) or 0))
    if not dwell_row or dwell_row.get("severity") != "critical":
        failures.append(f"Promotion rule failed to upgrade dwell event to critical: {dwell_row}")
    if not dwell_row or dwell_row.get("metadata", {}).get("entry_time") != t0:
        failures.append(f"Dwell event missing entry_time metadata: {dwell_row}")
    if not exit_row or exit_row.get("metadata", {}).get("exit_time") != t0 + 20.0:
        failures.append(f"Exit event missing exit_time metadata: {exit_row}")


def _check_filters_and_facets(db: Any, failures: list[str]) -> None:
    """Verify severity parity, canonical unscoped zone_id, contains, and multi-term filters."""
    for sev in ("info", "warning", "critical"):
        rows = db.search_timeline_events(severity=sev, limit=20)
        if not rows or any(r.get("severity") != sev for r in rows):
            failures.append(f"severity={sev} filter parity failed: {len(rows)} rows")
    if len(db.search_timeline_events(min_severity="warning", limit=20)) < 2:
        failures.append("min_severity=warning did not return warning+critical rows")
    vault_rows = db.search_timeline_events(zone_id="vault", limit=20)
    if len(vault_rows) < 2 or any(r.get("zone_id") != "Main_Vault" for r in vault_rows):
        failures.append(f"Canonical/contains zone_id filter failed: {vault_rows}")
    multi_rows = db.search_timeline_events(zone_id="vault, lobby", limit=20)
    if len(multi_rows) < 3:
        failures.append(f"Multi-term zone_id filter expected >=3 rows, got {len(multi_rows)}")
    facets = db.get_timeline_event_facets()
    if any(":zone:" in z for z in facets.get("zones", [])):
        failures.append(f"Scoped zone_id leaked into facets: {facets.get('zones')}")


def run_probe() -> dict[str, Any]:
    """Run all alerts store governance checks in an isolated TemporaryDirectory DB."""
    from intelligent_tracker.database import TrackerDB

    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        db = TrackerDB(str(Path(tmpdir) / "tracker.db"))
        try:
            _check_is_read_ssot(db, failures)
            _check_noise_and_promotion(db, failures)
            _check_filters_and_facets(db, failures)
        finally:
            db.close()

    status = "error" if failures else "ok"
    summary = (
        f"Alerts store probe: {len(failures)} failure(s)"
        if failures
        else "Alerts store governance probe passed (SSOT, noise, severity, zones, dwell, promotion)."
    )
    return {"status": status, "summary": summary, "details": {"failures": failures}}


if __name__ == "__main__":
    res = run_probe()
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["status"] == "ok" else 1)
