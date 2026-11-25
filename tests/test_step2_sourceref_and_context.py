"""Milestone 1+ tests for Step 2: SourceRef SSOT, schema v3 migration, and run_id wiring."""

import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from dashboard.services import video_analytics_service, video_report_store
from intelligent_tracker.active_learning import ActiveLearningManager
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.events.bus import EventBus
from intelligent_tracker.events.types import ZoneEvent
from intelligent_tracker.matching._gallery_matching import _notify_active_learning
from intelligent_tracker.matching._gallery_signals import emit_periodic_sighting
from intelligent_tracker.memory._event_formatters import normalize_event_doc
from intelligent_tracker.memory.fts_index import EventFTSIndex
from intelligent_tracker.repositories.sightings_query_helpers import build_sightings_where_clause
from intelligent_tracker.source_ref import build_source_ref, snapshot_path_to_url


def _write_tiny_mp4(path: str, frames: int = 5) -> None:
    """Write a tiny synthetic MP4 fixture for mock VideoIndexer tests."""
    fourcc = getattr(cv2, "VideoWriter_fourcc")(*"mp4v")
    writer = cv2.VideoWriter(path, fourcc, 5.0, (64, 64))
    try:
        for idx in range(frames):
            img = np.full((64, 64, 3), 40 + idx * 20, dtype=np.uint8)
            writer.write(img)
    finally:
        writer.release()


