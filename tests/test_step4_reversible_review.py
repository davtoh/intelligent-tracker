"""Step 4 M2 tests: Recurring Unknown Queue, Report Wrong, Tag Correct & Undo UI."""

import base64
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from dashboard.app import app as fastapi_app
from dashboard.dependencies import get_active_learning_mgr, get_camera_pool, get_db, set_shutting_down
from dashboard.services.video_scenario_reeval_service import reevaluate_video_run_scenarios
from intelligent_tracker.active_learning import ActiveLearningManager
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.matching._gallery_matching import match_persistent_gallery
from intelligent_tracker.memory.confidence import ConfidenceEngine
from intelligent_tracker.tracker import Track

REPO_ROOT = Path(__file__).resolve().parents[1]


def _make_b64_jpeg() -> str:
    img = np.full((64, 64, 3), 120, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")


def _run_node(script: str) -> dict:
    if not shutil.which("node"):
        raise unittest.SkipTest("node not available")
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", check=False)
    if proc.returncode != 0:
        raise AssertionError(f"Node script failed:\nSTDOUT:{proc.stdout}\nSTDERR:{proc.stderr}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


class TestRecurringUnknownAndReevalQueue(unittest.TestCase):
    """Verify recurring-unknown triage, empty-gallery miss routing, and 0-GPU re-eval."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = TrackerDB(os.path.join(self._tmp.name, "tracker.db"))
        self.addCleanup(self.db.close)
        self.crops_dir = os.path.join(self._tmp.name, "crops")
        self.al = ActiveLearningManager(self.db, crops_dir=self.crops_dir, debounce_interval=30.0, unknown_min_dwell_sec=3.0)
        self.frame = np.full((120, 120, 3), 90, dtype=np.uint8)

    def test_recurring_unknown_dwell_threshold_and_cooldown(self) -> None:
        trk = Track(track_id=11, bbox=(10, 10, 40, 40), label="person")
        trk.start_time, trk.last_seen = 0.0, 1.5
        self.assertIsNone(self.al.consider_candidate(trk, self.frame, similarity=0.20, suggested_entity_id=9, suggested_name="Wrong", camera_id="cam_a", timestamp=100.0))
        trk.last_seen = 3.5
        rid = self.al.consider_candidate(trk, self.frame, similarity=0.20, suggested_entity_id=9, suggested_name="Wrong", camera_id="cam_a", timestamp=105.0)
        self.assertIsNotNone(rid)
        item = self.db.get_review_item(int(rid))
        self.assertEqual(item["reason"], "recurring_unknown")
        self.assertIsNone(item["suggested_entity_id"])
        self.assertEqual(item["suggested_name"], "")
        self.assertIsNone(self.al.consider_candidate(trk, self.frame, similarity=0.20, camera_id="cam_a", timestamp=120.0))
        rid2 = self.al.consider_candidate(trk, self.frame, similarity=0.20, camera_id="cam_a", timestamp=140.0)
        self.assertIsNotNone(rid2)

    def test_empty_gallery_miss_routes_to_active_learning(self) -> None:
        trk = Track(track_id=22, bbox=(12, 12, 48, 48), label="person")
        trk.start_time, trk.last_seen = 0.0, 4.2
        matcher = SimpleNamespace(
            gallery_matrix=np.empty((0, 16), dtype=np.float32),
            gallery_entity_ids=[], gallery_names=[], gallery_categories=[],
            reid_threshold=0.70, topology=None, hysteresis=None,
            active_learning=self.al, video_filename="", current_media_offset_sec=0.0, run_id="",
        )
        res = match_persistent_gallery(matcher, trk, np.ones(16, dtype=np.float32), self.frame, "cam_empty", 200.0, "")
        self.assertIsNone(res)
        items = self.db.list_review_items(status="pending")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["reason"], "recurring_unknown")
        self.assertIsNone(items[0]["suggested_entity_id"])

    def test_reeval_zero_gpu_queues_unknown_and_borderline_once(self) -> None:
        eid = self.db.add_entity("Alice", category="person")
        det_frames = [
            {"frame_idx": 0, "timestamp": 0.0, "media_offset_sec": 0.0, "tracks": [{"track_id": 1, "bbox": [10, 10, 30, 30], "dwell_time": 0.5, "label": "person"}]},
            {"frame_idx": 10, "timestamp": 4.0, "media_offset_sec": 4.0, "tracks": [
                {"track_id": 1, "bbox": [10, 10, 30, 30], "dwell_time": 4.0, "label": "person"},
                {"track_id": 2, "bbox": [50, 10, 30, 30], "dwell_time": 1.0, "entity_id": eid, "entity_name": "Alice", "similarity": 0.55, "label": "person"},
            ]},
        ]
        saved = self.db.save_video_run("clip.mp4", report={"scenario_camera_id": "cam_v"}, config={}, frame_detections=det_frames)
        out1 = reevaluate_video_run_scenarios(self.db, "clip.mp4", run_id=saved["run_id"], scenario_mgr=SimpleNamespace(cameras={}))
        self.assertEqual(out1["queued_review_count"], 2)
        items = self.db.list_review_items(status="pending")
        self.assertEqual({i["reason"] for i in items}, {"recurring_unknown", "borderline"})
        out2 = reevaluate_video_run_scenarios(self.db, "clip.mp4", run_id=saved["run_id"], scenario_mgr=SimpleNamespace(cameras={}))
        self.assertEqual(out2["queued_review_count"], 0)


class TestReportWrongAndTagCorrectAPI(unittest.TestCase):
    """Verify POST /api/review/report-wrong and POST /api/tag/correct + Undo."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = TrackerDB(os.path.join(self._tmp.name, "tracker.db"))
        self.addCleanup(self.db.close)
        self.ce = ConfidenceEngine()
        self.al = ActiveLearningManager(self.db, crops_dir=os.path.join(self._tmp.name, "crops"), confidence_engine=self.ce)
        self.pool = SimpleNamespace(
            streams={}, confidence_engine=self.ce,
            get_stream=lambda _cid: None, reload_all_galleries=lambda: None,
        )
        set_shutting_down(False)
        fastapi_app.dependency_overrides[get_db] = lambda: self.db
        fastapi_app.dependency_overrides[get_active_learning_mgr] = lambda: self.al
        fastapi_app.dependency_overrides[get_camera_pool] = lambda: self.pool
        self.addCleanup(fastapi_app.dependency_overrides.clear)
        self.client = TestClient(fastapi_app)

    def test_report_wrong_endpoint_queues_timeline_flag(self) -> None:
        eid = self.db.add_entity("WrongGuy", category="person")
        sid = self.db.add_sighting(eid, track_id=9, source="cam_01", camera_id="cam_01", run_id="run_1")
        resp = self.client.post("/api/review/report-wrong", json={"sighting_id": sid, "notes": "False match"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "flagged")
        self.assertEqual(body["reason"], "timeline_flag")
        item = self.db.get_review_item(body["review_id"])
        self.assertEqual(item["reason"], "timeline_flag")
        self.assertEqual(item["suggested_entity_id"], eid)

    def test_tag_correct_and_undo_roundtrip(self) -> None:
        prior_eid = self.db.add_entity("Alice", category="person")
        self.db.add_sighting(prior_eid, track_id=5, source="cam_01", camera_id="cam_01", run_id="r9")
        with patch("dashboard.routers.tagging.CROPS_DIR", os.path.join(self._tmp.name, "crops")), \
             patch("dashboard.routers.tagging.reload_all_galleries"), \
             patch("dashboard.routers.review.reload_all_galleries"):
            resp = self.client.post("/api/tag/correct", json={
                "prior_entity_id": prior_eid, "entity_name": "Bob", "category": "person",
                "camera_id": "cam_01", "track_id": 5, "run_id": "r9", "crop_base64": _make_b64_jpeg(),
            })
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body["status"], "corrected")
            self.assertIsNotNone(body["decision_id"])
            self.assertEqual(len(self.db.get_sightings(entity_id=body["entity_id"])), 2)
            self.assertEqual(len(self.db.get_sightings(entity_id=prior_eid)), 0)
            undo = self.client.post(f"/api/review/decisions/{body['decision_id']}/undo", json={})
            self.assertEqual(undo.status_code, 200)
            self.assertEqual(undo.json()["status"], "undone")
            self.assertEqual(len(self.db.get_sightings(entity_id=prior_eid)), 1)


_REVIEW_UNDO_VM_TPL = """
const vm = require('vm');
const fetches = [];
const nodes = {};
const mk = (id) => {
  const listeners = {};
  const n = {
    id, style: { display: 'none' }, innerHTML: '', textContent: '', disabled: false, dataset: {}, attrs: {},
    getAttribute(k) { return this.attrs[k] ?? null; },
    addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
    click() { (listeners.click || []).forEach(fn => fn({ target: n })); },
    dispatchClick(target) { (listeners.click || []).forEach(fn => fn({ target })); },
  };
  nodes[id] = n; return n;
};
mk('review-undo-banner'); mk('sightings-timeline-list');
const ctx = vm.createContext({
  document: {
    getElementById(id) { if (id === 'btn-review-banner-undo' && !nodes[id]) mk(id); return nodes[id] || null; },
    addEventListener() {},
  },
  fetch: async (url, opts) => {
    fetches.push({ url, body: JSON.parse(opts.body) });
    return { ok: true, json: async () => ({ status: 'undone', action: 'confirm', review_id: 4 }) };
  },
});
ctx.window = ctx; ctx.showToast = () => {}; ctx.ReviewAndRSAC = { loadQueue() {} };
vm.runInContext(__SRC__, ctx);
(async () => {
  const api = ctx.ReviewUndoAndFlag;
  const b1 = api.renderReasonBadgeHtml({ reason: 'recurring_unknown' });
  const b2 = api.renderReasonBadgeHtml({ reason: 'timeline_flag' });
  api.recordResolvedDecision({ decision_id: 77, review_id: 4, status: 'confirmed', entity_name: 'Alice' });
  const bannerVisible = nodes['review-undo-banner'].style.display === 'flex';
  nodes['btn-review-banner-undo'].click();
  await new Promise(r => setImmediate(r));
  api.initTimelineFlagDelegation();
  const fakeBtn = {
    disabled: false, textContent: '🚩 Report wrong',
    classList: { contains: (c) => c === 'report-wrong-action' },
    getAttribute: (k) => ({ 'data-sighting-id': '12', 'data-entity-id': '3', 'data-camera-id': 'cam_01', 'data-track-id': '8' }[k] ?? ''),
  };
  nodes['sightings-timeline-list'].dispatchClick(fakeBtn);
  await new Promise(r => setImmediate(r));
  console.log(JSON.stringify({ b1, b2, bannerVisible, fetches, flaggedText: fakeBtn.textContent }));
})();
"""

_TAG_CORRECT_VM_TPL = """
const vm = require('vm');
const fetches = [];
const nodes = {};
const mk = (id, val = '') => {
  const listeners = {};
  const n = {
    id, value: val, textContent: '', style: { display: '' }, dataset: {}, focus() {},
    addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
    fire(ev, e = { preventDefault() {}, stopImmediatePropagation() {} }) { (listeners[ev] || []).forEach(fn => fn(e)); },
  };
  nodes[id] = n; return n;
};
mk('tag-entity-id', '5'); mk('tag-prior-entity-id', ''); mk('tag-name-input', 'Alice');
mk('tag-category-select', 'person'); mk('tag-source-type', 'live'); mk('tag-track-id', '4');
mk('tag-bbox-val', '[1,2,30,40]'); mk('tag-crop-base64', ''); mk('tag-notes-input', '');
mk('modal-tag-submit'); mk('btn-tag-discourage'); mk('btn-tag-correct'); mk('tag-entity-form');
const ctx = vm.createContext({
  document: { getElementById: (id) => nodes[id] || null, addEventListener() {} },
  fetch: async (url, opts) => {
    fetches.push({ url, body: JSON.parse(opts.body) });
    return { ok: true, json: async () => ({ status: 'corrected', decision_id: 9, entity_id: 8 }) };
  },
});
ctx.window = ctx; ctx.InteractiveCanvas = { closeTagModal() {} }; ctx.showToast = () => {};
vm.runInContext(__STATE_SRC__, ctx);
vm.runInContext(__ACT_SRC__, ctx);
(async () => {
  const s1 = ctx.TagModalState.syncFromDom();
  const showCorrect = nodes['btn-tag-correct'].style.display;
  ctx.TagFeedbackActions.initCorrectionControls(() => 'cam_01');
  nodes['btn-tag-correct'].fire('click');
  const s2 = ctx.TagModalState.syncFromDom();
  nodes['tag-name-input'].value = 'Bob';
  nodes['tag-entity-form'].fire('submit');
  await new Promise(r => setImmediate(r));
  console.log(JSON.stringify({ s1, showCorrect, s2, submitText: nodes['modal-tag-submit'].textContent, fetches }));
})();
"""


class TestStep4M2FrontendNodeVM(unittest.TestCase):
    """Node VM tests for Undo banner, Timeline Report Wrong, and Known-state Correct."""

    def test_review_undo_banner_reason_badges_and_timeline_flag(self) -> None:
        src = (REPO_ROOT / "dashboard/static/js/review_undo_and_flag.js").read_text(encoding="utf-8")
        out = _run_node(_REVIEW_UNDO_VM_TPL.replace("__SRC__", json.dumps(src)))
        self.assertIn("Recurring Unknown", out["b1"])
        self.assertIn("Timeline Flag", out["b2"])
        self.assertTrue(out["bannerVisible"])
        self.assertEqual(out["fetches"][0]["url"], "/api/review/decisions/77/undo")
        self.assertEqual(out["fetches"][1]["url"], "/api/review/report-wrong")
        self.assertEqual(out["fetches"][1]["body"]["sighting_id"], 12)
        self.assertEqual(out["flaggedText"], "🚩 Flagged")

    def test_tag_modal_known_state_correct_submode(self) -> None:
        state_src = (REPO_ROOT / "dashboard/static/js/tag_modal_state.js").read_text(encoding="utf-8")
        act_src = (REPO_ROOT / "dashboard/static/js/tag_feedback_actions.js").read_text(encoding="utf-8")
        script = _TAG_CORRECT_VM_TPL.replace("__STATE_SRC__", json.dumps(state_src)).replace("__ACT_SRC__", json.dumps(act_src))
        out = _run_node(script)
        self.assertEqual(out["s1"], "known")
        self.assertEqual(out["showCorrect"], "inline-flex")
        self.assertEqual(out["s2"], "correcting")
        self.assertEqual(out["fetches"][0]["url"], "/api/tag/correct")
        self.assertEqual(out["fetches"][0]["body"]["prior_entity_id"], 5)
        self.assertEqual(out["fetches"][0]["body"]["entity_name"], "Bob")


if __name__ == "__main__":
    unittest.main()
