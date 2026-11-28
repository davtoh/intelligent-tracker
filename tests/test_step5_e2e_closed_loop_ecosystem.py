"""Step 5 Milestone 4 E2E tests: Closed-loop video ecosystem & fallback branches."""

import os
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from dashboard import dependencies as deps
from dashboard.app import app
from dashboard.routers import analytics as analytics_router
from dashboard.schemas import VideoAnalyzeRequest
from dashboard.services import video_analytics_service as vas
from dashboard.services import video_report_store as vrs
from intelligent_tracker.active_learning import ActiveLearningManager
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.detectors.mock_detector import MockDetector
from intelligent_tracker.events import EventBus, RSACViolationEvent
from intelligent_tracker.reid import ReIDExtractorFactory
from intelligent_tracker.scenarios import ScenarioManager
from intelligent_tracker.tracker import Track
from intelligent_tracker.video import PipelineVideoWriter


class TestStep5E2EClosedLoopEcosystem(unittest.TestCase):
    """End-to-end verification of offline video indexing, API parity, and fallbacks."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = TrackerDB(os.path.join(self._tmp.name, "e2e_step5.db"))
        self.addCleanup(self.db.close)
        self.reports_dir = os.path.join(self._tmp.name, "reports")
        self.crops_dir = os.path.join(self._tmp.name, "crops")
        os.makedirs(self.reports_dir, exist_ok=True)
        os.makedirs(self.crops_dir, exist_ok=True)
        self.filename = "patrol_e2e.mp4"
        self.video_path = os.path.join(self._tmp.name, self.filename)
        self.empty_video_path = os.path.join(self._tmp.name, "empty_e2e.mp4")
        self._write_moving_box_video(self.video_path)
        self._write_blank_video(self.empty_video_path)
        self.scen_mgr = self._setup_spatial_profile()

    def _setup_spatial_profile(self) -> ScenarioManager:
        mgr = ScenarioManager(
            config_path=os.path.join(self._tmp.name, "scenarios.yaml"),
            db=self.db,
        )
        mgr.save_zone(
            "cam_e2e", "vault_zone",
            [(10, 10), (310, 10), (310, 230), (10, 230)], dwell_threshold=0.0,
        )
        mgr.save_tripwire(
            "cam_e2e", "door_wire", [(120, 10), (120, 230)], bidirectional=True,
        )
        self.db.set_rsac_rule(
            camera_id="cam_e2e", zone_id="vault_zone",
            allowed_categories=["staff"],
            denied_categories=["person", "unknown", "customer", "object", "visitor"],
            alarm_on_breach=True,
        )
        return mgr

    @staticmethod
    def _write_moving_box_video(path: str) -> None:
        with PipelineVideoWriter(path, fps=10.0, resolution=(320, 240)) as writer:
            for i in range(10):
                frame = np.full((240, 320, 3), 30, dtype=np.uint8)
                x0 = 40 + i * 16
                cv2.rectangle(frame, (x0, 60), (x0 + 60, 180), (0, 220, 80), -1)
                writer.write(frame)

    @staticmethod
    def _write_blank_video(path: str) -> None:
        with PipelineVideoWriter(path, fps=10.0, resolution=(320, 240)) as writer:
            for _ in range(6):
                writer.write(np.zeros((240, 320, 3), dtype=np.uint8))

    def _enroll_green_person(self) -> int:
        ref = np.full((240, 320, 3), 30, dtype=np.uint8)
        cv2.rectangle(ref, (40, 60), (100, 180), (0, 220, 80), -1)
        extractor = ReIDExtractorFactory.create("color")
        res = self.db.enroll_entity(
            name="E2E Intruder", category="person", frame=ref,
            bbox=(40, 60, 60, 120), extractor=extractor,
        )
        return int(res["id"]) if isinstance(res, dict) else int(res)

    def _run_analytics(
        self, filename: str, path: str, cam_id: str | None, classes: list[int] | None = None,
    ) -> dict:
        opts = vas.parse_analyze_options(
            1, "mock", 0.95, None, False,
            VideoAnalyzeRequest(
                detector="mock", sample_rate=1, confidence=0.95, classes=classes, scenario_camera_id=cam_id,
            ),
        )
        with (
            patch.object(vas, "_resolve_db", return_value=self.db),
            patch.object(vas, "get_scenario_mgr", return_value=self.scen_mgr),
            patch.object(vrs, "REPORTS_DIR", self.reports_dir),
        ):
            return vas.run_sync_analytics(filename, path, opts)

    def test_e2e_offline_indexing_persists_sightings_alerts_and_journey(self) -> None:
        """Offline indexing via FrameProcessor.step() persists sightings, alerts, and journey."""
        eid = self._enroll_green_person()
        report = self._run_analytics(self.filename, self.video_path, "cam_e2e")
        self.assertEqual(report["scenario_camera_id"], "cam_e2e")
        self.assertIn("vault_zone", report["zone_metrics"])
        self.assertIn("door_wire", report["tripwire_counts"])
        self.assertTrue(any(a["video_filename"] == self.filename for a in report["alerts"]))

        sightings = self.db.get_sightings(entity_id=eid, limit=20)
        self.assertGreater(len(sightings), 0)
        self.assertTrue(all(s["video_filename"] == self.filename for s in sightings))
        self.assertTrue(all(s["media_offset_sec"] is not None for s in sightings))

    def test_e2e_api_parity_sightings_events_review_and_journey(self) -> None:
        """All 4 API endpoints expose video_filename and media_offset_sec consistently."""
        eid = self._enroll_green_person()
        self._run_analytics(self.filename, self.video_path, "cam_e2e")
        al = ActiveLearningManager(db=self.db, crops_dir=self.crops_dir)
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        al.consider_candidate(
            track=Track(track_id=11, bbox=(40, 60, 60, 120), centroid=(70, 120), confidence=0.8),
            frame=frame, similarity=0.55, suggested_entity_id=eid,
            suggested_name="E2E Intruder", suggested_category="person",
            camera_id="cam_e2e", timestamp=1.5, video_filename=self.filename, media_offset_sec=1.5,
        )
        bus = EventBus(capacity=50)
        bus.start()
        self.addCleanup(bus.stop)
        bus.publish(RSACViolationEvent(
            camera_id="cam_e2e", zone_id="vault_zone", entity_id=eid,
            entity_name="E2E Intruder", entity_category="person",
            timestamp=time.time() + 1.0,
            metadata={"video_filename": self.filename, "media_offset_sec": 0.4},
        ))
        bus.wait_until_empty(timeout=2.0)
        stub_mgr = SimpleNamespace(db=self.db, event_bus=bus)
        with (
            patch.object(analytics_router, "get_active_stream_manager", return_value=stub_mgr),
            patch.object(deps, "_db", self.db),
        ):
            client = TestClient(app)
            self._assert_four_endpoints(client, eid)

    def _assert_four_endpoints(self, client: TestClient, eid: int) -> None:
        sg = client.get(f"/sightings?entity_id={eid}").json()
        self.assertGreater(len(sg), 0)
        self.assertEqual(sg[0]["video_filename"], self.filename)
        self.assertIsNotNone(sg[0]["media_offset_sec"])

        ev = client.get("/events?limit=10").json()
        self.assertGreater(len(ev), 0)
        self.assertEqual(ev[0]["video_filename"], self.filename)
        self.assertIsNotNone(ev[0]["media_offset_sec"])

        q = client.get("/api/active-learning/queue?status=pending").json()
        self.assertGreaterEqual(q["count"], 1)
        self.assertEqual(q["items"][0]["video_filename"], self.filename)
        self.assertAlmostEqual(float(q["items"][0]["media_offset_sec"]), 1.5, places=2)

        j = client.get(f"/api/journey/search?entity_id={eid}").json()
        self.assertGreater(len(j["hops"]), 0)
        self.assertEqual(j["hops"][0]["video_filename"], self.filename)
        self.assertIsNotNone(j["hops"][0]["media_offset_sec"])

    def test_fallback_scenario_none_and_missing_profile(self) -> None:
        """Fallback branches with scenario_camera_id=None or unknown profile run cleanly."""
        rep_none = self._run_analytics(self.filename, self.video_path, None)
        self.assertIsNone(rep_none["scenario_camera_id"])
        self.assertEqual(rep_none["zones"], [])
        self.assertEqual(rep_none["tripwires"], [])

        rep_missing = self._run_analytics(self.filename, self.video_path, "missing_cam")
        self.assertEqual(rep_missing["scenario_camera_id"], "missing_cam")
        self.assertEqual(rep_missing["zones"], [])
        self.assertEqual(rep_missing["tripwires"], [])

    def test_fallback_empty_detections_blank_video(self) -> None:
        """Empty detector output produces zero detections, zero alerts, and zero sightings."""
        eid = self._enroll_green_person()
        opts = vas.parse_analyze_options(
            1, "mock", 0.2, None, False,
            VideoAnalyzeRequest(detector="mock", sample_rate=1, scenario_camera_id="cam_e2e"),
        )
        with (
            patch.object(vas, "get_scenario_mgr", return_value=self.scen_mgr),
            patch.object(vrs, "REPORTS_DIR", self.reports_dir),
        ):
            indexer = vas.create_video_indexer(self.db, opts, safe_name="empty_e2e.mp4")
            try:
                indexer.detector = MockDetector(boxes=[])
                summary = indexer.process_video(self.empty_video_path, verbose=False)
                rep = vas.finalize_analytics_report(indexer, summary, "empty_e2e.mp4", opts)
            finally:
                vas._teardown_indexer_bus(indexer)
        self.assertEqual(rep["execution_summary"]["processed_frames"], 6)
        self.assertEqual(rep["total_detections"], 0)
        self.assertEqual(rep["alerts"], [])
        self.assertEqual(self.db.get_sightings(entity_id=eid, limit=10), [])


if __name__ == "__main__":
    unittest.main()
