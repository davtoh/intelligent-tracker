"""Unit and API tests for Step 3 Milestone 1: ProcessingModeService, Router & StreamTelemetry."""

from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from dashboard import app as app_module
from dashboard.dependencies import get_camera_pool
from dashboard.schemas import CameraRecordStatusResponse
from dashboard.services import processing_mode_service as pms_mod
from dashboard.services import stream_telemetry, stream_worker


class _FakeHomography:
    is_calibrated = True

    def track_to_ground(self, bbox):
        return (1.25, 2.5)


def _make_fake_manager():
    trk = SimpleNamespace(
        bbox=[10, 20, 30, 40],
        centroid=(20.0, 30.0),
        velocity=(1.0, -0.5),
        label="person",
        confidence=0.91,
        dwell_time=3.2,
        entity_name="Alice",
        category="person",
        is_cluttered=False,
        clutter_partner_id=None,
        state="active",
    )
    bus = MagicMock()
    bus.get_recent_events.return_value = [SimpleNamespace(event_type="zone_enter")]
    mgr = SimpleNamespace(
        camera_id="cam_01",
        homography=_FakeHomography(),
        overlays={"boxes": True},
        analytics=None,
        event_bus=bus,
        cfg={"detector": {"model": "mock"}},
        detector=SimpleNamespace(name="mock"),
        get_recording_status=lambda: {"is_recording": False},
    )
    return mgr, {1: trk}


class TestStreamTelemetryExtraction(unittest.TestCase):
    """Verify stream_telemetry extraction and StreamWorker backward-compatible re-exports."""

    def test_stream_worker_reexports_telemetry_helpers(self):
        self.assertIs(stream_worker._extract_recent_alerts, stream_telemetry._extract_recent_alerts)
        self.assertIs(stream_worker._extract_track_telemetry, stream_telemetry._extract_track_telemetry)
        self.assertIs(stream_worker._build_zones_data, stream_telemetry._build_zones_data)
        self.assertIs(stream_worker._build_tripwires_data, stream_telemetry._build_tripwires_data)
        self.assertIs(stream_worker._resolve_detector_telemetry, stream_telemetry._resolve_detector_telemetry)
        self.assertIs(stream_worker.build_stream_telemetry, stream_telemetry.build_stream_telemetry)

    def test_build_stream_telemetry_payload_shape(self):
        mgr, tracks = _make_fake_manager()
        payload = stream_telemetry.build_stream_telemetry(
            mgr, tracks, curr_t=100.0, measured_fps=24.55, shape=(480, 640, 3), frame_count=12
        )
        self.assertEqual(payload["camera_id"], "cam_01")
        self.assertEqual(payload["fps"], 24.6)
        self.assertEqual(payload["resolution"], "640x480")
        self.assertEqual(payload["detector_model"], "mock")
        self.assertEqual(payload["detector_status"], "simulation")
        self.assertEqual(len(payload["active_tracks"]), 1)
        self.assertEqual(payload["recent_alerts"], [{"event_type": "zone_enter"}])


