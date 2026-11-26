#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit/VM tests for Step 3 Milestone 3: Tag Modal Preview, AI Auto-Select & Commit."""

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODAL_HTML = REPO_ROOT / "dashboard" / "static" / "partials" / "modals" / "entity_modals.html"
OVERLAY_JS = REPO_ROOT / "dashboard" / "static" / "js" / "unified_canvas_overlay.js"
TAGGER_JS = REPO_ROOT / "dashboard" / "static" / "js" / "roi_draw_tagger.js"
INTERACTIVE_JS = REPO_ROOT / "dashboard" / "static" / "js" / "interactive_canvas.js"
SCRUBBER_RENDERER_JS = REPO_ROOT / "dashboard" / "static" / "js" / "scrubber_overlay_renderer.js"
SCRUBBER_JS = REPO_ROOT / "dashboard" / "static" / "js" / "scrubber_overlay.js"

_DOM_HARNESS = """
function makeEl(id, tag = 'div') {
  const listeners = {}, children = [], classes = new Set();
  const node = {
    id, tagName: tag.toUpperCase(), value: '', src: '', textContent: '', innerHTML: '',
    style: {}, dataset: {}, children, listeners, options: [],
    classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c), contains: (c) => classes.has(c) },
    addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
    removeEventListener: (ev, fn) => { listeners[ev] = (listeners[ev] || []).filter((f) => f !== fn); },
    emit: (ev, payload = {}) => (listeners[ev] || []).slice().map((fn) => fn({ preventDefault: () => {}, ...payload })),
    appendChild: (c) => { children.push(c); return c; },
    querySelectorAll: () => children,
    focus: () => {}, reset: () => {},
    getContext: () => ({
      save: () => {}, restore: () => {}, clearRect: () => {}, scale: () => {}, fillRect: () => {}, strokeRect: () => {},
      setLineDash: () => {}, measureText: () => ({ width: 40 }), fillText: () => {}, beginPath: () => {},
      moveTo: () => {}, lineTo: () => {}, stroke: () => {}, arc: () => {}, fill: () => {}, closePath: () => {},
    }),
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 640, height: 480 }),
    setPointerCapture: () => {}, releasePointerCapture: () => {},
  };
  return node;
}
function buildSandbox(fetchImpl) {
  const ids = [
    'modal-tag-entity', 'tag-entity-form', 'tag-track-id', 'tag-bbox-val', 'tag-entity-id',
    'tag-source-type', 'tag-video-filename', 'tag-timestamp-sec', 'tag-crop-base64',
    'tag-roi-preview-panel', 'tag-roi-crop-img', 'tag-ai-class-badge', 'tag-identity-candidates',
    'tag-name-input', 'tag-category-select', 'tag-notes-input', 'tag-modal-title',
    'modal-tag-close', 'modal-tag-cancel', 'interactive-canvas', 'video-stream',
    'scrubber-video-player', 'scrubber-overlay-canvas',
  ];
  const els = Object.fromEntries(ids.map((id) => [id, makeEl(id)]));
  els['tag-category-select'].options = [{ value: 'person' }, { value: 'vip' }, { value: 'vehicle' }, { value: 'object' }];
  els['video-stream'].naturalWidth = 640; els['video-stream'].naturalHeight = 480;
  els['scrubber-video-player'].videoWidth = 640; els['scrubber-video-player'].videoHeight = 480;
  els['scrubber-video-player'].currentTime = 12.5;
  els['interactive-canvas'].parentElement = makeEl('video-wrapper');
  els['scrubber-overlay-canvas'].parentElement = makeEl('scrubber-viewport');
  const win = {
    devicePixelRatio: 1, loadGalleryCalls: 0, toasts: [],
    addEventListener: () => {},
    loadGallery: () => { win.loadGalleryCalls += 1; },
    showToast: (...a) => win.toasts.push(a),
  };
  const doc = {
    readyState: 'complete',
    getElementById: (id) => els[id] || null,
    createElement: (tag) => makeEl('', tag),
    addEventListener: () => {},
  };
  const sb = { window: win, document: doc, fetch: fetchImpl, Math, Number, Array, Object, String, Boolean, JSON, Date, WeakMap, Map, Set, console };
  sb.globalThis = sb;
  return { sb, win, doc, els };
}
"""


