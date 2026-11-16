"""Tests for AsyncInferenceWorker and non-blocking StreamWorker integration."""

import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np

from dashboard.services.async_inference_worker import AsyncInferenceWorker
from dashboard.services.processing_mode_service import ProcessingModeService
from dashboard.services.stream_worker import StreamWorker
from intelligent_tracker.pipeline import FrameStepResult


def _make_worker_host(svc: ProcessingModeService) -> SimpleNamespace:
    """Create a minimal StreamManager stand-in for StreamWorker async tests."""
    return SimpleNamespace(
        camera_id="cam_async",
        name="Async Cam",
        width=160,
        height=120,
        _running=True,
        _stop_event=threading.Event(),
        _lock=threading.Lock(),
        _is_hibernating=False,
        subscriber_count=1,
        has_raw_subscribers=False,
        has_annotated_subscribers=False,
        is_recording=False,
        _in_camera_pool=False,
        _processing_mode_service=svc,
        _recording_controller=None,
        _latest_raw_frame=None,
        _latest_raw_jpeg=b"raw",
        _latest_jpeg=b"ann",
        _latest_telemetry={},
        _broadcast_telemetry=MagicMock(),
        _overlay_renderer=MagicMock(),
        overlays={},
        start_time=0.0,
        analytics=None,
        rsac_manager=None,
        event_bus=None,
        detector=None,
        homography=SimpleNamespace(is_calibrated=False, track_to_ground=lambda bbox: (0.0, 0.0)),
        draw_heatmap=False,
        video_source=None,
    )


def _make_paced_video_source(host: SimpleNamespace, frames: list[np.ndarray]) -> MagicMock:
    """Build a fake VideoSource yielding frames at ~10ms intervals then stopping."""
    idx = {"i": 0}

    def read(timeout: float = 1.0) -> tuple[bool, np.ndarray | None]:
        i = idx["i"]
        if i >= len(frames):
            host._stop_event.set()
            return False, None
        idx["i"] += 1
        time.sleep(0.01)
        return True, frames[i]

    vs = MagicMock()
    vs.__enter__.return_value = vs
    vs.__exit__.return_value = False
    vs.read.side_effect = read
    return vs


def _make_fake_track() -> SimpleNamespace:
    """Create a minimal track stub satisfying build_stream_telemetry."""
    return SimpleNamespace(
        bbox=[0, 0, 10, 10],
        centroid=(5.0, 5.0),
        velocity=(0.0, 0.0),
        label="person",
        confidence=0.9,
        dwell_time=0.0,
        state="confirmed",
    )


class TestAsyncInferenceWorker(unittest.TestCase):
    """Verify single-slot latest-frame semantics and clean shutdown."""

    def test_submit_drops_stale_intermediate_frames_when_slow(self) -> None:
        started = threading.Event()
        release = threading.Event()
        seen_markers: list[int] = []

        def fake_step(frame: np.ndarray, timestamp: float = 0.0, max_dim: int = 1280) -> FrameStepResult:
            marker = int(frame[0, 0, 0])
            seen_markers.append(marker)
            if marker == 1:
                started.set()
                release.wait(timeout=2.0)
            return FrameStepResult(frame=frame, tracks={marker: "ok"}, timestamp=timestamp, fps=15.0)

        proc = SimpleNamespace(step=fake_step)
        worker = AsyncInferenceWorker(proc)
        worker.start()
        self.addCleanup(worker.stop)

        f1 = np.full((8, 8, 3), 1, dtype=np.uint8)
        worker.submit(f1, 1.0)
        self.assertTrue(started.wait(timeout=1.0))

        for val in (2, 3, 4):
            worker.submit(np.full((8, 8, 3), val, dtype=np.uint8), float(val))
        release.set()

        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            res = worker.get_latest_result()
            if res is not None and 4 in res.tracks:
                break
            time.sleep(0.01)

        self.assertEqual(seen_markers, [1, 4])

    def test_get_latest_result_and_fast_stop(self) -> None:
        expected = FrameStepResult(
            frame=np.zeros((8, 8, 3), dtype=np.uint8),
            tracks={7: {"id": 7}},
            analytics={"count": 1},
            identifications=[{"id": 7, "name": "Alice"}],
            fps=24.0,
        )
        done = threading.Event()

        def fake_step(frame: np.ndarray, timestamp: float = 0.0, max_dim: int = 1280) -> FrameStepResult:
            done.set()
            return expected

        worker = AsyncInferenceWorker(SimpleNamespace(step=fake_step))
        self.assertIsNone(worker.get_latest_result())
        worker.start()
        worker.submit(np.zeros((8, 8, 3), dtype=np.uint8), 10.0)
        self.assertTrue(done.wait(timeout=1.0))

        deadline = time.monotonic() + 1.0
        while worker.get_latest_result() is None and time.monotonic() < deadline:
            time.sleep(0.01)

        cached = worker.get_latest_result()
        self.assertIsNotNone(cached)
        self.assertEqual(cached.tracks, {7: {"id": 7}})
        self.assertEqual(cached.analytics, {"count": 1})

        t0 = time.monotonic()
        worker.stop(timeout=1.0)
        self.assertLess(time.monotonic() - t0, 0.2)

    def test_stream_worker_reuses_cached_tracks_without_blocking_capture(self) -> None:
        svc = ProcessingModeService(mode="full_realtime")
        host = _make_worker_host(svc)
        frames = [np.full((16, 16, 3), i, dtype=np.uint8) for i in range(6)]
        host.video_source = _make_paced_video_source(host, frames)

        first_done = threading.Event()

        fake_trk = _make_fake_track()

        def slow_step(frame: np.ndarray, timestamp: float = 0.0, max_dim: int = 1280) -> FrameStepResult:
            if not first_done.is_set():
                first_done.set()
                return FrameStepResult(
                    frame=frame, tracks={42: fake_trk}, analytics={"n": 1}, fps=20.0
                )
            time.sleep(0.25)
            return FrameStepResult(
                frame=frame, tracks={99: fake_trk}, analytics={"n": 1}, fps=20.0
            )

        captured_tracks: list[dict] = []
        worker = StreamWorker(host)
        worker._get_processor = MagicMock(return_value=SimpleNamespace(frame_count=0, step=slow_step))
        orig_process = worker._process_single_frame

        def spy_process(step_res: FrameStepResult) -> None:
            captured_tracks.append(dict(step_res.tracks))
            orig_process(step_res)

        worker._process_single_frame = spy_process
        t0 = time.monotonic()
        worker.run()
        elapsed = time.monotonic() - t0

        self.assertEqual(len(captured_tracks), len(frames))
        self.assertLess(elapsed, 0.45)
        self.assertTrue(any(42 in t for t in captured_tracks))
