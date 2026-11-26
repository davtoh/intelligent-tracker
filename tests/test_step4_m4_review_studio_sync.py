"""Tests for Step 4 Milestone 4: Bidirectional #review <-> Video Studio Sync."""

import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

from dashboard.app import app as fastapi_app
from dashboard.dependencies import get_active_learning_mgr, get_db, set_shutting_down
from dashboard.services.negative_exemplar_service import NegativeExemplarService
from dashboard.services.roi_recognition_service import RoiRecognitionService
from intelligent_tracker.active_learning import ActiveLearningManager
from intelligent_tracker.database import TrackerDB

REPO_ROOT = Path(__file__).resolve().parents[1]


class _FakeTrack:
    def __init__(self, track_id: int, bbox: list[int]) -> None:
        self.track_id = track_id
        self.bbox = tuple(bbox)


class TestReviewQueueSchemaAndTriage(unittest.TestCase):
    """Verify review_queue migration, triage bbox preservation, and auto-resolve."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, "tracker.db")
        self.crops_dir = os.path.join(self._tmp.name, "crops")
        self.db = TrackerDB(self.db_path)
        self.addCleanup(self.db.close)

    def test_review_queue_schema_has_bbox_and_run_id_columns(self) -> None:
        cols = {r[1] for r in self.db._conn.execute("PRAGMA table_info(review_queue);").fetchall()}
        for col in ("bbox_json", "frame_width", "frame_height", "run_id"):
            self.assertIn(col, cols)

    def test_triage_preserves_bbox_and_frame_dimensions(self) -> None:
        mgr = ActiveLearningManager(self.db, crops_dir=self.crops_dir)
        frame = np.full((240, 320, 3), 128, dtype=np.uint8)
        rid = mgr.consider_candidate(
            _FakeTrack(7, [10, 20, 60, 80]),
            frame,
            similarity=0.55,
            camera_id="cam_01",
            timestamp=100.0,
            video_filename="clip.mp4",
            media_offset_sec=4.5,
            run_id="run_abc",
        )
        self.assertIsNotNone(rid)
        item = self.db.get_review_item(int(rid))
        self.assertEqual(item["bbox_json"], "[10, 20, 60, 80]")
        self.assertEqual(item["frame_width"], 320)
        self.assertEqual(item["frame_height"], 240)
        self.assertEqual(item["run_id"], "run_abc")

    def test_auto_resolve_matching_review_items_and_rollback_on_error(self) -> None:
        id1 = self.db.add_review_item(
            "cam_01", 11, "c1.jpg", similarity=0.55, video_filename="clip.mp4",
            media_offset_sec=3.0, bbox=[10, 10, 40, 60], frame_width=320, frame_height=240,
        )
        id2 = self.db.add_review_item(
            "cam_01", 22, "c2.jpg", similarity=0.55, video_filename="other.mp4",
            media_offset_sec=9.0, bbox=[10, 10, 40, 60],
        )
        resolved = self.db.auto_resolve_matching_review_items(
            video_filename="clip_h264.mp4", track_id=11, media_offset_sec=3.2, status="confirmed",
        )
        self.assertEqual([r["id"] for r in resolved], [id1])
        self.assertEqual(self.db.get_review_item(id1)["status"], "confirmed")
        self.assertEqual(self.db.get_review_item(id2)["status"], "pending")

        class _ConnProxy:
            def __init__(self, real: sqlite3.Connection) -> None:
                self._real, self.rollbacks = real, 0
            def rollback(self) -> None:
                self.rollbacks += 1
                self._real.rollback()
            def __getattr__(self, name: str) -> object:
                return getattr(self._real, name)

        proxy = _ConnProxy(self.db._conn)
        with patch.object(self.db, "_conn", proxy):
            with patch.object(self.db, "_fetch_pending_review_candidates", side_effect=sqlite3.Error("boom")):
                with self.assertRaises(sqlite3.Error):
                    self.db.auto_resolve_matching_review_items(video_filename="clip.mp4", track_id=22)
        self.assertEqual(proxy.rollbacks, 1)


class TestBidirectionalReviewSyncAPI(unittest.TestCase):
    """Verify /api/review/* <-> video_runs and /api/tag/* <-> review_queue sync."""

    def setUp(self) -> None:
        set_shutting_down(False)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = TrackerDB(os.path.join(self._tmp.name, "tracker.db"))
        self.addCleanup(self.db.close)
        self.crops_dir = os.path.join(self._tmp.name, "crops")
        os.makedirs(self.crops_dir, exist_ok=True)
        self.al_mgr = ActiveLearningManager(self.db, crops_dir=self.crops_dir)
        self.ent_id = self.db.add_entity("Alice", category="person")
        self.other_id = self.db.add_entity("Bob", category="person")
        self.run_id = self.db.save_video_run(
            video_filename="demo.mp4",
            report={"entities": [], "unique_entities_identified": 0},
            frame_detections=[{"time": 2.0, "frame": 20, "tracks": [{"track_id": 5, "bbox": [10, 10, 30, 50]}]}],
        )["run_id"]
        fastapi_app.dependency_overrides[get_db] = lambda: self.db
        fastapi_app.dependency_overrides[get_active_learning_mgr] = lambda: self.al_mgr
        self.addCleanup(fastapi_app.dependency_overrides.clear)
        self.client = TestClient(fastapi_app)

    def test_review_confirm_and_reassign_sync_video_runs(self) -> None:
        rid = self.db.add_review_item(
            "cam_01", 5, "", suggested_entity_id=self.ent_id, suggested_name="Alice",
            similarity=0.58, video_filename="demo.mp4", media_offset_sec=2.0,
            bbox=[10, 10, 30, 50], frame_width=320, frame_height=240, run_id=self.run_id,
        )
        with patch("dashboard.routers.review.reload_all_galleries"):
            resp = self.client.post(f"/api/review/{rid}/confirm", json={"notes": "ok"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn(self.run_id, body["sync"]["synced_runs"])
        run = self.db.get_video_run(self.run_id, include_detections=True)
        self.assertEqual(run["frame_detections"][0]["tracks"][0]["entity_name"], "Alice")

        rid2 = self.db.add_review_item(
            "cam_01", 5, "", suggested_entity_id=self.ent_id,
            similarity=0.52, video_filename="demo.mp4", media_offset_sec=2.0, run_id=self.run_id,
        )
        with patch("dashboard.routers.review.reload_all_galleries"):
            resp2 = self.client.post(f"/api/review/{rid2}/reassign", json={"target_entity_id": self.other_id, "notes": "fix"})
        self.assertEqual(resp2.status_code, 200)
        run2 = self.db.get_video_run(self.run_id, include_detections=True)
        self.assertEqual(run2["frame_detections"][0]["tracks"][0]["entity_name"], "Bob")

    def test_roi_commit_and_discourage_auto_resolve_review_queue(self) -> None:
        import base64
        import cv2
        img = np.full((64, 64, 3), 180, dtype=np.uint8)
        b64 = base64.b64encode(cv2.imencode(".jpg", img)[1].tobytes()).decode("ascii")
        r1 = self.db.add_review_item(
            "cam_01", 9, "", similarity=0.55, video_filename="demo.mp4", media_offset_sec=1.5, bbox=[5, 5, 30, 40],
        )
        svc = RoiRecognitionService(self.db, crops_dir=self.crops_dir)
        out = svc.commit_roi_tag(
            entity_name="Alice", category="person", entity_id=self.ent_id,
            video_filename="demo.mp4", timestamp_sec=1.5, bbox=[5, 5, 30, 40], crop_base64=b64, track_id=9,
        )
        self.assertEqual(out["review_sync"]["resolved_review_ids"], [r1])
        self.assertEqual(self.db.get_review_item(r1)["status"], "confirmed")

        r2 = self.db.add_review_item(
            "cam_01", 10, "", similarity=0.55, video_filename="demo.mp4", media_offset_sec=3.0, bbox=[8, 8, 24, 36],
        )
        neg = NegativeExemplarService(self.db, crops_dir=self.crops_dir)
        out2 = neg.discourage_roi(
            entity_id=self.ent_id, label="Alice", video_filename="demo.mp4",
            timestamp_sec=3.0, bbox=[8, 8, 24, 36], crop_base64=b64, track_id=10,
        )
        self.assertEqual(out2["review_sync"]["resolved_review_ids"], [r2])
        self.assertEqual(self.db.get_review_item(r2)["status"], "dismissed")


class TestStep4M4FrontendContracts(unittest.TestCase):
    """Node VM tests for ReviewAndRSAC, InteractiveCanvas, and TagFeedbackActions."""

    @unittest.skipUnless(shutil.which("node"), "Node.js not available")
    def test_review_card_provenance_and_studio_sync_hooks(self) -> None:
        script = r"""
const fs = require('fs'), vm = require('vm');
const calls = { fetches: [], invalidated: [], restored: [], overlaid: [], gallery: 0, reviewLoad: 0 };
const elems = new Map();
const makeEl = (id) => ({ id, value: '', style: {}, innerHTML: '', textContent: '', addEventListener: () => {}, querySelectorAll: () => [], reset: () => {} });
['review-queue-container', 'review-inbox-counter', 'header-review-badge', 'tag-name-input', 'tag-category-select', 'tag-source-type', 'tag-video-filename', 'tag-timestamp-sec', 'tag-track-id', 'tag-bbox-val', 'tag-entity-id', 'tag-crop-base64', 'tag-notes-input'].forEach((id) => elems.set(id, makeEl(id)));
const ctx = vm.createContext({
  window: null, document: { getElementById: (id) => elems.get(id) || null, querySelectorAll: () => [], addEventListener: (ev, fn) => { if (ev === 'DOMContentLoaded') ctx._domReady = fn; } },
  fetch: async (url, opts) => { calls.fetches.push(url); return { ok: true, json: async () => ({ status: 'confirmed', items: [], sync: { video_filename: 'demo.mp4' } }) }; },
  VideoBatchReports: { invalidateCachedReports: (fn) => calls.invalidated.push(fn), getCurrentFilename: () => 'demo.mp4', restoreReportForFile: (fn) => calls.restored.push(fn) },
  OverlayLayers: { ensureLoaded: (fn) => calls.overlaid.push(fn) },
  GalleryTimeline: { loadGallery: () => { calls.gallery += 1; } },
  showToast: () => {}, setTimeout, clearTimeout,
});
ctx.window = ctx;
vm.runInContext(fs.readFileSync('dashboard/static/js/tag_feedback_actions.js', 'utf8'), ctx);
vm.runInContext(fs.readFileSync('dashboard/static/review_and_rsac.js', 'utf8'), ctx);
ctx.ReviewAndRSAC.loadQueue = async () => { calls.reviewLoad += 1; };
ctx.TagFeedbackActions.onTagCommitted({ video_filename: 'demo.mp4' }, {});
if (calls.invalidated[0] !== 'demo.mp4' || calls.restored[0] !== 'demo.mp4' || calls.overlaid[0] !== 'demo.mp4' || calls.gallery < 1 || calls.reviewLoad < 1) {
  throw new Error('Sync hooks failed: ' + JSON.stringify(calls));
}
"""
        proc = subprocess.run(["node", "-e", script], cwd=str(REPO_ROOT), capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
