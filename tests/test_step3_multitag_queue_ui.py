#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Node VM tests for Step 3 Milestone 3: Multi-Box Hit-Test & TagTrackQueue."""

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "dashboard" / "static"
INDEX_HTML = STATIC_DIR / "index.html"
MODAL_HTML = STATIC_DIR / "partials" / "modals" / "entity_modals.html"
TAG_QUEUE_CSS = STATIC_DIR / "css" / "tag_queue.css"
OVERLAY_JS = STATIC_DIR / "js" / "unified_canvas_overlay.js"
TAGGER_JS = STATIC_DIR / "js" / "roi_draw_tagger.js"
QUEUE_JS = STATIC_DIR / "js" / "tag_track_queue.js"
INTERACTIVE_JS = STATIC_DIR / "js" / "interactive_canvas.js"
SCRUBBER_RENDERER_JS = STATIC_DIR / "js" / "scrubber_overlay_renderer.js"
SCRUBBER_JS = STATIC_DIR / "js" / "scrubber_overlay.js"

_DOM_HARNESS = """
function makeEl(id, tag = 'div') {
  const listeners = {}, children = [], classes = new Set();
  const node = {
    id, tagName: tag.toUpperCase(), value: '', src: '', textContent: '', title: '',
    _innerHTML: '',
    get innerHTML() { return node._innerHTML; },
    set innerHTML(v) { node._innerHTML = v; if (v === '') children.length = 0; },
    style: {}, dataset: {}, children, listeners, options: [],
    classList: {
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      contains: (c) => classes.has(c),
    },
    addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
    removeEventListener: (ev, fn) => { listeners[ev] = (listeners[ev] || []).filter((f) => f !== fn); },
    emit: (ev, payload = {}) => (listeners[ev] || []).slice().map((fn) => fn({ preventDefault: () => {}, ...payload })),
    appendChild: (c) => { children.push(c); return c; },
    querySelectorAll: () => children,
    focus: () => {}, reset: () => {},
    getContext: () => ({
      save: () => {}, restore: () => {}, clearRect: () => {}, scale: () => {}, fillRect: () => {}, strokeRect: () => {},
      setLineDash: () => {}, setTransform: () => {}, measureText: () => ({ width: 40 }), fillText: () => {},
      beginPath: () => {}, moveTo: () => {}, lineTo: () => {}, stroke: () => {}, arc: () => {}, fill: () => {}, closePath: () => {},
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
    'tag-track-picker-strip', 'tag-roi-preview-panel', 'tag-roi-crop-img', 'tag-ai-class-badge',
    'tag-identity-candidates', 'tag-name-input', 'tag-category-select', 'tag-notes-input',
    'tag-modal-title', 'modal-tag-close', 'modal-tag-cancel', 'btn-quick-tag',
    'interactive-canvas', 'live-stream-img', 'scrubber-video-player', 'scrubber-overlay-canvas',
  ];
  const els = Object.fromEntries(ids.map((id) => [id, makeEl(id)]));
  els['tag-category-select'].options = [{ value: 'person' }, { value: 'asset' }, { value: 'vehicle' }];
  els['live-stream-img'].naturalWidth = 640; els['live-stream-img'].naturalHeight = 480;
  els['scrubber-video-player'].videoWidth = 640; els['scrubber-video-player'].videoHeight = 480;
  els['scrubber-video-player'].currentTime = 5.0;
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
  const sb = {
    window: win, document: doc, fetch: fetchImpl,
    Math, Number, Array, Object, String, Boolean, JSON, Date, WeakMap, Map, Set, Promise, console,
  };
  sb.globalThis = sb;
  return { sb, win, doc, els };
}
"""


def _run_node(fetch_js: str, body_js: str, load_scrubber: bool = False) -> dict:
    """Execute TagTrackQueue + InteractiveCanvas (+ optional ScrubberOverlay) in Node VM."""
    files = [OVERLAY_JS, TAGGER_JS, QUEUE_JS, INTERACTIVE_JS]
    if load_scrubber:
        files += [SCRUBBER_RENDERER_JS, SCRUBBER_JS]
    loads = "\n".join(
        f"vm.runInNewContext(fs.readFileSync({json.dumps(str(p))}, 'utf8'), sb);"
        for p in files
    )
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


