#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Step 1 Milestone 4: End-to-end integration tests for event loop, JPEG modes & report cache."""

import asyncio
import json
import os
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from dashboard.routers import tagging as tagging_router
from dashboard.services import video_report_migration as migration_mod
from dashboard.services.stream_subscribers import StreamSubscriberMixin, StreamSubscriberRegistry
from dashboard.services.stream_worker import StreamWorker
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.pipeline import FrameStepResult


class _IntegratedStreamHost(StreamSubscriberMixin):
    """Minimal StreamManager-compatible host backed by a real StreamSubscriberRegistry."""

    def __init__(self, lease_ttl: float = 5.0) -> None:
        self._subscriber_registry = StreamSubscriberRegistry(lease_ttl=lease_ttl)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._latest_raw_jpeg: bytes | None = b"seed-raw"
        self._latest_jpeg: bytes | None = b"seed-ann"
        self.camera_id = "cam0"
        self.start_time = 0.0
        self.overlays: dict = {}
        self.draw_heatmap = False
        self.homography = SimpleNamespace(is_calibrated=False, track_to_ground=lambda *_a: (0.0, 0.0))
        self.analytics = None
        self.rsac_manager = None
        self.event_bus = None
        self._overlay_renderer = MagicMock()
        self._overlay_renderer.render.side_effect = lambda **kw: kw["frame"]
        self._recording_controller = MagicMock(is_recording=False)


def _step_result(frame_count: int = 1) -> FrameStepResult:
    """Build a synthetic 16x16 FrameStepResult."""
    frame = np.zeros((16, 16, 3), dtype=np.uint8)
    return FrameStepResult(frame=frame, tracks={}, frame_count=frame_count, timestamp=1.0, fps=30.0)


def _write_legacy_report(reports_dir: str, alias: str, run_id: str) -> str:
    """Write a minimal legacy *_reports.json file in an isolated temp directory."""
    path = os.path.join(reports_dir, f"{alias}_reports.json")
    payload = [
        {
            "run_id": run_id,
            "filename": f"{alias}.mp4",
            "base_filename": f"{alias}.mp4",
            "source_resolution": [1280, 720],
            "source_fps": 30.0,
            "report": {"frames_processed": 4, "total_detections": 2},
            "config": {"detector": "mock"},
        }
    ]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


class TestStep1PerfIntegration(unittest.IsolatedAsyncioTestCase):
    """Verify concurrent ROI offloading, MJPEG mode switching, and cached report listing."""

    def setUp(self) -> None:
        migration_mod.clear_migration_cache()
        self.addCleanup(migration_mod.clear_migration_cache)
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.reports_dir = os.path.join(self._tmpdir.name, "reports")
        os.makedirs(self.reports_dir, exist_ok=True)
        self.db = TrackerDB(db_path=os.path.join(self._tmpdir.name, "tracker.db"))
        self.addCleanup(self.db.close)
        self.lock = threading.RLock()

    async def test_concurrent_roi_recognition_and_cached_report_listing(self) -> None:
        _write_legacy_report(self.reports_dir, "demo", "run_int_1")
        started, release = threading.Event(), threading.Event()
        loop_tid = threading.get_ident()
        worker_tids: list[int] = []

        def _slow_recognize(**_kwargs) -> dict:
            worker_tids.append(threading.get_ident())
            started.set()
            release.wait(timeout=2.0)
            return {"candidates": [{"name": "Alice", "score": 0.9}]}

        async def _concurrent_report_checks() -> list[dict]:
            while not started.is_set():
                await asyncio.sleep(0.005)
            for _ in range(2):
                migration_mod.migrate_legacy_json_for_aliases(
                    "demo.mp4", ["demo"], self.reports_dir, self.db,
                    lambda fn: fn, lambda _: None, self.lock,
                )
            runs = self.db.list_video_runs("demo.mp4")
            release.set()
            return runs

        req = tagging_router.RoiRecognizeRequest(camera_id="cam0", bbox=[0, 0, 10, 10])
        fake_http_req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
        svc = SimpleNamespace(recognize_roi=_slow_recognize)
        with patch.object(tagging_router, "_build_service", return_value=svc), patch.object(
            migration_mod, "load_runs_file", wraps=migration_mod.load_runs_file
        ) as mock_load:
            roi_resp, runs = await asyncio.gather(
                tagging_router.recognize_roi_endpoint(req, fake_http_req),
                _concurrent_report_checks(),
            )
        self.assertEqual(roi_resp["status"], "success")
        self.assertNotEqual(worker_tids[0], loop_tid)
        self.assertEqual(mock_load.call_count, 1)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["run_id"], "run_int_1")

    def test_mjpeg_subscriber_mode_switching_end_to_end(self) -> None:
        host = _IntegratedStreamHost(lease_ttl=5.0)
        worker = StreamWorker(host)
        fake_jpg = (True, np.array([1, 2, 3], dtype=np.uint8))

        with patch("dashboard.services.stream_worker.cv2.imencode", return_value=fake_jpg) as enc:
            host.add_subscriber("raw1", annotated=False)
            worker._process_single_frame(_step_result(1))
            self.assertEqual(enc.call_count, 1)
            self.assertEqual(host._overlay_renderer.render.call_count, 0)

            host.add_subscriber("ann1", annotated=True)
            worker._process_single_frame(_step_result(2))
            self.assertEqual(enc.call_count, 3)
            self.assertEqual(host._overlay_renderer.render.call_count, 1)

            host.remove_subscriber("raw1")
            worker._process_single_frame(_step_result(3))
            self.assertEqual(enc.call_count, 4)
            self.assertEqual(host._overlay_renderer.render.call_count, 2)

            host.remove_subscriber("ann1")
            host.register_ws_subscriber(MagicMock())
            worker._process_single_frame(_step_result(4))
            self.assertEqual(enc.call_count, 4)
            self.assertEqual(host._overlay_renderer.render.call_count, 2)

    def test_save_and_migrate_video_run_roundtrip(self) -> None:
        dets = [{"frame_index": 0, "detections": [{"id": 1, "bbox": [1, 2, 3, 4]}]}]
        saved = self.db.save_video_run(
            video_filename="demo.mp4",
            report={"frames_processed": 1},
            frame_detections=dets,
            run_id="run_saved_1",
        )
        self.assertEqual(saved["frame_detections"], dets)
        _write_legacy_report(self.reports_dir, "demo", "run_legacy_1")
        migration_mod.migrate_legacy_json_for_aliases(
            "demo.mp4", ["demo"], self.reports_dir, self.db,
            lambda fn: fn, lambda _: None, self.lock,
        )
        runs = self.db.list_video_runs("demo.mp4")
        self.assertEqual({r["run_id"] for r in runs}, {"run_saved_1", "run_legacy_1"})


if __name__ == "__main__":
    unittest.main()
