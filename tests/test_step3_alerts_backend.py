"""Tests for Step 3 Milestone 3: #alerts unread state, telemetry count, and admin API."""

import csv
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.dependencies import get_db
from dashboard.services.stream_telemetry import build_stream_telemetry, invalidate_unread_alert_cache
from intelligent_tracker.database import TrackerDB


class _FailingWriteCursor:
    """Proxy sqlite3.Cursor that raises OperationalError on UPDATE/DELETE."""

    def __init__(self, inner: sqlite3.Cursor) -> None:
        self._inner = inner

    def execute(self, sql: str, params=()):
        if sql.lstrip().upper().startswith(("UPDATE", "DELETE")):
            raise sqlite3.OperationalError("injected write failure")
        return self._inner.execute(sql, params)

    def close(self) -> None:
        self._inner.close()


class _ConnProxy:
    """Proxy sqlite3.Connection recording rollback calls."""

    def __init__(self, inner: sqlite3.Connection) -> None:
        self._inner = inner
        self.rollback_calls = 0

    def cursor(self) -> _FailingWriteCursor:
        return _FailingWriteCursor(self._inner.cursor())

    def commit(self) -> None:
        self._inner.commit()

    def rollback(self) -> None:
        self.rollback_calls += 1
        self._inner.rollback()


