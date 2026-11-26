"""Tests for Step 3 Milestone 1: SORT + ByteTrack 2-stage association, defaults, and ownership."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from types import SimpleNamespace

import numpy as np

from dashboard.services.camera_cfg_builder import build_custom_cfg
from dashboard.services.camera_config_store import CameraConfigStore
from dashboard.services.stream_pool_coordinator import _build_custom_cfg
from dashboard.services.video_analytics_service import parse_analyze_options
from intelligent_tracker.batch import VideoIndexer
from intelligent_tracker.detectors.base import Detection
from intelligent_tracker.detectors.onnx_detector import OnnxDetector
from intelligent_tracker.pipeline.config import PipelineConfig, load_pipeline_config
from intelligent_tracker.tracker.bytetrack_association import (
    associate_two_stage,
    split_detections_by_confidence,
)
from intelligent_tracker.tracker.sort import SortTracker
from intelligent_tracker.tracker.track import Track
from intelligent_tracker.world import WorldGraph
from intelligent_tracker.world.ownership import OwnershipAssociationEngine

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "dashboard" / "static"


def _make_det(bbox: tuple[int, int, int, int], conf: float, label: str = "person", class_id: int = 0) -> Detection:
    """Create a Detection fixture with explicit bbox, confidence, and label."""
    return Detection(bbox=bbox, class_id=class_id, confidence=conf, label=label)


def _run_node_panel(script: str) -> dict:
    """Execute a Node.js vm.runInContext check for detector_config_panel.js."""
    if not shutil.which("node"):
        raise unittest.SkipTest("node binary not available")
    js_path = STATIC_DIR / "js" / "detector_config_panel.js"
    harness = f"""
