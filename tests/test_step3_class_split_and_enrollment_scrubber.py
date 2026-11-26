"""Tests for Step 3 Milestone 3: COCO vs. Gallery Class Split and Enrollment Scrubber."""

import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock

import numpy as np

from dashboard.routers.system import get_system_capabilities
from dashboard.schemas import (
    CameraAddRequest,
    CameraUpdateRequest,
    VideoAddAsCameraRequest,
    VideoAnalyzeRequest,
)
from dashboard.services.camera_config_store import CameraConfigStore
from dashboard.services.stream_pool_coordinator import _build_custom_cfg
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.matching.gallery import GalleryMatcher
from intelligent_tracker.pipeline.config import PipelineConfig
from intelligent_tracker.tracker import Track

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "dashboard" / "static"


def _run_node_vm(js_files: list[Path], script: str) -> dict:
    """Execute a Node.js vm.runInContext test harness and return parsed JSON."""
    if not shutil.which("node"):
        raise unittest.SkipTest("node binary not available")
    files_json = json.dumps([str(p) for p in js_files])
    harness = f"""
const fs = require('fs');
const vm = require('vm');
const files = {files_json};
const ctx = vm.createContext({{ console, JSON, Math, Number, String, Array, Object, Boolean, Promise, RegExp, encodeURIComponent, setTimeout, clearTimeout }});
ctx.window = ctx;
ctx.globalThis = ctx;
{script}
"""
    proc = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=20, check=False)
    if proc.returncode != 0:
        raise AssertionError(f"Node VM failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


class TestStep3ClassSplitAndEnrollmentScrubber(unittest.TestCase):
    """Verify Milestone 3 backend filtering, budgets, and frontend Node VM contracts."""

    def test_system_capabilities_exposes_tracked_categories_and_coco_classes(self):
        caps = asyncio.run(get_system_capabilities(rsac=None))
        self.assertIn("coco_classes", caps)
        self.assertIn("person", caps["coco_classes"])
        self.assertIn("tracked_categories", caps)
        self.assertTrue(len(caps["tracked_categories"]) >= 1)
        self.assertIn("id", caps["tracked_categories"][0])

    def test_schemas_and_config_store_tracked_categories_persistence(self):
        req_add = CameraAddRequest(id="c1", name="Cam 1", source="synthetic", classes="person,car", tracked_categories="vip, staff")
        req_upd = CameraUpdateRequest(tracked_categories=["restricted"])
        req_vid = VideoAnalyzeRequest(classes=["person"], tracked_categories="vip")
        req_feed = VideoAddAsCameraRequest(tracked_categories=["staff", "vip"])
        self.assertEqual(req_add.tracked_categories, ["vip", "staff"])
        self.assertEqual(req_upd.tracked_categories, ["restricted"])
        self.assertEqual(req_vid.tracked_categories, ["vip"])
        self.assertEqual(req_feed.tracked_categories, ["staff", "vip"])

        with tempfile.TemporaryDirectory() as tmp:
            store = CameraConfigStore(config_file=os.path.join(tmp, "cameras.json"))
            entry = store.build_and_store_entry("c1", "Cam 1", "synthetic", classes=["person"], tracked_categories=["vip"])
            self.assertEqual(entry["tracked_categories"], ["vip"])
            custom_cfg = _build_custom_cfg(entry)
            self.assertEqual(custom_cfg["reid"]["tracked_categories"], ["vip"])
            pcfg = PipelineConfig.from_dict(custom_cfg, camera_id="c1")
            self.assertEqual(pcfg.detector_classes, ["person"])
            self.assertEqual(pcfg.tracked_categories, ["vip"])

    def test_gallery_matcher_filters_by_tracked_categories_decoupled_from_coco(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        db = TrackerDB(db_path=os.path.join(tmp, "test.db"))
        self.addCleanup(db.close)
        vec = np.ones(8, dtype=np.float32) / np.sqrt(8.0)
        eid_vip = db.add_entity("Alice VIP", category="vip")
        eid_staff = db.add_entity("Bob Staff", category="staff")
        db.add_signature(eid_vip, vec, is_anchor=True)
        db.add_signature(eid_staff, vec * 0.99, is_anchor=True)

        ext = MagicMock()
        ext.embedding_dim = 8
        ext.extract.return_value = vec
        frame = np.zeros((64, 64, 3), dtype=np.uint8)

        m_vip = GalleryMatcher(db=db, extractor=ext, reid_threshold=0.5, min_track_hits=1, tracked_categories=["vip"])
        trk1 = Track(track_id=1, bbox=(5, 5, 30, 30), label="person")
        trk1.hits = 2
        ev1 = m_vip.match_track(trk1, frame, timestamp=10.0)
        self.assertIsNotNone(ev1)
        self.assertEqual(ev1.entity_id, eid_vip)

        m_only_restricted = GalleryMatcher(db=db, extractor=ext, reid_threshold=0.5, min_track_hits=1, tracked_categories=["restricted"])
        trk2 = Track(track_id=2, bbox=(5, 5, 30, 30), label="person")
        trk2.hits = 2
        ev2 = m_only_restricted.match_track(trk2, frame, timestamp=11.0)
        self.assertIsNone(ev2)

    def test_modularity_budgets_and_scrubber_timeline_slider_contract(self):
        budgets = {
            STATIC_DIR / "video_scrubber.js": 340,
            STATIC_DIR / "js" / "scrubber_timeline_slider.js": 181,
            STATIC_DIR / "index.html": 180,
            STATIC_DIR / "js" / "camera_ai_config.js": 280,
            REPO_ROOT / "dashboard" / "services" / "camera_config_store.py": 180,
            REPO_ROOT / "dashboard" / "services" / "stream_pool_coordinator.py": 240,
        }
        for path, limit in budgets.items():
            lines = len(path.read_text(encoding="utf-8").splitlines())
            self.assertLess(lines, limit, f"{path.name} has {lines} lines (limit < {limit})")

        res = _run_node_vm(
            [STATIC_DIR / "js" / "scrubber_timeline_slider.js"],
            """
const makeEl = () => ({ listeners: {}, style: {}, textContent: '', value: '0', classList: { add(){}, remove(){} }, addEventListener(t, fn){ (this.listeners[t] ||= []).push(fn); } });
const vid = { paused: true, currentTime: 0, duration: 10, videoWidth: 320, videoHeight: 240, play: async () => { vid.paused = false; }, pause: () => { vid.paused = true; }, listeners: {}, addEventListener(t, fn){ (this.listeners[t] ||= []).push(fn); } };
const slider = makeEl(), timeDisp = makeEl(), playBtn = makeEl(), prevBtn = makeEl(), nextBtn = makeEl();
ctx.document = { getElementById: () => null };
vm.runInContext(fs.readFileSync(files[0], 'utf8'), ctx);
const ctrl = ctx.ScrubberTimelineSlider.create({ videoPlayer: vid, slider, timeDisplay: timeDisp, playBtn, prevBtn, nextBtn, standaloneDisplay: true });
ctrl.bind();
ctrl.stepFrame(3);
console.log(JSON.stringify({ t: vid.currentTime, disp: timeDisp.textContent, slider: slider.value }));
""",
        )
        self.assertAlmostEqual(res["t"], 0.1, delta=0.01)
        self.assertEqual(res["disp"], "00:00 / 00:10")

    def test_enrollment_recorded_video_scrubber_captures_onto_canvas(self):
        js_files = [STATIC_DIR / "js" / "scrubber_timeline_slider.js", STATIC_DIR / "js" / "universal_enrollment.js"]
        res = _run_node_vm(
            js_files,
            """
const makeEl = (id) => ({ id, style: {}, value: '', innerHTML: '', options: [], selectedIndex: 0, dataset: {}, listeners: {}, classList: { add(){}, remove(){}, toggle(){} }, addEventListener(t, fn){ (this.listeners[t] ||= []).push(fn); }, dispatchEvent(e){ (this.listeners[e.type] || []).forEach(fn => fn(e)); }, getContext: () => ({ drawImage(){}, clearRect(){}, strokeRect(){}, fillRect(){} }), toDataURL: () => 'data:image/jpeg;base64,VIDFRAME' });
const els = {};
['modal-universal-enrollment','enroll-camera-select','enroll-bbox-canvas','enroll-canvas-placeholder','enroll-video-scrubber-box','enroll-scrubber-video','enroll-scrubber-slider','enroll-scrubber-time','enroll-scrubber-play','enroll-scrubber-prev','enroll-scrubber-next','enroll-scrubber-grab','enroll-category-select','enroll-crop-preview-box','enroll-crop-preview-img','enroll-crop-meta','enroll-collision-banner','universal-enrollment-form','enroll-file-input','btn-open-enrollment','modal-enroll-close','modal-enroll-cancel','btn-capture-freeze','btn-upload-enroll-crop'].forEach(id => els[id] = makeEl(id));
els['enroll-scrubber-video'].videoWidth = 640; els['enroll-scrubber-video'].videoHeight = 360; els['enroll-scrubber-video'].duration = 20; els['enroll-scrubber-video'].paused = true; els['enroll-scrubber-video'].load = () => {};
ctx.document = { getElementById: (id) => els[id] || null, createElement: () => makeEl('tmp') };
ctx.Image = class { set src(v){ if (this.onload) this.onload(); } get naturalWidth(){ return 640; } get naturalHeight(){ return 360; } };
ctx.fetch = async (url) => ({ ok: true, json: async () => url.includes('/api/videos') ? { videos: [{ filename: 'lobby.mp4', video_url: '/videos/lobby.mp4' }] } : (url.includes('/api/cameras') ? [{ id: 'cam_01', name: 'Lobby' }] : [{ id: 'vip', name: 'VIP' }]) });
files.forEach(f => vm.runInContext(fs.readFileSync(f, 'utf8'), ctx));
vm.runInContext(`(async () => {
  UniversalEnrollment.init();
  await UniversalEnrollment.populateCameraSelect();
  const sel = document.getElementById('enroll-camera-select');
  sel.value = 'video:lobby.mp4';
  sel.options = [{ value: 'video:lobby.mp4', getAttribute: () => '/videos/lobby.mp4' }];
  sel.dispatchEvent({ type: 'change', target: sel });
  const vid = document.getElementById('enroll-scrubber-video');
  vid.currentTime = 5;
  vid.dispatchEvent({ type: 'seeked' });
  console.log(JSON.stringify({ html: sel.innerHTML, boxDisp: document.getElementById('enroll-video-scrubber-box').style.display, canvasW: document.getElementById('enroll-bbox-canvas').width }));
})();`, ctx);
""",
        )
        self.assertIn('<optgroup label="Camera Profiles">', res["html"])
        self.assertIn('<optgroup label="Recorded Videos">', res["html"])
        self.assertEqual(res["boxDisp"], "block")
        self.assertEqual(res["canvasW"], 640)

    def test_coco_vs_gallery_ui_split_across_camera_batch_and_feed_modals(self):
        js_files = [STATIC_DIR / "js" / "camera_form_helpers.js", STATIC_DIR / "js" / "camera_ai_config.js"]
        res = _run_node_vm(
            js_files,
            """
const makeEl = (id) => ({ id, value: '', textContent: '', innerHTML: '', checked: false, style: {}, classList: { toggle(){}, add(){}, remove(){} }, addEventListener(){}, querySelectorAll: () => [], parentElement: null });
const els = {};
['cam-detector-select','cam-tracker-select','cam-conf-range','cam-conf-input','cam-conf-display','cam-classes-input','cam-armed-checkbox','cam-source-input'].forEach(id => els[id] = makeEl(id));
const lbl = makeEl('lbl');
const parentGroup = { parentNode: { insertBefore: (el) => { els[el.id] = el; els['cam-tracked-categories-input'] = makeEl('cam-tracked-categories-input'); } } };
els['cam-classes-input'].parentElement = parentGroup;
ctx.document = { readyState: 'complete', getElementById: (id) => els[id] || null, querySelector: (s) => s.includes('cam-classes-input') ? lbl : null, querySelectorAll: () => [], createElement: () => makeEl('new') };
ctx.fetch = async () => ({ ok: true, json: async () => ({ detectors: ['yolov8'], trackers: ['centroid'], tracked_categories: [{ id: 'vip', name: 'VIP' }] }) });
files.forEach(f => vm.runInContext(fs.readFileSync(f, 'utf8'), ctx));
vm.runInContext(`(async () => {
  await CameraAIConfig.loadCapabilities();
  CameraAIConfig.setValues({ detector: 'yolov8', tracker: 'centroid', classes: ['person'], tracked_categories: ['vip', 'staff'] });
  const vals = CameraAIConfig.getValues();
  console.log(JSON.stringify({ label: document.querySelector('label[for="cam-classes-input"]').textContent, vals }));
})();`, ctx);
""",
        )
        self.assertIn("Detector Classes (COCO)", res["label"])
        self.assertEqual(res["vals"]["classes"], ["person"])
        self.assertEqual(res["vals"]["tracked_categories"], ["vip", "staff"])


if __name__ == "__main__":
    unittest.main()
