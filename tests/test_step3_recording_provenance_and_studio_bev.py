"""Unit and API tests for Step 3 Milestone 1: H.264 recording, 409 guard & async ffprobe."""

import asyncio
import io
import os
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import UploadFile
from fastapi.testclient import TestClient
import numpy as np

from dashboard.app import app
from dashboard.dependencies import get_camera_pool, get_stream_manager
from dashboard.routers import videos as videos_router
from dashboard.services.alerts_query_service import query_merged_events
from dashboard.services.recording_transcode_helper import (
    find_active_recording_for_file,
    get_active_recording_provenance,
    is_web_playable_codec,
)
from dashboard.services.stream_recording import StreamRecordingController
from intelligent_tracker.analytics import AnalyticsEngine
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.events import EventBus
from intelligent_tracker.geometry import Tripwire, ZoneROI
from intelligent_tracker.matching._gallery_signals import emit_periodic_sighting
from intelligent_tracker.pipeline import FrameProcessor, PipelineBundle, PipelineConfig
from intelligent_tracker.pipeline.post_detection_governance import publish_id_events
from intelligent_tracker.tracker import Track
from intelligent_tracker.video.writers import DEFAULT_CODEC_FALLBACKS, PipelineVideoWriter


class _StubWriter:
    """Minimal PipelineVideoWriter stand-in for deterministic codec/lock tests."""

    def __init__(self, out_path: str, codec: str = "mp4v", **_kwargs) -> None:
        self.output_path = out_path
        self.codec = codec
        self.frames_written = 0
        self.started_at = time.time()
        self._open = True
        with open(out_path, "wb") as fh:
            fh.write(b"\x00\x00\x00\x18ftypmp42")

    @property
    def is_open(self) -> bool:
        return self._open

    def write(self, _frame: np.ndarray) -> bool:
        self.frames_written += 1
        return True

    def release(self) -> None:
        self._open = False

    def snapshot(self) -> dict:
        return {
            "output_path": self.output_path,
            "codec": self.codec,
            "fps": 20.0,
            "width": 320,
            "height": 240,
            "frames_written": self.frames_written,
            "started_at": self.started_at,
            "elapsed_s": 0.1,
            "size_bytes": os.path.getsize(self.output_path),
            "is_open": self._open,
        }


class _RecordingStreamStub:
    """Minimal StreamManager stub exposing active recording status."""

    def __init__(self, camera_id: str, filename: str, output_path: str, active: bool = True) -> None:
        self.camera_id = camera_id
        self.is_recording = active
        self._status = {
            "camera_id": camera_id,
            "is_recording": active,
            "recording_id": "rec_active_1",
            "filename": filename,
            "output_path": output_path,
        }

    def get_recording_status(self) -> dict:
        return dict(self._status)