class TestStep2Milestone1Backend(unittest.TestCase):
    """Isolated backend tests for SourceRef, schema v3, and pipeline run_id propagation."""

    def _make_temp_db(self, db_name: str = "test.db") -> tuple[str, TrackerDB]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = TrackerDB(os.path.join(tmp.name, db_name))
        self.addCleanup(db.close)
        return tmp.name, db

    def test_build_source_ref_and_snapshot_url(self) -> None:
        self.assertEqual(snapshot_path_to_url(r"data\crops\sighting_1.jpg"), "/api/crops/sighting_1.jpg")
        self.assertEqual(snapshot_path_to_url("/api/crops/existing.jpg"), "/api/crops/existing.jpg")
        self.assertEqual(snapshot_path_to_url("../secret/bad.jpg"), "")
        cam_ref = build_source_ref(
            camera_id="cam_front", ts=1700.0, track_id=3, entity_id=7,
            zone_id="lobby", bbox="[10, 20, 30, 40]", snapshot_path="data/crops/a.jpg",
        )
        self.assertEqual(cam_ref["kind"], "camera")
        self.assertEqual(cam_ref["bbox"], [10, 20, 30, 40])
        self.assertEqual(cam_ref["snapshot_url"], "/api/crops/a.jpg")
        self.assertNotIn("video_filename", cam_ref)
        vid_ref = build_source_ref(
            video_filename="clip.mp4", run_id="run_1234", media_offset_sec=4.1256,
        )
        self.assertEqual(vid_ref["kind"], "video")
        self.assertEqual(vid_ref["media_offset_sec"], 4.126)
        self.assertEqual(vid_ref["run_id"], "run_1234")

    def test_user_version_3_migration_from_v2_is_idempotent(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = os.path.join(tmp.name, "legacy_v2.db")
        conn = sqlite3.connect(db_path)
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
            "VALUES ('sighting', 'cam_1', 500.0, 'Legacy v2 event')"
        )
        conn.execute("PRAGMA user_version = 2;")
        conn.commit()
        conn.close()

        db = TrackerDB(db_path)
        self.addCleanup(db.close)
        self.assertEqual(db.get_schema_version(), 3)
        cols = {r[1] for r in db._conn.execute("PRAGMA table_info(world_timeline_events);").fetchall()}
        self.assertIn("run_id", cols)
        idxs = {r[1] for r in db._conn.execute("PRAGMA index_list(world_timeline_events);").fetchall()}
        self.assertIn("idx_timeline_run_id", idxs)
        row = db.get_timeline_event(1)
        self.assertIsNotNone(row)
        self.assertEqual(row["summary"], "Legacy v2 event")

    def test_sightings_where_clause_camera_id_or_source_and_run_id(self) -> None:
        _, db = self._make_temp_db()
        eid = db.add_entity(name="Alice", category="person")
        db.add_sighting(
            entity_id=eid, track_id=1, source="clip.mp4", camera_id="cam_lobby",
            video_filename="clip.mp4", media_offset_sec=2.5, run_id="run_aaa",
        )
        db.add_sighting(
            entity_id=eid, track_id=2, source="cam_gate", camera_id="cam_gate", run_id="run_bbb",
        )
        where_sql, params = build_sightings_where_clause(source="cam_lobby", run_id="run_aaa")
        self.assertIn("(s.camera_id = ? OR s.source = ?)", where_sql)
        self.assertEqual(params, ["cam_lobby", "cam_lobby", "run_aaa"])
        hits = db.get_sightings(source="cam_lobby", run_id="run_aaa")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["camera_id"], "cam_lobby")
        self.assertEqual(db.count_sightings(camera_id="cam_gate", run_id="run_bbb"), 1)

    def test_timeline_event_run_id_and_source_ref_roundtrip(self) -> None:
        _, db = self._make_temp_db()
        bus = EventBus()
        self.addCleanup(bus.stop)
        fts = EventFTSIndex(db=db, event_bus=bus, auto_attach=True)
        self.addCleanup(fts.stop)
        ev = ZoneEvent(
            camera_id="cam_a", zone_id="entry", track_id=5, entity_id=None,
            entity_name="Guest", timestamp=1234.5, bbox=(1, 2, 30, 40),
            metadata={"video_filename": "demo.mp4", "media_offset_sec": 1.5, "run_id": "run_z9"},
        )
        doc = normalize_event_doc(ev)
        self.assertEqual(doc["run_id"], "run_z9")
        self.assertEqual(doc["source_ref"]["kind"], "video")
        self.assertEqual(doc["source_ref"]["run_id"], "run_z9")
        row_id = fts.handle_event(ev)
        stored = db.get_timeline_event(int(row_id))
        self.assertEqual(stored["run_id"], "run_z9")
        self.assertEqual(stored["source_ref"]["video_filename"], "demo.mp4")
        self.assertEqual(stored["source_ref"]["zone_id"], "entry")

    def test_gallery_matching_and_signals_forward_run_id_and_camera_id(self) -> None:
        tmpdir, db = self._make_temp_db()
        eid = db.add_entity(name="Bob", category="person")
        al = ActiveLearningManager(db=db, min_confidence=0.4, max_confidence=0.75, crops_dir=tmpdir)
        matcher = SimpleNamespace(
            db=db, active_learning=al, gallery_entity_ids=[eid], gallery_names=["Bob"],
            gallery_categories=["person"], video_filename="clip.mp4",
            current_media_offset_sec=3.25, run_id="run_match1", camera_id="cam_dock",
            crops_dir=tmpdir, sighting_interval=0.0, _last_sighting_time={}, fts_index=EventFTSIndex(db=db),
        )
        frame = np.full((64, 64, 3), 180, dtype=np.uint8)
        trk = SimpleNamespace(track_id=11, bbox=(4, 4, 40, 50))
        _notify_active_learning(matcher, trk, frame, 0, 0.55, "clip.mp4", 100.0)
        pending = db.list_review_items(status="pending")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["run_id"], "run_match1")
        self.assertEqual(pending[0]["video_filename"], "clip.mp4")
        self.assertAlmostEqual(float(pending[0]["media_offset_sec"]), 3.25)

        emitted = emit_periodic_sighting(
            matcher, entity_id=eid, name="Bob", category="person", track=trk,
            confidence=0.92, source="clip.mp4", zone_id="bay", timestamp=200.0, frame=frame,
        )
        self.assertTrue(emitted)
        sightings = db.get_sightings(entity_id=eid, run_id="run_match1")
        self.assertEqual(len(sightings), 1)
        self.assertEqual(sightings[0]["camera_id"], "cam_dock")
        timeline = db.search_timeline_events(entity_id=eid)
        self.assertEqual(timeline[0]["run_id"], "run_match1")

    def test_video_analytics_service_propagates_pregenerated_run_id(self) -> None:
        tmpdir, db = self._make_temp_db("tracker.db")
        mp4_path = os.path.join(tmpdir, "sample.mp4")
        _write_tiny_mp4(mp4_path, frames=5)
        reports_dir = os.path.join(tmpdir, "reports")
        captured: dict[str, str] = {}

        orig_create = video_analytics_service.create_video_indexer

        def _spy_create(*args, **kwargs):
            idx = orig_create(*args, **kwargs)
            captured["indexer_run_id"] = getattr(idx, "run_id", "")
            captured["matcher_run_id"] = getattr(getattr(idx, "matcher", None), "run_id", "")
            captured["al_run_id"] = getattr(getattr(idx, "active_learning", None), "run_id", "")
            return idx

        opts = {
            "detector": "mock", "sample_rate": 2, "confidence": 0.4,
            "classes": None, "tracked_categories": None, "scenario_camera_id": None,
        }
        with (
            patch.object(video_analytics_service, "_resolve_db", return_value=db),
            patch.object(video_report_store, "REPORTS_DIR", reports_dir),
            patch.object(video_analytics_service, "create_video_indexer", side_effect=_spy_create),
        ):
            report = video_analytics_service.run_sync_analytics("sample.mp4", mp4_path, opts)

        rid = str(report.get("run_id") or "")
        self.assertTrue(rid.startswith("run_"))
        self.assertEqual(captured["indexer_run_id"], rid)
        self.assertEqual(captured["matcher_run_id"], rid)
        self.assertEqual(captured["al_run_id"], rid)
        self.assertIsNotNone(db.get_video_run(rid, video_filename="sample.mp4"))