def _run_node(fetch_js: str, body_js: str, load_scrubber: bool = False) -> dict:
    """Run InteractiveCanvas (+ optional ScrubberOverlay) in an async Node VM."""
    files = [OVERLAY_JS, TAGGER_JS, INTERACTIVE_JS] + ([SCRUBBER_RENDERER_JS, SCRUBBER_JS] if load_scrubber else [])
    loads = "\n".join(f"vm.runInNewContext(fs.readFileSync({json.dumps(str(p))}, 'utf8'), sb);" for p in files)
    script = (
        "const fs = require('fs'), vm = require('vm');\n"
        + _DOM_HARNESS
        + f"const fetchCalls = [];\nconst {{ sb, win, doc, els }} = buildSandbox({fetch_js});\n"
        + loads
        + f"\n(async () => {{\n{body_js}\n}})().then((res) => {{ process.stdout.write(JSON.stringify(res)); }})"
        + ".catch((e) => { console.error(e); process.exit(1); });"
    )
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, env=dict(os.environ), timeout=15)
    if proc.returncode != 0:
        raise AssertionError(f"Node VM failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}")
    return json.loads(proc.stdout)


@unittest.skipUnless(shutil.which("node"), "Node.js required for JS VM integration tests")
class TestStep3TagModalIntegration(unittest.TestCase):
    """Verify Milestone 3 modal preview, AI class auto-select, candidate chips, and commit."""

    def test_entity_modals_html_contains_roi_preview_and_context_inputs(self) -> None:
        html = MODAL_HTML.read_text(encoding="utf-8")
        for marker in (
            'id="tag-roi-preview-panel"', 'id="tag-roi-crop-img"', 'id="tag-ai-class-badge"',
            'id="tag-identity-candidates"', 'id="tag-entity-id"', 'id="tag-source-type"',
            'id="tag-video-filename"', 'id="tag-timestamp-sec"', 'id="tag-crop-base64"',
            'data-category-select', 'value="person"',
        ):
            self.assertIn(marker, html)

    def test_live_recognition_preview_and_ai_category_autoselect(self) -> None:
        fetch_js = """async (url, opts) => {
          fetchCalls.push({ url, body: JSON.parse(opts.body) });
          return { ok: true, json: async () => ({ status: 'success', data: {
            crop_base64: 'data:image/jpeg;base64,ABC',
            classification: { label: 'vehicle', confidence: 0.88 },
            candidates: [],
          }})};
        }"""
        body_js = """
        win.InteractiveCanvas.initTagModal(() => 'cam_02');
        win.RoiDrawTagger.openWithRecognition({ sourceType: 'live', cameraId: 'cam_02', bbox: [10, 20, 80, 120] });
        await new Promise((r) => setTimeout(r, 15));
        return {
          fetchCalls, panelDisplay: els['tag-roi-preview-panel'].style.display,
          cropSrc: els['tag-roi-crop-img'].src, cropVal: els['tag-crop-base64'].value,
          badge: els['tag-ai-class-badge'].textContent, category: els['tag-category-select'].value,
        };"""
        res = _run_node(fetch_js, body_js)
        self.assertEqual(res["fetchCalls"][0]["url"], "/api/tag/recognize-roi")
        self.assertEqual(res["fetchCalls"][0]["body"]["camera_id"], "cam_02")
        self.assertEqual(res["panelDisplay"], "flex")
        self.assertEqual(res["cropSrc"], "data:image/jpeg;base64,ABC")
        self.assertEqual(res["badge"], "AI: vehicle (88%)")
        self.assertEqual(res["category"], "vehicle")

    def test_candidate_chip_selection_and_live_commit_refreshes_gallery(self) -> None:
        fetch_js = """async (url, opts) => {
          fetchCalls.push({ url, body: JSON.parse(opts.body) });
          if (url.includes('recognize-roi')) {
            return { ok: true, json: async () => ({ status: 'success', data: {
              crop_base64: 'data:image/jpeg;base64,XYZ',
              classification: { label: 'person', confidence: 0.91 },
              candidates: [{ entity_id: 7, name: 'Alice', category: 'vip', similarity: 0.94 }],
            }})};
          }
          return { ok: true, json: async () => ({ status: 'success', data: { entity_id: 7 } }) };
        }"""
        body_js = """
        win.InteractiveCanvas.initTagModal(() => 'cam_01');
        win.RoiDrawTagger.openWithRecognition({ sourceType: 'live', cameraId: 'cam_01', bbox: [5, 5, 40, 90] });
        await new Promise((r) => setTimeout(r, 15));
        const chip = els['tag-identity-candidates'].children[0];
        chip.emit('click');
        await Promise.all(els['tag-entity-form'].emit('submit'));
        return {
          entityId: els['tag-entity-id'].value, name: els['tag-name-input'].value,
          category: els['tag-category-select'].value, commit: fetchCalls[1],
          loadGalleryCalls: win.loadGalleryCalls, modalDisplay: els['modal-tag-entity'].style.display,
        };"""
        res = _run_node(fetch_js, body_js)
        self.assertEqual(res["entityId"], "7")
        self.assertEqual(res["name"], "Alice")
        self.assertEqual(res["category"], "vip")
        self.assertEqual(res["commit"]["url"], "/api/tag/commit")
        self.assertEqual(res["commit"]["body"]["entity_id"], 7)
        self.assertEqual(res["commit"]["body"]["camera_id"], "cam_01")
        self.assertEqual(res["loadGalleryCalls"], 1)
        self.assertEqual(res["modalDisplay"], "none")

    def test_scrubber_overlay_binds_roi_tagger_and_commits_video_context(self) -> None:
        fetch_js = """async (url, opts) => {
          fetchCalls.push({ url, body: JSON.parse(opts.body) });
          if (url.includes('recognize-roi')) {
            return { ok: true, json: async () => ({ status: 'success', data: {
              crop_base64: 'data:image/jpeg;base64,VID', classification: { label: 'person', confidence: 0.8 }, candidates: [],
            }})};
          }
          return { ok: true, json: async () => ({ status: 'success', data: { entity_id: 9 } }) };
        }"""
        body_js = """
        win.InteractiveCanvas.initTagModal(() => 'cam_01');
        win.ScrubberOverlay.setDetections([{ time: 12.5, tracks: [{ id: 3, bbox: [100, 100, 60, 120] }] }]);
        const sc = els['scrubber-overlay-canvas'];
        sc.emit('pointerdown', { button: 0, pointerId: 1, clientX: 110, clientY: 110 });
        sc.emit('pointerup', { button: 0, pointerId: 1, clientX: 110, clientY: 110 });
        await new Promise((r) => setTimeout(r, 15));
        els['tag-name-input'].value = 'Bob';
        await Promise.all(els['tag-entity-form'].emit('submit'));
        return { recognize: fetchCalls[0], commit: fetchCalls[1] };"""
        res = _run_node(fetch_js, body_js, load_scrubber=True)
        self.assertEqual(res["recognize"]["url"], "/api/tag/recognize-roi")
        self.assertIsNone(res["recognize"]["body"]["camera_id"])
        self.assertEqual(res["recognize"]["body"]["timestamp_sec"], 12.5)
        self.assertEqual(res["commit"]["url"], "/api/tag/commit")
        self.assertEqual(res["commit"]["body"]["entity_name"], "Bob")
        self.assertEqual(res["commit"]["body"]["timestamp_sec"], 12.5)
        self.assertIsNone(res["commit"]["body"]["camera_id"])

    def test_modularity_line_budgets(self) -> None:
        self.assertLess(len(INTERACTIVE_JS.read_text(encoding="utf-8").splitlines()), 240)
        self.assertLess(len(SCRUBBER_JS.read_text(encoding="utf-8").splitlines()), 345)


if __name__ == "__main__":
    unittest.main()