class TestProcessingModeService(unittest.TestCase):
    """Verify ProcessingModeService policy transitions across modes, tabs, and pools."""

    def test_focus_only_hibernates_unfocused_and_gates_tabs(self):
        svc = pms_mod.ProcessingModeService(mode="focus_only", focused_camera_id="cam_01", active_tab="live")
        self.assertFalse(svc.should_hibernate_camera("cam_01", subscriber_count=1))
        self.assertTrue(svc.should_hibernate_camera("cam_02", subscriber_count=1))
        self.assertFalse(svc.should_hibernate_camera("cam_02", subscriber_count=0, is_recording=True))
        self.assertTrue(svc.should_run_vision_step("cam_01"))
        self.assertFalse(svc.should_run_vision_step("cam_02"))
        svc.update(active_tab="videos")
        self.assertFalse(svc.should_run_vision_step("cam_01"))
        self.assertTrue(svc.should_run_vision_step("cam_01", is_recording=True))

    def test_full_realtime_capture_only_and_paused_policies(self):
        svc = pms_mod.ProcessingModeService(mode="full_realtime", focused_camera_id="cam_01", active_tab="studio")
        self.assertFalse(svc.should_hibernate_camera("cam_02", subscriber_count=0, in_camera_pool=True))
        self.assertTrue(svc.should_run_vision_step("cam_02"))

        svc.update(mode="capture_only")
        self.assertFalse(svc.should_run_vision_step("cam_01", is_recording=True))
        self.assertTrue(svc.should_hibernate_camera("cam_01", subscriber_count=0))

        svc.update(mode="paused")
        self.assertTrue(svc.should_hibernate_camera("cam_01", subscriber_count=2))
        self.assertFalse(svc.should_hibernate_camera("cam_01", subscriber_count=0, is_recording=True))
        self.assertFalse(svc.should_run_vision_step("cam_01"))

    def test_invalid_mode_raises_value_error(self):
        svc = pms_mod.ProcessingModeService()
        with self.assertRaises(ValueError):
            svc.update(mode="turbo_unknown")

    def test_apply_to_pool_resumes_hibernating_camera_and_enqueues_deferred(self):
        svc = pms_mod.ProcessingModeService(mode="full_realtime")
        vs = MagicMock()
        sm = SimpleNamespace(
            is_running=True, _is_hibernating=True, is_recording=False, subscriber_count=0, video_source=vs
        )
        pool = SimpleNamespace(streams={"cam_01": sm})
        states = svc.apply_to_pool(pool)
        self.assertFalse(sm._is_hibernating)
        vs.resume.assert_called_once()
        self.assertFalse(states["cam_01"]["should_hibernate"])

        fake_job = SimpleNamespace(job_id="job_123", status="queued")
        with patch.object(pms_mod, "submit_async_analytics_job", return_value=fake_job):
            entry = svc.enqueue_deferred_indexing("rec.mp4", camera_id="cam_01", recording_id="r1", job_mgr=MagicMock())
        self.assertEqual(entry["job_id"], "job_123")
        self.assertEqual(len(svc.get_state()["deferred_jobs"]), 1)


class TestProcessingModeRouterAPI(unittest.TestCase):
    """Verify GET and POST /api/system/processing-mode endpoints and schema parity."""

    @classmethod
    def setUpClass(cls):
        cls.prev_service = pms_mod._service_instance
        pms_mod._service_instance = pms_mod.ProcessingModeService()
        cls.fake_pool = SimpleNamespace(
            streams={
                "cam_01": SimpleNamespace(is_running=True, _is_hibernating=False, is_recording=False, subscriber_count=1),
                "cam_02": SimpleNamespace(is_running=True, _is_hibernating=True, is_recording=False, subscriber_count=0),
            }
        )
        app_module.app.dependency_overrides[get_camera_pool] = lambda: cls.fake_pool
        cls.client = TestClient(app_module.app, raise_server_exceptions=True)

    @classmethod
    def tearDownClass(cls):
        app_module.app.dependency_overrides.clear()
        pms_mod._service_instance = cls.prev_service

    def test_get_and_post_processing_mode_endpoints(self):
        resp = self.client.get("/api/system/processing-mode")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["mode"], "focus_only")
        self.assertIn("cam_02", data["camera_states"])
        self.assertTrue(data["camera_states"]["cam_02"]["should_hibernate"])

        upd = self.client.post(
            "/api/system/processing-mode",
            json={"mode": "full_realtime", "focused_camera_id": "cam_02", "active_tab": "live"},
        )
        self.assertEqual(upd.status_code, 200)
        upd_data = upd.json()
        self.assertEqual(upd_data["mode"], "full_realtime")
        self.assertEqual(upd_data["focused_camera_id"], "cam_02")
        self.assertFalse(upd_data["camera_states"]["cam_02"]["should_hibernate"])

    def test_post_invalid_mode_returns_400_and_record_schema_has_new_fields(self):
        bad = self.client.post("/api/system/processing-mode", json={"mode": "invalid_mode"})
        self.assertEqual(bad.status_code, 400)
        rec = CameraRecordStatusResponse(
            camera_id="cam_01", is_recording=False, status="idle", processing_mode="capture_only", deferred_job_id="j1"
        )
        self.assertEqual(rec.processing_mode, "capture_only")
        self.assertEqual(rec.deferred_job_id, "j1")


if __name__ == "__main__":
    unittest.main()
