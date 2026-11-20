#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit tests for Step 1 Milestone 1: asyncio.to_thread offloading in routers."""

import asyncio
import os
import subprocess
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from dashboard.routers import tagging as tagging_router
from dashboard.routers import video_jobs as video_jobs_router
from dashboard.services.roi_recognition_service import (
    RoiNotFoundError,
    RoiUnavailableError,
)


def _fake_request() -> SimpleNamespace:
    """Create a minimal FastAPI Request-like stub."""
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))


async def _run_offload_probe(coro, started: threading.Event, release: threading.Event):
    """Run coroutine concurrently with an event-loop probe to prove non-blocking."""
    progressed = False

    async def _probe():
        nonlocal progressed
        while not started.is_set():
            await asyncio.sleep(0.005)
        progressed = True
        release.set()

    probe_task = asyncio.create_task(_probe())
    try:
        result = await coro
    finally:
        release.set()
        await probe_task
    return result, progressed


class TestTaggingRouterOffload(unittest.IsolatedAsyncioTestCase):
    """Verify ROI tagging endpoints offload blocking work off the event loop."""

    async def test_recognize_roi_offloads_to_worker_thread(self):
        loop_tid = threading.get_ident()
        worker_tids: list[int] = []
        started, release = threading.Event(), threading.Event()

        def _fake_recognize(**_kwargs):
            worker_tids.append(threading.get_ident())
            started.set()
            release.wait(timeout=2.0)
            return {"candidates": []}

        svc = SimpleNamespace(recognize_roi=_fake_recognize)
        req = tagging_router.RoiRecognizeRequest(camera_id="cam0", bbox=[0, 0, 10, 10])
        with patch.object(tagging_router, "_build_service", return_value=svc):
            resp, progressed = await _run_offload_probe(
                tagging_router.recognize_roi_endpoint(req, _fake_request()),
                started,
                release,
            )
        self.assertTrue(progressed)
        self.assertEqual(resp["status"], "success")
        self.assertEqual(len(worker_tids), 1)
        self.assertNotEqual(worker_tids[0], loop_tid)

    async def test_recognize_roi_error_branches(self):
        req = tagging_router.RoiRecognizeRequest(camera_id="cam0", bbox=[0, 0, 10, 10])
        cases = [
            (ValueError("bad bbox"), 400),
            (RoiNotFoundError("no frame"), 404),
            (RoiUnavailableError("no detector"), 503),
        ]
        for exc, expected_code in cases:
            svc = SimpleNamespace(recognize_roi=MagicMock(side_effect=exc))
            with patch.object(tagging_router, "_build_service", return_value=svc):
                with self.assertRaises(HTTPException) as ctx:
                    await tagging_router.recognize_roi_endpoint(req, _fake_request())
                self.assertEqual(ctx.exception.status_code, expected_code)

    async def test_recognize_roi_db_unavailable_returns_503(self):
        req = tagging_router.RoiRecognizeRequest(camera_id="cam0", bbox=[0, 0, 10, 10])
        with patch.object(tagging_router, "get_db", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                await tagging_router.recognize_roi_endpoint(req, _fake_request())
            self.assertEqual(ctx.exception.status_code, 503)

    async def test_commit_roi_tag_offloads_commit_and_gallery_reload(self):
        loop_tid = threading.get_ident()
        tids: list[tuple[str, int]] = []
        started, release = threading.Event(), threading.Event()

        def _fake_commit(**_kwargs):
            tids.append(("commit", threading.get_ident()))
            started.set()
            release.wait(timeout=2.0)
            return {"entity_id": 7}

        def _fake_reload(conn=None):
            tids.append(("reload", threading.get_ident()))

        svc = SimpleNamespace(commit_roi_tag=_fake_commit)
        req = tagging_router.TagCommitRequest(entity_name="Alice", bbox=[0, 0, 10, 10])
        with patch.object(tagging_router, "_build_service", return_value=svc), patch.object(
            tagging_router, "reload_all_galleries", side_effect=_fake_reload
        ):
            resp, progressed = await _run_offload_probe(
                tagging_router.commit_roi_tag_endpoint(req, _fake_request()),
                started,
                release,
            )
        self.assertTrue(progressed)
        self.assertEqual(resp, {"status": "success", "data": {"entity_id": 7}})
        self.assertEqual([name for name, _ in tids], ["commit", "reload"])
        for _, tid in tids:
            self.assertNotEqual(tid, loop_tid)

    async def test_commit_roi_tag_error_branches(self):
        req = tagging_router.TagCommitRequest(entity_name="Alice", bbox=[0, 0, 10, 10])
        cases = [
            (ValueError("empty"), 400),
            (RoiNotFoundError("missing"), 404),
            (RoiUnavailableError("offline"), 503),
        ]
        for exc, expected_code in cases:
            svc = SimpleNamespace(commit_roi_tag=MagicMock(side_effect=exc))
            with patch.object(tagging_router, "_build_service", return_value=svc):
                with self.assertRaises(HTTPException) as ctx:
                    await tagging_router.commit_roi_tag_endpoint(req, _fake_request())
                self.assertEqual(ctx.exception.status_code, expected_code)


class TestVideoJobsSyncOffload(unittest.IsolatedAsyncioTestCase):
    """Verify synchronous transcode/analyze routes offload blocking work."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.video_name = "sample.mp4"
        self.video_path = os.path.join(self._tmpdir.name, self.video_name)
        with open(self.video_path, "wb") as fh:
            fh.write(b"fake-mp4")
        self.fake_mgr = SimpleNamespace(get_active_job_for_file=lambda _name: None)

    async def test_transcode_sync_offloads_to_worker_thread(self):
        loop_tid = threading.get_ident()
        worker_tids: list[int] = []
        started, release = threading.Event(), threading.Event()
        out_path = os.path.join(self._tmpdir.name, "sample_h264.mp4")

        def _fake_transcode(**_kwargs):
            worker_tids.append(threading.get_ident())
            started.set()
            release.wait(timeout=2.0)
            with open(out_path, "wb") as fh:
                fh.write(b"h264")

        pair = {"output_filename": "sample_h264.mp4", "output_path": out_path}
        with patch.object(video_jobs_router, "VIDEOS_DIR", self._tmpdir.name), patch.object(
            video_jobs_router, "get_video_job_manager", return_value=self.fake_mgr
        ), patch.object(
            video_jobs_router.VideoTranscodeService, "get_h264_pair_info", return_value=pair
        ), patch.object(
            video_jobs_router.VideoTranscodeService, "transcode_to_h264", side_effect=_fake_transcode
        ):
            resp, progressed = await _run_offload_probe(
                video_jobs_router.transcode_video(self.video_name, async_mode=False, force=False),
                started,
                release,
            )
        self.assertTrue(progressed)
        self.assertEqual(resp["status"], "success")
        self.assertNotEqual(worker_tids[0], loop_tid)

    async def test_transcode_sync_error_branches(self):
        out_path = os.path.join(self._tmpdir.name, "sample_h264.mp4")
        pair = {"output_filename": "sample_h264.mp4", "output_path": out_path}
        with patch.object(video_jobs_router, "VIDEOS_DIR", self._tmpdir.name):
            with self.assertRaises(HTTPException) as missing_ctx:
                await video_jobs_router.transcode_video("missing.mp4", async_mode=False)
            self.assertEqual(missing_ctx.exception.status_code, 404)

        for exc, code in [(subprocess.TimeoutExpired("ffmpeg", 300), 504), (RuntimeError("boom"), 500)]:
            with patch.object(video_jobs_router, "VIDEOS_DIR", self._tmpdir.name), patch.object(
                video_jobs_router, "get_video_job_manager", return_value=self.fake_mgr
            ), patch.object(
                video_jobs_router.VideoTranscodeService, "get_h264_pair_info", return_value=pair
            ), patch.object(
                video_jobs_router.VideoTranscodeService, "transcode_to_h264", side_effect=exc
            ):
                with self.assertRaises(HTTPException) as ctx:
                    await video_jobs_router.transcode_video(self.video_name, async_mode=False)
                self.assertEqual(ctx.exception.status_code, code)

    async def test_analyze_sync_offloads_to_worker_thread(self):
        loop_tid = threading.get_ident()
        worker_tids: list[int] = []
        started, release = threading.Event(), threading.Event()

        def _fake_sync_analytics(_name, _path, _opts):
            worker_tids.append(threading.get_ident())
            started.set()
            release.wait(timeout=2.0)
            return {"total_frames": 10}

        opts = {"is_async": False, "detector": "mock", "sample_rate": 1, "confidence": None, "classes": None}
        with patch.object(video_jobs_router, "VIDEOS_DIR", self._tmpdir.name), patch.object(
            video_jobs_router, "get_video_job_manager", return_value=self.fake_mgr
        ), patch.object(
            video_jobs_router, "parse_analyze_options", return_value=opts
        ), patch.object(
            video_jobs_router, "run_sync_analytics", side_effect=_fake_sync_analytics
        ):
            resp, progressed = await _run_offload_probe(
                video_jobs_router.analyze_video(self.video_name, async_mode=False),
                started,
                release,
            )
        self.assertTrue(progressed)
        self.assertEqual(resp, {"status": "success", "report": {"total_frames": 10}})
        self.assertNotEqual(worker_tids[0], loop_tid)

    async def test_analyze_missing_video_returns_404(self):
        with patch.object(video_jobs_router, "VIDEOS_DIR", self._tmpdir.name):
            with self.assertRaises(HTTPException) as ctx:
                await video_jobs_router.analyze_video("missing.mp4", async_mode=False)
            self.assertEqual(ctx.exception.status_code, 404)
