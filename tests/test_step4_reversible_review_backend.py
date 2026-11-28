"""Backend unit tests for Step 4 M1: Schema v5 & Reversible Review Audit."""

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
from fastapi.testclient import TestClient

from dashboard.app import app as fastapi_app
from dashboard.dependencies import get_active_learning_mgr, get_db, set_shutting_down
from intelligent_tracker.active_learning import ActiveLearningManager
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.memory.confidence import ConfidenceEngine


class _FailingCursor:
    """Proxy cursor that raises sqlite3.Error on execute."""

    def execute(self, *_args: object, **_kwargs: object) -> None:
        raise sqlite3.Error("injected failure")

    def close(self) -> None:
        return None


class _ConnProxy:
    """SQLite connection proxy counting rollback invocations."""

    def __init__(self, real: sqlite3.Connection, *, fail_execute: bool = False) -> None:
        self._real = real
        self._fail_execute = fail_execute
        self.rollbacks = 0

    def cursor(self) -> object:
        return _FailingCursor() if self._fail_execute else self._real.cursor()

    def rollback(self) -> None:
        self.rollbacks += 1
        self._real.rollback()

    def __getattr__(self, name: str) -> object:
        return getattr(self._real, name)


class TestReviewSchemaV5AndRepo(unittest.TestCase):
    """Verify schema v5 migration, ReviewDecisionMixin, and rollback invariants."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, "tracker.db")
        self.db = TrackerDB(self.db_path)
        self.addCleanup(self.db.close)

    def test_schema_v5_idempotent_upgrade(self) -> None:
        ver = self.db._conn.execute("PRAGMA user_version;").fetchone()[0]
        self.assertGreaterEqual(ver, 5)
        cols = {r[1] for r in self.db._conn.execute("PRAGMA table_info(review_decisions);").fetchall()}
        for col in ("review_id", "action", "prior_status", "created_signature_id", "prior_state_json", "undone"):
            self.assertIn(col, cols)
        # Simulate v4 DB and re-run _init_schema idempotently
        self.db._conn.execute("PRAGMA user_version = 4;")
        self.db._conn.commit()
        self.db._init_schema()
        self.assertGreaterEqual(self.db._conn.execute("PRAGMA user_version;").fetchone()[0], 5)

    def test_repo_crud_and_rollback_on_sqlite_error(self) -> None:
        eid1 = self.db.add_entity("Alice", category="person")
        eid2 = self.db.add_entity("Bob", category="person")
        sig_id = self.db.add_signature(eid1, np.ones(16, dtype=np.float32))
        ver_id = self.db.record_descriptor_version(eid1, embedding=np.ones(16, dtype=np.float32))
        s1 = self.db.add_sighting(eid1, track_id=7, source="clip.mp4", camera_id="cam_01", run_id="r1", video_filename="clip.mp4")
        s2 = self.db.add_sighting(eid1, track_id=7, source="clip.mp4", camera_id="cam_01", run_id="r1", video_filename="clip.mp4")
        rid = self.db.add_review_item("cam_01", 7, "", suggested_entity_id=eid1, similarity=0.55)

        did = self.db.record_review_decision(
            rid, "confirm", prior_status="pending", prior_entity_id=eid1, new_entity_id=eid1,
            created_signature_id=sig_id, created_descriptor_version_id=ver_id, created_sighting_id=s1,
            prior_state={"camera_id": "cam_01", "track_id": 7}, notes="verified",
        )
        rec = self.db.get_review_decision(did)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["prior_state"]["camera_id"], "cam_01")
        self.assertFalse(rec["undone"])
        self.assertEqual(self.db.get_latest_decision_for_review(rid)["id"], did)

        moved = self.db.reassign_sightings_by_provenance(
            from_entity_id=eid1, to_entity_id=eid2, camera_id="cam_01", run_id="r1", track_id=7,
        )
        self.assertEqual(moved, 2)
        self.assertTrue(self.db.delete_sighting_by_id(s1))
        self.assertTrue(self.db.prune_descriptor_version(ver_id))
        self.assertTrue(self.db.delete_signature(sig_id))
        self.assertTrue(self.db.mark_decision_undone(did, undone_by="admin"))
        self.assertIsNone(self.db.get_latest_decision_for_review(rid, include_undone=False))
        self.assertEqual(len(self.db.list_review_decisions(review_id=rid, include_undone=True)), 1)
        self.assertIsNotNone(self.db.get_sightings(entity_id=eid2))
        self.assertEqual(len(self.db.get_sightings(entity_id=eid2)), 1)
        self.assertEqual(self.db.get_sightings(entity_id=eid2)[0]["id"], s2)

    def test_repo_write_rollback_on_sqlite_error(self) -> None:
        eid1 = self.db.add_entity("Alice", category="person")
        eid2 = self.db.add_entity("Bob", category="person")
        rid = self.db.add_review_item("cam_01", 7, "", suggested_entity_id=eid1, similarity=0.55)
        proxy = _ConnProxy(self.db._conn, fail_execute=True)
        with patch.object(self.db, "_conn", proxy):
            for fn in (
                lambda: self.db.record_review_decision(rid, "confirm"),
                lambda: self.db.mark_decision_undone(1),
                lambda: self.db.delete_sighting_by_id(1),
                lambda: self.db.reassign_sightings_by_provenance(from_entity_id=eid2, to_entity_id=eid1),
                lambda: self.db.prune_descriptor_version(1),
                lambda: self.db.delete_signature(1),
            ):
                with self.assertRaises(sqlite3.Error):
                    fn()
        self.assertEqual(proxy.rollbacks, 6)


class TestConfidenceReversal(unittest.TestCase):
    """Verify ConfidenceEngine.revert_human_feedback restores counters cleanly."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = TrackerDB(os.path.join(self._tmp.name, "tracker.db"))
        self.addCleanup(self.db.close)
        self.engine = ConfidenceEngine(db=self.db)
        self.alice = self.db.add_entity("Alice", category="person")
        self.bob = self.db.add_entity("Bob", category="person")

    def test_revert_confirm_dismiss_and_reassign(self) -> None:
        self.engine.record_human_feedback(self.alice, "confirm", camera_id="cam_01", timestamp=1000.0)
        self.assertEqual(self.engine.get_state(self.alice, timestamp=1000.0).confirmation_count, 1)
        self.engine.revert_human_feedback(self.alice, "confirm", camera_id="cam_01", timestamp=1001.0)
        self.assertEqual(self.engine.get_state(self.alice, timestamp=1001.0).confirmation_count, 0)

        self.engine.record_human_feedback(self.alice, "dismiss", camera_id="cam_01", timestamp=1002.0)
        st_rej = self.engine.get_state(self.alice, timestamp=1002.0)
        self.assertEqual(st_rej.rejection_count, 1)
        self.assertGreater(st_rej.ambiguity_penalty, 0.0)
        self.engine.revert_human_feedback(self.alice, "dismiss", camera_id="cam_01", timestamp=1003.0)
        st_undo = self.engine.get_state(self.alice, timestamp=1003.0)
        self.assertEqual(st_undo.rejection_count, 0)
        self.assertAlmostEqual(st_undo.ambiguity_penalty, 0.0)

        self.engine.record_human_feedback(self.bob, "reassign", previous_entity_id=self.alice, timestamp=1004.0)
        self.assertEqual(self.engine.get_state(self.bob, timestamp=1004.0).confirmation_count, 1)
        self.assertEqual(self.engine.get_state(self.alice, timestamp=1004.0).rejection_count, 1)
        self.engine.revert_human_feedback(self.bob, "reassign", previous_entity_id=self.alice, timestamp=1005.0)
        self.assertEqual(self.engine.get_state(self.bob, timestamp=1005.0).confirmation_count, 0)
        self.assertEqual(self.engine.get_state(self.alice, timestamp=1005.0).rejection_count, 0)


