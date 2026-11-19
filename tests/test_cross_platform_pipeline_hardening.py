#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Milestone 1 verification tests for Step 1.5 cross-platform pipeline hardening."""

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.camera_pool import CameraPool
from dashboard.dependencies import clear_app_state, set_camera_pool
from dashboard.services.camera_config_store import CameraConfigStore
from dashboard.services.camera_diagnostics import CameraHealthManager
from dashboard.services.stream_worker import StreamWorker
from dashboard.services.video_jobs_service import get_video_job_manager, reset_video_job_manager
from intelligent_tracker.camera_device import CameraDeviceHandler
from intelligent_tracker.camera_resolver import CameraPathResolver
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.pipeline.config import _is_video_file
from intelligent_tracker.video import VideoSource


class TestCrossPlatformPathsAndDevices(unittest.TestCase):
    """Tests for portable path normalization, macOS fallback, and video extensions."""

    def test_normalize_source_path_host_container_and_windows(self) -> None:
        ws_root = CameraPathResolver.get_workspace_root()
        win_abs = str(ws_root).replace("/", "\\") + "\\data\\videos\\clip.mp4"
        with patch.object(CameraDeviceHandler, "is_container_environment", return_value=False):
            self.assertEqual(CameraPathResolver.normalize_source_path(win_abs), "data/videos/clip.mp4")
            self.assertEqual(CameraPathResolver.normalize_source_path("./data\\videos\\clip.mp4"), "data/videos/clip.mp4")
        with patch.object(CameraDeviceHandler, "is_container_environment", return_value=True):
            self.assertEqual(CameraPathResolver.normalize_source_path("/app/data/videos/clip.mp4"), "data/videos/clip.mp4")

    def test_resolve_file_source_uses_normalized_filename_on_windows_paths(self) -> None:
        resolved, err, attempted = CameraPathResolver.resolve_file_source(r"C:\foreign\box\nonexistent_win_clip_xyz.mp4")
        self.assertIsNone(resolved)
        self.assertEqual(err, "FILE_NOT_FOUND")
        self.assertTrue(any(p.endswith("nonexistent_win_clip_xyz.mp4") for p in attempted))
        self.assertTrue(any(os.path.join("data", "videos", "nonexistent_win_clip_xyz.mp4") in p for p in attempted))

    def test_darwin_camera_enumeration_and_video_extensions(self) -> None:
        fake_proc = MagicMock(returncode=0, stdout=json.dumps({"SPCameraDataType": [{"_name": "FaceTime HD Camera"}]}))
        with patch("intelligent_tracker.camera_device.sys.platform", "darwin"):
            with patch("intelligent_tracker.camera_device_enum.subprocess.run", return_value=fake_proc):
                self.assertEqual(CameraDeviceHandler.get_device_names(), ["FaceTime HD Camera"])
            with patch("intelligent_tracker.camera_device_enum.subprocess.run", side_effect=OSError("missing")):
                self.assertEqual(CameraDeviceHandler.get_device_names(), [])
        for ext in (".wmv", ".flv", ".webm", ".m4v"):
            self.assertTrue(_is_video_file(f"sample{ext}"))

    def test_camera_config_store_normalizes_loaded_and_stored_paths(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg_path = os.path.join(tmp.name, "cameras.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump([{"id": "c1", "name": "C1", "source": "/app/data/videos/a.mp4", "type": "video_file"}], f)
        store = CameraConfigStore(config_file=cfg_path)
        configs, _ = store.load_cameras()
        self.assertEqual(configs["c1"]["source"], "data/videos/a.mp4")
        entry = store.build_and_store_entry("c2", "C2", r"app\data\videos\b.mp4", cam_type="video_file")
        self.assertEqual(entry["source"], "data/videos/b.mp4")
        _, _, updated = store.update_entry("c2", source="/app/data/videos/c.mp4")
        self.assertEqual(updated["source"], "data/videos/c.mp4")

    def test_add_video_as_camera_normalizes_workspace_path(self) -> None:
        ws_videos = os.path.join(str(CameraPathResolver.get_workspace_root()), "data", "videos")
        fake_pool = MagicMock()
        set_camera_pool(fake_pool)
        self.addCleanup(clear_app_state, app)
        with patch("dashboard.routers.videos.VIDEOS_DIR", ws_videos):
            with patch("dashboard.routers.videos.os.path.exists", return_value=True):
                resp = TestClient(app).post("/api/videos/demo_clip.mp4/add_as_camera")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(fake_pool.add_camera.call_args.kwargs["source"], "data/videos/demo_clip.mp4")


class TestBootstrapRetryAndWorkerRecovery(unittest.TestCase):
    """Tests for fast-fail missing files, skipped YOLO init, retry endpoint, and StreamWorker."""

    def test_capture_worker_fails_fast_on_missing_file(self) -> None:
        vs = VideoSource(source="data/videos/does_not_exist_12345.mp4", auto_reconnect=True, reconnect_delay=5.0)
        t0 = time.monotonic()
        vs.start()
        self.addCleanup(vs.stop)
        for _ in range(40):
            if vs._thread is None or not vs._thread.is_alive():
                break
            time.sleep(0.05)
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 2.0)
        self.assertFalse(vs._thread is not None and vs._thread.is_alive())

    def test_unavailable_usb_skips_stream_manager_and_retries_via_api(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg_path = os.path.join(tmp.name, "cameras.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump([{"id": "usb1", "name": "USB 1", "source": "1", "type": "usb", "enabled": True}], f)
        with (
            patch.object(CameraDeviceHandler, "get_device_names", return_value=["Cam 0"]),
            patch.object(CameraDeviceHandler, "probe_device", return_value=None),
            patch("dashboard.services.stream_pool_coordinator.StreamManager") as mock_sm_cls,
        ):
            pool = CameraPool(config_file=cfg_path, db_path=os.path.join(tmp.name, "t.db"), autostart=True)
        self.addCleanup(pool.stop_all)
        mock_sm_cls.assert_not_called()
        self.assertEqual(CameraHealthManager().get_health("usb1").error_code, "DEVICE_UNAVAILABLE")

        set_camera_pool(pool)
        self.addCleanup(clear_app_state, app)
        fake_mgr = MagicMock(is_running=False)
        with (
            patch.object(CameraDeviceHandler, "get_device_names", return_value=["Cam 0", "USB 1"]),
            patch.object(CameraDeviceHandler, "probe_device", return_value={"index": 1, "valid": True}),
            patch("dashboard.services.stream_pool_coordinator.StreamManager", return_value=fake_mgr) as mock_retry_sm,
        ):
            resp = TestClient(app).post("/api/cameras/usb1/retry")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "online")
        mock_retry_sm.assert_called_once()
        fake_mgr.start.assert_called_once()

    def test_stream_worker_survives_transient_exceptions_and_recovers(self) -> None:
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        calls = {"n": 0}
        recovered = threading.Event()
        fake_vs = MagicMock()
        fake_vs.__enter__ = MagicMock(return_value=fake_vs)
        fake_vs.__exit__ = MagicMock(return_value=False)
        fake_vs.read = MagicMock(return_value=(True, frame))
        mgr = MagicMock(
            camera_id="cam_rec", name="Cam Rec", width=64, height=48,
            video_source=fake_vs, _running=True, _stop_event=threading.Event(),
            _lock=threading.RLock(), _latest_jpeg=None, _latest_raw_jpeg=None,
            _latest_telemetry={}, _is_hibernating=False, is_recording=False,
            subscriber_count=1, has_raw_subscribers=True, has_annotated_subscribers=True,
            _recording_controller=None, _processing_mode_service=None,
            _overlay_renderer=MagicMock(render=MagicMock(return_value=frame)),
            overlays={}, start_time=time.time(), analytics=None, rsac_manager=None,
            homography=None, draw_heatmap=False, _pipeline_bundle=MagicMock(),
        )
        def _fake_step(_aw, frm, ts, seq, _run_vis):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise RuntimeError("transient gpu glitch")
            recovered.set()
            mgr._stop_event.set()
            return MagicMock(frame=frm, tracks={}, timestamp=ts, fps=30.0, frame_count=seq)

        with patch("dashboard.services.stream_worker.build_live_step_result", side_effect=_fake_step):
            with patch("dashboard.services.stream_worker.FrameProcessor") as mock_fp:
                mock_fp.return_value.frame_count = 0
                StreamWorker(mgr).run()
        self.assertTrue(recovered.is_set())
        self.assertEqual(CameraHealthManager().get_health("cam_rec").status, "online")

    def test_stream_worker_publishes_both_error_placeholders_after_threshold(self) -> None:
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        calls = {"n": 0}
        fake_vs = MagicMock()
        fake_vs.__enter__ = MagicMock(return_value=fake_vs)
        fake_vs.__exit__ = MagicMock(return_value=False)
        fake_vs.read = MagicMock(return_value=(True, frame))
        mgr = MagicMock(
            camera_id="cam_err12", width=64, height=48,
            video_source=fake_vs, _running=True, _stop_event=threading.Event(),
            _lock=threading.RLock(), _latest_jpeg=None, _latest_raw_jpeg=None,
            _latest_telemetry={"status": "online"}, _is_hibernating=False,
            is_recording=False, subscriber_count=1, _processing_mode_service=None,
            _pipeline_bundle=MagicMock(),
        )
        mgr.name = "Cam Err"
        def _always_fail(*_args):
            calls["n"] += 1
            if calls["n"] >= 11:
                mgr._stop_event.set()
            raise RuntimeError("persistent error")

        with patch("dashboard.services.stream_worker.build_live_step_result", side_effect=_always_fail):
            with patch("dashboard.services.stream_worker.FrameProcessor") as mock_fp:
                mock_fp.return_value.frame_count = 0
                StreamWorker(mgr).run()
        self.assertIsNotNone(mgr._latest_jpeg)
        self.assertIsNotNone(mgr._latest_raw_jpeg)
        self.assertEqual(mgr._latest_telemetry["status"], "error")


class TestOpenTraceFixes(unittest.TestCase):
    """Tests for TRC-007 (closed DB), TRC-001 (delete_video), and TRC-004 (shutdown 503)."""

    def test_signature_repo_closed_db_guards(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = TrackerDB(os.path.join(tmp.name, "sig.db"))
        db.close()
        self.assertEqual(db.get_signatures(), [])
        mat, eids, names, cats = db.get_gallery_embeddings(expected_dim=512)
        self.assertEqual(mat.shape, (0, 512))
        self.assertEqual((eids, names, cats), ([], [], []))
        self.assertFalse(db.update_entity_signature(1, crop_path="x.jpg"))
        with self.assertRaises(RuntimeError):
            db.add_signature(1, np.ones(4, dtype=np.float32))

    def test_delete_video_releases_camera_pool_and_returns_409_on_lock(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        clip = os.path.join(tmp.name, "locked_clip.mp4")
        Path(clip).write_bytes(b"fake")
        fake_pool = MagicMock()
        fake_pool.camera_configs = {"v1": {"source": "data/videos/locked_clip.mp4", "enabled": True}}
        fake_pool.streams = {}
        set_camera_pool(fake_pool)
        self.addCleanup(clear_app_state, app)
        with patch("dashboard.routers.videos.VIDEOS_DIR", tmp.name):
            with patch("dashboard.routers.videos.os.remove", side_effect=PermissionError("locked")):
                resp = TestClient(app).delete("/api/videos/locked_clip.mp4")
        self.assertEqual(resp.status_code, 409)
        fake_pool.toggle_camera.assert_called_once_with("v1", enabled=False)

    def test_video_jobs_shutdown_returns_503(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        clip = os.path.join(tmp.name, "job_clip.mp4")
        Path(clip).write_bytes(b"fake")
        self.addCleanup(reset_video_job_manager)
        get_video_job_manager().shutdown()
        with patch("dashboard.routers.video_jobs.VIDEOS_DIR", tmp.name):
            client = TestClient(app)
            r_tr = client.post("/api/videos/job_clip.mp4/transcode?async_mode=true")
            r_an = client.post("/api/videos/job_clip.mp4/analyze?async_mode=true&detector=mock")
        self.assertEqual(r_tr.status_code, 503)
        self.assertEqual(r_an.status_code, 503)


if __name__ == "__main__":
    unittest.main()
