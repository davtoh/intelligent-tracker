#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Unit & Runtime Regression Tests for Video Studio Scrubber UX,
Natural Card Stacking Context, Report Deletion UI, and Paired Controls.
"""

import json
import os
import pathlib
import re
import shutil
import subprocess
import unittest

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR / "dashboard" / "static"
CSS_DIR = STATIC_DIR / "css"
JS_DIR = STATIC_DIR / "js"


class TestScrubberUXStaticAndModularityContracts(unittest.TestCase):
    """Verify CSS stacking rules, script/style import ordering, and modularity budgets."""

    def test_css_stacking_context_rules_and_zero_important(self):
        """scrubber.css sets relative positioning and natural z-index elevation without !important."""
        scrubber_css = (CSS_DIR / "scrubber.css").read_text(encoding="utf-8")
        overlays_css = (CSS_DIR / "scrubber_overlays.css").read_text(encoding="utf-8")
        styles_css = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")
        index_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

        self.assertRegex(scrubber_css, r"\.video-file-card\s*\{[^}]*position:\s*relative;")
        self.assertIn(".video-file-card:has(.video-action-menu:not([hidden]))", scrubber_css)
        self.assertIn(".video-file-card.menu-open", scrubber_css)
        self.assertRegex(scrubber_css, r"z-index:\s*25;")

        self.assertEqual(len(re.findall(r"!important\b", scrubber_css, re.IGNORECASE)), 0)
        self.assertEqual(len(re.findall(r"!important\b", overlays_css, re.IGNORECASE)), 0)

        scrubber_idx = styles_css.index('css/scrubber.css')
        overlays_idx = styles_css.index('css/scrubber_overlays.css')
        self.assertLess(scrubber_idx, overlays_idx)

        reports_js_idx = index_html.index('/static/js/video_batch_reports.js')
        batch_js_idx = index_html.index('/static/js/video_batch.js')
        self.assertLess(reports_js_idx, batch_js_idx)

        playback_js_idx = index_html.index('/static/js/scrubber_playback_state.js')
        bridge_js_idx = index_html.index('/static/js/scrubber_library_bridge.js')
        scrubber_js_idx = index_html.index('/static/video_scrubber.js')
        self.assertLess(playback_js_idx, bridge_js_idx)
        self.assertLess(bridge_js_idx, scrubber_js_idx)

    def test_modularity_budgets_under_350_lines(self):
        """Extracted CSS and JS modules stay strictly within modularity budgets."""
        targets = [
            CSS_DIR / "scrubber.css",
            CSS_DIR / "scrubber_overlays.css",
            JS_DIR / "video_batch.js",
            JS_DIR / "video_batch_reports.js",
            JS_DIR / "scrubber_playback_state.js",
            JS_DIR / "scrubber_library_bridge.js",
        ]
        for path in targets:
            line_count = len(path.read_text(encoding="utf-8").splitlines())
            self.assertLess(
                line_count,
                350,
                f"{path.name} has {line_count} lines; expected < 350 lines",
            )
        video_scrubber_lines = len((STATIC_DIR / "video_scrubber.js").read_text(encoding="utf-8").splitlines())
        self.assertLess(video_scrubber_lines, 500, f"video_scrubber.js exceeded 500L ceiling ({video_scrubber_lines})")


class TestMilestone2JSRuntimeBehaviors(unittest.TestCase):
    """Execute real JS modules in Node.js VM to verify UI, stacking class, and deletion sync."""

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS runtime verification")
    def _run_js(self, files: list[str], body: str) -> dict:
        prelude = """
const fs = require('fs'), vm = require('vm'), path = require('path'), jsDir = process.env.JS_DIR;
const byId = new Map(), docListeners = new Map(), winListeners = new Map(), storage = new Map(), draws = [];
const allRootEls = [];

