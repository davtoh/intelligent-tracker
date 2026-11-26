#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tests for Step 3 Milestone 2: Dynamic Semantic Category Badges & Pre-Enrollment Collision Guard."""

import base64
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from dashboard.app import app as fastapi_app
from dashboard.dependencies import (
    get_camera_pool,
    get_db,
    get_enrollment_mgr,
    get_rsac_mgr,
    set_shutting_down,
)
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.enrollment import UniversalEnrollmentManager
from intelligent_tracker.rsac import RSACManager

REPO_ROOT = Path(__file__).resolve().parent.parent
BADGE_JS = REPO_ROOT / "dashboard" / "static" / "js" / "category_badge_manager.js"
ENROLL_JS = REPO_ROOT / "dashboard" / "static" / "js" / "universal_enrollment.js"


def _make_b64_jpeg(color=(40, 120, 200)) -> str:
    img = np.full((32, 32, 3), color, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")


class _ColorExtractor:
    """Deterministic extractor returning unit vector from mean BGR color."""

    def extract_crop(self, crop: np.ndarray) -> np.ndarray:
        mean = crop.mean(axis=(0, 1)).astype(np.float32)
        vec = np.array([mean[0], mean[1], mean[2], 1.0], dtype=np.float32)
        norm = float(np.linalg.norm(vec))
        return vec / (norm if norm > 1e-6 else 1.0)


class TestEnrollmentCollisionUnit(unittest.TestCase):
    """Verify check_collision(), merge_entity_id, and force_create_new."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = TrackerDB(db_path=os.path.join(self.tmp.name, "unit.db"))
        self.addCleanup(self.db.close)
        self.mgr = UniversalEnrollmentManager(
            db=self.db,
            extractor=_ColorExtractor(),
            crops_dir=os.path.join(self.tmp.name, "crops"),
        )

    def test_check_collision_and_merge_vs_create_new(self) -> None:
        blue = np.full((32, 32, 3), (220, 30, 10), dtype=np.uint8)
        red = np.full((32, 32, 3), (10, 20, 230), dtype=np.uint8)
        alice = self.mgr.enroll(name="Alice", category="vip", crop=blue)

        hit = self.mgr.check_collision(crop=blue, threshold=0.85, top_k=3)
        self.assertTrue(hit["has_collision"])
        self.assertEqual(hit["matches"][0]["entity_id"], alice["entity_id"])
        self.assertGreaterEqual(hit["matches"][0]["similarity"], 0.99)

        miss = self.mgr.check_collision(crop=red, threshold=0.85, top_k=3)
        self.assertFalse(miss["has_collision"])
        self.assertEqual(miss["matches"], [])

        merged = self.mgr.enroll(
            name="Alice Alt", category="vip", crop=blue, merge_entity_id=alice["entity_id"]
        )
        self.assertTrue(merged["merged"])
        self.assertEqual(merged["entity_id"], alice["entity_id"])
        self.assertEqual(len(self.db.get_entity_signatures(alice["entity_id"])), 2)

        forced = self.mgr.enroll(name="Alice", category="vip", crop=blue, force_create_new=True)
        self.assertFalse(forced["merged"])
        self.assertNotEqual(forced["entity_id"], alice["entity_id"])


class TestBadgesAndCollisionAPI(unittest.TestCase):
    """Verify PUT /api/rsac/categories/{id} and POST /api/enroll/check-collision."""

    def setUp(self) -> None:
        set_shutting_down(False)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = TrackerDB(db_path=os.path.join(self.tmp.name, "api.db"))
        self.addCleanup(self.db.close)
        self.rsac = RSACManager(db=self.db)
        self.enroll_mgr = UniversalEnrollmentManager(
            db=self.db,
            extractor=_ColorExtractor(),
            crops_dir=os.path.join(self.tmp.name, "crops"),
        )
        self.pool = MagicMock()
        self.pool.get_stream.return_value = None
        fastapi_app.dependency_overrides[get_db] = lambda: self.db
        fastapi_app.dependency_overrides[get_rsac_mgr] = lambda: self.rsac
        fastapi_app.dependency_overrides[get_enrollment_mgr] = lambda: self.enroll_mgr
        fastapi_app.dependency_overrides[get_camera_pool] = lambda: self.pool
        self.addCleanup(fastapi_app.dependency_overrides.clear)
        self.client = TestClient(fastapi_app)

    def test_category_put_and_collision_routes(self) -> None:
        with patch("dashboard.routers.rsac.reload_all_galleries"), patch(
            "dashboard.routers.categories_and_collision.reload_all_galleries"
        ):
            c_res = self.client.post(
                "/api/rsac/categories",
                json={"id": "contractor", "name": "Contractor", "color": "#10b981", "badge_icon": "🛠️"},
            )
            self.assertEqual(c_res.status_code, 200)
            u_res = self.client.put(
                "/api/rsac/categories/contractor",
                json={"name": "Site Contractor", "color": "#f59e0b", "badge_icon": "🦺", "description": "Temp"},
            )
            self.assertEqual(u_res.status_code, 200)
            self.assertEqual(u_res.json()["status"], "updated")
            self.assertEqual(u_res.json()["category"]["name"], "Site Contractor")
            self.assertEqual(self.client.put("/api/rsac/categories/missing_cat", json={"name": "X"}).status_code, 404)

            b64 = _make_b64_jpeg((200, 40, 20))
            enr = self.client.post("/api/enroll", json={"name": "Bob", "category": "contractor", "crop_base64": b64})
            self.assertEqual(enr.status_code, 200)
            bob_id = enr.json()["entity_id"]

            col = self.client.post("/api/enroll/check-collision", json={"crop_base64": b64, "threshold": 0.72})
            self.assertEqual(col.status_code, 200)
            self.assertTrue(col.json()["has_collision"])
            self.assertEqual(col.json()["matches"][0]["entity_id"], bob_id)

            merged = self.client.post(
                "/api/enroll",
                json={"name": "Bob2", "category": "contractor", "crop_base64": b64, "merge_entity_id": bob_id},
            )
            self.assertEqual(merged.status_code, 200)
            self.assertEqual(merged.json()["entity_id"], bob_id)


@unittest.skipUnless(shutil.which("node"), "Node.js required for VM frontend tests")
class TestCategoryBadgeAndCollisionUI(unittest.TestCase):
    """Node VM tests for CategoryBadgeManager sync across 5 targets and collision banner."""

    def _run_vm(self, script_paths, body: str) -> dict:
        sources = ", ".join(json.dumps(str(p)) for p in script_paths)
        harness = f"""
const fs = require('fs'), vm = require('vm');
const makeEl = (id) => {{
  const el = {{
    id, value: '', innerHTML: '', textContent: '', style: {{}}, options: [],
    listeners: {{}}, attrs: {{}},
    classList: {{ _s: new Set(), add(c){{this._s.add(c);}}, remove(c){{this._s.delete(c);}}, contains(c){{return this._s.has(c);}} }},
    addEventListener(t, fn) {{ (this.listeners[t] = this.listeners[t] || []).push(fn); }},
    getAttribute(k) {{ return this.attrs[k] ?? null; }},
    setAttribute(k, v) {{ this.attrs[k] = String(v); }},
    querySelectorAll() {{ return []; }},
    querySelector() {{ return null; }},
    closest() {{ return null; }},
    reset() {{}},
  }};
  return el;
}};
const byId = new Map();
const getOrMake = (id) => {{ if (!byId.has(id)) byId.set(id, makeEl(id)); return byId.get(id); }};
const document = {{ getElementById: (id) => byId.get(id) || null, querySelectorAll: () => [], querySelector: () => null, createElement: () => makeEl('tmp') }};
const window = {{ document, showToast() {{}}, alert() {{}}, setTimeout, clearTimeout }};
const ctx = vm.createContext({{ window, document, console, getOrMake, makeEl, byId, fetch: async () => ({{ ok: true, json: async () => [] }}), FormData: function(){{}}, URL, Image: function(){{}}, alert() {{}} }});
for (const p of [{sources}]) vm.runInContext(fs.readFileSync(p, 'utf8'), ctx);
vm.runInContext(`(async () => {{
  {body}
}})().then(res => console.log(JSON.stringify(res))).catch(err => {{ console.error(err); process.exit(1); }});`, ctx);
"""
        proc = subprocess.run(["node", "-e", harness], capture_output=True, text=True, check=True)
        return json.loads(proc.stdout.strip())

    def test_badge_manager_syncs_five_targets(self) -> None:
        body = """
        ['enroll-category-select','tag-category-select','quick-enroll-category-select','modal-zone-category-select','gallery-category-filters'].forEach(getOrMake);
        const cats = [{ id: 'contractor', name: 'Contractor', color: '#10b981', badge_icon: '🦺', description: '' }];
        fetch = async (url) => ({ ok: true, json: async () => cats });
        await window.CategoryBadgeManager.init();
        return {
          enroll: byId.get('enroll-category-select').innerHTML,
          tag: byId.get('tag-category-select').innerHTML,
          quick: byId.get('quick-enroll-category-select').innerHTML,
          zone: byId.get('modal-zone-category-select').innerHTML,
          pills: byId.get('gallery-category-filters').innerHTML,
        };
        """
        out = self._run_vm([BADGE_JS], body)
        for key in ("enroll", "tag", "quick", "zone", "pills"):
            self.assertIn("Contractor", out[key])
        self.assertIn("All Categories", out["zone"])

    def test_collision_banner_merge_flow(self) -> None:
        body = """
        ['modal-universal-enrollment','universal-enrollment-form','enroll-name-input','enroll-category-select',
         'enroll-camera-select','enroll-collision-banner','btn-submit-enrollment','enroll-file-input'].forEach(getOrMake);
        const canvas = getOrMake('enroll-bbox-canvas');
        canvas.getContext = () => ({ drawImage() {}, clearRect() {}, strokeRect() {}, fillRect() {} });
        canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100 });
        document.createElement = (t) => ({ width: 0, height: 0, getContext: () => ({ drawImage() {} }), toDataURL: () => 'data:image/jpeg;base64,AAA=' });
        class MockImg { set src(v) { this.naturalWidth = 100; this.naturalHeight = 100; if (this.onload) this.onload(); } }
        Image = MockImg;
        byId.get('enroll-name-input').value = 'Alice';
        byId.get('enroll-camera-select').value = 'cam_01';
        const calls = [];
        fetch = async (url, opts) => {
          calls.push({ url, body: opts && opts.body ? JSON.parse(opts.body) : null });
          if (url === '/api/enroll/check-collision') return { ok: true, json: async () => ({ has_collision: true, matches: [{ entity_id: 42, name: 'Alice', similarity: 0.94 }] }) };
          return { ok: true, json: async () => ({ entity_id: 42 }) };
        };
        window.UniversalEnrollment.init();
        window.UniversalEnrollment.loadFreezeImage('data:image/jpeg;base64,BBB=', canvas, null);
        canvas.listeners.mousedown[0]({ clientX: 10, clientY: 10 });
        canvas.listeners.mouseup[0]({ clientX: 60, clientY: 60 });
        await byId.get('universal-enrollment-form').listeners.submit[0]({ preventDefault() {} });
        const bannerHtml = byId.get('enroll-collision-banner').innerHTML;
        const mergeBtn = makeEl('btn-enroll-merge-existing');
        byId.set('btn-enroll-merge-existing', mergeBtn);
        // Re-run via direct click simulation on banner button
        return { bannerHtml, collisionChecked: calls.some(c => c.url === '/api/enroll/check-collision'), enrollCallsBeforeMerge: calls.filter(c => c.url === '/api/enroll').length };
        """
        out = self._run_vm([BADGE_JS, ENROLL_JS], body)
        self.assertTrue(out["collisionChecked"])
        self.assertEqual(out["enrollCallsBeforeMerge"], 0)
        self.assertIn("btn-enroll-merge-existing", out["bannerHtml"])
        self.assertIn("btn-enroll-create-new", out["bannerHtml"])
