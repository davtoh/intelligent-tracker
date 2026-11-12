#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit & API Tests for Transactional H.264 Staging and Force-Transcode Rollback.
"""

import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from collections.abc import Callable
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.dependencies import VIDEOS_DIR
from dashboard.services.video_jobs_service import get_video_job_manager
from dashboard.services.video_transcoder import VideoTranscodeService


class _FakeStdout:
    """Line-yielding stdout stub supporting mid-stream cancellation."""

    def __init__(self, lines: list[str], on_first_line: Callable[[], None] | None = None):
        self._lines = list(lines)
        self._idx = 0
        self._on_first_line = on_first_line

    def readline(self) -> str:
        if self._idx == 0 and self._on_first_line is not None:
            self._on_first_line()
        if self._idx >= len(self._lines):
            return ""
        line = self._lines[self._idx]
        self._idx += 1
        return line

    def close(self) -> None:
        pass


class _FakeStderr:
    def __init__(self, lines: list[str] | None = None):
        self._lines = list(lines or [])
        self._idx = 0

    def readline(self) -> str:
        if self._idx >= len(self._lines):
            return ""
        line = self._lines[self._idx]
        self._idx += 1
        return line

    def close(self) -> None:
        pass


class TestTranscodeAtomicRollback(unittest.TestCase):
    """Verify transactional staging `.part.mp4` preserves existing `_h264.mp4` on cancel/error."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_transcode_rollback_")
        self.input_path = os.path.join(self.temp_dir, "clip_hevc.mp4")
        self.output_path = os.path.join(self.temp_dir, "clip_hevc_h264.mp4")
        self.staging_path = f"{self.output_path}.part.mp4"
        with open(self.input_path, "wb") as f:
            f.write(b"FAKE_HEVC_SOURCE")
        self.original_bytes = b"VALID_EXISTING_H264_PAYLOAD_v1"
        with open(self.output_path, "wb") as f:
            f.write(self.original_bytes)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_async_pre_cancelled_preserves_existing_h264(self):
        """Pre-set stop_event exits before Popen and preserves pre-existing _h264.mp4."""
        stop_event = threading.Event()
        stop_event.set()
        with self.assertRaises(RuntimeError) as ctx:
            VideoTranscodeService.transcode_to_h264_async(
                self.input_path, self.output_path, stop_event=stop_event
            )
        self.assertIn("cancelled", str(ctx.exception).lower())
        self.assertFalse(os.path.exists(self.staging_path))
        with open(self.output_path, "rb") as f:
            self.assertEqual(f.read(), self.original_bytes)

    def test_async_mid_flight_cancel_preserves_existing_h264_and_removes_staging(self):
        """Cancelling a force=true re-transcode mid-flight cleans .part.mp4 and keeps _h264.mp4."""
        stop_event = threading.Event()
        recorded_cmd: list[str] = []

        def fake_popen(cmd, **_kwargs):
            recorded_cmd.extend(cmd)
            staging_target = cmd[-1]
            with open(staging_target, "wb") as f:
                f.write(b"PARTIAL_CORRUPT_STREAM")

            proc = MagicMock()
            proc.stdout = _FakeStdout(
                ["frame=5\n", "out_time_us=100000\n"],
                on_first_line=lambda: stop_event.set(),
            )
            proc.stderr = _FakeStderr([])
            proc.poll.side_effect = lambda: 1 if stop_event.is_set() else None
            proc.wait.return_value = 1
            proc.returncode = 1
            return proc

        with patch.object(
            VideoTranscodeService, "probe_video", return_value={"duration": 10.0}
        ), patch("dashboard.services.video_transcoder.subprocess.Popen", side_effect=fake_popen):
            with self.assertRaises(RuntimeError) as ctx:
                VideoTranscodeService.transcode_to_h264_async(
                    self.input_path, self.output_path, stop_event=stop_event
                )

        self.assertIn("cancelled", str(ctx.exception).lower())
        self.assertEqual(recorded_cmd[-1], self.staging_path)
        self.assertFalse(os.path.exists(self.staging_path))
        with open(self.output_path, "rb") as f:
            self.assertEqual(f.read(), self.original_bytes)

    def test_async_nonzero_exit_preserves_existing_h264(self):
        """FFmpeg failure removes staging file and leaves pre-existing _h264.mp4 untouched."""
        def fake_popen(cmd, **_kwargs):
            with open(cmd[-1], "wb") as f:
                f.write(b"BROKEN_STAGING")
            proc = MagicMock()
            proc.stdout = _FakeStdout([])
            proc.stderr = _FakeStderr(["muxer error"])
            proc.poll.return_value = 1
            proc.wait.return_value = 1
            proc.returncode = 1
            return proc

        with patch.object(
            VideoTranscodeService, "probe_video", return_value={"duration": 5.0}
        ), patch("dashboard.services.video_transcoder.subprocess.Popen", side_effect=fake_popen):
            with self.assertRaises(RuntimeError) as ctx:
                VideoTranscodeService.transcode_to_h264_async(self.input_path, self.output_path)

        self.assertIn("muxer error", str(ctx.exception))
        self.assertFalse(os.path.exists(self.staging_path))
        with open(self.output_path, "rb") as f:
            self.assertEqual(f.read(), self.original_bytes)

    def test_async_success_atomically_replaces_existing_h264(self):
        """Verified completion promotes .part.mp4 into output_path and leaves no .part.mp4."""
        new_bytes = b"NEW_H264_FASTSTART_STREAM_v2"

        def fake_popen(cmd, **_kwargs):
            with open(cmd[-1], "wb") as f:
                f.write(new_bytes)
            proc = MagicMock()
            proc.stdout = _FakeStdout(["frame=10\n", "progress=end\n"])
            proc.stderr = _FakeStderr([])
            proc.poll.return_value = 0
            proc.wait.return_value = 0
            proc.returncode = 0
            return proc

        with patch.object(
            VideoTranscodeService, "probe_video", return_value={"duration": 5.0}
        ), patch("dashboard.services.video_transcoder.subprocess.Popen", side_effect=fake_popen):
            ok = VideoTranscodeService.transcode_to_h264_async(self.input_path, self.output_path)

        self.assertTrue(ok)
        self.assertFalse(os.path.exists(self.staging_path))
        with open(self.output_path, "rb") as f:
            self.assertEqual(f.read(), new_bytes)

    def test_sync_timeout_and_failure_preserve_existing_h264(self):
        """Synchronous transcode_to_h264 cleans .part.mp4 on error/timeout and promotes on success."""
        def fake_run_fail(cmd, **_kwargs):
            with open(cmd[-1], "wb") as f:
                f.write(b"PARTIAL_SYNC")
            res = MagicMock()
            res.returncode = 1
            res.stderr = "codec failure"
            return res

        with patch("dashboard.services.video_transcoder.subprocess.run", side_effect=fake_run_fail):
            with self.assertRaises(RuntimeError):
                VideoTranscodeService.transcode_to_h264(self.input_path, self.output_path)
        self.assertFalse(os.path.exists(self.staging_path))
        with open(self.output_path, "rb") as f:
            self.assertEqual(f.read(), self.original_bytes)

        def fake_run_timeout(cmd, **_kwargs):
            with open(cmd[-1], "wb") as f:
                f.write(b"PARTIAL_TIMEOUT")
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=1.0)

        with patch("dashboard.services.video_transcoder.subprocess.run", side_effect=fake_run_timeout):
            with self.assertRaises(subprocess.TimeoutExpired):
                VideoTranscodeService.transcode_to_h264(self.input_path, self.output_path)
        self.assertFalse(os.path.exists(self.staging_path))
        with open(self.output_path, "rb") as f:
            self.assertEqual(f.read(), self.original_bytes)

        new_sync_bytes = b"NEW_SYNC_H264_BYTES"

        def fake_run_ok(cmd, **_kwargs):
            with open(cmd[-1], "wb") as f:
                f.write(new_sync_bytes)
            res = MagicMock()
            res.returncode = 0
            res.stderr = ""
            return res

        with patch("dashboard.services.video_transcoder.subprocess.run", side_effect=fake_run_ok):
            self.assertTrue(VideoTranscodeService.transcode_to_h264(self.input_path, self.output_path))
        self.assertFalse(os.path.exists(self.staging_path))
        with open(self.output_path, "rb") as f:
            self.assertEqual(f.read(), new_sync_bytes)

    def test_empty_staging_file_raises_and_preserves_existing_h264(self):
        """Zero-byte staging file is never promoted over an existing _h264.mp4."""
        def fake_run_empty(cmd, **_kwargs):
            with open(cmd[-1], "wb") as f:
                f.write(b"")
            res = MagicMock()
            res.returncode = 0
            res.stderr = ""
            return res

        with patch("dashboard.services.video_transcoder.subprocess.run", side_effect=fake_run_empty):
            with self.assertRaises(RuntimeError):
                VideoTranscodeService.transcode_to_h264(self.input_path, self.output_path)
        self.assertFalse(os.path.exists(self.staging_path))
        with open(self.output_path, "rb") as f:
            self.assertEqual(f.read(), self.original_bytes)

    def test_api_force_transcode_cancel_preserves_h264_and_hides_part_files(self):
        """API cancel of force=true transcode keeps original _h264.mp4 and hides .part.mp4 from list."""
        os.makedirs(VIDEOS_DIR, exist_ok=True)
        src_name = "rollback_api_clip.mp4"
        h264_name = "rollback_api_clip_h264.mp4"
        src_path = os.path.join(VIDEOS_DIR, src_name)
        h264_path = os.path.join(VIDEOS_DIR, h264_name)
        part_path = f"{h264_path}.part.mp4"
        prior_bytes = b"PRIOR_WORKING_H264_CLIP"
        with open(src_path, "wb") as f:
            f.write(b"FAKE_SRC")
        with open(h264_path, "wb") as f:
            f.write(prior_bytes)

        started = threading.Event()

        def slow_transcode(*, input_path, output_path, stop_event, **_kwargs):
            staging = f"{output_path}.part.mp4"
            with open(staging, "wb") as f:
                f.write(b"IN_FLIGHT_PART")
            started.set()
            while not stop_event.is_set():
                stop_event.wait(0.05)
            os.remove(staging)
            raise RuntimeError("Transcoding was cancelled by user")

        client = TestClient(app)
        try:
            with patch.object(
                VideoTranscodeService, "transcode_to_h264_async", side_effect=slow_transcode
            ):
                resp = client.post(f"/api/videos/{src_name}/transcode?async_mode=true&force=true")
                self.assertEqual(resp.status_code, 202)
                job_id = resp.json()["job_id"]
                self.assertTrue(started.wait(timeout=2.0))

                # Staging .part.mp4 must not leak into GET /api/videos listing
                list_resp = client.get("/api/videos")
                self.assertEqual(list_resp.status_code, 200)
                listed_names = [item["filename"] for item in list_resp.json()]
                self.assertFalse(any(name.endswith(".part.mp4") for name in listed_names))

                cancel_resp = client.post(f"/api/videos/jobs/{job_id}/cancel")
                self.assertEqual(cancel_resp.status_code, 200)

                for _ in range(40):
                    st = client.get(f"/api/videos/jobs/{job_id}").json()["status"]
                    if st == "cancelled":
                        break
                    time.sleep(0.02)

            self.assertFalse(os.path.exists(part_path))
            with open(h264_path, "rb") as f:
                self.assertEqual(f.read(), prior_bytes)
        finally:
            get_video_job_manager().cancel_active_job_for_file(src_name, wait_timeout=1.0)
            for p in (src_path, h264_path, part_path):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass


if __name__ == "__main__":
    unittest.main()
