#!/usr/bin/env python3
"""Diagnostic Probe: alerts_store_probe.

Verifies SQLite is_read SSOT, unread_alert_count accuracy, and acknowledge_events
write-through behavior in an isolated TemporaryDirectory database.
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


def run_probe() -> dict[str, Any]:
    """Verify alerts is_read SSOT and unread count transitions in isolated DB."""
    from dashboard.services.events_admin_service import acknowledge_events
    from intelligent_tracker.database import TrackerDB

    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        db = TrackerDB(str(Path(tmpdir) / "tracker.db"))
        try:
            ev_id = db.index_timeline_event(
                "Entity entered z_1",
                event_type="zone_entry",
                camera_id="cam_1",
                zone_id="z_1",
                timestamp=time.time(),
                title="Zone Entry",
            )
            if db.count_unread_timeline_events() != 1:
                failures.append(f"Expected 1 unread alert, got: {db.count_unread_timeline_events()}")

            ack = acknowledge_events(db, event_ids=[ev_id], is_read=True)
            if ack.get("unread_alert_count") != 0 or ack.get("updated") != 1:
                failures.append(f"Acknowledge failed to clear unread count: {ack}")

            reopened = acknowledge_events(db, event_ids=[ev_id], is_read=False)
            if reopened.get("unread_alert_count") != 1:
                failures.append(f"Mark unread failed to restore unread count: {reopened}")
        finally:
            db.close()

    status = "error" if failures else "ok"
    summary = f"Alerts store probe: {len(failures)} failure(s)" if failures else "Alerts SQLite is_read SSOT probe passed."
    return {"status": status, "summary": summary, "details": {"failures": failures}}


if __name__ == "__main__":
    res = run_probe()
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["status"] == "ok" else 1)
