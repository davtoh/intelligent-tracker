#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tests for Step 3 Milestone 1: Negative & Correction Exemplars + Discourage Flow."""

import base64
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from dashboard.app import app as fastapi_app
from dashboard.dependencies import get_camera_pool, get_db, set_shutting_down
from dashboard.routers import tagging as tagging_router
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.matching.gallery import GalleryMatcher
from intelligent_tracker.tracker import Track

REPO_ROOT = Path(__file__).resolve().parent.parent
MODAL_HTML = REPO_ROOT / "dashboard" / "static" / "partials" / "modals" / "entity_modals.html"
INDEX_HTML = REPO_ROOT / "dashboard" / "static" / "index.html"
OVERLAY_JS = REPO_ROOT / "dashboard" / "static" / "js" / "unified_canvas_overlay.js"
TAGGER_JS = REPO_ROOT / "dashboard" / "static" / "js" / "roi_draw_tagger.js"
FEEDBACK_JS = REPO_ROOT / "dashboard" / "static" / "js" / "tag_feedback_actions.js"
INTERACTIVE_JS = REPO_ROOT / "dashboard" / "static" / "js" / "interactive_canvas.js"


def _make_b64_jpeg(color=(40, 120, 200)) -> str:
    img = np.full((32, 32, 3), color, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")


class TestNegativeExemplarRepo(unittest.TestCase):
    """Verify NegativeExemplarMixin CRUD, normalization, and rollback invariants."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "test.db")
        self.db = TrackerDB(db_path=self.db_path)
        self.addCleanup(self.db.close)

    def test_crud_and_positive_gallery_isolation(self) -> None:
        eid = self.db.add_entity(name="Alice", category="person")
        pos = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        neg = np.array([0.0, 3.0, 4.0, 0.0], dtype=np.float32)
        self.db.add_signature(eid, pos)
        ex1 = self.db.add_negative_exemplar(neg, entity_id=eid, label="Alice", source="cam_1")
        ex2 = self.db.add_negative_exemplar(pos, entity_id=None, label="clutter", source="cam_1")

        g_mat, g_ids, _, _ = self.db.get_gallery_embeddings(expected_dim=4)
        self.assertEqual(g_ids, [eid])
        self.assertEqual(g_mat.shape, (1, 4))

        n_mat, n_ids, n_labels = self.db.get_negative_embeddings(expected_dim=4)
        self.assertEqual(n_mat.shape, (2, 4))
        self.assertEqual(n_ids, [eid, None])
        self.assertEqual(n_labels, ["Alice", "clutter"])
        self.assertAlmostEqual(float(np.linalg.norm(n_mat[0])), 1.0, places=5)
        self.assertEqual(len(self.db.get_negative_exemplars(entity_id=eid)), 1)
        self.assertTrue(self.db.delete_negative_exemplar(ex1))
        self.assertFalse(self.db.delete_negative_exemplar(ex1))
        self.assertEqual(self.db.clear_negative_exemplars(), 1)
        self.assertGreater(ex2, 0)

    def test_write_rollback_on_sqlite_error(self) -> None:
        with self.assertRaises(sqlite3.Error):
            self.db.add_negative_exemplar(
                np.array([1.0, 0.0], dtype=np.float32), entity_id=999999
            )
        self.assertFalse(self.db._conn.in_transaction)


class TestGalleryNegativeSuppression(unittest.TestCase):
    """Verify per-entity and global false-positive suppression in GalleryMatcher."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = TrackerDB(db_path=os.path.join(self.tmp.name, "gallery.db"))
        self.addCleanup(self.db.close)

    def _make_extractor(self, vec: np.ndarray) -> MagicMock:
        ext = MagicMock()
        ext.embedding_dim = int(vec.shape[0])
        ext.extract.return_value = vec
        return ext

    def test_per_entity_negative_suppresses_wrong_identity(self) -> None:
        eid_a = self.db.add_entity(name="Alice", category="person")
        eid_b = self.db.add_entity(name="Bob", category="person")
        v_a = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        v_b = np.array([0.8, 0.6, 0.0, 0.0], dtype=np.float32)
        self.db.add_signature(eid_a, v_a)
        self.db.add_signature(eid_b, v_b)
        self.db.add_negative_exemplar(v_a, entity_id=eid_a, label="Not Alice")

        matcher = GalleryMatcher(
            db=self.db, extractor=self._make_extractor(v_a),
            reid_threshold=0.65, negative_suppression_threshold=0.78,
        )
        trk = Track(track_id=1, bbox=(10, 10, 50, 50), label="person")
        trk.hits = 3
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        ev = matcher.match_track(trk, frame, source="cam_1", timestamp=100.0)
        self.assertIsNotNone(ev)
        self.assertEqual(ev.entity_id, eid_b)
        self.assertEqual(trk.entity_name, "Bob")

    def test_global_negative_suppresses_match_and_active_learning(self) -> None:
        eid_a = self.db.add_entity(name="Alice", category="person")
        v_a = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        self.db.add_signature(eid_a, v_a)
        self.db.add_negative_exemplar(v_a, entity_id=None, label="clutter")

        al = MagicMock()
        matcher = GalleryMatcher(
            db=self.db, extractor=self._make_extractor(v_a),
            reid_threshold=0.65, global_negative_threshold=0.82, active_learning=al,
        )
        trk = Track(track_id=2, bbox=(10, 10, 50, 50), label="person")
        trk.hits = 3
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        ev = matcher.match_track(trk, frame, source="cam_1", timestamp=100.0)
        self.assertIsNone(ev)
        self.assertIsNone(getattr(trk, "entity_id", None))
        al.consider_candidate.assert_not_called()


class TestNegativeExemplarAPI(unittest.TestCase):
    """Verify /api/tag/discourage and /api/tag/negatives routes."""

    def setUp(self) -> None:
        set_shutting_down(False)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = TrackerDB(db_path=os.path.join(self.tmp.name, "api.db"))
        self.addCleanup(self.db.close)
        self.crops_dir = os.path.join(self.tmp.name, "crops")
        self.pool = MagicMock()
        self.pool.confidence_engine = MagicMock()
        self.trk = Track(track_id=7, bbox=(5, 5, 30, 30), label="person")
        self.trk.entity_id = 1
        self.trk.entity_name = "Alice"
        self.mgr = SimpleNamespace(
            tracker=SimpleNamespace(tracks={7: self.trk}),
            gallery_matcher=SimpleNamespace(_identified_tracks={7: {"entity_id": 1}}),
            confidence_engine=self.pool.confidence_engine,
            reid_extractor=None,
        )
        self.pool.get_stream.return_value = self.mgr
        fastapi_app.dependency_overrides[get_db] = lambda: self.db
        fastapi_app.dependency_overrides[get_camera_pool] = lambda: self.pool
        self.addCleanup(fastapi_app.dependency_overrides.clear)

    def test_discourage_list_and_delete_endpoints(self) -> None:
        eid = self.db.add_entity(name="Alice", category="person")
        with (
            patch.object(tagging_router, "CROPS_DIR", self.crops_dir),
            patch.object(tagging_router, "get_active_stream_manager", return_value=self.mgr),
            patch.object(tagging_router, "reload_all_galleries") as reload_mock,
            patch.object(fastapi_app.router, "lifespan_context", new=lambda a: _NullAsyncCtx()),
        ):
            client = TestClient(fastapi_app)
            resp = client.post("/api/tag/discourage", json={
                "entity_id": eid, "label": "Alice", "camera_id": "cam_01",
                "track_id": 7, "crop_base64": _make_b64_jpeg(), "notes": "wrong person",
            })
            self.assertEqual(resp.status_code, 200, resp.text)
            ex_id = resp.json()["data"]["exemplar_id"]
            self.assertFalse(hasattr(self.trk, "entity_id"))
            self.assertNotIn(7, self.mgr.gallery_matcher._identified_tracks)
            self.pool.confidence_engine.record_human_feedback.assert_called_once()
            self.assertEqual(reload_mock.call_count, 1)

            listed = client.get(f"/api/tag/negatives?entity_id={eid}")
            self.assertEqual(listed.status_code, 200)
            self.assertEqual(len(listed.json()["data"]), 1)

            deleted = client.delete(f"/api/tag/negatives/{ex_id}")
            self.assertEqual(deleted.status_code, 200)
            self.assertEqual(client.delete(f"/api/tag/negatives/{ex_id}").status_code, 404)


class _NullAsyncCtx:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *args):
        return False


