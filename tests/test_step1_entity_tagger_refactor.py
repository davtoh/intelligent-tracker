"""Unit tests for Step 1 Milestone 3: EntityTaggerService decomposition and deterministic Re-ID."""

import os
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from dashboard.services import entity_tagger
from dashboard.services.entity_tagger import EntityTaggerService
from intelligent_tracker.database import TrackerDB


class TestEntityTaggerRefactor(unittest.TestCase):
    """Verify EntityTaggerService branch coverage, deterministic embeddings, and modularity."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self._db_path = os.path.join(self._tmpdir.name, "test_tracker.db")
        self.db = TrackerDB(db_path=self._db_path)
        self.addCleanup(self.db.close)
        self.crops_dir = os.path.join(self._tmpdir.name, "crops")
        self.frame = np.zeros((120, 160, 3), dtype=np.uint8)
        self.frame[20:80, 30:90] = (40, 180, 220)

    def test_explicit_bbox_and_deterministic_embedding_when_reid_none(self) -> None:
        with patch.object(entity_tagger, "CROPS_DIR", self.crops_dir):
            res1 = EntityTaggerService.tag_entity(
                raw_frame=self.frame,
                db=self.db,
                entity_name="Alice",
                category="person",
                bbox=[30, 20, 60, 60],
                camera_id="cam_test",
            )
            res2 = EntityTaggerService.tag_entity(
                raw_frame=self.frame,
                db=self.db,
                entity_name="Alice",
                category="person",
                bbox=[30, 20, 60, 60],
                camera_id="cam_test",
            )

        self.assertEqual(res1["entity_id"], res2["entity_id"])
        self.assertEqual(res1["name"], "Alice")
        self.assertEqual(res1["category"], "person")
        self.assertTrue(os.path.exists(res1["crop_path"]))

        sigs = self.db.get_signatures(entity_id=res1["entity_id"])
        self.assertEqual(len(sigs), 2)
        emb1 = np.asarray(sigs[0]["embedding"], dtype=np.float32)
        emb2 = np.asarray(sigs[1]["embedding"], dtype=np.float32)
        np.testing.assert_allclose(emb1, emb2, atol=1e-6)

    def test_active_track_id_resolves_bbox_and_updates_identity(self) -> None:
        track = SimpleNamespace(bbox=[10, 15, 40, 50], entity_name=None, category=None)
        tracker = SimpleNamespace(tracks={7: track})
        gallery_matcher = MagicMock()

        with patch.object(entity_tagger, "CROPS_DIR", self.crops_dir):
            res = EntityTaggerService.tag_entity(
                raw_frame=self.frame,
                db=self.db,
                entity_name="Bob",
                category="staff",
                track_id=7,
                tracker=tracker,
                gallery_matcher=gallery_matcher,
            )

        self.assertEqual(res["name"], "Bob")
        self.assertEqual(track.entity_name, "Bob")
        self.assertEqual(track.category, "staff")
        gallery_matcher.refresh_gallery.assert_called_once()

    def test_missing_bbox_and_missing_track_raises_value_error(self) -> None:
        tracker = SimpleNamespace(tracks={1: SimpleNamespace(bbox=[0, 0, 10, 10])})
        with self.assertRaises(ValueError) as ctx:
            EntityTaggerService.tag_entity(
                raw_frame=self.frame,
                db=self.db,
                entity_name="Ghost",
                track_id=999,
                tracker=tracker,
            )
        self.assertIn("Select or draw a bounding box", str(ctx.exception))

    def test_reid_extractor_error_falls_back_to_deterministic_color(self) -> None:
        bad_extractor = MagicMock()
        bad_extractor.extract_crop.side_effect = RuntimeError("onnx failed")
        with patch.object(entity_tagger, "CROPS_DIR", self.crops_dir):
            res = EntityTaggerService.tag_entity(
                raw_frame=self.frame,
                db=self.db,
                entity_name="FallbackUser",
                bbox=[25, 25, 50, 50],
                reid_extractor=bad_extractor,
            )
        self.assertIn("signature_id", res)
        sigs = self.db.get_signatures(entity_id=res["entity_id"])
        self.assertEqual(len(sigs), 1)

    def test_missing_db_or_empty_frame_raises_runtime_error(self) -> None:
        with self.assertRaises(RuntimeError):
            EntityTaggerService.tag_entity(raw_frame=self.frame, db=None, entity_name="X")
        with self.assertRaises(RuntimeError):
            EntityTaggerService.tag_entity(raw_frame=None, db=self.db, entity_name="X")

    def test_entity_tagger_passes_modularity_audit(self) -> None:
        diagnose_script = os.path.join(
            os.path.expanduser("~"),
            ".gemini",
            "config",
            "skills",
            "system-diagnostics",
            "scripts",
            "diagnose.py",
        )
        if not os.path.exists(diagnose_script):
            self.skipTest("system-diagnostics diagnose.py not installed")
        proc = subprocess.run(
            [
                sys.executable,
                diagnose_script,
                "audit",
                "--path",
                "dashboard/services/entity_tagger.py",
                "--max-lines",
                "350",
                "--max-fn-lines",
                "35",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
