"""Backend unit & router tests for Step 3 Milestone 4: Learned Classes & COCO Overrides."""

import base64
import os
import tempfile
import types
import unittest

import cv2
import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard.routers.learned_classes import router as learned_classes_router
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.matching.learned_class_matcher import LearnedClassMatcher
from intelligent_tracker.pipeline.bundle import PipelineBundle
from intelligent_tracker.pipeline.config import PipelineConfig
from intelligent_tracker.pipeline.frame_processor import FrameProcessor


class _FailingConnProxy:
    """Proxy around sqlite3.Connection that raises on execute and tracks rollback calls."""

    def __init__(self, real_conn):
        self._real = real_conn
        self.rollback_called = 0

    def cursor(self):
        return self

    def execute(self, *_args, **_kwargs):
        raise RuntimeError("simulated sqlite write failure")

    def rollback(self):
        self.rollback_called += 1
        return self._real.rollback()

    def close(self):
        return None


class _FixedExtractor:
    """Deterministic unit-vector extractor for matcher and router tests."""

    def __init__(self, vec: np.ndarray):
        self._vec = np.asarray(vec, dtype=np.float32)

    def extract(self, _crop: np.ndarray) -> np.ndarray:
        return self._vec.copy()


def _make_jpeg_b64() -> str:
    img = np.full((32, 32, 3), 120, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")


class TestLearnedClassesBackend(unittest.TestCase):
    """Covers schema v4, repo rollback, LearnedClassMatcher, FrameProcessor, and FastAPI router."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, "test_m4.db")
        self.db = TrackerDB(self.db_path)
        self.addCleanup(self.db.close)

    def test_schema_v4_idempotency(self) -> None:
        ver = self.db._conn.execute("PRAGMA user_version;").fetchone()[0]
        self.assertGreaterEqual(ver, 4)
        db2 = TrackerDB(self.db_path)
        self.addCleanup(db2.close)
        ver2 = db2._conn.execute("PRAGMA user_version;").fetchone()[0]
        self.assertEqual(ver2, ver)
        self.assertEqual(db2.list_learned_classes(), [])

    def test_repository_write_calls_rollback_on_error(self) -> None:
        real_conn = self.db._conn
        proxy = _FailingConnProxy(real_conn)
        self.db._conn = proxy
        try:
            with self.assertRaises(RuntimeError):
                self.db.create_learned_class("Delivery Box")
            self.assertGreaterEqual(proxy.rollback_called, 1)
        finally:
            self.db._conn = real_conn

    def test_matcher_prototype_scoring_and_collision_detection(self) -> None:
        lc_a = self.db.create_learned_class("Delivery Box", parent_coco_class="suitcase", threshold=0.65)
        vec_a = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        self.db.add_learned_class_exemplar(lc_a["id"], vec_a, crop_path="/crops/a.jpg")
        ent_id = self.db.add_entity("Alice", category="staff")
        self.db.add_signature(ent_id, np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32))

        matcher = LearnedClassMatcher(self.db, extractor=_FixedExtractor(vec_a), camera_id="cam_1")
        hit = matcher.score_embedding(vec_a, parent_coco_class="suitcase")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["name"], "Delivery Box")
        self.assertIsNone(matcher.score_embedding(vec_a, parent_coco_class="person"))

        col_lc = matcher.check_collision(vec_a, threshold=0.78)
        self.assertTrue(any(c["kind"] == "learned_class" and c["name"] == "Delivery Box" for c in col_lc))
        col_ent = matcher.check_collision(np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32), threshold=0.78)
        self.assertTrue(any(c["kind"] == "entity" and c["name"] == "Alice" for c in col_ent))

    def test_frame_processor_applies_camera_coco_suppress_and_relabel(self) -> None:
        self.db.set_camera_class_override("cam_front", "chair", action="suppress")
        self.db.set_camera_class_override("cam_front", "backpack", action="relabel", relabel_to="delivery_bag")
        lc_matcher = LearnedClassMatcher(self.db, extractor=None, camera_id="cam_front")

        class _StubDetector:
            def detect(self, _frame):
                return [
                    types.SimpleNamespace(bbox=(5, 5, 20, 20), class_name="chair", confidence=0.9),
                    types.SimpleNamespace(bbox=(30, 30, 25, 25), class_name="backpack", confidence=0.85),
                ]

        cfg = PipelineConfig(camera_id="cam_front", source="mock")
        bundle = PipelineBundle(config=cfg, db=self.db, detector=_StubDetector(), learned_class_matcher=lc_matcher)
        proc = FrameProcessor(bundle)
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        dets = proc._run_detector(frame)
        self.assertEqual(len(dets), 1)
        self.assertEqual(dets[0].class_name, "delivery_bag")

    def test_fastapi_learned_classes_and_overrides_crud(self) -> None:
        app = FastAPI()
        app.include_router(learned_classes_router)
        app.state.db = self.db
        app.state.camera_pool = None
        client = TestClient(app)

        res = client.post("/api/classes/learned", json={"name": "Forklift", "threshold": 0.65})
        self.assertEqual(res.status_code, 201)
        cid = res.json()["id"]

        listed = client.get("/api/classes/learned")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 1)

        upd = client.put(f"/api/classes/learned/{cid}", json={"threshold": 0.72})
        self.assertEqual(upd.status_code, 200)
        self.assertAlmostEqual(upd.json()["threshold"], 0.72)

        enr = client.post(f"/api/classes/learned/{cid}/exemplars", json={"crop_base64": _make_jpeg_b64()})
        self.assertEqual(enr.status_code, 200)
        self.assertTrue(enr.json()["enrolled"])

        ov_put = client.put("/api/classes/overrides/cam_0", json={"coco_class": "potted plant", "action": "suppress"})
        self.assertEqual(ov_put.status_code, 200)
        ov_get = client.get("/api/classes/overrides/cam_0")
        self.assertEqual(len(ov_get.json()), 1)
        ov_del = client.delete("/api/classes/overrides/cam_0/potted plant")
        self.assertEqual(ov_del.status_code, 200)

        del_res = client.delete(f"/api/classes/learned/{cid}")
        self.assertEqual(del_res.status_code, 200)


if __name__ == "__main__":
    unittest.main()