const makeEl = (tag = 'div', id = '') => {
  const attrs = new Map(), listeners = new Map(), classes = new Set();
  const el = {
    tagName: tag.toUpperCase(), id, style: {}, hidden: false, disabled: false,
    textContent: '', value: '', title: '', tabIndex: 0, _html: '', _children: [],
    parentNode: null, parentElement: null,
    classList: {
      add: (...c) => c.forEach(x => classes.add(x)),
      remove: (...c) => c.forEach(x => classes.delete(x)),
      toggle: (c, f) => (f === undefined ? (classes.has(c) ? classes.delete(c) : classes.add(c)) : (f ? classes.add(c) : classes.delete(c))),
      contains: (c) => classes.has(c),
    },
    setAttribute: (k, v) => {
      attrs.set(k, String(v));
      if (k === 'class') String(v).split(/\\s+/).filter(Boolean).forEach(x => classes.add(x));
      if (k === 'id') { el.id = String(v); byId.set(el.id, el); }
    },
    getAttribute: (k) => (attrs.has(k) ? attrs.get(k) : null),
    removeAttribute: (k) => attrs.delete(k),
    addEventListener: (t, fn) => { if (!listeners.has(t)) listeners.set(t, []); listeners.get(t).push(fn); },
    dispatchEvent: (ev) => {
      ev.target = ev.target || el; ev.currentTarget = el;
      ev.stopPropagation = ev.stopPropagation || (() => {});
      ev.preventDefault = ev.preventDefault || (() => {});
      (listeners.get(ev.type) || []).forEach(fn => fn(ev));
    },
    click: () => el.dispatchEvent({ type: 'click', target: el }),
    focus: () => { doc.activeElement = el; },
    matches: () => false,
    contains: (c) => el === c || el._children.includes(c) || el._children.some(ch => ch.contains(c)),
    closest: (sel) => {
      const parts = sel.split(',').map(s => s.trim());
      let cur = el;
      while (cur) {
        if (parts.some(p => p.startsWith('.') && cur.classList.contains(p.slice(1)))) return cur;
        cur = cur.parentElement || cur.parentNode;
      }
      return null;
    },
    insertBefore: (n) => { n.parentNode = el; n.parentElement = el; if (n.id) byId.set(n.id, n); allRootEls.push(n); },
    querySelectorAll: (sel) => {
      const matchesOne = (c, p) => {
        if (p.startsWith('#')) return c.id === p.slice(1);
        if (p.startsWith('.')) {
          const m = p.match(/^\\.([^\\[]+)(\\[data-filename="([^"]+)"\\])?/);
          if (!m || !c.classList.contains(m[1])) return false;
          return m[3] ? c.getAttribute('data-filename') === m[3].replace(/\\\\/g, '') : true;
        }
        return c.tagName.toLowerCase() === p.toLowerCase();
      };
      const parts = sel.split(',').map(s => s.trim());
      const out = [];
      const walk = (node) => {
        for (const ch of node._children) {
          if (parts.some(p => matchesOne(ch, p))) out.push(ch);
          walk(ch);
        }
      };
      walk(el);
      return out;
    },
    querySelector: (sel) => el.querySelectorAll(sel)[0] || null,
    getBoundingClientRect: () => el._rect || { left: 0, top: 0, width: 960, height: 543 },
  };
  Object.defineProperty(el, 'innerHTML', {
    get: () => el._html,
    set: (html) => {
      el._html = String(html);
      el._children = [];
      el.textContent = '';
      const stack = [el];
      const tagRe = /<(\\/?)(div|button|select|option|span|h4|label|code|strong)\\b([^>]*)>/gi;
      let lastIdx = 0;
      for (let m; (m = tagRe.exec(el._html)) !== null;) {
        const chunk = el._html.slice(lastIdx, m.index);
        if (chunk.trim()) stack[stack.length - 1].textContent += chunk.trim();
        lastIdx = tagRe.lastIndex;
        const isClose = m[1] === '/';
        const tagName = m[2].toLowerCase();
        if (isClose) {
          if (stack.length > 1) stack.pop();
          continue;
        }
        const parent = stack[stack.length - 1];
        const child = makeEl(tagName);
        child.parentNode = parent;
        child.parentElement = parent;
        const attrStr = m[3] || '';
        for (let am, attrRe = /([a-zA-Z0-9_-]+)="([^"]*)"/g; (am = attrRe.exec(attrStr)) !== null;) {
          child.setAttribute(am[1], am[2]);
        }
        if (/\\bhidden\\b/i.test(attrStr)) child.hidden = true;
        if (/\\bselected\\b/i.test(attrStr)) parent.value = child.getAttribute('value') || '';
        parent._children.push(child);
        if (!['option'].includes(tagName) && !attrStr.trim().endsWith('/')) {
          stack.push(child);
        }
      }
    },
  });
  return el;
};

const stage = makeEl('div', 'scrubber-stage');
const viewport = makeEl('div', 'scrubber-viewport');
viewport.parentNode = stage; viewport._rect = { left: 0, top: 0, width: 960, height: 543 };
const player = makeEl('video', 'scrubber-video-player');
player._rect = { left: 0, top: 0, width: 960, height: 543 };
player.videoWidth = 1920; player.videoHeight = 1080; player.currentTime = 1.0;
player.duration = 0; player.paused = true; player.error = null; player.playCalls = 0;
player.pause = () => { player.paused = true; };
player.play = async () => { player.paused = false; player.playCalls += 1; };
player.load = () => {};
const canvas = makeEl('canvas', 'scrubber-overlay-canvas');
canvas.parentElement = viewport;
const ctx2d = {
  strokeStyle: '', fillStyle: '', lineWidth: 1, font: '', textBaseline: 'top',
  save: () => {}, restore: () => {}, scale: () => {}, clearRect: () => {}, fillRect: () => {},
  strokeRect: (x, y, w, h) => draws.push({ op: 'strokeRect', x, y, w, h, stroke: ctx2d.strokeStyle }),
  measureText: (txt) => ({ width: txt.length * 6 }),
  fillText: (txt, x, y) => draws.push({ op: 'fillText', txt, x, y, fill: ctx2d.fillStyle }),
};
canvas.getContext = () => ctx2d;
const layersBar = makeEl('div', 'scrubber-overlay-layers'), layersStatus = makeEl('div', 'scrubber-overlay-layers-status');
const reportContainer = makeEl('div', 'video-batch-report-container'), analyzeBtn = makeEl('button', 'btn-video-analyze');
const listContainer = makeEl('div', 'video-recordings-list');
const timelineSlider = makeEl('input', 'scrubber-timeline-slider'); timelineSlider.value = 0;
const timeDisplay = makeEl('span', 'scrubber-time-display');
const btnPlay = makeEl('button', 'scrubber-btn-play');
const btnPrev = makeEl('button', 'scrubber-btn-prev');
const btnNext = makeEl('button', 'scrubber-btn-next');
const tabPolicySelect = makeEl('select', 'scrubber-tab-policy'); tabPolicySelect.value = 'auto-resume';
const loadedTitle = makeEl('span', 'scrubber-loaded-title');
const addCamBtn = makeEl('button', 'btn-video-add-camera');
[player, canvas, layersBar, layersStatus, reportContainer, analyzeBtn, listContainer,
 timelineSlider, timeDisplay, btnPlay, btnPrev, btnNext, tabPolicySelect, loadedTitle, addCamBtn].forEach(e => {
  byId.set(e.id, e);
  allRootEls.push(e);
});