const fs = require('fs');
const vm = require('vm');
const ctx = vm.createContext({{ console, JSON, Math, Number, String, Array, Object, Boolean, RegExp }});
ctx.window = ctx;
ctx.globalThis = ctx;
vm.runInContext(fs.readFileSync({json.dumps(str(js_path))}, 'utf8'), ctx);
vm.runInContext({json.dumps(script)}, ctx);
"""
    proc = subprocess.run(["node", "-e", harness], capture_output=True, text=True, check=True)
    return json.loads(proc.stdout.strip().splitlines()[-1])


class TestByteTrackAndDefaults(unittest.TestCase):
    """Verify ByteTrack 2-stage association, default config propagation, and ownership classes."""

    def test_split_detections_by_confidence(self) -> None:
        high, low = split_detections_by_confidence([0.8, 0.25, 0.05, 0.4], 0.4, 0.1)
        self.assertEqual(high, [0, 3])
        self.assertEqual(low, [1])
        high_off, low_off = split_detections_by_confidence([0.8, 0.25, 0.05], 0.4, 0.0)
        self.assertEqual(high_off, [0, 1, 2])
        self.assertEqual(low_off, [])

    def test_two_stage_association_suppresses_unmatched_low_conf_spawns(self) -> None:
        matches, unmatched_high = associate_two_stage(
            predicted_boxes=[(100, 100, 40, 80)],
            det_bboxes=[(102, 100, 40, 80), (300, 300, 40, 40), (400, 400, 30, 30)],
            det_scores=[0.2, 0.85, 0.15],
            trk_labels=["person"],
            trk_classes=[0],
            trk_embs=[None],
            det_labels=["person", "person", "person"],
            det_classes=[0, 0, 0],
            iou_threshold=0.3,
            high_conf_threshold=0.4,
            low_conf_threshold=0.1,
        )
        self.assertEqual(matches, [(0, 0)])
        self.assertEqual(unmatched_high, [1])

    def test_sort_tracker_bridges_low_conf_occlusion_and_blocks_phantom_tracks(self) -> None:
        tracker = SortTracker(min_hits=1, iou_threshold=0.3, high_conf_threshold=0.4, low_conf_threshold=0.1)
        t0 = tracker.update([_make_det((100, 100, 50, 100), 0.9)], timestamp=1.0)
        self.assertEqual(len(t0), 1)
        tid = next(iter(t0))

        t1 = tracker.update(
            [_make_det((104, 100, 50, 100), 0.2), _make_det((420, 320, 40, 60), 0.18)],
            timestamp=1.1,
        )
        self.assertEqual(list(t1.keys()), [tid])

        t2 = tracker.update([_make_det((108, 100, 50, 100), 0.85)], timestamp=1.2)
        self.assertEqual(list(t2.keys()), [tid])

    def test_sort_tracker_single_stage_when_low_conf_disabled(self) -> None:
        tracker = SortTracker(min_hits=1, iou_threshold=0.3, high_conf_threshold=0.4, low_conf_threshold=0.0)
        tracks = tracker.update([_make_det((200, 200, 40, 60), 0.2)], timestamp=1.0)
        self.assertEqual(len(tracks), 1)

    def test_onnx_filter_candidates_respects_low_conf_threshold(self) -> None:
        det = OnnxDetector.__new__(OnnxDetector)
        det.conf_threshold = 0.4
        det.low_conf_threshold = 0.1
        det.classes = {0}
        preds = np.array(
            [[100.0, 100.0, 20.0, 40.0, 0.8, 0.1], [200.0, 200.0, 20.0, 40.0, 0.2, 0.05], [300.0, 300.0, 20.0, 40.0, 0.05, 0.01]],
            dtype=np.float32,
        )
        filtered = det._filter_candidates(preds)
        self.assertIsNotNone(filtered)
        assert filtered is not None
        self.assertEqual(len(filtered[5]), 2)
        det.low_conf_threshold = None
        filtered_hi = det._filter_candidates(preds)
        assert filtered_hi is not None
        self.assertEqual(len(filtered_hi[5]), 1)

    def test_sort_and_ownership_classes_defaults_everywhere(self) -> None:
        raw_default = load_pipeline_config("configs/default.yaml")
        self.assertEqual(raw_default["tracker"]["type"], "sort")
        self.assertEqual(raw_default["tracker"]["min_hits"], 3)
        self.assertEqual(raw_default["tracker"]["high_conf_threshold"], 0.4)
        self.assertEqual(raw_default["tracker"]["low_conf_threshold"], 0.1)
        self.assertEqual(raw_default["detector"]["classes"], ["person", "backpack", "handbag", "suitcase"])

        cfg = PipelineConfig.from_dict(raw_default)
        self.assertEqual(cfg.tracker_type, "sort")
        self.assertEqual(cfg.tracker_high_conf_threshold, 0.4)
        self.assertEqual(cfg.tracker_low_conf_threshold, 0.1)

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = CameraConfigStore(config_file=os.path.join(tmp.name, "cameras.json"))
        loaded, seeded = store.load_cameras()
        self.assertTrue(seeded)
        self.assertEqual(loaded["cam_01"]["tracker"], "sort")
        entry = store.build_and_store_entry("cam_02", "Side Door", "synthetic", cam_type="synthetic", high_conf_threshold=0.5)
        self.assertEqual(entry["tracker"], "sort")
        self.assertEqual(entry["high_conf_threshold"], 0.5)

        indexer = VideoIndexer(db_path=os.path.join(tmp.name, "batch.db"), detector_name="mock", reid_name="color")
        self.addCleanup(indexer.close)
        self.assertIsInstance(indexer.tracker, SortTracker)

    def test_custom_cfg_builder_and_video_options_propagate_tracker_tuning(self) -> None:
        built = build_custom_cfg(
            {
                "detector": "yolov8",
                "confidence": 0.35,
                "classes": ["person", "backpack"],
                "agnostic_nms": True,
                "tracker": "sort",
                "min_hits": 4,
                "iou_threshold": 0.35,
                "high_conf_threshold": 0.45,
                "low_conf_threshold": 0.12,
                "tracked_categories": ["vip"],
            }
        )
        self.assertEqual(built, _build_custom_cfg({
            "detector": "yolov8", "confidence": 0.35, "classes": ["person", "backpack"],
            "agnostic_nms": True, "tracker": "sort", "min_hits": 4, "iou_threshold": 0.35,
            "high_conf_threshold": 0.45, "low_conf_threshold": 0.12, "tracked_categories": ["vip"],
        }))
        assert built is not None
        self.assertTrue(built["detector"]["agnostic_nms"])
        self.assertEqual(built["tracker"]["low_conf_threshold"], 0.12)
        self.assertEqual(built["reid"]["tracked_categories"], ["vip"])
        opts = parse_analyze_options(2, "mock", 0.3, None, False, SimpleNamespace(sample_rate=None, detector=None, confidence=None, classes=None, tracked_categories=None, async_mode=None, scenario_camera_id=None, tracker="sort"))
        self.assertEqual(opts["tracker"], "sort")

    def test_ownership_engine_activates_carries_and_owned_by_edges(self) -> None:
        graph = WorldGraph()
        engine = OwnershipAssociationEngine(graph, min_carry_seconds=0.5)
        tracks = {
            1: Track(track_id=1, bbox=(100, 100, 60, 140), centroid=(130.0, 170.0), label="person"),
            2: Track(track_id=2, bbox=(115, 145, 35, 35), centroid=(132.0, 162.0), label="backpack"),
            3: Track(track_id=3, bbox=(125, 155, 30, 30), centroid=(140.0, 170.0), label="handbag"),
        }
        engine.update("cam_01", tracks, timestamp=10.0)
        engine.update("cam_01", tracks, timestamp=11.0)
        relations = {(e.source_id, e.relation, e.target_id) for e in graph.get_edges()}
        self.assertIn(("track:cam_01:1", "CARRIES", "track:cam_01:2"), relations)
        self.assertIn(("track:cam_01:2", "OWNED_BY", "track:cam_01:1"), relations)
        self.assertIn(("track:cam_01:1", "CARRIES", "track:cam_01:3"), relations)

    def test_detector_config_panel_person_bags_preset_and_sort_default(self) -> None:
        html = (STATIC_DIR / "partials" / "modals" / "detector_config_panel.html").read_text(encoding="utf-8")
        self.assertIn('data-classes="person, backpack, handbag, suitcase"', html)
        self.assertIn('<option value="sort" selected>', html)
        res = _run_node_panel(
            """
function mkBtn(classes) {
  const cls = new Set();
  return {
    dataset: {}, listeners: {},
    classList: { add: (c) => cls.add(c), remove: (c) => cls.delete(c), has: (c) => cls.has(c) },
    getAttribute: (k) => (k === 'data-classes' ? classes : ''),
    addEventListener(ev, fn) { this.listeners[ev] = fn; },
    click() { this.listeners.click && this.listeners.click(); },
  };
}
const btnBags = mkBtn('person, backpack, handbag, suitcase');
const inp = { value: '', dataset: {}, addEventListener() {} };
const panel = { querySelectorAll: () => [btnBags] };
const els = { 'cam-classes-input': inp, 'detector-config-panel': panel };
var document = { getElementById: (id) => els[id] || null };
DetectorConfigPanel.bindPanelEvents();
btnBags.click();
const vals = DetectorConfigPanel.readValues();
console.log(JSON.stringify({ classes: inp.value, active: btnBags.classList.has('active'), tracker: vals.tracker }));
"""
        )
        self.assertEqual(res["classes"], "person, backpack, handbag, suitcase")
        self.assertTrue(res["active"])
        self.assertEqual(res["tracker"], "sort")
