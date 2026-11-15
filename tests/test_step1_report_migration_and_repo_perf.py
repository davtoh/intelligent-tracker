#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Step 1 Milestone 3 tests: migration mtime cache & save_video_run hydration."""

import json
import os
import tempfile
import threading
import unittest
from unittest.mock import patch

from dashboard.services import video_report_migration as migration_mod
from dashboard.services.video_report_migration import (
    clear_migration_cache,
    migrate_legacy_json_for_aliases,
)
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.repositories import video_run_repo


def _write_legacy_report(reports_dir: str, alias: str, run_id: str, total: int = 1) -> str:
    rep_path = os.path.join(reports_dir, f"{alias}_reports.json")
    payload = [
        {
            "run_id": run_id,
            "filename": f"{alias}.mp4",
            "base_filename": f"{alias}.mp4",
            "source_resolution": [1280, 720],
            "source_fps": 30.0,
            "report": {"frames_processed": total, "total_detections": total},
            "config": {"detector": "mock"},
        }
    ]
    with open(rep_path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return rep_path


class TestMigrationCacheAndRepoPerf(unittest.TestCase):
    """Verify mtime-aware legacy migration cache and save_video_run hydration."""

    def setUp(self) -> None:
        clear_migration_cache()
        self.addCleanup(clear_migration_cache)
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.reports_dir = os.path.join(self._tmpdir.name, "reports")
        os.makedirs(self.reports_dir, exist_ok=True)
        self.db_path = os.path.join(self._tmpdir.name, "tracker.db")
        self.db = TrackerDB(db_path=self.db_path)
        self.addCleanup(self.db.close)
        self.lock = threading.RLock()

    def test_migration_skips_disk_and_db_when_file_unchanged(self) -> None:
        _write_legacy_report(self.reports_dir, "clip", "run_1")
        with patch.object(
            migration_mod, "load_runs_file", wraps=migration_mod.load_runs_file
        ) as mock_load, patch.object(
            self.db, "get_video_run", wraps=self.db.get_video_run
        ) as mock_get:
            migrate_legacy_json_for_aliases(
                "clip.mp4", ["clip"], self.reports_dir, self.db,
                lambda fn: fn, lambda _: None, self.lock,
            )
            migrate_legacy_json_for_aliases(
                "clip.mp4", ["clip"], self.reports_dir, self.db,
                lambda fn: fn, lambda _: None, self.lock,
            )
            self.assertEqual(mock_load.call_count, 1)
            self.assertEqual(mock_get.call_count, 2)

    def test_migration_reruns_on_mtime_change_or_cache_clear(self) -> None:
        rep_path = _write_legacy_report(self.reports_dir, "clip", "run_2")
        with patch.object(
            migration_mod, "load_runs_file", wraps=migration_mod.load_runs_file
        ) as mock_load:
            migrate_legacy_json_for_aliases(
                "clip.mp4", ["clip"], self.reports_dir, self.db,
                lambda fn: fn, lambda _: None, self.lock,
            )
            st = os.stat(rep_path)
            os.utime(rep_path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
            migrate_legacy_json_for_aliases(
                "clip.mp4", ["clip"], self.reports_dir, self.db,
                lambda fn: fn, lambda _: None, self.lock,
            )
            clear_migration_cache()
            migrate_legacy_json_for_aliases(
                "clip.mp4", ["clip"], self.reports_dir, self.db,
                lambda fn: fn, lambda _: None, self.lock,
            )
            self.assertEqual(mock_load.call_count, 3)

    def test_migration_reruns_for_distinct_database(self) -> None:
        _write_legacy_report(self.reports_dir, "clip", "run_3")
        other_db = TrackerDB(db_path=os.path.join(self._tmpdir.name, "other.db"))
        self.addCleanup(other_db.close)
        migrate_legacy_json_for_aliases(
            "clip.mp4", ["clip"], self.reports_dir, self.db,
            lambda fn: fn, lambda _: None, self.lock,
        )
        migrate_legacy_json_for_aliases(
            "clip.mp4", ["clip"], self.reports_dir, other_db,
            lambda fn: fn, lambda _: None, self.lock,
        )
        self.assertIsNotNone(other_db.get_video_run("run_3"))

    def test_save_video_run_hydrates_detections_without_json_reparse(self) -> None:
        dets = [{"frame_index": 0, "detections": [{"id": 1, "bbox": [1, 2, 3, 4]}]}]
        with patch.object(
            self.db, "get_video_run", wraps=self.db.get_video_run
        ) as mock_get, patch.object(
            video_run_repo, "_parse_json", wraps=video_run_repo._parse_json
        ) as mock_parse:
            saved = self.db.save_video_run(
                video_filename="clip.mp4",
                report={"frames_processed": 1},
                frame_detections=dets,
                run_id="run_fast",
            )
        mock_get.assert_called_once_with("run_fast", include_detections=False)
        self.assertEqual(saved["frame_detections"], dets)
        self.assertTrue(saved["has_detections"])
        raw_calls = [c.args[0] for c in mock_parse.call_args_list if c.args]
        self.assertFalse(any(isinstance(x, str) and "frame_index" in x for x in raw_calls))

    def test_save_video_run_without_detections_preserves_metadata_only(self) -> None:
        saved = self.db.save_video_run(
            video_filename="clip.mp4",
            report={"frames_processed": 2},
            frame_detections=None,
            run_id="run_meta",
        )
        self.assertNotIn("frame_detections", saved)
        self.assertFalse(saved["has_detections"])


if __name__ == "__main__":
    unittest.main()
