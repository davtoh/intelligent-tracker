#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Targeted regression tests for Step 1 Milestone 1 backend critical seams."""

import base64
import json
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from dashboard import app as app_module
from dashboard.dependencies import (
    clear_app_state,
    get_camera_pool,
    get_db,
    resolve_stream_manager,
    set_camera_pool,
    set_shutting_down,
    set_stream_manager,
)
from dashboard.services.async_inference_worker import AsyncInferenceWorker, _merge_cached_step_result
from dashboard.services.stream_recording import StreamRecordingController
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.pipeline import FrameStepResult


class TestStep1BackendBugs(unittest.TestCase):
    """Verify Findings 1 & 4 and BE-1/BE-2/BE-4 backend fixes."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, "test.db")
        self.db = TrackerDB(self.db_path)
        self.addCleanup(self.db.close)
        set_shutting_down(False)
        clear_app_state(app_module.app)
        app_module.app.dependency_overrides.clear()
        self.addCleanup(app_module.app.dependency_overrides.clear)
        self.addCleanup(clear_app_state, app_module.app)
        self.addCleanup(set_shutting_down, False)

    def test_offline_camera_never_aliases_primary_stream(self) -> None:
        """Explicit camera_id missing from pool must return None and fail /stream, /ws, /freeze_frame."""
        primary = MagicMock(camera_id="cam_0")
        pool = MagicMock(primary_stream=primary)
        pool.get_stream.side_effect = lambda cid=None: primary if cid in (None, "cam_0") else None
        self.assertIsNone(resolve_stream_manager("usb_2", pool=pool, sm=primary))
        self.assertIs(resolve_stream_manager(None, pool=pool, sm=primary), primary)

        set_camera_pool(pool, app_module.app)
        set_stream_manager(primary, app_module.app)
        self.addCleanup(set_camera_pool, None, app_module.app)
        self.addCleanup(set_stream_manager, None, app_module.app)
        client = TestClient(app_module.app)
        self.assertEqual(client.get("/stream/usb_2").status_code, 503)
        self.assertEqual(client.get("/api/cameras/usb_2/freeze_frame").status_code, 404)
        with self.assertRaises(WebSocketDisconnect) as ctx:
            with client.websocket_connect("/ws/usb_2") as ws:
                ws.receive_json()
        self.assertEqual(ctx.exception.code, 1013)

    def test_two_step_roi_commit_preserves_direct_crop_dimensions(self) -> None:
        """Sending both crop_base64 and full-frame bbox must not double-crop in recognize/commit."""
        crop_bgr = np.random.default_rng(42).integers(20, 230, size=(120, 80, 3), dtype=np.uint8)
        ok, buf = cv2.imencode(".jpg", crop_bgr)
        self.assertTrue(ok)
        b64 = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")
        crops_dir = os.path.join(self._tmp.name, "crops")
        app_module.app.dependency_overrides[get_db] = lambda: self.db
        app_module.app.dependency_overrides[get_camera_pool] = lambda: None
        with patch("dashboard.routers.tagging.CROPS_DIR", crops_dir), \
             patch("dashboard.routers.tagging.reload_all_galleries"), \
             patch("dashboard.services.roi_recognition_service._resolve_roi_models", return_value=(None, None)):
            client = TestClient(app_module.app)
            rec = client.post("/api/tag/recognize-roi", json={"crop_base64": b64, "bbox": [500, 500, 80, 120]})
            self.assertEqual(rec.status_code, 200)
            self.assertEqual(rec.json()["data"]["bbox"], [0, 0, 80, 120])
            commit = client.post(
                "/api/tag/commit",
                json={"entity_name": "Alice", "category": "person", "crop_base64": b64, "bbox": [500, 500, 80, 120]},
            )
            self.assertEqual(commit.status_code, 200)
            saved = cv2.imread(commit.json()["data"]["crop_path"])
            assert saved is not None
            self.assertEqual(saved.shape[:2], (120, 80))
            self.assertGreater(float(np.std(saved)), 1.0)

    def test_signature_repo_calls_rollback_on_sqlite_error(self) -> None:
        """SignatureMixin.add_signature and update_entity_signature must rollback on error."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.execute.side_effect = RuntimeError("db error")
        mock_conn.cursor.return_value = mock_cur
        with patch.object(self.db, "_conn", mock_conn):
            with self.assertRaises(RuntimeError):
                self.db.add_signature(1, np.zeros(8, dtype=np.float32))
            self.assertEqual(mock_conn.rollback.call_count, 1)
            with self.assertRaises(RuntimeError):
                self.db.update_entity_signature(1, embedding=np.zeros(8, dtype=np.float32))
            self.assertEqual(mock_conn.rollback.call_count, 2)

    def test_app_state_db_survives_primary_stream_restart(self) -> None:
        """app.state.db must remain open when primary_stream closes its own PipelineBundle."""
        cfg_path = os.path.join(self._tmp.name, "cameras.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump([{"id": "cam_0", "name": "Cam 0", "source": "synthetic", "type": "synthetic", "enabled": False}], f)
        primary_sm = MagicMock(db=TrackerDB(self.db_path), event_bus=None, event_fts_index=None, confidence_engine=None)
        fake_pool = MagicMock(primary_stream=primary_sm, world_graph=None, event_bus=None, event_fts_index=None, confidence_engine=None)
        fake_pool.streams = {"cam_0": primary_sm}
        fake_pool._coordinator = MagicMock()
        with patch.dict(os.environ, {"CAMERAS_CONFIG_PATH": cfg_path, "TRACKER_DB_PATH": self.db_path}), \
             patch("dashboard.app.CameraPool", return_value=fake_pool):
            _, _, _, owned_db = app_module._init_runtime_services(app_module.app)
            self.addCleanup(lambda: owned_db.close() if owned_db else None)
            self.assertIsNotNone(app_module.app.state.db)
            self.assertIsNot(app_module.app.state.db, primary_sm.db)
            primary_sm.db.close()
            self.assertIsNotNone(app_module.app.state.db._conn)
            self.assertEqual(app_module.app.state.db.list_entities(), [])

    def test_analytics_di_override_and_async_worker_monotonic_fallback(self) -> None:
        """analytics.py honors dependency_overrides and AsyncInferenceWorker uses monotonic fallback."""
        self.db.add_entity("Bob", category="person")
        app_module.app.dependency_overrides[get_db] = lambda: self.db
        client = TestClient(app_module.app)
        resp = client.get("/entities")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([e["name"] for e in resp.json()], ["Bob"])

        worker = AsyncInferenceWorker(processor=MagicMock())
        worker.submit(np.zeros((8, 8, 3), dtype=np.uint8), timestamp=1_700_000_000.0, frame_seq=1)
        _, wall_ts, mono_ts, _ = worker._pending
        self.assertEqual(wall_ts, 1_700_000_000.0)
        self.assertLess(abs(mono_ts - time.monotonic()), 5.0)

        cached = FrameStepResult(frame=np.zeros((8, 8, 3), dtype=np.uint8), timestamp=1_700_000_000.0)
        worker._latest_result = cached
        merged = _merge_cached_step_result(
            worker, np.zeros((8, 8, 3), dtype=np.uint8), time.monotonic(), 1_700_000_005.0, 2, None, None, "cam_0", False,
        )
        self.assertEqual(merged.inference_lag_ms, 0.0)

    def test_recording_controller_persists_outside_lock(self) -> None:
        """StreamRecordingController.stop() must run _persist_live_capture_run outside _lock."""
        writer = MagicMock(is_open=True)
        writer.snapshot.return_value = {"width": 640, "height": 480, "fps": 20.0}
        ctrl = StreamRecordingController("cam_0", output_dir=self._tmp.name, writer_factory=lambda *a, **kw: writer)
        ctrl.start(filename="rec.mp4")
        lock_free: list[bool] = []

        def _fake_persist(*args, **kwargs):
            def _probe():
                acquired = ctrl._lock.acquire(blocking=False)
                lock_free.append(acquired)
                if acquired:
                    ctrl._lock.release()
            t = threading.Thread(target=_probe)
            t.start()
            t.join(timeout=2.0)
            return {"run_id": 7}

        with patch.object(ctrl, "_persist_live_capture_run", side_effect=_fake_persist):
            meta = ctrl.stop()
        self.assertEqual(lock_free, [True])
        self.assertEqual(meta.get("report_run_id"), 7)


if __name__ == "__main__":
    unittest.main()
