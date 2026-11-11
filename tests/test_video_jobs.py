import os
import shutil
import tempfile
import threading
import time
import unittest
import cv2
import numpy as np
from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.dependencies import VIDEOS_DIR
from dashboard.services.video_jobs_service import (
    JobStatus,
    VideoJobManager,
    get_video_job_manager,
)
from dashboard.services.video_transcoder import VideoTranscodeService
from intelligent_tracker.batch import VideoIndexer


def create_synthetic_video(path: str, num_frames: int = 30, fps: float = 30.0, width: int = 320, height: int = 240) -> str:
    """Create a minimal synthetic MP4 file for testing."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(path, fourcc, fps, (width, height))
    for i in range(num_frames):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        x = int(10 + (i * 5) % (width - 60))
        cv2.rectangle(frame, (x, 50), (x + 40, 100), (0, 255, 0), -1)
        writer.write(frame)
    writer.release()
    return path


class TestVideoWorkerHooks(unittest.TestCase):
    """Unit tests for VideoIndexer and VideoTranscodeService cancellation and progress hooks."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.video_path = os.path.join(self.temp_dir.name, "synthetic_test.mp4")
        create_synthetic_video(self.video_path, num_frames=30, fps=15.0)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_video_indexer_progress_callback(self):
        """VideoIndexer invokes progress_callback with expected metric keys."""
        callbacks = []

        def on_progress(p):
            callbacks.append(dict(p))

        indexer = VideoIndexer(
            db_path=os.path.join(self.temp_dir.name, "test.db"),
            detector_name="mock",
            sample_rate=1,
        )
        summary = indexer.process_video(
            video_path=self.video_path,
            verbose=False,
            progress_callback=on_progress,
        )

        self.assertFalse(summary.get("cancelled", False))
        self.assertGreater(len(callbacks), 0)
        last_cb = callbacks[-1]
        self.assertIn("read_frames", last_cb)
        self.assertIn("total_frames", last_cb)
        self.assertIn("percent", last_cb)
        self.assertEqual(last_cb["percent"], 100.0)
        self.assertEqual(last_cb["read_frames"], 30)

    def test_video_indexer_stop_event_cancellation(self):
        """VideoIndexer respects stop_event and exits with cancelled=True."""
        stop_event = threading.Event()
        callbacks = []

        def on_progress(p):
            callbacks.append(p)
            if p.get("read_frames", 0) >= 10:
                stop_event.set()

        indexer = VideoIndexer(
            db_path=os.path.join(self.temp_dir.name, "test.db"),
            detector_name="mock",
            sample_rate=1,
        )
        summary = indexer.process_video(
            video_path=self.video_path,
            verbose=False,
            progress_callback=on_progress,
            stop_event=stop_event,
        )

        self.assertTrue(summary.get("cancelled", False))
        self.assertLess(summary["read_frames"], 30)

    def test_video_transcoder_async_progress_and_completion(self):
        """VideoTranscodeService.transcode_to_h264_async transcodes and reports progress."""
        out_path = os.path.join(self.temp_dir.name, "transcoded.mp4")
        callbacks = []

        def on_progress(p):
            callbacks.append(dict(p))

        success = VideoTranscodeService.transcode_to_h264_async(
            input_path=self.video_path,
            output_path=out_path,
            target_resolution="720p",
            progress_callback=on_progress,
        )

        self.assertTrue(success)
        self.assertTrue(os.path.exists(out_path))
        self.assertGreater(len(callbacks), 0)
        self.assertEqual(callbacks[-1]["percent"], 100.0)

    def test_video_transcoder_async_cancellation(self):
        """VideoTranscodeService.transcode_to_h264_async handles cancellation and removes partial output."""
        out_path = os.path.join(self.temp_dir.name, "cancelled.mp4")
        stop_event = threading.Event()
        stop_event.set()

        with self.assertRaises(RuntimeError) as ctx:
            VideoTranscodeService.transcode_to_h264_async(
                input_path=self.video_path,
                output_path=out_path,
                progress_callback=None,
                stop_event=stop_event,
            )

        self.assertIn("cancelled", str(ctx.exception).lower())
        self.assertFalse(os.path.exists(out_path))


