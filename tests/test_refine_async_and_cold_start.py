"""Focused tests for async router offloading and StreamWorker cold-start DB isolation."""

import asyncio
import os
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from dashboard.routers import rsac as rsac_router
from dashboard.schemas import CustomCategoryCreateRequest
from dashboard.services.stream_worker import StreamWorker
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.detectors import MockDetector
from intelligent_tracker.matching.gallery import GalleryMatcher
from intelligent_tracker.pipeline import PipelineBundle, PipelineConfig
from intelligent_tracker.reid import ReIDExtractorFactory
from intelligent_tracker.tracker import CentroidTracker


def _build_worker_host(db: TrackerDB, matcher: GalleryMatcher) -> SimpleNamespace:
    """Create a minimal StreamWorker host wired to an isolated PipelineBundle."""
    bundle = PipelineBundle(
        config=PipelineConfig(camera_id="cold_cam", detector_model="mock"),
        db=db,
        detector=MockDetector(),
        tracker=CentroidTracker(),
        reid_extractor=matcher.extractor,
        gallery_matcher=matcher,
    )
    return SimpleNamespace(
        camera_id="cold_cam",
        name="Cold Cam",
        db=db,
        detector=bundle.detector,
        tracker=bundle.tracker,
        analytics=None,
        reid_extractor=bundle.reid_extractor,
        gallery_matcher=matcher,
        rsac_manager=None,
        event_bus=None,
        world_graph=None,
        world_bridge=None,
        topology=None,
        homography=SimpleNamespace(is_calibrated=False, track_to_ground=lambda _b: (0.0, 0.0)),
        overlays={},
        draw_heatmap=False,
        start_time=0.0,
        has_raw_subscribers=False,
        has_annotated_subscribers=True,
        _lock=threading.Lock(),
        _stop_event=threading.Event(),
        _latest_raw_frame=None,
        _latest_raw_jpeg=None,
        _latest_jpeg=None,
        _latest_telemetry=None,
        _pipeline_bundle=bundle,
        _overlay_renderer=SimpleNamespace(render=lambda **kw: kw["frame"]),
        _broadcast_telemetry=MagicMock(),
    )


class TestRsacAsyncOffloading(unittest.IsolatedAsyncioTestCase):
    """Verify RSAC routes offload synchronous SQLite and gallery reloads off the event loop."""

    async def test_list_active_learning_queue_runs_off_event_loop(self) -> None:
        loop_tid = threading.get_ident()
        call_tids: list[int] = []

        def _list_review_items(status: str = "pending", limit: int = 50) -> list[dict]:
            call_tids.append(threading.get_ident())
            return [{"id": 1, "status": status, "limit": limit}]

        fake_db = SimpleNamespace(list_review_items=_list_review_items)
        resp = await rsac_router.list_active_learning_queue(status="pending", limit=10, db=fake_db)
        self.assertEqual(resp["count"], 1)
        self.assertEqual(len(call_tids), 1)
        self.assertNotEqual(call_tids[0], loop_tid)

    async def test_create_category_and_reload_galleries_run_off_event_loop(self) -> None:
        loop_tid = threading.get_ident()
        call_tids: list[int] = []

        def _register_category(**_kwargs) -> SimpleNamespace:
            call_tids.append(threading.get_ident())
            return SimpleNamespace(to_dict=lambda: {"id": "badge_x", "name": "Badge X"})

        def _reload_galleries(conn=None) -> None:
            call_tids.append(threading.get_ident())

        fake_rsac = SimpleNamespace(register_category=_register_category)
        req = CustomCategoryCreateRequest(id="badge_x", name="Badge X")
        fake_http_req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
        with patch.object(rsac_router, "reload_all_galleries", side_effect=_reload_galleries):
            resp = await rsac_router.create_custom_category(req, fake_http_req, rsac=fake_rsac)
        self.assertEqual(resp["status"], "success")
        self.assertEqual(len(call_tids), 2)
        self.assertTrue(all(tid != loop_tid for tid in call_tids))


class TestStreamWorkerColdStart(unittest.TestCase):
    """Verify StreamWorker cold-start on unseeded empty DB alongside pre-seeded DB fixtures."""

    def test_stream_worker_cold_start_on_unseeded_empty_db(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        db = TrackerDB(db_path=os.path.join(tmpdir.name, "empty.db"))
        self.addCleanup(db.close)
        extractor = ReIDExtractorFactory.create("color")
        matcher = GalleryMatcher(db=db, extractor=extractor)
        host = _build_worker_host(db, matcher)
        worker = StreamWorker(host)

        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        step_res = worker._get_processor().step(frame, timestamp=1.0, max_dim=160)
        worker._process_single_frame(step_res)

        self.assertEqual(db.list_entities(), [])
        self.assertEqual(db.get_signatures(), [])
        self.assertIsNotNone(host._latest_telemetry)
        self.assertEqual(host._latest_telemetry["camera_id"], "cold_cam")
        self.assertEqual(host._latest_telemetry["frame_count"], 1)

    def test_stream_worker_warm_start_on_preseeded_db(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        db = TrackerDB(db_path=os.path.join(tmpdir.name, "seeded.db"))
        self.addCleanup(db.close)
        extractor = ReIDExtractorFactory.create("color")
        emb = extractor.extract(np.full((64, 64, 3), 120, dtype=np.uint8))
        entity_id = db.add_entity(name="Alice", category="person")
        db.add_signature(entity_id=entity_id, embedding=emb)

        matcher = GalleryMatcher(db=db, extractor=extractor)
        host = _build_worker_host(db, matcher)
        worker = StreamWorker(host)

        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        step_res = worker._get_processor().step(frame, timestamp=1.0, max_dim=160)
        worker._process_single_frame(step_res)

        self.assertEqual(len(db.list_entities()), 1)
        self.assertEqual(len(db.get_signatures()), 1)
        self.assertEqual(host._latest_telemetry["frame_count"], 1)


if __name__ == "__main__":
    unittest.main()