class TestStep3MultiTagQueueUI(unittest.TestCase):
    """Verify multi-box hit testing, #tag-track-picker-strip switching, and Quick-Tag queue."""

    def test_assets_markup_and_line_budgets(self) -> None:
        index_html = INDEX_HTML.read_text(encoding="utf-8")
        modal_html = MODAL_HTML.read_text(encoding="utf-8")
        css = TAG_QUEUE_CSS.read_text(encoding="utf-8")
        self.assertIn('id="tag-track-picker-strip"', modal_html)
        self.assertIn('/static/css/tag_queue.css', index_html)
        self.assertIn('/static/js/tag_track_queue.js', index_html)
        self.assertLess(index_html.find('/static/js/tag_track_queue.js'), index_html.find('/static/js/interactive_canvas.js'))
        self.assertNotIn("!important", css)
        self.assertLessEqual(len(QUEUE_JS.read_text(encoding="utf-8").splitlines()), 220)
        self.assertLessEqual(len(css.splitlines()), 95)
        self.assertLess(len(modal_html.splitlines()), 240)
        self.assertLess(len(index_html.splitlines()), 180)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_hit_test_tracks_at_point_orders_smallest_and_topmost_first(self) -> None:
        body_js = """
        const T = win.RoiDrawTagger;
        const tracks = [
          { id: 1, bbox: [100, 100, 200, 200] },
          { id: 2, bbox: [120, 120, 60, 60] },
          { id: 3, bbox: [120, 120, 60, 60] },
          { id: 4, bbox: [110, 110, 100, 100] },
        ];
        const hits = T.hitTestTracksAtPoint(140, 140, tracks).map((t) => t.id);
        const top = T.hitTestTrackAtPoint(140, 140, tracks)?.id;
        return { hits, top };
        """
        out = _run_node("async () => ({ ok: true, json: async () => ({}) })", body_js)
        self.assertEqual(out["hits"], [3, 2, 4, 1])
        self.assertEqual(out["top"], 3)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_overlap_click_populates_picker_strip_and_switches_with_seq_guard(self) -> None:
        fetch_js = """async (url, opts) => {
          const body = JSON.parse(opts.body);
          fetchCalls.push({ url, body });
          const isFirst = body.bbox && body.bbox[2] === 40;
          await new Promise((r) => setTimeout(r, isFirst ? 35 : 5));
          return { ok: true, json: async () => ({ status: 'success', data: {
            crop_base64: isFirst ? 'data:image/jpeg;base64,SLOW' : 'data:image/jpeg;base64,FAST',
            classification: { label: isFirst ? 'asset' : 'person', confidence: 0.9 },
            candidates: [],
          }})};
        }"""
        body_js = """
        win.InteractiveCanvas.initTagModal(() => 'cam_01');
        const tracks = [
          { id: 10, class_name: 'person', bbox: [100, 100, 140, 180] },
          { id: 11, class_name: 'backpack', bbox: [120, 120, 40, 40] },
        ];
        win.InteractiveCanvas.drawOverlay(null, els['interactive-canvas'], els['live-stream-img'], tracks, null, {});
        const c = els['interactive-canvas'];
        c.emit('pointerdown', { button: 0, pointerId: 1, clientX: 130, clientY: 130 });
        c.emit('pointerup', { button: 0, pointerId: 1, clientX: 130, clientY: 130 });
        const strip = els['tag-track-picker-strip'];
        const chips = strip.children[1].children;
        chips[1].emit('click');
        await new Promise((r) => setTimeout(r, 55));
        return {
          stripDisplay: strip.style.display,
          chipCount: chips.length,
          activeTrackId: String(els['tag-track-id'].value),
          cropSrc: els['tag-roi-crop-img'].src,
          badge: els['tag-ai-class-badge'].textContent,
        };
        """
        out = _run_node(fetch_js, body_js)
        self.assertEqual(out["stripDisplay"], "flex")
        self.assertEqual(out["chipCount"], 2)
        self.assertEqual(out["activeTrackId"], "10")
        self.assertEqual(out["cropSrc"], "data:image/jpeg;base64,FAST")
        self.assertIn("person", out["badge"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_quick_tag_queue_advances_on_submit_and_closes_when_complete(self) -> None:
        fetch_js = """async (url, opts) => {
          fetchCalls.push({ url, body: JSON.parse(opts.body) });
          if (url.includes('recognize-roi')) return { ok: true, json: async () => ({ status: 'success', data: { crop_base64: 'data:image/jpeg;base64,Q', classification: { label: 'person', confidence: 0.85 }, candidates: [] } }) };
          return { ok: true, json: async () => ({ status: 'success', data: { entity_id: 1 } }) };
        }"""
        body_js = """
        win.InteractiveCanvas.initTagModal(() => 'cam_01');
        const tracks = [{ id: 21, class_name: 'person', bbox: [10, 10, 50, 90] }, { id: 22, class_name: 'laptop', bbox: [200, 200, 60, 40] }];
        win.InteractiveCanvas.drawOverlay(null, els['interactive-canvas'], els['live-stream-img'], tracks, null, {});
        els['btn-quick-tag'].emit('click');
        const firstId = String(els['tag-track-id'].value);
        els['tag-name-input'].value = 'Alice';
        await Promise.all(els['tag-entity-form'].emit('submit'));
        const afterFirst = { modalDisplay: els['modal-tag-entity'].style.display, nextTrackId: String(els['tag-track-id'].value), remaining: win.TagTrackQueue.getState().remaining };
        els['tag-name-input'].value = 'MacBook';
        await Promise.all(els['tag-entity-form'].emit('submit'));
        return { firstId, afterFirst, finalDisplay: els['modal-tag-entity'].style.display, finalTotal: win.TagTrackQueue.getState().total, commits: fetchCalls.filter((c) => c.url === '/api/tag/commit').map((c) => c.body.track_id) };
        """
        out = _run_node(fetch_js, body_js)
        self.assertEqual(out["firstId"], "21")
        self.assertEqual(out["afterFirst"], {"modalDisplay": "flex", "nextTrackId": "22", "remaining": 1})
        self.assertEqual(out["finalDisplay"], "none")
        self.assertEqual(out["finalTotal"], 0)
        self.assertEqual(out["commits"], [21, 22])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_scrubber_collects_overlapping_tracks_across_visible_layers_and_cancel_clears(self) -> None:
        fetch_js = """async (url, opts) => {
          fetchCalls.push({ url, body: JSON.parse(opts.body) });
          return { ok: true, json: async () => ({ status: 'success', data: {
            crop_base64: 'data:image/jpeg;base64,S', classification: { label: 'person', confidence: 0.8 }, candidates: [],
          }})};
        }"""
        body_js = """
        win.InteractiveCanvas.initTagModal(() => 'cam_01');
        win.ScrubberOverlay.setLayer('run_a', { label: 'Run A', frameDetections: [{ time: 5.0, tracks: [{ id: 1, bbox: [100, 100, 120, 140] }] }] });
        win.ScrubberOverlay.setLayer('run_b', { label: 'Run B', frameDetections: [{ time: 5.0, tracks: [{ id: 2, bbox: [110, 110, 60, 60] }] }] });
        const sc = els['scrubber-overlay-canvas'];
        sc.emit('pointerdown', { button: 0, pointerId: 1, clientX: 120, clientY: 120 });
        sc.emit('pointerup', { button: 0, pointerId: 1, clientX: 120, clientY: 120 });
        const beforeCancel = win.TagTrackQueue.getState().total;
        els['modal-tag-cancel'].emit('click');
        return { beforeCancel, afterCancel: win.TagTrackQueue.getState().total, stripDisplay: els['tag-track-picker-strip'].style.display };
        """
        out = _run_node(fetch_js, body_js, load_scrubber=True)
        self.assertEqual(out["beforeCancel"], 2)
        self.assertEqual(out["afterCancel"], 0)
        self.assertEqual(out["stripDisplay"], "none")


if __name__ == "__main__":
    unittest.main()