class TestVideoJobManager(unittest.TestCase):
    """Unit tests for the standalone VideoJobManager coordinator."""

    def setUp(self):
        self.manager = VideoJobManager(max_concurrent=2)

    def tearDown(self):
        self.manager.shutdown()

    def test_submit_and_complete_job(self):
        """Job completes successfully and records output metrics."""
        done_event = threading.Event()

        def runner(job, stop_ev, progress_cb):
            progress_cb({"percent": 50.0, "stage": "halfway"})
            done_event.wait(0.05)
            return {"items": 42}

        job = self.manager.submit_job("test_type", "test_video.mp4", runner)
        self.assertEqual(job.status, JobStatus.RUNNING)
        done_event.set()

        # Wait for worker thread to finish
        for _ in range(50):
            if job.status == JobStatus.COMPLETED:
                break
            time.sleep(0.02)

        self.assertEqual(job.status, JobStatus.COMPLETED)
        self.assertEqual(job.progress, 100.0)
        self.assertEqual(job.result, {"items": 42})

    def test_per_video_mutual_exclusion(self):
        """Attempting to submit concurrent jobs for the same video raises ValueError."""
        block_event = threading.Event()

        def runner(job, stop_ev, progress_cb):
            block_event.wait(1.0)
            return {}

        job1 = self.manager.submit_job("transcode", "clip_a.mp4", runner)
        self.assertIsNotNone(job1)

        with self.assertRaises(ValueError) as ctx:
            self.manager.submit_job("analytics", "clip_a.mp4", runner)

        self.assertIn("already active", str(ctx.exception).lower())
        block_event.set()

    def test_concurrency_throttle_and_cancellation(self):
        """Manager respects max_concurrent bound and cancels active tasks."""
        hold_event = threading.Event()

        def slow_runner(job, stop_ev, progress_cb):
            stop_ev.wait(1.0)
            return {}

        job1 = self.manager.submit_job("transcode", "video1.mp4", slow_runner)
        job2 = self.manager.submit_job("transcode", "video2.mp4", slow_runner)
        job3 = self.manager.submit_job("transcode", "video3.mp4", slow_runner)

        # 2 jobs should be RUNNING, 3rd queued/PENDING
        time.sleep(0.05)
        self.assertEqual(job1.status, JobStatus.RUNNING)
        self.assertEqual(job2.status, JobStatus.RUNNING)
        self.assertEqual(job3.status, JobStatus.PENDING)

        # Cancel job1
        cancelled = self.manager.cancel_job(job1.job_id)
        self.assertTrue(cancelled)

        for _ in range(50):
            if job1.status == JobStatus.CANCELLED:
                break
            time.sleep(0.02)

        self.assertEqual(job1.status, JobStatus.CANCELLED)

        # Now job3 should be picked up and transition to RUNNING
        for _ in range(50):
            if job3.status == JobStatus.RUNNING:
                break
            time.sleep(0.02)
        self.assertEqual(job3.status, JobStatus.RUNNING)

        hold_event.set()


class TestVideoJobAPI(unittest.TestCase):
    """Integration tests for the REST endpoints in dashboard/routers/videos.py."""

    @classmethod
    def setUpClass(cls):
        os.makedirs(VIDEOS_DIR, exist_ok=True)
        cls.client = TestClient(app)
        cls.test_filename = "test_job_api_clip.mp4"
        cls.test_path = os.path.join(VIDEOS_DIR, cls.test_filename)
        create_synthetic_video(cls.test_path, num_frames=20, fps=10.0)

    @classmethod
    def tearDownClass(cls):
        get_video_job_manager().shutdown()
        if os.path.exists(cls.test_path):
            try:
                os.remove(cls.test_path)
            except OSError:
                pass
        # Clean up any generated transcodes
        transcoded = os.path.join(VIDEOS_DIR, "test_job_api_clip_h264.mp4")
        if os.path.exists(transcoded):
            try:
                os.remove(transcoded)
            except OSError:
                pass

    def test_01_api_transcode_async_and_conflict(self):
        """Verify 202 Accepted and 409 Conflict behavior for transcode jobs."""
        resp = self.client.post(f"/api/videos/{self.test_filename}/transcode?async_mode=true")
        self.assertEqual(resp.status_code, 202)
        data = resp.json()
        self.assertEqual(data["status"], "accepted")
        job_id = data["job_id"]
        self.assertTrue(job_id.startswith("job_"))

        # Immediate re-click should trigger 409 Conflict with active job details
        resp_conflict = self.client.post(f"/api/videos/{self.test_filename}/transcode?async_mode=true")
        self.assertEqual(resp_conflict.status_code, 409)
        conflict_data = resp_conflict.json()
        self.assertEqual(conflict_data["error"], "conflict")
        self.assertEqual(conflict_data["active_job"]["job_id"], job_id)

        # Poll status
        resp_status = self.client.get(f"/api/videos/jobs/{job_id}")
        self.assertEqual(resp_status.status_code, 200)
        job_dict = resp_status.json()
        self.assertEqual(job_dict["filename"], self.test_filename)

        # Wait for transcode completion
        for _ in range(100):
            r = self.client.get(f"/api/videos/jobs/{job_id}")
            if r.json()["status"] in ("completed", "failed"):
                break
            time.sleep(0.05)

        final_job = self.client.get(f"/api/videos/jobs/{job_id}").json()
        self.assertIn(final_job["status"], ("completed", "failed"))

    def test_02_api_analyze_async_and_cancellation(self):
        """Verify 202 Accepted, progress polling, and cancellation for analytics."""
        resp = self.client.post(
            f"/api/videos/{self.test_filename}/analyze?async_mode=true&detector=mock&sample_rate=1"
        )
        self.assertEqual(resp.status_code, 202)
        job_id = resp.json()["job_id"]

        # Cancel job
        cancel_resp = self.client.post(f"/api/videos/jobs/{job_id}/cancel")
        self.assertEqual(cancel_resp.status_code, 200)
        self.assertEqual(cancel_resp.json()["status"], "cancelling")

        # Wait for worker thread to stop
        for _ in range(50):
            r = self.client.get(f"/api/videos/jobs/{job_id}")
            if r.json()["status"] in ("cancelled", "completed"):
                break
            time.sleep(0.05)

        status_data = self.client.get(f"/api/videos/jobs/{job_id}").json()
        self.assertIn(status_data["status"], ("cancelled", "completed"))

    def test_03_api_list_jobs(self):
        """Verify GET /api/videos/jobs lists recent jobs."""
        resp = self.client.get("/api/videos/jobs")
        self.assertEqual(resp.status_code, 200)
        jobs = resp.json()
        self.assertIsInstance(jobs, list)
        self.assertGreater(len(jobs), 0)


if __name__ == "__main__":
    unittest.main()