class TestMemoryUnreadMigration(unittest.TestCase):
    """Verify idempotent is_read/acknowledged_at migration and row hydration."""

    def test_fresh_db_has_unread_columns_index_and_user_version(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = TrackerDB(db_path=str(Path(tmp.name) / "fresh.db"))
        self.addCleanup(db.close)

        cols = {r[1] for r in db._conn.execute("PRAGMA table_info(world_timeline_events)").fetchall()}
        self.assertIn("is_read", cols)
        self.assertIn("acknowledged_at", cols)
        idxs = {r[1] for r in db._conn.execute("PRAGMA index_list(world_timeline_events)").fetchall()}
        self.assertIn("idx_world_timeline_unread", idxs)
        self.assertGreaterEqual(db.get_schema_version(), 1)

    def test_legacy_v1_db_migrates_without_losing_rows(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "legacy_v1.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE world_timeline_events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL DEFAULT 'sighting', "
            "entity_id INTEGER, entity_name TEXT DEFAULT '', category TEXT DEFAULT '', "
            "camera_id TEXT DEFAULT '', zone_id TEXT DEFAULT '', timestamp REAL NOT NULL, "
            "confidence REAL DEFAULT 1.0, title TEXT DEFAULT '', summary TEXT NOT NULL DEFAULT '', "
            "tags TEXT DEFAULT '', metadata_json TEXT DEFAULT '{}', "
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "INSERT INTO world_timeline_events (event_type, camera_id, timestamp, summary) "
            "VALUES ('intrusion_alert', 'cam_1', 1000.0, 'Legacy event')"
        )
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
        conn.close()

        db = TrackerDB(db_path=str(db_path))
        self.addCleanup(db.close)
        self.assertGreaterEqual(db.get_schema_version(), 1)
        ev = db.get_timeline_event(1)
        self.assertIsNotNone(ev)
        self.assertFalse(ev["is_read"])
        self.assertIsNone(ev["acknowledged_at"])
        hits = db.search_timeline_events(camera_id="cam_1")
        self.assertEqual(len(hits), 1)
        self.assertFalse(hits[0]["is_read"])


class TestEventsAdminMixinAndTelemetry(unittest.TestCase):
    """Verify EventsAdminMixin CRUD, rollback safety, and stream telemetry unread count."""

    def setUp(self) -> None:
        invalidate_unread_alert_cache()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = TrackerDB(db_path=str(Path(self._tmp.name) / "admin.db"))
        self.addCleanup(self.db.close)

    def test_acknowledge_rollback_on_write_error(self) -> None:
        eid = self.db.index_timeline_event("Alert A", event_type="intrusion", camera_id="cam_1", timestamp=100.0)
        real_conn = self.db._conn
        proxy = _ConnProxy(real_conn)
        self.db._conn = proxy
        try:
            with self.assertRaises(sqlite3.OperationalError):
                self.db.acknowledge_timeline_events(event_ids=[eid], is_read=True)
            self.assertEqual(proxy.rollback_calls, 1)
            with self.assertRaises(sqlite3.OperationalError):
                self.db.clear_timeline_events(camera_id="cam_1")
            self.assertEqual(proxy.rollback_calls, 2)
        finally:
            self.db._conn = real_conn

    def test_stream_telemetry_unread_count_and_closed_fallback(self) -> None:
        self.db.index_timeline_event("A1", camera_id="cam_1", timestamp=100.0)
        self.db.index_timeline_event("A2", camera_id="cam_1", timestamp=101.0)
        mgr = MagicMock(camera_id="cam_1", overlays={}, analytics=None, event_bus=None, is_armed=False, db=self.db)
        mgr.homography.is_calibrated = False
        mgr.homography.track_to_ground.return_value = (0.0, 0.0)
        mgr.get_recording_status.return_value = {"is_recording": False}

        telem = build_stream_telemetry(mgr, {}, 10.0, 15.0, (360, 640, 3), 1)
        self.assertEqual(telem["unread_alert_count"], 2)

        self.db.close()
        telem_closed = build_stream_telemetry(mgr, {}, 11.0, 15.0, (360, 640, 3), 2)
        self.assertEqual(telem_closed["unread_alert_count"], 0)
        mgr.db = None
        telem_none = build_stream_telemetry(mgr, {}, 12.0, 15.0, (360, 640, 3), 3)
        self.assertEqual(telem_none["unread_alert_count"], 0)


class TestEventsAdminAPI(unittest.TestCase):
    """Verify /api/events/* endpoints and unread_alert_count on GET /events."""

    def setUp(self) -> None:
        invalidate_unread_alert_cache()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = TrackerDB(db_path=str(Path(self._tmp.name) / "api.db"))
        self.addCleanup(self.db.close)
        self.e1 = self.db.index_timeline_event(
            "Crit 1", event_type="rsac_breach", camera_id="cam_a", zone_id="vault",
            timestamp=200.0, metadata={"severity": "critical"},
        )
        self.e2 = self.db.index_timeline_event(
            "Warn 2", event_type="dwell_exceeded", camera_id="cam_a", zone_id="lobby",
            timestamp=210.0, metadata={"severity": "warning"},
        )
        self.e3 = self.db.index_timeline_event(
            "Info 3", event_type="sighting", camera_id="cam_b", zone_id="dock",
            timestamp=220.0, metadata={"severity": "info"},
        )
        pool = MagicMock()
        pool.list_cameras.return_value = [{"camera_id": "cam_live_only"}]
        app.dependency_overrides[get_db] = lambda: self.db
        app.state.stream_manager = None
        app.state.camera_pool = pool
        self.addCleanup(self._reset_app)
        self.client = TestClient(app)

    def _reset_app(self) -> None:
        app.dependency_overrides.clear()
        app.state.camera_pool = None

    def test_paginated_events_and_facets(self) -> None:
        resp = self.client.get("/events?paginated=true&limit=2")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["unread_alert_count"], 3)

        facets = self.client.get("/api/events/facets")
        self.assertEqual(facets.status_code, 200)
        body = facets.json()
        self.assertIn("cam_live_only", body["cameras"])
        self.assertIn("cam_a", body["cameras"])
        self.assertIn("vault", body["zones"])
        self.assertIn("rsac_breach", body["event_types"])
        self.assertIn("critical", body["severities"])

    def test_acknowledge_single_batch_toggle_and_mark_all(self) -> None:
        r1 = self.client.patch("/api/events/acknowledge", json={"event_id": self.e1, "is_read": True})
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()["unread_alert_count"], 2)

        r2 = self.client.patch("/api/events/acknowledge", json={"event_id": self.e1, "is_read": False})
        self.assertEqual(r2.json()["unread_alert_count"], 3)

        r3 = self.client.patch("/api/events/acknowledge", json={"event_ids": [self.e1, self.e2], "is_read": True})
        self.assertEqual(r3.json()["updated"], 2)
        self.assertEqual(r3.json()["unread_alert_count"], 1)

        r4 = self.client.patch("/api/events/acknowledge", json={"mark_all": True, "is_read": True})
        self.assertEqual(r4.json()["updated"], 1)
        self.assertEqual(r4.json()["unread_alert_count"], 0)

    def test_delete_and_clear_events(self) -> None:
        d1 = self.client.delete(f"/api/events/{self.e3}")
        self.assertEqual(d1.status_code, 200)
        self.assertEqual(d1.json()["unread_alert_count"], 2)
        d2 = self.client.delete(f"/api/events/{self.e3}")
        self.assertEqual(d2.status_code, 404)

        self.client.patch("/api/events/acknowledge", json={"event_id": self.e1, "is_read": True})
        c1 = self.client.post("/api/events/clear", json={"read_only": True})
        self.assertEqual(c1.status_code, 200)
        self.assertEqual(c1.json()["deleted"], 1)
        self.assertEqual(c1.json()["unread_alert_count"], 1)

        c2 = self.client.post("/api/events/clear", json={"camera_id": "cam_a", "severity": "warning"})
        self.assertEqual(c2.status_code, 200)
        self.assertEqual(c2.json()["deleted"], 1)
        self.assertEqual(c2.json()["unread_alert_count"], 0)

    def test_export_csv_and_json(self) -> None:
        j_resp = self.client.get("/api/events/export?format=json&camera_id=cam_a")
        self.assertEqual(j_resp.status_code, 200)
        self.assertEqual(len(j_resp.json()), 2)

        c_resp = self.client.get("/api/events/export?format=csv&severity=critical")
        self.assertEqual(c_resp.status_code, 200)
        self.assertIn("text/csv", c_resp.headers["content-type"])
        rows = list(csv.DictReader(io.StringIO(c_resp.text)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["camera_id"], "cam_a")

        bad = self.client.get("/api/events/export?format=xml")
        self.assertEqual(bad.status_code, 400)
