"""Unit tests for Step 4 Milestone 3: Live-record FrameStepResult handoff & export UI."""

import json
import os
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

import numpy as np

from dashboard.services.stream_recording import StreamRecordingController
from dashboard.services.stream_worker import StreamWorker
from dashboard.stream_manager import StreamManager
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.pipeline.frame_processor import FrameStepResult


class _FakeWriter:
    """Minimal in-memory writer stub for deterministic recording handoff tests."""

    def __init__(self, path: str, fps: float = 20.0, resolution: tuple[int, int] = (96, 64), **kwargs) -> None:
        self.path = path
        self.fps = fps
        self.resolution = resolution
        self.is_open = True
        self.frames = 0

    def write(self, frame: np.ndarray) -> bool:
        self.frames += 1
        return True

    def release(self) -> None:
        self.is_open = False

    def snapshot(self) -> dict:
        return {
            "codec": "mp4v",
            "fps": self.fps,
            "width": self.resolution[0],
            "height": self.resolution[1],
            "frames_written": self.frames,
            "elapsed_s": round(self.frames / max(1.0, self.fps), 3),
            "size_bytes": 1024,
        }


class _FakeTrack:
    """Minimal track stub exposing to_dict()."""

    def __init__(self, track_id: int, entity_id: int | None = None) -> None:
        self._data = {"track_id": track_id, "bbox": [10, 10, 40, 50], "entity_id": entity_id, "label": "person"}

    def to_dict(self) -> dict:
        return dict(self._data)


class TestLiveRecordingHandoff(unittest.TestCase):
    """Verify live recording metadata buffering, TrackerDB persistence, and export UI."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.db = TrackerDB(db_path=os.path.join(self.tmpdir.name, "tracker.db"))
        self.addCleanup(self.db.close)

    def test_live_capture_handoff_persists_run_and_detection_stream(self) -> None:
        """Stopping a live recording with FrameStepResult persists a live_capture run."""
        ctrl = StreamRecordingController(
            "cam_01", output_dir=self.tmpdir.name, writer_factory=_FakeWriter, db_getter=lambda: self.db
        )
        ctrl.start(filename="live_clip.mp4", fps=20.0, resolution=(96, 64))
        frame = np.zeros((64, 96, 3), dtype=np.uint8)
        step1 = FrameStepResult(
            frame=frame, detections=[object()], tracks={1: _FakeTrack(1, entity_id=7)},
            identifications=[SimpleNamespace(entity_id=7)], timestamp=100.0, fps=20.0, frame_count=51,
        )
        step2 = FrameStepResult(
            frame=frame, detections=[object()], tracks={1: _FakeTrack(1, entity_id=7)},
            identifications=[], timestamp=100.5, fps=20.0, frame_count=52,
        )
        self.assertTrue(ctrl.write_frame(frame, frame, step_res=step1))
        self.assertTrue(ctrl.write_frame(frame, frame, step_res=step2))
        meta = ctrl.stop()

        self.assertIn("report_run_id", meta)
        runs = self.db.list_video_runs("live_clip.mp4")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["run_type"], "live_capture")
        self.assertEqual(runs[0]["report"]["frames_processed"], 2)
        self.assertEqual(runs[0]["report"]["total_sightings"], 1)
        self.assertEqual(runs[0]["report"]["unique_entities_identified"], 1)

        stream = self.db.get_video_detection_stream("live_clip.mp4")
        self.assertIsNotNone(stream)
        self.assertEqual(len(stream["frame_detections"]), 2)
        self.assertEqual(stream["frame_detections"][0]["time"], 0.0)
        self.assertEqual(stream["frame_detections"][1]["time"], 0.5)

    def test_live_capture_skips_db_when_db_getter_returns_none(self) -> None:
        """Recording without a resolved DB completes stop() without touching default DB."""
        ctrl = StreamRecordingController("cam_01", output_dir=self.tmpdir.name, writer_factory=_FakeWriter)
        ctrl.start(filename="no_db.mp4", fps=20.0, resolution=(96, 64))
        frame = np.zeros((64, 96, 3), dtype=np.uint8)
        step = FrameStepResult(frame=frame, tracks={1: _FakeTrack(1)}, timestamp=10.0, frame_count=1)
        ctrl.write_frame(frame, frame, step_res=step)
        meta = ctrl.stop()
        self.assertEqual(meta["status"], "stopped")
        self.assertNotIn("report_run_id", meta)

    def test_stream_worker_passes_step_res_and_manager_wires_db_getter(self) -> None:
        """StreamWorker forwards step_res to recorder and StreamManager wires db_getter."""
        mgr = StreamManager(
            db_path=os.path.join(self.tmpdir.name, "mgr.db"),
            camera_id="cam_01",
            source_override=0,
            custom_cfg={"video": {"width": 64, "height": 48}, "recording": {"output_dir": self.tmpdir.name}},
        )
        self.addCleanup(mgr.stop)
        self.assertTrue(callable(mgr._recording_controller._db_getter))
        mgr._recording_controller = MagicMock()
        mgr._recording_controller.is_recording = True
        worker = StreamWorker(mgr)
        worker._encode_raw_frame = MagicMock()
        worker._encode_annotated_frame = MagicMock(return_value=np.zeros((48, 64, 3), dtype=np.uint8))
        worker._build_telemetry = MagicMock(return_value={"camera_id": "cam_01"})
        mgr._broadcast_telemetry = MagicMock()
        step_res = FrameStepResult(frame=np.zeros((48, 64, 3), dtype=np.uint8), timestamp=1.0, frame_count=1)
        worker._process_single_frame(step_res)
        _, kwargs = mgr._recording_controller.write_frame.call_args
        self.assertIs(kwargs.get("step_res"), step_res)

    def test_video_batch_reports_renders_export_button_and_live_capture_badge(self) -> None:
        """video_batch_reports.js renders #btn-export-report-run and Live Capture badge."""
        if not shutil.which("node"):
            self.skipTest("Node.js not installed")
        js_path = os.path.join(os.path.dirname(__file__), "..", "dashboard", "static", "js", "video_batch_reports.js")
        script = f"""
const fs = require('fs');
const vm = require('vm');
const sandbox = {{ window: {{}}, localStorage: {{ getItem: () => null, setItem: () => {{}} }}, document: {{}}, console }};
vm.runInNewContext(fs.readFileSync({json.dumps(os.path.abspath(js_path))}, 'utf8'), sandbox);
const runs = [{{
  run_id: 'r_live',
  run_type: 'live_capture',
  config: {{ detector: 'live_pipeline', sample_rate: 1, confidence: 0.4 }},
  report: {{ frames_processed: 12, total_detections: 4, total_sightings: 2, unique_entities_identified: 1 }}
}}];
const html = sandbox.window.VideoBatchReports.renderReportCards(
  runs[0].report, 'live_clip.mp4', {{ detector: 'live_pipeline', sampleRate: 1, confidence: 0.4, runType: 'live_capture' }}, runs, 'r_live'
);
console.log(JSON.stringify({{
  hasExportBtn: html.includes('id="btn-export-report-run"'),
  hasExportHref: html.includes('/api/videos/live_clip.mp4/reports/r_live/export'),
  hasLiveBadge: html.includes('Live Capture')
}}));
"""
        proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
        out = json.loads(proc.stdout.strip())
        self.assertTrue(out["hasExportBtn"])
        self.assertTrue(out["hasExportHref"])
        self.assertTrue(out["hasLiveBadge"])


if __name__ == "__main__":
    unittest.main()