const doc = {
  readyState: 'complete', activeElement: null,
  getElementById: (id) => byId.get(id) || null,
  createElement: (tag) => makeEl(tag),
  querySelector: (sel) => (sel === '.scrubber-viewport' ? viewport : doc.querySelectorAll(sel)[0] || null),
  querySelectorAll: (sel) => allRootEls.flatMap(root => root.querySelectorAll(sel)),
  addEventListener: (t, fn) => { if (!docListeners.has(t)) docListeners.set(t, []); docListeners.get(t).push(fn); },
  dispatchEvent: (ev) => (docListeners.get(ev.type) || []).forEach(fn => fn(ev)),
};

function CustomEvent(type, init = {}) { this.type = type; this.detail = init.detail; }
function HTMLElement() {}
const toasts = [];
const sandbox = {
  console, Math, Number, String, Array, Object, Map, Set, JSON, Promise, Infinity, isNaN, parseFloat, parseInt, encodeURIComponent,
  HTMLElement, CustomEvent, MediaError: { MEDIA_ERR_SRC_NOT_SUPPORTED: 4 },
  CSS: { escape: (s) => String(s).replace(/[^a-zA-Z0-9_-]/g, '\\\\$&') },
  localStorage: { getItem: (k) => (storage.has(k) ? storage.get(k) : null), setItem: (k, v) => storage.set(k, String(v)) },
  getComputedStyle: () => ({ direction: 'ltr' }), requestAnimationFrame: () => 1, cancelAnimationFrame: () => {},
  document: doc, fetch: async () => ({ ok: false, json: async () => ({}) }), devicePixelRatio: 1,
  showToast: (msg, type) => toasts.push({ msg, type }),
};
sandbox.window = sandbox;
sandbox.addEventListener = (t, fn) => { if (!winListeners.has(t)) winListeners.set(t, []); winListeners.get(t).push(fn); };
sandbox.dispatchEvent = (ev) => Promise.all((winListeners.get(ev.type) || []).map(fn => fn(ev)));
vm.createContext(sandbox);
JSON.parse(process.env.JS_FILES).forEach(f => vm.runInContext(fs.readFileSync(path.join(jsDir, f), 'utf8'), sandbox, { filename: f }));
(async () => {
"""
        epilogue = "\n})().catch(err => { console.error(err); process.exit(1); });"
        env = dict(os.environ, JS_DIR=str(JS_DIR), JS_FILES=json.dumps(files))
        proc = subprocess.run(
            ["node", "-e", prelude + body + epilogue],
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )
        self.assertEqual(
            proc.returncode,
            0,
            f"Node harness failed:\nSTDERR:\n{proc.stderr}\nSTDOUT:\n{proc.stdout}",
        )
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_video_library_menu_open_toggles_card_stacking_class(self):
        """Opening/closing .video-action-menu toggles .menu-open on parent .video-file-card."""
        res = self._run_js(
            ["video_library.js"],
            """
const files = [
  { filename: 'cam_1.mp4', video_url: '/videos/cam_1.mp4', size_mb: 10.0, codec: 'hevc', web_compatible: false, has_converted_h264: true, converted_filename: 'cam_1_h264.mp4' },
  { filename: 'cam_2.mp4', video_url: '/videos/cam_2.mp4', size_mb: 12.0, codec: 'hevc', web_compatible: false, has_converted_h264: true, converted_filename: 'cam_2_h264.mp4' },
];
sandbox.VideoLibrary.registerVideos(files);
listContainer.innerHTML = files.map(f => sandbox.VideoLibrary.renderVideoFileCard(f, 'cam_1.mp4')).join('');
sandbox.VideoLibrary.bindPairedActionControls(listContainer);

const cards = listContainer.querySelectorAll('.video-file-card');
const toggle1 = cards[0].querySelector('.btn-action-menu-toggle');
const menu1 = cards[0].querySelector('.video-action-menu');
const toggle2 = cards[1].querySelector('.btn-action-menu-toggle');
const menu2 = cards[1].querySelector('.video-action-menu');

toggle1.click();
const afterOpen1 = {
  card1MenuOpen: cards[0].classList.contains('menu-open'),
  card2MenuOpen: cards[1].classList.contains('menu-open'),
  menu1Hidden: menu1.hidden,
  expanded1: toggle1.getAttribute('aria-expanded'),
};

toggle2.click();
const afterOpen2 = {
  card1MenuOpen: cards[0].classList.contains('menu-open'),
  card2MenuOpen: cards[1].classList.contains('menu-open'),
  menu1Hidden: menu1.hidden,
  menu2Hidden: menu2.hidden,
  expanded1: toggle1.getAttribute('aria-expanded'),
  expanded2: toggle2.getAttribute('aria-expanded'),
};

doc.dispatchEvent({ type: 'keydown', key: 'Escape' });
const afterEsc = {
  card1MenuOpen: cards[0].classList.contains('menu-open'),
  card2MenuOpen: cards[1].classList.contains('menu-open'),
  menu2Hidden: menu2.hidden,
};
console.log(JSON.stringify({ afterOpen1, afterOpen2, afterEsc }));
""",
        )
        self.assertEqual(
            res["afterOpen1"],
            {"card1MenuOpen": True, "card2MenuOpen": False, "menu1Hidden": False, "expanded1": "true"},
        )
        self.assertEqual(
            res["afterOpen2"],
            {
                "card1MenuOpen": False,
                "card2MenuOpen": True,
                "menu1Hidden": True,
                "menu2Hidden": False,
                "expanded1": "false",
                "expanded2": "true",
            },
        )
        self.assertEqual(
            res["afterEsc"],
            {"card1MenuOpen": False, "card2MenuOpen": False, "menu2Hidden": True},
        )

    def test_force_reconvert_cancel_preserves_paired_h264_switch_controls(self):
        """Cancelling a force=true re-convert job keeps paired H.264 switch buttons and restores Re-convert."""
        res = self._run_js(
            ["video_library.js"],
            """
let refreshCalls = 0;
sandbox.loadVideosList = () => { refreshCalls += 1; };
sandbox.VideoJobClient = {
  currentViewedFilename: 'hevc_cam.mp4',
  getActiveJob: () => null,
  startTranscode: async (fn, opts) => ({ job: { job_id: 'jt1', job_type: 'transcode', filename: fn, status: 'running', progress: 15, force: opts.force } }),
};
const files = [
  { filename: 'hevc_cam.mp4', video_url: '/videos/hevc_cam.mp4', size_mb: 14.0, codec: 'hevc', web_compatible: false, has_converted_h264: true, converted_filename: 'hevc_cam_h264.mp4' },
];
sandbox.VideoLibrary.registerVideos(files);
listContainer.innerHTML = sandbox.VideoLibrary.renderVideoFileCard(files[0], 'hevc_cam.mp4');
sandbox.VideoLibrary.bindPairedActionControls(listContainer);
sandbox.VideoLibrary.showCodecNotice('HEVC unsupported', 'hevc_cam.mp4');

const reconvertBtn = listContainer.querySelector('.btn-reconvert-video');
reconvertBtn.click();
await new Promise(r => setTimeout(r, 5));

await sandbox.dispatchEvent(new CustomEvent('video-job-event', {
  detail: { type: 'job-update', data: { job_id: 'jt1', job_type: 'transcode', filename: 'hevc_cam.mp4', status: 'running', progress: 42 } }
}));
const whileRunningLabel = reconvertBtn.textContent;
const whileRunningDisabled = reconvertBtn.disabled;

await sandbox.dispatchEvent(new CustomEvent('video-job-event', {
  detail: { type: 'job-finished', data: { job_id: 'jt1', job_type: 'transcode', filename: 'hevc_cam.mp4', status: 'cancelled' } }
}));

const notice = doc.getElementById('scrubber-codec-notice');
console.log(JSON.stringify({
  whileRunningLabel,
  whileRunningDisabled,
  afterCancelLabel: reconvertBtn.textContent,
  afterCancelDisabled: reconvertBtn.disabled,
  cardHasSwitch: Boolean(listContainer.querySelector('.btn-switch-h264') && !listContainer.querySelector('.btn-switch-h264').disabled),
  noticeHasSwitch: Boolean(notice.querySelector('.btn-switch-h264')),
  pairedPreserved: sandbox.VideoLibrary.getPairedH264('hevc_cam.mp4'),
  refreshCalls,
}));
""",
        )
        self.assertEqual(res["whileRunningLabel"], "⏳ 42%")
        self.assertTrue(res["whileRunningDisabled"])
        self.assertEqual(res["afterCancelLabel"], "↺ Re-convert")
        self.assertFalse(res["afterCancelDisabled"])
        self.assertTrue(res["cardHasSwitch"])
        self.assertTrue(res["noticeHasSwitch"])
        self.assertEqual(res["pairedPreserved"]["convertedFilename"], "hevc_cam_h264.mp4")
        self.assertEqual(res["refreshCalls"], 1)

    def test_report_delete_run_and_clear_all_syncs_dropdown_layers_and_canvas(self):
        """Delete Run & Clear All update History dropdown, #scrubber-overlay-layers, and ScrubberOverlay canvas."""
        res = self._run_js(
            [
                "scrubber_overlay_renderer.js",
                "scrubber_overlay.js",
                "overlay_layer_toolbar.js",
                "overlay_layers.js",
                "video_batch_reports.js",
                "video_batch.js",
            ],
            """
let runsOnDisk = [
  { run_id: 'r2', config: { detector: 'yolov8', classes: ['truck'], confidence: 0.4 }, report: { frames_processed: 10, total_detections: 5 } },
  { run_id: 'r1', config: { detector: 'yolov8', classes: ['person'], confidence: 0.4 }, report: { frames_processed: 10, total_detections: 3 } },
];
const streams = {
  r1: { source_resolution: [1920, 1080], frame_detections: [{ time: 1.0, tracks: [{ track_id: 1, label: 'person', confidence: 0.9, bbox: [100, 100, 50, 100] }] }] },
  r2: { source_resolution: [1920, 1080], frame_detections: [{ time: 1.0, tracks: [{ track_id: 2, label: 'truck', confidence: 0.85, bbox: [400, 200, 120, 80] }] }] },
};
const apiCalls = [];
sandbox.fetch = async (url, opts = {}) => {
  const method = (opts.method || 'GET').toUpperCase();
  apiCalls.push({ method, url });
  if (method === 'DELETE' && url.endsWith('/reports/r2')) {
    runsOnDisk = runsOnDisk.filter(r => r.run_id !== 'r2');
    return { ok: true, json: async () => ({ status: 'success', deleted_run_id: 'r2' }) };
  }
  if (method === 'DELETE' && url.endsWith('/reports')) {
    const count = runsOnDisk.length;
    runsOnDisk = [];
    return { ok: true, json: async () => ({ status: 'success', cleared_count: count }) };
  }
  if (url.endsWith('/reports')) {
    return { ok: true, json: async () => runsOnDisk.slice() };
  }
  const m = url.match(/reports\\/([^/]+)\\/detections/);
  return { ok: Boolean(m && streams[m[1]]), json: async () => streams[m[1]] };
};

await sandbox.VideoBatch.restoreReportForFile('gate_cam.mp4');
await new Promise(r => setTimeout(r, 10));
layersBar.querySelectorAll('.overlay-layer-chip').find(c => c.getAttribute('data-run-id') === 'r1').click();
await new Promise(r => setTimeout(r, 10));
draws.length = 0;
sandbox.ScrubberOverlay.render();

const beforeDelete = {
  options: reportContainer.querySelectorAll('option').map(o => o.getAttribute('value')),
  chips: layersBar.querySelectorAll('.overlay-layer-chip').map(c => c.getAttribute('data-run-id')),
  activeLayerIds: sandbox.ScrubberOverlay.getActiveLayerIds(),
  strokeCount: draws.filter(d => d.op === 'strokeRect').length,
};

reportContainer.querySelector('#btn-delete-report-run').click();
await new Promise(r => setTimeout(r, 20));
draws.length = 0;
sandbox.ScrubberOverlay.render();
const afterSingleDelete = {
  options: reportContainer.querySelectorAll('option').map(o => o.getAttribute('value')),
  chips: layersBar.querySelectorAll('.overlay-layer-chip').map(c => c.getAttribute('data-run-id')),
  activeLayerIds: sandbox.ScrubberOverlay.getActiveLayerIds(),
  strokeCount: draws.filter(d => d.op === 'strokeRect').length,
  reportHasPerson: reportContainer.innerHTML.includes('person'),
  reportHasTruck: reportContainer.innerHTML.includes('truck'),
};

reportContainer.querySelector('#btn-clear-report-runs').click();
await new Promise(r => setTimeout(r, 20));
draws.length = 0;
sandbox.ScrubberOverlay.render();
const afterClearAll = {
  options: reportContainer.querySelectorAll('option').map(o => o.getAttribute('value')),
  layersBarHidden: layersBar.hidden,
  layersBarHtml: layersBar.innerHTML,
  activeLayerIds: sandbox.ScrubberOverlay.getActiveLayerIds(),
  strokeCount: draws.filter(d => d.op === 'strokeRect').length,
  hasEmptyState: reportContainer.innerHTML.includes('Batch Video Analytics'),
  storageEntry: JSON.parse(sandbox.localStorage.getItem('intelligent_tracker_overlay_layers_v1') || '{}')['gate_cam'] ?? null,
};

console.log(JSON.stringify({ apiCalls, beforeDelete, afterSingleDelete, afterClearAll }));
""",
        )
        self.assertEqual(res["beforeDelete"]["options"], ["r2", "r1"])
        self.assertEqual(set(res["beforeDelete"]["activeLayerIds"]), {"r2", "r1"})
        self.assertEqual(res["beforeDelete"]["strokeCount"], 2)

        self.assertEqual(res["afterSingleDelete"]["options"], ["r1"])
        self.assertEqual(res["afterSingleDelete"]["chips"], ["r1"])
        self.assertEqual(res["afterSingleDelete"]["activeLayerIds"], ["r1"])
        self.assertEqual(res["afterSingleDelete"]["strokeCount"], 1)
        self.assertTrue(res["afterSingleDelete"]["reportHasPerson"])
        self.assertFalse(res["afterSingleDelete"]["reportHasTruck"])

        self.assertEqual(res["afterClearAll"]["options"], [])
        self.assertTrue(res["afterClearAll"]["layersBarHidden"])
        self.assertEqual(res["afterClearAll"]["layersBarHtml"], "")
        self.assertEqual(res["afterClearAll"]["activeLayerIds"], [])
        self.assertEqual(res["afterClearAll"]["strokeCount"], 0)
        self.assertTrue(res["afterClearAll"]["hasEmptyState"])
        self.assertIsNone(res["afterClearAll"]["storageEntry"])

    def test_delete_error_and_async_view_isolation(self):
        """Failed DELETE re-enables buttons; switching video mid-delete prevents overwriting active view."""
        res = self._run_js(
            ["video_batch_reports.js", "video_batch.js"],
            """
let mode = 'fail';
sandbox.fetch = async (url, opts = {}) => {
  const method = (opts.method || 'GET').toUpperCase();
  if (method === 'DELETE') {
    if (mode === 'fail') return { ok: false, statusText: 'Server Error', json: async () => ({ detail: 'Disk locked' }) };
    await new Promise(r => setTimeout(r, 15));
    return { ok: true, json: async () => ({ status: 'success', deleted_run_id: 'r1' }) };
  }
  if (mode === 'fail') {
    return { ok: true, json: async () => [{ run_id: 'r1', config: { detector: 'yolov8', classes: ['person'] }, report: { frames_processed: 5 } }] };
  }
  return { ok: true, json: async () => [] };
};

await sandbox.VideoBatch.restoreReportForFile('vid_a.mp4');
const failedDeleteResult = await sandbox.VideoBatchReports.deleteReportRun('vid_a.mp4', 'r1');
const btnDisabledAfterFail = reportContainer.querySelector('#btn-delete-report-run').disabled;

mode = 'slow-ok';
const pendingDelete = sandbox.VideoBatchReports.deleteReportRun('vid_a.mp4', 'r1');
sandbox.VideoBatch.setCurrentBatchFilename('other.mp4');
reportContainer.innerHTML = '<div>OTHER_ACTIVE_VIEW</div>';
const slowDeleteResult = await pendingDelete;

console.log(JSON.stringify({
  failedDeleteResult,
  btnDisabledAfterFail,
  slowDeleteResult,
  activeHtml: reportContainer.innerHTML,
  toasts,
}));
""",
        )
        self.assertFalse(res["failedDeleteResult"])
        self.assertFalse(res["btnDisabledAfterFail"])
        self.assertTrue(res["slowDeleteResult"])
        self.assertEqual(res["activeHtml"], "<div>OTHER_ACTIVE_VIEW</div>")
        self.assertEqual(res["toasts"][0]["type"], "error")


class TestMilestone3LayerScalingAndTimelinePersistence(unittest.TestCase):
    """Verify Milestone 3 layer-isolated resolution scaling and policy-governed slider persistence."""

    def _run_js(self, files: list[str], body: str) -> dict:
        return TestMilestone2JSRuntimeBehaviors()._run_js(files, body)

    def test_concurrent_multi_resolution_layer_scaling_isolation(self):
        """Concurrent 2688x1520 & 1920x1086 layers scale independently without primary cross-contamination."""
        res = self._run_js(
            ["scrubber_overlay_renderer.js", "scrubber_overlay.js"],
            """
player.videoWidth = 1920; player.videoHeight = 1086; player.currentTime = 2.0;

// Primary/Run 1: 2688x1520 detection at normalized center (0.5, 0.25) -> [1344, 380, 134.4, 152]
sandbox.ScrubberOverlay.setLayer('r1', {
  runId: 'r1',
  shortLabel: 'R1',
  color: sandbox.ScrubberOverlay.PALETTES[0],
  sourceResolution: [2688, 1520],
  frameDetections: [{ time: 2.0, tracks: [{ track_id: 1, label: 'car', confidence: 0.9, bbox: [1344, 380, 134.4, 152] }] }],
});

// Run 2: 1920x1086 detection WITHOUT per-frame source_resolution (relies on layer.sourceResolution)
sandbox.ScrubberOverlay.setLayer('r2', {
  runId: 'r2',
  shortLabel: 'R2',
  color: sandbox.ScrubberOverlay.PALETTES[1],
  sourceResolution: [1920, 1086],
  frameDetections: [{ time: 2.0, tracks: [{ track_id: 2, label: 'car', confidence: 0.88, bbox: [960, 271.5, 96, 108.6] }] }],
});

// Run 3: null layer.sourceResolution while r1 (primary) is 2688x1520 -> MUST fall back to player [1920, 1086], NOT r1!
sandbox.ScrubberOverlay.setLayer('r3', {
  runId: 'r3',
  shortLabel: 'R3',
  color: sandbox.ScrubberOverlay.PALETTES[2],
  sourceResolution: null,
  frameDetections: [{ time: 2.0, tracks: [{ track_id: 3, label: 'truck', confidence: 0.82, bbox: [960, 271.5, 96, 108.6] }] }],
});
// Force r1 back as primary so r3 would be contaminated if getPrimaryLayer()?.sourceResolution were used
sandbox.ScrubberOverlay.setLayer('r1', {
  runId: 'r1',
  shortLabel: 'R1',
  color: sandbox.ScrubberOverlay.PALETTES[0],
  sourceResolution: [2688, 1520],
  frameDetections: [{ time: 2.0, tracks: [{ track_id: 1, label: 'car', confidence: 0.9, bbox: [1344, 380, 134.4, 152] }] }],
});

draws.length = 0;
sandbox.ScrubberOverlay.render();
const rectsOn1920 = draws.filter(d => d.op === 'strokeRect');

// Switch player to original 2688x1520 and re-render r1 + r2
sandbox.ScrubberOverlay.removeLayer('r3');
player.videoWidth = 2688; player.videoHeight = 1520;
draws.length = 0;
sandbox.ScrubberOverlay.render();
const rectsOn2688 = draws.filter(d => d.op === 'strokeRect');

console.log(JSON.stringify({ rectsOn1920, rectsOn2688 }));
""",
        )
        # On 1920x1086 player, R2, R3 (null fallback->player 1920x1086), and R1 all land at x=480, y=135.75!
        self.assertEqual(len(res["rectsOn1920"]), 3)
        for rect in res["rectsOn1920"]:
            self.assertAlmostEqual(rect["x"], 480.0, delta=0.5)
            self.assertAlmostEqual(rect["y"], 135.75, delta=0.5)
            self.assertAlmostEqual(rect["w"], 48.0, delta=0.5)
            self.assertAlmostEqual(rect["h"], 54.3, delta=0.5)

        self.assertEqual(len(res["rectsOn2688"]), 2)
        for rect in res["rectsOn2688"]:
            self.assertAlmostEqual(rect["x"], 480.0, delta=0.5)
            self.assertAlmostEqual(rect["y"], 135.75, delta=0.5)

    def test_scrubber_timeline_preserves_position_across_pairs_recordings_and_policies(self):
        """scrubber-timeline-slider preserves stem position on auto-resume/keep-paused and resets on reset."""
        res = self._run_js(
            ["scrubber_playback_state.js", "scrubber_library_bridge.js", "video_library.js", "../video_scrubber.js"],
            """
// Simulate real browser <video>.load() resetting currentTime/duration until loadedmetadata fires
player.load = () => { player.currentTime = 0; player.duration = NaN; player.error = null; };
const finishLoad = (dur) => { player.duration = dur; player.dispatchEvent({ type: 'loadedmetadata' }); };

// 1. keep-paused: scrub clip_a_h264.mp4 to 12.5s / 50s (25%)
sandbox.VideoScrubber.setTabPolicy('keep-paused');
sandbox.VideoScrubber.loadVideoIntoPlayer('/videos/clip_a_h264.mp4', 'clip_a_h264.mp4', true, 'h264');
finishLoad(50);
timelineSlider.value = 25;
timelineSlider.dispatchEvent({ type: 'input', target: timelineSlider });
const clipAAfterScrub = { t: player.currentTime, slider: Number(timelineSlider.value) };

// 2. Switch to distinct recording clip_b_h264.mp4 -> starts at 0, scrub to 60s / 100s (60%)
sandbox.VideoScrubber.loadVideoIntoPlayer('/videos/clip_b_h264.mp4', 'clip_b_h264.mp4', true, 'h264');
const clipBInitial = { t: player.currentTime, slider: Number(timelineSlider.value) };
finishLoad(100);
timelineSlider.value = 60;
timelineSlider.dispatchEvent({ type: 'input', target: timelineSlider });

// 3. Switch back to clip_a_h264.mp4 -> slider immediately shows 25% and loadedmetadata restores 12.5s
sandbox.VideoScrubber.loadVideoIntoPlayer('/videos/clip_a_h264.mp4', 'clip_a_h264.mp4', true, 'h264');
const clipABeforeMeta = { slider: Number(timelineSlider.value) };
finishLoad(50);
const clipAAfterMeta = { t: player.currentTime, slider: Number(timelineSlider.value), playCalls: player.playCalls };

// 4. Switch to unplayable HEVC original clip_a.mp4 (error, no loadedmetadata), then back to clip_a_h264.mp4
sandbox.VideoScrubber.loadVideoIntoPlayer('/videos/clip_a.mp4', 'clip_a.mp4', false, 'hevc');
player.error = { code: 4 };
player.currentTime = 0;
player.dispatchEvent({ type: 'error' });
sandbox.VideoLibrary.switchToH264('clip_a_h264.mp4', '/videos/clip_a_h264.mp4');
finishLoad(50);
const afterHevcRoundTrip = { t: player.currentTime, slider: Number(timelineSlider.value), paused: player.paused };

// 5. auto-resume: play clip_a_h264.mp4 at 20s (40%), switch to clip_b (paused at 60%), switch back -> resumes!
sandbox.VideoScrubber.setTabPolicy('auto-resume');
await player.play();
player.playCalls = 0;
timelineSlider.value = 40;
timelineSlider.dispatchEvent({ type: 'input', target: timelineSlider });

sandbox.VideoScrubber.loadVideoIntoPlayer('/videos/clip_b_h264.mp4', 'clip_b_h264.mp4', true, 'h264');
finishLoad(100);
const clipBWhileAutoResume = { t: player.currentTime, slider: Number(timelineSlider.value), paused: player.paused, playCalls: player.playCalls };

sandbox.VideoScrubber.loadVideoIntoPlayer('/videos/clip_a_h264.mp4', 'clip_a_h264.mp4', true, 'h264');
finishLoad(50);
await new Promise(r => setTimeout(r, 5));
const clipAAutoResumed = { t: player.currentTime, slider: Number(timelineSlider.value), paused: player.paused, playCalls: player.playCalls };

// 6. reset: change #scrubber-tab-policy select to 'reset' -> loading clip_a_h264.mp4 resets slider & time to 0
tabPolicySelect.value = 'reset';
tabPolicySelect.dispatchEvent({ type: 'change', target: tabPolicySelect });
sandbox.VideoScrubber.loadVideoIntoPlayer('/videos/clip_a_h264.mp4', 'clip_a_h264.mp4', true, 'h264');
const afterResetBeforeMeta = { slider: Number(timelineSlider.value), t: player.currentTime };
finishLoad(50);
const afterResetAfterMeta = { slider: Number(timelineSlider.value), t: player.currentTime, saved: sandbox.VideoScrubber.getSavedPlaybackState('clip_a.mp4') };

console.log(JSON.stringify({
  clipAAfterScrub,
  clipBInitial,
  clipABeforeMeta,
  clipAAfterMeta,
  afterHevcRoundTrip,
  clipBWhileAutoResume,
  clipAAutoResumed,
  afterResetBeforeMeta,
  afterResetAfterMeta,
}));
""",
        )
        self.assertEqual(res["clipAAfterScrub"], {"t": 12.5, "slider": 25})
        self.assertEqual(res["clipBInitial"], {"t": 0, "slider": 0})
        self.assertEqual(res["clipABeforeMeta"], {"slider": 25})
        self.assertEqual(res["clipAAfterMeta"], {"t": 12.5, "slider": 25, "playCalls": 0})
        self.assertEqual(res["afterHevcRoundTrip"], {"t": 12.5, "slider": 25, "paused": True})
        self.assertEqual(res["clipBWhileAutoResume"], {"t": 60, "slider": 60, "paused": True, "playCalls": 0})
        self.assertEqual(res["clipAAutoResumed"], {"t": 20, "slider": 40, "paused": False, "playCalls": 1})
        self.assertEqual(res["afterResetBeforeMeta"], {"slider": 0, "t": 0})
        self.assertEqual(res["afterResetAfterMeta"], {"slider": 0, "t": 0, "saved": None})

    def test_playback_state_hydrates_from_local_storage_without_autoplay(self):
        """Saved stem timestamp survives simulated reload in localStorage without unexpected autoplay."""
        res = self._run_js(
            ["scrubber_playback_state.js", "scrubber_library_bridge.js", "../video_scrubber.js"],
            """
sandbox.localStorage.setItem(
  sandbox.ScrubberPlaybackState.STORAGE_KEY,
  JSON.stringify({ clip_persisted: { time: 18, duration: 60, pct: 30 } })
);
// Re-run scripts in a fresh inner VM sharing the same localStorage
const freshStorage = sandbox.localStorage;
const freshCtx = {
  ...sandbox,
  localStorage: freshStorage,
  window: null,
};
freshCtx.window = freshCtx;
vm.createContext(freshCtx);
['scrubber_playback_state.js', 'scrubber_library_bridge.js', '../video_scrubber.js'].forEach(f =>
  vm.runInContext(fs.readFileSync(path.join(jsDir, f), 'utf8'), freshCtx, { filename: f })
);
player.playCalls = 0;
player.paused = true;
freshCtx.VideoScrubber.loadVideoIntoPlayer('/videos/clip_persisted_h264.mp4', 'clip_persisted_h264.mp4', true, 'h264');
player.duration = 60;
player.dispatchEvent({ type: 'loadedmetadata' });

console.log(JSON.stringify({
  t: player.currentTime,
  slider: Number(timelineSlider.value),
  playCalls: player.playCalls,
  saved: freshCtx.VideoScrubber.getSavedPlaybackState('clip_persisted.mp4'),
}));
""",
        )
        self.assertEqual(res["t"], 18)
        self.assertEqual(res["slider"], 30)
        self.assertEqual(res["playCalls"], 0)
        self.assertEqual(res["saved"]["time"], 18)
        self.assertFalse(res["saved"]["wasPlaying"])

    def test_reconvert_button_text_containment_and_dimensions(self):
        """Rendered .video-action-menu overrides .glass-panel clamping and contains full Re-convert label."""
        res = self._run_js(
            ["video_library.js"],
            """
const files = [
  { filename: 'cam_1.mp4', video_url: '/videos/cam_1.mp4', size_mb: 10.0, codec: 'hevc', web_compatible: false, has_converted_h264: true, converted_filename: 'cam_1_h264.mp4' },
];
sandbox.VideoLibrary.registerVideos(files);
listContainer.innerHTML = sandbox.VideoLibrary.renderVideoFileCard(files[0], 'cam_1.mp4');
sandbox.VideoLibrary.bindPairedActionControls(listContainer);

const toggle = listContainer.querySelector('.btn-action-menu-toggle');
const menu = listContainer.querySelector('.video-action-menu');
const reconvertBtn = menu.querySelector('.btn-reconvert-video');
toggle.click();

console.log(JSON.stringify({
  menuHidden: menu.hidden,
  menuHasGlassPanel: menu.classList.contains('glass-panel'),
  menuRole: menu.getAttribute('role'),
  btnText: reconvertBtn.textContent,
  btnRole: reconvertBtn.getAttribute('role'),
  btnHasXsClass: reconvertBtn.classList.contains('btn-xs'),
}));
""",
        )
        self.assertFalse(res["menuHidden"])
        self.assertTrue(res["menuHasGlassPanel"])
        self.assertEqual(res["menuRole"], "menu")
        self.assertEqual(res["btnText"], "↺ Re-convert")
        self.assertEqual(res["btnRole"], "menuitem")
        self.assertTrue(res["btnHasXsClass"])

        scrubber_css = (CSS_DIR / "scrubber.css").read_text(encoding="utf-8")
        menu_glass_match = re.search(r"\.video-action-menu\.glass-panel\s*\{([^}]*)\}", scrubber_css)
        self.assertIsNotNone(menu_glass_match, "Expected .video-action-menu.glass-panel specificity override")
        menu_glass_block = menu_glass_match.group(1)
        min_width_match = re.search(r"min-width:\s*(\d+)px;", menu_glass_block)
        self.assertIsNotNone(min_width_match)
        self.assertGreaterEqual(int(min_width_match.group(1)), 124)
        self.assertIn("width: max-content;", menu_glass_block)
        self.assertNotRegex(menu_glass_block, r"max-width:\s*100%;")
        self.assertIn("max-width: calc(100vw - 32px);", menu_glass_block)

        btn_blocks = re.findall(r"(?:\A|\n)\s*\.video-action-menu\s+\.btn-xs\s*\{([^}]*)\}", scrubber_css)
        self.assertTrue(btn_blocks, "Expected .video-action-menu .btn-xs rule block in scrubber.css")
        combined_btn_css = "\n".join(btn_blocks)
        self.assertIn("width: 100%;", combined_btn_css)
        self.assertIn("white-space: nowrap;", combined_btn_css)
        self.assertRegex(combined_btn_css, r"background:\s*rgba\(")
        self.assertNotIn("text-overflow: ellipsis", combined_btn_css)


if __name__ == "__main__":
    unittest.main()