class TestStep3Milestone1RecordingAndTranscode(unittest.TestCase):
    """Tests for avc1-first recording, auto-transcode, 409 guard, and async ffprobe."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.addCleanup(app.dependency_overrides.clear)

    def test_default_codec_fallbacks_prefer_avc1_and_snapshot_started_at(self) -> None:
        """DEFAULT_CODEC_FALLBACKS prefers avc1 first and snapshot exposes started_at."""
        self.assertEqual(DEFAULT_CODEC_FALLBACKS, ("avc1", "mp4v", "MJPG", "XVID"))
        tried: list[str] = []

        class _FakeCvWriter:
            def __init__(self, ok: bool) -> None:
                self._ok = ok

            def isOpened(self) -> bool:
                return self._ok

            def write(self, _f) -> None:
                pass

            def release(self) -> None:
                pass

        def _fake_fourcc(*chars: str) -> str:
            code = "".join(chars)
            tried.append(code)
            return code

        def _fake_writer(_path, fourcc, _fps, _size):
            return _FakeCvWriter(ok=(fourcc == "mp4v"))

        out_path = os.path.join(self.tmpdir.name, "fallback.mp4")
        with (
            patch("intelligent_tracker.video.writers.cv2.VideoWriter_fourcc", side_effect=_fake_fourcc),
            patch("intelligent_tracker.video.writers.cv2.VideoWriter", side_effect=_fake_writer),
        ):
            writer = PipelineVideoWriter(out_path, fps=15.0, resolution=(160, 120))
            self.addCleanup(writer.release)
            self.assertEqual(tried[:2], ["avc1", "mp4v"])
            self.assertEqual(writer.codec, "mp4v")
            snap = writer.snapshot()
            self.assertAlmostEqual(snap["started_at"], writer.started_at, places=3)

    def test_web_playable_codec_and_find_active_recording_helper(self) -> None:
        """Codec classifier and active-recording finder match pool and primary streams."""
        for codec in ("avc1", "h264", "H264", "x264", "avc3"):
            self.assertTrue(is_web_playable_codec(codec))
        for codec in ("mp4v", "MJPG", "XVID", ""):
            self.assertFalse(is_web_playable_codec(codec))

        rec_path = os.path.join(self.tmpdir.name, "live_cam.mp4")
        active_sm = _RecordingStreamStub("cam_live", "live_cam.mp4", rec_path, active=True)
        idle_sm = _RecordingStreamStub("cam_idle", "other.mp4", rec_path, active=False)
        pool = SimpleNamespace(streams={"cam_live": active_sm, "cam_idle": idle_sm}, _lock=threading.RLock())

        found = find_active_recording_for_file("live_cam.mp4", pool, None)
        self.assertIsNotNone(found)
        self.assertEqual(found["camera_id"], "cam_live")
        self.assertEqual(found["recording_id"], "rec_active_1")
        self.assertIsNone(find_active_recording_for_file("other.mp4", pool, None))
        found_primary = find_active_recording_for_file(rec_path, None, active_sm)
        self.assertIsNotNone(found_primary)
        self.assertEqual(found_primary["camera_id"], "cam_live")

    def _make_lock_probing_job_mgr(self, ctrl_ref: list, lock_free: list, submitted: list):
        class _FakeJobMgr:
            is_shutdown = False

            def get_active_job_for_file(self, _name: str):
                return None

            def submit_job(self, *, job_type: str, filename: str, runner_fn, initial_metrics=None):
                acquired: list[bool] = []

                def _probe_lock() -> None:
                    ok = ctrl_ref[0]._lock.acquire(blocking=False)
                    acquired.append(ok)
                    if ok:
                        ctrl_ref[0]._lock.release()

                t = threading.Thread(target=_probe_lock)
                t.start()
                t.join(timeout=2.0)
                lock_free.append(bool(acquired and acquired[0]))
                submitted.append((job_type, filename))
                return SimpleNamespace(job_id="job_auto_h264_1")

        return _FakeJobMgr()

    def test_stop_queues_auto_transcode_outside_lock_for_mp4v(self) -> None:
        """stop() queues H.264 transcode outside _lock for mp4v and skips for avc1/disabled."""
        lock_free: list[bool] = []
        submitted: list[tuple[str, str]] = []
        ctrl_ref: list[StreamRecordingController] = []
        fake_mgr = self._make_lock_probing_job_mgr(ctrl_ref, lock_free, submitted)
        ctrl = StreamRecordingController(
            camera_id="cam_rec", output_dir=self.tmpdir.name,
            writer_factory=lambda p, **kw: _StubWriter(p, codec="mp4v", **kw),
            job_mgr_getter=lambda: fake_mgr, auto_transcode=True,
        )
        ctrl_ref.append(ctrl)
        ctrl.start(filename="clip_mp4v.mp4")
        ctrl.write_frame(np.zeros((60, 80, 3), dtype=np.uint8))
        meta = ctrl.stop()
        self.assertEqual(meta.get("transcode_job_id"), "job_auto_h264_1")
        self.assertEqual(ctrl.status().get("transcode_job_id"), "job_auto_h264_1")
        self.assertEqual(submitted, [("transcode", "clip_mp4v.mp4")])
        self.assertEqual(lock_free, [True])

        ctrl_h264 = StreamRecordingController(
            camera_id="cam_h264", output_dir=self.tmpdir.name,
            writer_factory=lambda p, **kw: _StubWriter(p, codec="avc1", **kw),
            job_mgr_getter=lambda: fake_mgr, auto_transcode=True,
        )
        ctrl_h264.start(filename="clip_avc1.mp4")
        ctrl_h264.write_frame(np.zeros((60, 80, 3), dtype=np.uint8))
        self.assertIsNone(ctrl_h264.stop().get("transcode_job_id"))
        self.assertEqual(len(submitted), 1)

    def test_transcode_endpoint_returns_409_when_actively_recording(self) -> None:
        """POST /api/videos/{filename}/transcode returns 409 before FFmpeg when recording is active."""
        filename = "recording_in_progress.mp4"
        video_path = os.path.join(self.tmpdir.name, filename)
        with open(video_path, "wb") as fh:
            fh.write(b"\x00\x00\x00\x18ftypmp42")

        active_sm = _RecordingStreamStub("cam_02", filename, video_path, active=True)
        pool = SimpleNamespace(streams={"cam_02": active_sm}, _lock=threading.RLock())
        app.dependency_overrides[get_camera_pool] = lambda: pool
        app.dependency_overrides[get_stream_manager] = lambda: None

        client = TestClient(app)
        with (
            patch("dashboard.routers.video_jobs.VIDEOS_DIR", self.tmpdir.name),
            patch("dashboard.routers.video_jobs.VideoTranscodeService.transcode_to_h264_async") as mock_async,
            patch("dashboard.routers.video_jobs.VideoTranscodeService.transcode_to_h264") as mock_sync,
        ):
            resp = client.post(f"/api/videos/{filename}/transcode")
            self.assertEqual(resp.status_code, 409)
            body = resp.json()
            self.assertEqual(body["error"], "conflict")
            self.assertEqual(body["active_recording"]["camera_id"], "cam_02")
            mock_async.assert_not_called()
            mock_sync.assert_not_called()

    def test_list_and_upload_videos_offload_ffprobe_via_to_thread(self) -> None:
        """list_videos() and upload_video() offload probe_video and auto-transcode via asyncio.to_thread."""
        sample_path = os.path.join(self.tmpdir.name, "sample.mp4")
        with open(sample_path, "wb") as fh:
            fh.write(b"\x00\x00\x00\x18ftypmp42")

        offloaded: list[str] = []
        real_to_thread = asyncio.to_thread

        async def _spy_to_thread(func, *args, **kwargs):
            offloaded.append(getattr(func, "_mock_name", None) or getattr(func, "__name__", str(func)))
            return await real_to_thread(func, *args, **kwargs)

        fake_probe = {"codec": "mpeg4", "web_compatible": False, "width": 320, "height": 240, "duration": 1.0, "fps": 20.0}
        fake_h264_probe = {**fake_probe, "codec": "h264", "web_compatible": True}

        def _fake_auto(_dest_path: str, _safe_name: str):
            out = os.path.join(self.tmpdir.name, "uploaded_h264.mp4")
            with open(out, "wb") as fh:
                fh.write(b"\x00\x00\x00\x18ftypmp42")
            return "uploaded_h264.mp4", out, fake_h264_probe

        async def _run() -> None:
            with (
                patch("dashboard.routers.videos.VIDEOS_DIR", self.tmpdir.name),
                patch("dashboard.routers.videos.asyncio.to_thread", side_effect=_spy_to_thread),
                patch("dashboard.routers.videos.VideoTranscodeService.probe_video", return_value=fake_probe),
                patch("dashboard.routers.videos._handle_auto_transcode", side_effect=_fake_auto),
            ):
                listed = await videos_router.list_videos()
                self.assertEqual(len(listed), 1)
                self.assertIn("probe_video", offloaded)
                offloaded.clear()
                upload = UploadFile(filename="uploaded.mp4", file=io.BytesIO(b"\x00\x00\x00\x18ftypmp42"))
                res = await videos_router.upload_video(file=upload, auto_transcode=True)
                self.assertEqual(res["filename"], "uploaded_h264.mp4")
                self.assertTrue(res["web_compatible"])
                self.assertEqual(offloaded, ["probe_video", "_handle_auto_transcode"])

        asyncio.run(_run())

    def test_get_active_recording_provenance_and_frame_processor_propagation(self) -> None:
        """Active recording provenance propagates to FrameProcessor and clears cleanly on stop."""
        self.assertEqual(get_active_recording_provenance(None), (None, None))
        ctrl = StreamRecordingController(
            camera_id="cam_live", output_dir=self.tmpdir.name,
            writer_factory=lambda p, **kw: _StubWriter(p, codec="avc1", **kw), auto_transcode=False,
        )
        self.assertEqual(get_active_recording_provenance(ctrl), (None, None))
        ctrl.start(filename="live_prov.mp4")
        fn, started_at = get_active_recording_provenance(ctrl)
        self.assertEqual(fn, "live_prov.mp4")
        self.assertIsNotNone(started_at)

        matcher = SimpleNamespace(video_filename="", current_media_offset_sec=None)
        analytics = AnalyticsEngine(camera_id="cam_live", heatmap_enabled=False)
        proc = FrameProcessor(PipelineBundle(config=PipelineConfig(camera_id="cam_live"), analytics=analytics, gallery_matcher=matcher))
        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        proc.set_recording_provenance(fn, started_at)
        proc.step(frame, timestamp=float(started_at) + 12.5)
        self.assertEqual((matcher.video_filename, analytics.video_filename), ("live_prov.mp4", "live_prov.mp4"))
        self.assertAlmostEqual(matcher.current_media_offset_sec, 12.5, places=2)

        ctrl.stop()
        proc.set_recording_provenance(*get_active_recording_provenance(ctrl))
        proc.step(frame, timestamp=float(started_at) + 15.0)
        self.assertEqual((matcher.video_filename, matcher.current_media_offset_sec), ("", None))

        off_m = SimpleNamespace(video_filename="offline_clip.mp4", current_media_offset_sec=42.0)
        FrameProcessor(PipelineBundle(config=PipelineConfig(camera_id="offline_video"), gallery_matcher=off_m)).step(frame, timestamp=1700000042.0)
        self.assertEqual((off_m.video_filename, off_m.current_media_offset_sec), ("offline_clip.mp4", 42.0))

    def test_live_recording_stamps_clip_provenance_on_alerts_sightings_and_bus_fallback(self) -> None:
        """Live zone/tripwire/capacity/pet/ID/restricted alerts and sightings carry clip provenance."""
        db, bus = TrackerDB(db_path=os.path.join(self.tmpdir.name, "prov.db")), EventBus()
        bus.start()
        self.addCleanup(db.close)
        self.addCleanup(bus.stop)
        eid = db.add_entity(name="Mallory", category="restricted")
        zone = ZoneROI(name="vault", polygon=[(0, 0), (100, 0), (100, 100), (0, 100)], capacity_limit=1)
        analytics = AnalyticsEngine(
            zones=[zone], tripwires=[Tripwire(line_segment=((50, 0), (50, 100)), name="gate")],
            heatmap_enabled=False, event_bus=bus, camera_id="cam_01", pet_whitelist={"pet"},
        )
        analytics.video_filename, analytics.current_media_offset_sec = "cam_live_rec.mp4", 14.25
        frame = np.zeros((120, 120, 3), dtype=np.uint8)
        t1 = Track(track_id=1, centroid=(20.0, 50.0), bbox=(10, 40, 20, 20), label="person")
        t2 = Track(track_id=2, centroid=(30.0, 50.0), bbox=(20, 40, 20, 20), label="dog")
        setattr(t2, "entity_category", "pet")
        analytics.update({1: t1}, timestamp=1700000010.0, current_frame=frame)
        t1.centroid = (80.0, 50.0)
        analytics.update({1: t1, 2: t2}, timestamp=1700000014.25, current_frame=frame)

        matcher = SimpleNamespace(
            db=db, fts_index=None, _last_sighting_time={}, sighting_interval=5.0,
            video_filename="cam_live_rec.mp4", current_media_offset_sec=14.25, camera_id="", run_id="", crops_dir=self.tmpdir.name,
        )
        bundle = PipelineBundle(config=PipelineConfig(camera_id="cam_01"), analytics=analytics, gallery_matcher=matcher, event_bus=bus)
        id_ev = SimpleNamespace(track_id=1, entity_id=eid, name="Mallory", category="restricted", similarity=0.92, zone_id="vault")
        publish_id_events(bundle, frame, {1: t1}, [id_ev], timestamp=1700000014.25)
        self.assertTrue(emit_periodic_sighting(
            matcher, entity_id=eid, name="Mallory", category="restricted", track=t1,
            confidence=0.92, source="cam_01", zone_id="vault", timestamp=1700000014.25, frame=frame,
        ))
        s0 = db.get_sightings(entity_id=eid)[0]
        self.assertEqual((s0["video_filename"], s0["camera_id"]), ("cam_live_rec.mp4", "cam_01"))
        self.assertAlmostEqual(s0["media_offset_sec"], 14.25, places=2)
        bus_items = query_merged_events(SimpleNamespace(event_bus=bus), db=None, limit=50)
        self.assertTrue({"zone_enter", "tripwire_cross", "occupancy_threshold", "pet_activity", "entity_identified", "restricted_entity_alert"} <= {e["event_type"] for e in bus_items})
        for ev in bus_items:
            self.assertEqual((ev.get("video_filename"), round(float(ev.get("media_offset_sec") or 0.0), 2)), ("cam_live_rec.mp4", 14.25))


class TestStep3Milestone3BevPoseAndBounds(unittest.TestCase):
    """Verify OBS-025/026 staggered cameras, entity calibrated bounds, and derived poses."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory(prefix="step3_m3_bev_")
        self.addCleanup(self.tmpdir.cleanup)

    def test_stagger_uncalibrated_cameras_and_exclude_raw_pixel_entities(self) -> None:
        """Uncalibrated cameras stagger into non-overlapping slots and raw-pixel entities skip bounds."""
        from intelligent_tracker.world.graph import WorldGraph
        from intelligent_tracker.world.minimap import WorldTacticalMinimap
        from intelligent_tracker.world.nodes import CameraNode, WorldEntity

        wg = WorldGraph()
        wg.register_camera(CameraNode(camera_id="cam_a", name="Cam A"))
        wg.register_camera(CameraNode(camera_id="cam_b", name="Cam B"))
        wg.upsert_entity(WorldEntity(
            world_entity_id="session:cam_a:1", name="RawPx",
            camera_tracks={"cam_a": 1}, global_xy=(960.0, 540.0),
        ))
        telemetry = WorldTacticalMinimap(wg).build_world_minimap_telemetry()
        cams = {c["camera_id"]: c for c in telemetry["cameras"]}
        pa, pb = cams["cam_a"]["world_pose"], cams["cam_b"]["world_pose"]
        self.assertNotEqual((pa["origin_x"], pa["origin_y"]), (pb["origin_x"], pb["origin_y"]))
        self.assertGreaterEqual(abs(pb["origin_x"] - pa["origin_x"]) + abs(pb["origin_y"] - pa["origin_y"]), 4.0)
        self.assertFalse(telemetry["entities"][0]["calibrated"])
        self.assertLess(telemetry["bounds"]["width_m"], 100.0)
        self.assertLess(telemetry["bounds"]["height_m"], 100.0)

    def test_derive_pose_from_homography_and_preserve_custom_pose(self) -> None:
        """sync_homography_to_world derives a default pose only when no custom pose exists."""
        from intelligent_tracker.homography import GroundPlaneHomography
        from intelligent_tracker.world._bridge_helpers import is_camera_calibrated
        from intelligent_tracker.world.coordinates import (
            GlobalCoordinateMapper,
            derive_pose_from_homography,
            sync_homography_to_world,
        )
        from intelligent_tracker.world.graph import WorldGraph
        from intelligent_tracker.world.nodes import CameraNode

        mapper = GlobalCoordinateMapper()
        wg = WorldGraph(coordinate_mapper=mapper)
        homo = GroundPlaneHomography(
            src_points=[(0, 0), (100, 0), (100, 80), (0, 80)],
            metric_width=10.0, metric_height=8.0, camera_id="cam_cal",
        )
        derived = derive_pose_from_homography("cam_cal", homo)
        self.assertEqual((derived.origin_x, derived.origin_y, derived.yaw_deg), (5.0, 8.0, -90.0))

        sync_homography_to_world(wg, mapper, "cam_cal", homo)
        self.assertTrue(is_camera_calibrated("cam_cal", coordinate_mapper=mapper, world_graph=wg))
        pose_cal = mapper.get_pose("cam_cal")
        self.assertIsNotNone(pose_cal)
        self.assertEqual((pose_cal.origin_x, pose_cal.origin_y, pose_cal.yaw_deg), (5.0, 8.0, -90.0))

        wg.register_camera(CameraNode(camera_id="cam_custom", name="Custom", world_pose=(12.0, 4.0, 45.0)))
        sync_homography_to_world(wg, mapper, "cam_custom", homo)
        custom_node = wg.get_node("cam_custom", node_type="camera")
        self.assertEqual(tuple(custom_node.world_pose), (12.0, 4.0, 45.0))

    def test_post_homography_route_persists_derived_pose_only_when_missing(self) -> None:
        """POST /api/scenarios/homography persists derived CameraWorldPose without clobbering custom pose."""
        import asyncio
        from unittest.mock import patch
        from dashboard.routers.scenarios import save_homography_route
        from dashboard.schemas import HomographyCalibrationRequest
        from intelligent_tracker.scenarios import ScenarioManager

        db = TrackerDB(db_path=os.path.join(self.tmpdir.name, "homo_pose.db"))
        self.addCleanup(db.close)
        sm = ScenarioManager(config_path=os.path.join(self.tmpdir.name, "scen.yaml"), db=db)
        req = HomographyCalibrationRequest(
            camera_id="cam_api",
            src_points=[[0, 0], [100, 0], [100, 80], [0, 80]],
            metric_width=10.0, metric_height=8.0,
        )
        fake_request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
        with patch("dashboard.routers.scenarios.get_active_stream_manager", return_value=None):
            res = asyncio.run(save_homography_route(req, fake_request, sm))
        self.assertEqual(res["status"], "success")
        saved = db.get_world_pose("cam_api")
        self.assertIsNotNone(saved)
        self.assertEqual((saved["origin_x"], saved["origin_y"], saved["yaw_deg"]), (5.0, 8.0, -90.0))

        db.save_world_pose("cam_api", 20.0, 30.0, 15.0, 1.0)
        with patch("dashboard.routers.scenarios.get_active_stream_manager", return_value=None):
            asyncio.run(save_homography_route(req, fake_request, sm))
        kept = db.get_world_pose("cam_api")
        self.assertEqual((kept["origin_x"], kept["origin_y"], kept["yaw_deg"]), (20.0, 30.0, 15.0))


if __name__ == "__main__":
    unittest.main()
