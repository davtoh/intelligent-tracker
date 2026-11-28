"""Step 2 unit and Node VM tests for synthetic Re-ID parity, live ROI preview, and camera/batch config."""

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from dashboard.camera_pool import CameraPool
from dashboard.routers.system import get_system_capabilities
from dashboard.services import video_analytics_service as vas
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.detectors import MockDetector
from intelligent_tracker.enrollment import UniversalEnrollmentManager
from intelligent_tracker.matching import GalleryMatcher
from intelligent_tracker.rsac import RSACManager
from intelligent_tracker.tracker import Track
from intelligent_tracker.video.synthetic import SyntheticFrameGenerator

REPO = Path(__file__).resolve().parents[1]
JS = REPO / "dashboard" / "static" / "js"


def _run_node(script: str) -> dict:
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False, timeout=20)
    if proc.returncode != 0:
        raise AssertionError(f"Node VM failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return json.loads(proc.stdout.strip())


class TestStep2SyntheticReIDAndConfig(unittest.TestCase):
    """Backend tests for MockDetector synthetic parity, Re-ID match, and config round-trips."""

    def _temp_dir(self) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return tmp.name

    def test_mock_detector_aligns_with_synthetic_p1_p2_and_falls_back(self) -> None:
        det = MockDetector(width=640, height=480)
        blank_dets = det.detect(np.zeros((480, 640, 3), dtype=np.uint8))
        self.assertEqual(len(blank_dets), 1)
        self.assertEqual(blank_dets[0].bbox[2:], (60, 120))

        gen = SyntheticFrameGenerator(width=640, height=480, fps=30)
        ok, frame = gen.read()
        self.assertTrue(ok and frame is not None)
        synth_dets = det.detect(frame)
        self.assertEqual(len(synth_dets), 2)
        widths_heights = sorted([d.bbox[2:] for d in synth_dets])
        self.assertEqual(widths_heights, [(37, 81), (41, 91)])

    def test_synthetic_p1_enroll_matches_p1_not_p2(self) -> None:
        tmp = self._temp_dir()
        db = TrackerDB(os.path.join(tmp, "tracker.db"))
        self.addCleanup(db.close)
        gen = SyntheticFrameGenerator(width=640, height=480, fps=30)
        det = MockDetector(width=640, height=480)
        _, frame1 = gen.read()
        dets1 = det.detect(frame1)
        p1_box1 = next(d.bbox for d in dets1 if d.bbox[2:] == (41, 91))

        enroll_mgr = UniversalEnrollmentManager(db=db, crops_dir=os.path.join(tmp, "crops"))
        res = enroll_mgr.enroll(name="P1", category="person", frame=frame1, bbox=p1_box1)
        eid = res["entity_id"]

        for _ in range(15):
            gen.read()
        _, frame2 = gen.read()
        dets2 = det.detect(frame2)
        p1_box2 = next(d.bbox for d in dets2 if d.bbox[2:] == (41, 91))
        p2_box2 = next(d.bbox for d in dets2 if d.bbox[2:] == (37, 81))

        matcher = GalleryMatcher(db=db, extractor=enroll_mgr.extractor, reid_threshold=0.5, min_track_hits=1)
        t_p1 = Track(track_id=1, bbox=p1_box2, label="mock_person")
        t_p1.hits = 2
        ev1 = matcher.match_track(t_p1, frame2, timestamp=1.0)
        self.assertIsNotNone(ev1)
        self.assertEqual(ev1.entity_id, eid)

        t_p2 = Track(track_id=2, bbox=p2_box2, label="mock_person")
        t_p2.hits = 2
        ev2 = matcher.match_track(t_p2, frame2, timestamp=1.1)
        self.assertIsNone(ev2)

    def test_camera_pool_exposes_tracked_categories_and_agnostic_nms(self) -> None:
        tmp = self._temp_dir()
        cfg_file = os.path.join(tmp, "cameras.json")
        db_file = os.path.join(tmp, "tracker.db")
        pool = CameraPool(config_file=cfg_file, db_path=db_file, autostart=False)
        self.addCleanup(pool.stop_all)
        pool.add_camera(
            "cam_edit", "Edit Cam", "synthetic", cam_type="synthetic",
            detector="mock", tracker="sort", tracked_categories=["vip", "staff"],
            agnostic_nms=False, enabled=False, autostart=False,
        )
        row = next(r for r in pool.list_cameras() if r["id"] == "cam_edit")
        self.assertEqual(row["tracked_categories"], ["vip", "staff"])
        self.assertFalse(row["agnostic_nms"])
        pool.update_camera("cam_edit", tracked_categories=["restricted"], agnostic_nms=True)
        row2 = next(r for r in pool.list_cameras() if r["id"] == "cam_edit")
        self.assertEqual(row2["tracked_categories"], ["restricted"])
        self.assertTrue(row2["agnostic_nms"])

    def test_video_analytics_config_meta_and_capabilities_entities(self) -> None:
        tmp = self._temp_dir()
        db = TrackerDB(os.path.join(tmp, "cap.db"))
        self.addCleanup(db.close)
        db.add_entity("P1", "person")
        caps = asyncio.run(get_system_capabilities(rsac=RSACManager(db=db), db=db))
        self.assertTrue(any(e["name"] == "P1" for e in caps["enrolled_entities"]))

        fake_idx = MagicMock()
        fake_idx.process_video.return_value = {"processed_frames": 1}
        fake_idx.generate_occurrence_report.return_value = {}
        fake_idx.analytics = None
        fake_idx.event_bus = None
        fake_idx._fts_index = None
        fake_idx._collected_alerts = []
        opts = vas.parse_analyze_options(1, "mock", 0.4, None, False, None, tracked_categories="vip,staff")
        with (
            patch.object(vas, "_resolve_db", return_value=db),
            patch.object(vas, "create_video_indexer", return_value=fake_idx),
            patch.object(vas, "save_report_run", return_value={"run_id": "run_1"}) as save_mock,
        ):
            vas.run_sync_analytics("demo.mp4", os.path.join(tmp, "demo.mp4"), opts)
        self.assertEqual(save_mock.call_args.kwargs["config"]["tracked_categories"], ["vip", "staff"])


@unittest.skipUnless(shutil.which("node"), "Node.js required for JS VM tests")
class TestStep2FrontendContracts(unittest.TestCase):
    """Node VM tests for OBS-004, OBS-006, OBS-010, and OBS-018."""

    def test_gallery_load_resets_filters_for_newly_enrolled_entity(self) -> None:
        script = (
            "const fs = require('fs'), vm = require('vm');\n"
            f"const code = fs.readFileSync({json.dumps(str(JS / 'gallery_timeline.js'))}, 'utf8');\n"
            "const grid = { innerHTML: '' }, search = { value: 'missing' };\n"
            "const mkPill = (cat, act) => ({ cls: new Set(act ? ['active'] : []), getAttribute: (k) => k === 'data-category' ? cat : null, classList: { toggle: (c, v) => v ? mkPill._s(cat, true) : mkPill._s(cat, false), contains: (c) => mkPill._g(cat) } });\n"
            "const pillState = { '': false, 'vip': true }; mkPill._s = (k, v) => { pillState[k] = v; }; mkPill._g = (k) => !!pillState[k];\n"
            "const pAll = mkPill('', false), pVip = mkPill('vip', true);\n"
            "const doc = { getElementById: (id) => ({ 'entity-gallery-grid': grid, 'gallery-search-input': search }[id] || null), querySelector: (s) => s === '.filter-pill.active' ? (pillState['vip'] ? pVip : pAll) : null, querySelectorAll: (s) => s.includes('filter-pill') ? [pAll, pVip] : [] };\n"
            "const win = {}; const sb = { window: win, document: doc, fetch: async () => ({ json: async () => [{ id: 42, name: 'P1', category: 'person' }] }), console, Math, Number, String, Boolean, Array, Object, JSON, Promise };\n"
            "vm.runInNewContext(code, sb);\n"
            "(async () => {\n"
            "  await win.GalleryTimeline.loadGallery({ highlightEntityId: 42 });\n"
            "  process.stdout.write(JSON.stringify({ search: search.value, allActive: pillState[''], vipActive: pillState['vip'], html: grid.innerHTML }));\n"
            "})();\n"
        )
        out = _run_node(script)
        self.assertEqual(out["search"], "")
        self.assertTrue(out["allActive"])
        self.assertFalse(out["vipActive"])
        self.assertIn("P1", out["html"])

    def test_roi_draw_triggers_debounced_collision_and_ai_suggestion(self) -> None:
        script = (
            "const fs = require('fs'), vm = require('vm');\n"
            f"const sCode = fs.readFileSync({json.dumps(str(JS / 'enrollment_stage_controller.js'))}, 'utf8');\n"
            "const meta = { textContent: '' }, banner = { style: { display: 'none' }, innerHTML: '' };\n"
            "const doc = { getElementById: (id) => ({ 'enroll-crop-meta': meta, 'enroll-collision-banner': banner }[id] || null) };\n"
            "const calls = [];\n"
            "const fakeFetch = async (url) => { calls.push(url); return url.includes('check-collision') ? { ok: true, json: async () => ({ has_collision: true, matches: [{ entity_id: 7, name: 'P1', similarity: 0.94 }] }) } : { ok: true, json: async () => ({ status: 'success', data: { classification: { label: 'person', confidence: 0.91 }, candidates: [{ entity_id: 7, name: 'P1', category: 'person', similarity: 0.94, is_known: true }] } }) }; };\n"
            "const win = {}; const sb = { window: win, document: doc, fetch: fakeFetch, setTimeout: (fn) => { setImmediate(fn); return 1; }, clearTimeout: () => {}, Promise, console, Math, Number, String, Array, Object, JSON };\n"
            "vm.runInNewContext(sCode, sb);\n"
            "win.EnrollmentStageController.scheduleRoiPreviewCheck({ camera_id: 'cam_01', bbox: [10, 10, 40, 90], crop_base64: 'data:image/jpeg;base64,AA==', baseMetaText: 'Region: 40x90 px at (10, 10)' });\n"
            "setImmediate(() => setTimeout(() => process.stdout.write(JSON.stringify({ calls, meta: meta.textContent, bannerDisplay: banner.style.display, bannerHtml: banner.innerHTML })), 20));\n"
        )
        out = _run_node(script)
        self.assertEqual(len(out["calls"]), 2)
        self.assertIn("AI: person (91%)", out["meta"])
        self.assertEqual(out["bannerDisplay"], "block")
        self.assertIn("Merge into P1", out["bannerHtml"])

    def test_camera_config_roundtrip_and_batch_gallery_hint(self) -> None:
        script = (
            "const fs = require('fs'), vm = require('vm');\n"
            f"const pCode = fs.readFileSync({json.dumps(str(JS / 'detector_config_panel.js'))}, 'utf8');\n"
            f"const hCode = fs.readFileSync({json.dumps(str(JS / 'camera_form_helpers.js'))}, 'utf8');\n"
            f"const bCode = fs.readFileSync({json.dumps(str(JS / 'video_batch.js'))}, 'utf8');\n"
            "const catsInp = { id: 'cam-tracked-categories-input', value: '' };\n"
            "const nmsEl = { checked: true };\n"
            "const camHint = { innerHTML: '', textContent: '', querySelectorAll: () => [] };\n"
            "const batchHint = { innerHTML: '', textContent: '', querySelectorAll: () => [] };\n"
            "const batchModal = { style: { display: 'none' }, addEventListener: () => {} };\n"
            "const els = { 'cam-tracked-categories-input': catsInp, 'cam-agnostic-nms-checkbox': nmsEl, 'cam-detector-select': { value: 'mock' }, 'cam-tracker-select': { value: 'sort' }, 'cam-conf-input': { value: '0.40' }, 'cam-classes-input': { value: '' }, 'cam-armed-checkbox': { checked: false }, 'cam-gallery-entities-hint': camHint, 'batch-gallery-entities-hint': batchHint, 'modal-video-batch-analyze': batchModal, 'cam-tracked-categories-group': { id: 'cam-tracked-categories-group' } };\n"
            "const doc = { readyState: 'complete', getElementById: (id) => els[id] || null, querySelector: () => null, querySelectorAll: () => [], addEventListener: () => {} };\n"
            "const win = { addEventListener: () => {} }; const sb = { window: win, document: doc, fetch: async (u) => ({ ok: true, json: async () => u === '/entities' ? [{ id: 1, name: 'P1', category: 'person' }] : { cameras: {} } }), console, Math, Number, String, Boolean, Array, Object, Set, JSON, Promise, CustomEvent: class {} };\n"
            "vm.runInNewContext(pCode, sb); vm.runInNewContext(hCode, sb); vm.runInNewContext(bCode, sb);\n"
            "win.DetectorConfigPanel.applyValues({ agnostic_nms: false }); catsInp.value = 'vip';\n"
            "const payload = win.CameraFormHelpers.buildCameraPayload({ id: 'c1', name: 'C1', source: 'synthetic', aiConfig: win.DetectorConfigPanel.readValues() });\n"
            "win.CameraFormHelpers.syncTrackedCategoriesUI({ enrolled_entities: [{ id: 1, name: 'P1', category: 'person' }] });\n"
            "win.VideoBatch.openBatchModal('clip.mp4');\n"
            "setTimeout(() => process.stdout.write(JSON.stringify({ payload, camHint: camHint.innerHTML, batchHint: batchHint.innerHTML })), 20);\n"
        )
        out = _run_node(script)
        self.assertEqual(out["payload"]["tracked_categories"], ["vip"])
        self.assertFalse(out["payload"]["agnostic_nms"])
        self.assertIn("P1 (person)", out["camHint"])
        self.assertIn("P1 (person)", out["batchHint"])
