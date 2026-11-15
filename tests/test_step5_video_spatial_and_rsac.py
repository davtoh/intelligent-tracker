"""Step 5 Milestone 2 tests: Spatial profile, RSAC alerts & Active Learning for offline videos."""

import os
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from dashboard import dependencies as deps
from dashboard.app import app
from dashboard.schemas import VideoAnalyzeRequest
from dashboard.services import video_analytics_service as vas
from dashboard.services import video_report_store as vrs
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.scenarios import ScenarioManager
from intelligent_tracker.tracker import Track
from intelligent_tracker.video import PipelineVideoWriter


class TestStep5VideoSpatialAndRSAC(unittest.TestCase):
    """Verify offline video analysis with scenario_camera_id, RSAC alerts, and Active Learning."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, "step5_spatial.db")
        self.db = TrackerDB(self.db_path)
        self.addCleanup(self.db.close)

        self.videos_dir = os.path.join(self._tmp.name, "videos")
        self.reports_dir = os.path.join(self._tmp.name, "reports")
        os.makedirs(self.videos_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)
        self.filename = "patrol_clip.mp4"
        self.video_path = os.path.join(self.videos_dir, self.filename)
        self._write_moving_box_video(self.video_path)

        self.scen_mgr = ScenarioManager(
            config_path=os.path.join(self._tmp.name, "scenarios.yaml"),
            db=self.db,
        )
        self.scen_mgr.save_zone(
            "cam_spatial",
            "vault_zone",
            [(10, 10), (310, 10), (310, 230), (10, 230)],
            dwell_threshold=0.0,
        )
        self.scen_mgr.save_tripwire(
            "cam_spatial",
            "door_wire",
            [(120, 10), (120, 230)],
            bidirectional=True,
        )
        self.db.set_rsac_rule(
            camera_id="cam_spatial",
            zone_id="vault_zone",
            allowed_categories=["staff"],
            denied_categories=["person", "unknown", "customer", "object", "visitor"],
            alarm_on_breach=True,
        )

    @staticmethod
    def _write_moving_box_video(path: str) -> None:
        with PipelineVideoWriter(path, fps=10.0, resolution=(320, 240)) as writer:
            for i in range(10):
                frame = np.full((240, 320, 3), 30, dtype=np.uint8)
                x0 = 40 + i * 16
                cv2.rectangle(frame, (x0, 60), (x0 + 60, 180), (0, 220, 80), -1)
                writer.write(frame)

    def test_parse_analyze_options_includes_scenario_camera_id(self) -> None:
        """parse_analyze_options normalizes scenario_camera_id from request or query."""
        req = VideoAnalyzeRequest(detector="mock", sample_rate=2, scenario_camera_id=" cam_spatial ")
        opts = vas.parse_analyze_options(1, None, None, None, None, req)
        self.assertEqual(opts["scenario_camera_id"], "cam_spatial")
        self.assertEqual(opts["detector"], "mock")

        blank_req = VideoAnalyzeRequest(detector="mock", scenario_camera_id="   ")
        opts_blank = vas.parse_analyze_options(1, None, None, None, None, blank_req)
        self.assertIsNone(opts_blank["scenario_camera_id"])

    def test_offline_analysis_computes_spatial_metrics_and_rsac_alerts(self) -> None:
        """run_sync_analytics with scenario_camera_id computes zones/tripwires and RSAC alerts."""
        opts = vas.parse_analyze_options(
            1, "mock", 0.3, None, False, VideoAnalyzeRequest(detector="mock", scenario_camera_id="cam_spatial")
        )
        with (
            patch.object(vas, "_resolve_db", return_value=self.db),
            patch.object(vas, "get_scenario_mgr", return_value=self.scen_mgr),
            patch.object(vrs, "REPORTS_DIR", self.reports_dir),
        ):
            report = vas.run_sync_analytics(self.filename, self.video_path, opts)

        self.assertEqual(report["scenario_camera_id"], "cam_spatial")
        self.assertEqual(len(report["zones"]), 1)
        self.assertEqual(len(report["tripwires"]), 1)
        self.assertIn("vault_zone", report["zone_metrics"])
        self.assertGreaterEqual(report["zone_metrics"]["vault_zone"]["total_entries"], 1)
        self.assertIn("door_wire", report["tripwire_counts"])
        self.assertTrue(len(report["alerts"]) >= 1)
        for alert in report["alerts"]:
            self.assertEqual(alert["video_filename"], self.filename)
            self.assertIn("media_offset_sec", alert)
        rsac_alerts = [a for a in report["alerts"] if a["event_type"] == "rsac_violation"]
        self.assertTrue(len(rsac_alerts) >= 1)

    def test_create_video_indexer_wires_active_learning_with_media_offset(self) -> None:
        """create_video_indexer wires ActiveLearningManager so queued items carry media offsets."""
        opts = vas.parse_analyze_options(
            1, "mock", 0.3, None, False, VideoAnalyzeRequest(detector="mock", scenario_camera_id="cam_spatial")
        )
        with patch.object(vas, "get_scenario_mgr", return_value=self.scen_mgr):
            indexer = vas.create_video_indexer(self.db, opts, safe_name=self.filename)
        try:
            frame = np.zeros((240, 320, 3), dtype=np.uint8)
            track = Track(track_id=7, bbox=(60, 60, 120, 180), centroid=(90, 120), confidence=0.8)
            eid = self.db.add_entity("Test Staff", category="staff")
            item_id = indexer.active_learning.consider_candidate(
                track=track, frame=frame, similarity=0.55,
                suggested_entity_id=eid, suggested_name="Test Staff", suggested_category="staff",
                camera_id="cam_spatial", timestamp=4.5,
                video_filename=self.filename, media_offset_sec=4.5,
            )
            self.assertIsNotNone(item_id)
            item = self.db.get_review_item(item_id)
            self.assertIsNotNone(item)
            self.assertEqual(item["video_filename"], self.filename)
            self.assertAlmostEqual(item["media_offset_sec"], 4.5, places=2)
        finally:
            vas._teardown_indexer_bus(indexer)

    def test_analyze_endpoint_persists_spatial_report_via_test_client(self) -> None:
        """POST /api/videos/{filename}/analyze accepts scenario_camera_id and persists spatial report."""
        from dashboard.routers import video_jobs as vj_router

        with (
            patch.object(vj_router, "VIDEOS_DIR", self.videos_dir),
            patch.object(vas, "_resolve_db", return_value=self.db),
            patch.object(vas, "get_scenario_mgr", return_value=self.scen_mgr),
            patch.object(vrs, "REPORTS_DIR", self.reports_dir),
            patch.object(deps, "_db", self.db),
        ):
            client = TestClient(app)
            resp = client.post(
                f"/api/videos/{self.filename}/analyze",
                json={"detector": "mock", "sample_rate": 1, "scenario_camera_id": "cam_spatial", "async_mode": False},
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "success")
        rep = body["report"]
        self.assertEqual(rep["scenario_camera_id"], "cam_spatial")
        self.assertIn("vault_zone", rep["zone_metrics"])
        self.assertIn("door_wire", rep["tripwire_counts"])
        self.assertTrue(any(a["video_filename"] == self.filename for a in rep["alerts"]))

    def test_frontend_spatial_controls_and_studio_wiring(self) -> None:
        """HTML modal, video_batch.js, and studio.js expose scenario profile selectors."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "dashboard/static/partials/modals/video_modals.html"), encoding="utf-8") as f:
            modal_html = f.read()
        with open(os.path.join(root, "dashboard/static/js/video_batch.js"), encoding="utf-8") as f:
            batch_js = f.read()
        with open(os.path.join(root, "dashboard/static/studio.js"), encoding="utf-8") as f:
            studio_js = f.read()

        self.assertIn("batch-scenario-select", modal_html)
        self.assertIn("batch-scenario-select", batch_js)
        self.assertIn("scenario_camera_id", batch_js)
        self.assertIn("studio-camera-select", studio_js)
        self.assertIn("/api/videos", studio_js)


if __name__ == "__main__":
    unittest.main()