class TestReversibleReviewAPI(unittest.TestCase):
    """End-to-end confirm/reassign/enroll-new/dismiss -> /undo restoration tests."""

    def setUp(self) -> None:
        set_shutting_down(False)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = TrackerDB(os.path.join(self._tmp.name, "tracker.db"))
        self.addCleanup(self.db.close)
        self.conf = ConfidenceEngine(db=self.db)
        self.al_mgr = ActiveLearningManager(self.db, crops_dir=self._tmp.name, confidence_engine=self.conf)
        self.alice = self.db.add_entity("Alice", category="person")
        self.bob = self.db.add_entity("Bob", category="person")
        self.run_id = self.db.save_video_run(
            video_filename="demo.mp4",
            report={"entities": [], "unique_entities_identified": 0},
            frame_detections=[{"time": 2.0, "frame": 20, "tracks": [{"track_id": 5, "bbox": [10, 10, 30, 50]}]}],
        )["run_id"]
        fastapi_app.dependency_overrides[get_db] = lambda: self.db
        fastapi_app.dependency_overrides[get_active_learning_mgr] = lambda: self.al_mgr
        self.addCleanup(fastapi_app.dependency_overrides.clear)
        self.client = TestClient(fastapi_app)

    def _add_item(self, suggested_id: int | None = None, name: str = "Alice") -> int:
        return self.db.add_review_item(
            "cam_01", 5, "", suggested_entity_id=suggested_id, suggested_name=name,
            similarity=0.58, video_filename="demo.mp4", media_offset_sec=2.0,
            bbox=[10, 10, 30, 50], frame_width=320, frame_height=240, run_id=self.run_id,
        )

    def test_confirm_and_undo_by_decision_id(self) -> None:
        rid = self._add_item(self.alice, "Alice")
        reload_mock = MagicMock()
        with patch("dashboard.routers.review.reload_all_galleries", reload_mock):
            resp = self.client.post(f"/api/review/{rid}/confirm", json={"notes": "looks right"})
            self.assertEqual(resp.status_code, 200)
            did = resp.json()["decision_id"]
            self.assertIsNotNone(did)
            sightings = self.db.get_sightings(entity_id=self.alice)
            self.assertEqual(len(sightings), 1)
            self.assertEqual(sightings[0]["camera_id"], "cam_01")
            self.assertEqual(sightings[0]["run_id"], self.run_id)
            self.assertEqual(len(self.db.get_signatures(entity_id=self.alice)), 1)

            undo = self.client.post(f"/api/review/decisions/{did}/undo", json={"reviewer": "qa"})
            self.assertEqual(undo.status_code, 200)
            body = undo.json()
            self.assertEqual(body["status"], "undone")
            self.assertTrue(body["reverted"]["signature"])
            self.assertTrue(body["reverted"]["sighting"])
            self.assertTrue(body["reverted"]["descriptor_version"])
            self.assertEqual(self.db.get_review_item(rid)["status"], "pending")
            self.assertEqual(len(self.db.get_signatures(entity_id=self.alice)), 0)
            self.assertEqual(len(self.db.get_sightings(entity_id=self.alice)), 0)
            run = self.db.get_video_run(self.run_id, include_detections=True)
            self.assertIsNone(run["frame_detections"][0]["tracks"][0]["entity_id"])
            self.assertEqual(self.conf.get_state(self.alice).confirmation_count, 0)
            self.assertEqual(reload_mock.call_count, 2)

            # Second undo returns 409
            dup = self.client.post(f"/api/review/decisions/{did}/undo")
            self.assertEqual(dup.status_code, 409)

    def test_reassign_enroll_new_and_dismiss_undo(self) -> None:
        rid1 = self._add_item(self.alice, "Alice")
        with patch("dashboard.routers.review.reload_all_galleries"):
            r1 = self.client.post(f"/api/review/{rid1}/reassign", json={"target_entity_id": self.bob, "notes": "bob"})
            self.assertEqual(r1.status_code, 200)
            u1 = self.client.post(f"/api/review/{rid1}/undo")
            self.assertEqual(u1.status_code, 200)
            self.assertEqual(self.db.get_review_item(rid1)["status"], "pending")
            self.assertEqual(len(self.db.get_signatures(entity_id=self.bob)), 0)
            run1 = self.db.get_video_run(self.run_id, include_detections=True)
            self.assertEqual(run1["frame_detections"][0]["tracks"][0]["entity_id"], self.alice)

            rid2 = self._add_item(None, "")
            r2 = self.client.post(f"/api/review/{rid2}/enroll-new", json={"name": "Charlie", "category": "person"})
            self.assertEqual(r2.status_code, 200)
            new_eid = r2.json()["entity_id"]
            self.assertIsNotNone(self.db.get_entity(new_eid))
            u2 = self.client.post(f"/api/review/decisions/{r2.json()['decision_id']}/undo")
            self.assertEqual(u2.status_code, 200)
            self.assertTrue(u2.json()["reverted"]["created_entity"])
            self.assertIsNone(self.db.get_entity(new_eid))

            rid3 = self._add_item(self.alice, "Alice")
            r3 = self.client.post(f"/api/review/{rid3}/dismiss", json={"notes": "blurry"})
            self.assertEqual(r3.status_code, 200)
            decs = self.client.get(f"/api/review/decisions?review_id={rid3}").json()
            self.assertEqual(decs["count"], 1)
            u3 = self.client.post(f"/api/review/{rid3}/undo")
            self.assertEqual(u3.status_code, 200)
            self.assertEqual(self.db.get_review_item(rid3)["status"], "pending")
            self.assertEqual(self.conf.get_state(self.alice).rejection_count, 0)


if __name__ == "__main__":
    unittest.main()
