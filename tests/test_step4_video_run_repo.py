"""Unit tests for TrackerDB video_runs schema, VideoRunRepositoryMixin & migrations."""

import os
import sqlite3
import tempfile
import unittest

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.repositories.video_schema import apply_video_schema_migrations


class TestStep4VideoRunRepo(unittest.TestCase):
    """Isolated tests for TrackerDB video_runs CRUD, aliases, and schema migrations."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.db_path = os.path.join(self._tmpdir.name, "test_tracker.db")
        self.db = TrackerDB(db_path=self.db_path)
        self.addCleanup(self.db.close)

    def _sample_report(self, frames: int = 10) -> dict:
        return {
            "frames_processed": frames,
            "total_detections": 4,
            "total_sightings": 2,
            "unique_entities_identified": 1,
            "source_resolution": [1280, 720],
        }

    def test_save_and_get_video_run_roundtrip(self) -> None:
        detections = [{"frame": 0, "time_sec": 0.0, "detections": [{"id": 1}]}]
        saved = self.db.save_video_run(
            video_filename="cam1_clip.mp4",
            report=self._sample_report(),
            config={"sample_rate": 5},
            frame_detections=detections,
            source_resolution=[1280, 720],
            source_fps=30.0,
            run_type="live_record",
            run_id="run_abc123",
            timestamp=1700000000.0,
        )
        self.assertEqual(saved["run_id"], "run_abc123")
        self.assertEqual(saved["run_type"], "live_record")
        self.assertEqual(saved["source_resolution"], [1280, 720])
        self.assertTrue(saved["has_detections"])

        fetched = self.db.get_video_run("run_abc123", include_detections=True)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["config"], {"sample_rate": 5})
        self.assertEqual(fetched["frame_detections"], detections)

    def test_alias_consolidation_across_h264_and_base(self) -> None:
        self.db.save_video_run(
            video_filename="clip.mp4",
            report=self._sample_report(5),
            frame_detections=[{"frame": 0, "detections": []}],
            run_id="run_orig",
            timestamp=100.0,
        )
        self.db.save_video_run(
            video_filename="clip_h264.mp4",
            report=self._sample_report(8),
            frame_detections=[{"frame": 1, "detections": [{"id": 2}]}],
            run_id="run_h264",
            timestamp=200.0,
        )
        runs_from_base = self.db.list_video_runs("clip.mp4")
        runs_from_h264 = self.db.list_video_runs("clip_h264.mp4")
        self.assertEqual([r["run_id"] for r in runs_from_base], ["run_h264", "run_orig"])
        self.assertEqual([r["run_id"] for r in runs_from_h264], ["run_h264", "run_orig"])

        stream = self.db.get_video_detection_stream("clip.mp4")
        self.assertIsNotNone(stream)
        self.assertEqual(stream["run_id"], "run_h264")
        self.assertEqual(stream["frame_count"], 1)

    def test_update_resolution_delete_and_clear_runs(self) -> None:
        self.db.save_video_run("yard.mp4", self._sample_report(), run_id="r1", timestamp=10.0)
        self.db.save_video_run("yard_h264.mp4", self._sample_report(), run_id="r2", timestamp=20.0)
        self.assertTrue(self.db.update_video_run_resolution("r1", [1920, 1080], 29.97))
        updated = self.db.get_video_run("r1")
        self.assertEqual(updated["source_resolution"], [1920, 1080])
        self.assertAlmostEqual(updated["source_fps"], 29.97, places=2)

        self.assertTrue(self.db.delete_video_run("yard_h264.mp4", "r1"))
        self.assertIsNone(self.db.get_video_run("r1"))
        self.assertEqual(self.db.clear_video_runs("yard.mp4"), 1)
        self.assertEqual(self.db.list_video_runs("yard.mp4"), [])

    def test_media_columns_present_and_migrations_idempotent(self) -> None:
        with self.db._lock:
            for table in ("sightings", "world_timeline_events"):
                cols = {
                    row[1]
                    for row in self.db._conn.execute(f"PRAGMA table_info({table});").fetchall()
                }
                self.assertIn("video_filename", cols)
                self.assertIn("media_offset_sec", cols)
            cur = self.db._conn.cursor()
            apply_video_schema_migrations(cur)
            apply_video_schema_migrations(cur)
            cur.close()

    def test_legacy_db_migration_preserves_existing_rows(self) -> None:
        legacy_path = os.path.join(self._tmpdir.name, "legacy.db")
        conn = sqlite3.connect(legacy_path)
        conn.execute(
            "CREATE TABLE sightings (id INTEGER PRIMARY KEY, entity_id INTEGER, source TEXT, timestamp TIMESTAMP);"
        )
        conn.execute("INSERT INTO sightings (entity_id, source) VALUES (1, 'cam0');")
        conn.commit()
        conn.close()

        migrated = TrackerDB(db_path=legacy_path)
        self.addCleanup(migrated.close)
        row = migrated._conn.execute(
            "SELECT entity_id, source, video_filename, media_offset_sec FROM sightings;"
        ).fetchone()
        self.assertEqual((row["entity_id"], row["source"], row["video_filename"]), (1, "cam0", ""))
        self.assertEqual(row["media_offset_sec"], 0.0)

    def test_edge_cases_empty_and_missing_detections(self) -> None:
        with self.assertRaises(ValueError):
            self.db.save_video_run("   ", self._sample_report())
        self.db.save_video_run("nodet.mp4", self._sample_report(), frame_detections=None, run_id="r_nodet")
        self.assertIsNone(self.db.get_video_detection_stream("nodet.mp4"))
        self.assertFalse(self.db.delete_video_run("nodet.mp4", "nonexistent"))


if __name__ == "__main__":
    unittest.main()