_NODE_HARNESS = """
const fs = require('fs'), vm = require('vm');
function makeEl(id, tag = 'div') {
  const listeners = {}, children = [], classes = new Set();
  return {
    id, tagName: tag.toUpperCase(), value: '', src: '', textContent: '', innerHTML: '',
    style: {}, dataset: {}, children, listeners, options: [{ value: 'person' }],
    classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c), contains: (c) => classes.has(c) },
    setAttribute: () => {},
    addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
    emit: (ev, p = {}) => (listeners[ev] || []).slice().map((fn) => fn({ preventDefault: () => {}, stopPropagation: () => {}, ...p })),
    appendChild: (c) => { children.push(c); return c; },
    querySelectorAll: () => children, focus: () => {}, reset: () => {},
    getContext: () => ({ save: () => {}, restore: () => {}, clearRect: () => {}, scale: () => {} }),
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 640, height: 480 }),
  };
}
const ids = [
  'modal-tag-entity', 'tag-entity-form', 'tag-track-id', 'tag-bbox-val', 'tag-entity-id',
  'tag-source-type', 'tag-video-filename', 'tag-timestamp-sec', 'tag-crop-base64',
  'tag-roi-preview-panel', 'tag-roi-crop-img', 'tag-ai-class-badge', 'tag-identity-candidates',
  'tag-name-input', 'tag-category-select', 'tag-notes-input', 'tag-modal-title',
  'modal-tag-close', 'modal-tag-cancel', 'btn-tag-discourage', 'interactive-canvas', 'video-stream',
];
const els = Object.fromEntries(ids.map((id) => [id, makeEl(id)]));
els['interactive-canvas'].parentElement = makeEl('video-wrapper');
const fetchCalls = [];
const win = { devicePixelRatio: 1, toasts: [], addEventListener: () => {}, showToast: (...a) => win.toasts.push(a) };
const doc = { readyState: 'complete', getElementById: (id) => els[id] || null, createElement: (t) => makeEl('', t), addEventListener: () => {} };
const fetchImpl = async (url, opts) => {
  fetchCalls.push({ url, body: JSON.parse(opts.body) });
  if (url === '/api/tag/recognize-roi') {
    return { ok: true, json: async () => ({ status: 'success', data: { crop_base64: 'data:image/jpeg;base64,AAA', classification: { label: 'person', confidence: 0.9 }, candidates: [{ entity_id: 42, name: 'Mallory', category: 'person', similarity: 0.81 }] } }) };
  }
  return { ok: true, json: async () => ({ status: 'success', data: { exemplar_id: 9 } }) };
};
const sb = { window: win, document: doc, fetch: fetchImpl, Math, Number, Array, Object, String, Boolean, JSON, Date, WeakMap, Map, Set, console };
sb.globalThis = sb;
"""


def _run_node_vm(body_js: str) -> dict:
    files = [OVERLAY_JS, TAGGER_JS, FEEDBACK_JS, INTERACTIVE_JS]
    loads = "\n".join(f"vm.runInNewContext(fs.readFileSync({json.dumps(str(p))}, 'utf8'), sb);" for p in files)
    script = _NODE_HARNESS + loads + f"\n(async () => {{\n{body_js}\n}})().then((r) => process.stdout.write(JSON.stringify(r))).catch((e) => {{ console.error(e); process.exit(1); }});"
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, env=dict(os.environ), timeout=15)
    if proc.returncode != 0:
        raise AssertionError(f"Node VM failed:\n{proc.stderr}")
    return json.loads(proc.stdout)


@unittest.skipUnless(shutil.which("node"), "Node.js required")
class TestTagFeedbackActionsVM(unittest.TestCase):
    """Verify #btn-tag-discourage and candidate discourage chip in Node VM."""

    def test_html_contracts_and_discourage_actions(self) -> None:
        self.assertIn('id="btn-tag-discourage"', MODAL_HTML.read_text(encoding="utf-8"))
        self.assertIn("/static/js/tag_feedback_actions.js", INDEX_HTML.read_text(encoding="utf-8"))
        out = _run_node_vm("""
        win.InteractiveCanvas.initTagModal(() => 'cam_03');
        win.InteractiveCanvas.openWithRecognition({ sourceType: 'live', cameraId: 'cam_03', bbox: [1, 2, 30, 40], track: { id: 5 } });
        await new Promise((r) => setTimeout(r, 20));
        const chip = els['tag-identity-candidates'].children[0];
        const xBtn = chip.children[0];
        await xBtn.emit('click')[0];
        els['tag-entity-id'].value = '';
        els['tag-crop-base64'].value = 'data:image/jpeg;base64,BBB';
        await els['btn-tag-discourage'].emit('click')[0];
        return { fetchCalls, modalDisplay: els['modal-tag-entity'].style.display, toastCount: win.toasts.length };
        """)
        disc_calls = [c for c in out["fetchCalls"] if c["url"] == "/api/tag/discourage"]
        self.assertEqual(len(disc_calls), 2)
        self.assertEqual(disc_calls[0]["body"]["entity_id"], 42)
        self.assertIsNone(disc_calls[1]["body"]["entity_id"])
        self.assertEqual(out["modalDisplay"], "none")
        self.assertEqual(out["toastCount"], 2)


if __name__ == "__main__":
    unittest.main()
