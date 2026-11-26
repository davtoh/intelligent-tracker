"""Milestone 2 UI contract tests: wide dialogs, enrollment stage, two-state tag modal, MediaEmptyState."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "dashboard" / "static"

_VM_HELPERS = r"""
const vm = require('vm');
const fs = require('fs');
function makeEl(id, extra = {}) {
  const listeners = {};
  const classes = new Set();
  const children = [];
  const attrs = {};
  return Object.assign({
    id, value: '', textContent: '', innerHTML: '', src: '', disabled: false,
    checked: false, style: {}, dataset: {}, options: [], selectedIndex: 0,
    parentElement: null, children,
    classList: {
      add: (...c) => c.forEach(x => classes.add(x)),
      remove: (...c) => c.forEach(x => classes.delete(x)),
      contains: (c) => classes.has(c),
      toggle: (c, f) => (f === undefined ? (classes.has(c) ? classes.delete(c) : classes.add(c)) : (f ? classes.add(c) : classes.delete(c))),
    },
    setAttribute: (k, v) => { attrs[k] = String(v); },
    getAttribute: (k) => (k in attrs ? attrs[k] : (k === 'src' ? '' : null)),
    removeAttribute: (k) => { delete attrs[k]; },
    addEventListener: (t, fn) => { (listeners[t] ||= []).push(fn); },
    dispatchEvent: (e) => (listeners[e?.type] || []).map(fn => fn(e)),
    querySelector: () => null,
    querySelectorAll: () => [],
    appendChild: (c) => { children.push(c); return c; },
    insertAdjacentElement: (_pos, c) => { children.push(c); return c; },
    remove: () => {},
    focus: () => {},
    reset: () => {},
    getContext: () => ({ drawImage() {}, clearRect() {}, strokeRect() {}, fillRect() {} }),
    toDataURL: () => 'data:image/jpeg;base64,CROP',
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 640, height: 360 }),
  }, extra);
}
function runVm(files, body) {
  const els = new Map();
  const ctx = vm.createContext({
    console, setTimeout, clearTimeout, setInterval, clearInterval,
    URLSearchParams, encodeURIComponent, decodeURIComponent,
    document: {
      readyState: 'complete',
      getElementById: (id) => els.get(id) || null,
      createElement: (tag) => makeEl(tag),
      querySelectorAll: () => [],
      addEventListener: () => {},
    },
    window: null,
    addEventListener: () => {},
    showToast: () => {},
    alert: () => {},
    localStorage: { getItem: () => null, setItem: () => {} },
    Image: class { set src(v) { this._s = v; if (this.onload) this.onload(); } get naturalWidth() { return 640; } get naturalHeight() { return 360; } },
    __els: els, __makeEl: makeEl,
  });
  ctx.window = ctx;
  const code = files.map(f => fs.readFileSync(f, 'utf8')).join('\n;\n') + '\n;\n(async () => {\n' + body + '\n})();';
  vm.runInContext(code, ctx);
}
"""


def _run_node(files: list[Path], body: str) -> dict:
    if not shutil.which("node"):
        raise unittest.SkipTest("node binary not available")
    file_list = json.dumps([str(p) for p in files])
    script = _VM_HELPERS + f"\nrunVm({file_list}, {json.dumps(body)});\n"
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise AssertionError(f"Node VM failed:\n{proc.stderr}\n{proc.stdout}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


_ENROLLMENT_STAGE_JS = r"""
const ids = ['tab-videos','scrubber-video-player','gallery-enroll-source-badge','modal-universal-enrollment','enroll-camera-select','enroll-bbox-canvas','enroll-canvas-placeholder','enroll-video-scrubber-box','enroll-scrubber-video','enroll-scrubber-slider','enroll-scrubber-time','enroll-scrubber-play','enroll-scrubber-prev','enroll-scrubber-next','enroll-scrubber-grab','enroll-category-select','enroll-name-input','enroll-role-input','enroll-notes-input','enroll-locked-anchor-cb','enroll-crop-preview-box','enroll-crop-preview-img','enroll-crop-meta','enroll-collision-banner','universal-enrollment-form','enroll-file-input','btn-open-enrollment','modal-enroll-close','modal-enroll-cancel','btn-capture-freeze','btn-upload-enroll-crop','btn-submit-enrollment'];
ids.forEach(id => __els.set(id, __makeEl(id)));
__els.get('tab-videos').classList.add('active');
__els.get('scrubber-video-player').dataset.filename = 'gate.mp4';
const vid = __els.get('enroll-scrubber-video');
Object.assign(vid, { paused: true, currentTime: 0, duration: 10, videoWidth: 640, videoHeight: 360, load: () => {}, pause: () => {} });
const payloads = [];
window.fetch = async (url, init) => {
  if (url.includes('/api/videos')) return { ok: true, json: async () => ({ videos: [{ filename: 'gate.mp4', video_url: '/videos/gate.mp4', fps: 24 }] }) };
  if (url.includes('/api/cameras')) return { ok: true, json: async () => [{ id: 'cam_01', name: 'Gate' }] };
  if (url.includes('/api/rsac/categories')) return { ok: true, json: async () => [{ id: 'person', name: 'Person' }] };
  if (url.includes('/api/enroll/check-collision')) return { ok: true, json: async () => ({ has_collision: false }) };
  if (url.includes('/api/enroll')) { payloads.push(JSON.parse(init.body)); return { ok: true, json: async () => ({ entity_id: 9 }) }; }
  return { ok: true, json: async () => ({}) };
};
UniversalEnrollment.init();
await UniversalEnrollment.populateCameraSelect();
const sel = __els.get('enroll-camera-select');
sel.options = [{ value: 'video:gate.mp4', getAttribute: (k) => k === 'data-fps' ? '24' : '/videos/gate.mp4' }];
sel.selectedIndex = 0;
await UniversalEnrollment.captureFreezeFrame(__els.get('enroll-bbox-canvas'), __els.get('enroll-canvas-placeholder'));
__els.get('enroll-scrubber-next').dispatchEvent({ type: 'click' });
const steppedTime = vid.currentTime;
vid.currentTime = 2.5;
vid.dispatchEvent({ type: 'timeupdate' });
__els.get('enroll-name-input').value = 'Alice';
UniversalEnrollment.loadFreezeImage('data:image/jpeg;base64,ABC', __els.get('enroll-bbox-canvas'), __els.get('enroll-canvas-placeholder'));
const canvas = __els.get('enroll-bbox-canvas');
canvas.dispatchEvent({ type: 'mousedown', clientX: 10, clientY: 10 });
canvas.dispatchEvent({ type: 'mouseup', clientX: 60, clientY: 60 });
await __els.get('universal-enrollment-form').dispatchEvent({ type: 'submit', preventDefault: () => {} })[0];
console.log(JSON.stringify({ selected: sel.value, badge: __els.get('gallery-enroll-source-badge').textContent, steppedTime, payload: payloads[0] }));
"""


class TestStep1DialogsEnrollmentAndMediaUI(unittest.TestCase):
    """Contract and Node VM tests for Milestone 2 UI components."""

    def test_modal_grid_css_and_html_line_budgets(self) -> None:
        grid_css = (STATIC_DIR / "css" / "modal_forms_grid.css").read_text(encoding="utf-8")
        modals_css = (STATIC_DIR / "css" / "modals.css").read_text(encoding="utf-8")
        for token in (".form-row", ".col-4", ".col-8", ".modal-left-col", ".modal-right-col"):
            self.assertIn(token, grid_css)
        self.assertIn("resize: both", modals_css)
        self.assertIn("@container (inline-size < 900px)", modals_css)
        self.assertNotIn("!important", grid_css)
        self.assertNotIn("!important", modals_css)
        self.assertLess(len((STATIC_DIR / "index.html").read_text(encoding="utf-8").splitlines()), 180)
        self.assertLess(len((STATIC_DIR / "partials" / "modals" / "entity_modals.html").read_text(encoding="utf-8").splitlines()), 240)
        self.assertLess(len((STATIC_DIR / "partials" / "modals" / "camera_modals.html").read_text(encoding="utf-8").splitlines()), 250)

    def test_unified_enrollment_stage_fps_step_and_metadata(self) -> None:
        entity_html = (STATIC_DIR / "partials" / "modals" / "entity_modals.html").read_text(encoding="utf-8")
        gallery_html = (STATIC_DIR / "partials" / "tabs" / "gallery.html").read_text(encoding="utf-8")
        self.assertIn('id="gallery-enroll-source-badge"', gallery_html)
        stage_pos = entity_html.index('class="enroll-canvas-wrapper"')
        vid_pos = entity_html.index('id="enroll-scrubber-video"')
        box_pos = entity_html.index('id="enroll-video-scrubber-box"')
        self.assertLess(stage_pos, vid_pos)
        self.assertLess(vid_pos, box_pos)
        files = [
            STATIC_DIR / "js" / "scrubber_timeline_slider.js",
            STATIC_DIR / "js" / "enrollment_stage_controller.js",
            STATIC_DIR / "js" / "universal_enrollment.js",
        ]
        res = _run_node(files, _ENROLLMENT_STAGE_JS)
        self.assertEqual(res["selected"], "video:gate.mp4")
        self.assertEqual(res["badge"], "Video: gate.mp4")
        self.assertAlmostEqual(res["steppedTime"], 1.0 / 24.0, places=4)
        self.assertEqual(res["payload"]["video_filename"], "gate.mp4")
        self.assertAlmostEqual(res["payload"]["media_offset_sec"], 2.5, places=2)

    def test_two_state_tag_modal_and_in_place_candidate_suppression(self) -> None:
        files = [
            STATIC_DIR / "js" / "tag_modal_state.js",
            STATIC_DIR / "js" / "tag_feedback_actions.js",
            STATIC_DIR / "js" / "interactive_canvas.js",
        ]
        res = _run_node(files, """
const ids = ['modal-tag-entity','tag-entity-form','tag-track-id','tag-bbox-val','tag-entity-id','tag-source-type','tag-video-filename','tag-timestamp-sec','tag-crop-base64','tag-name-input','tag-category-select','tag-notes-input','tag-modal-title','tag-roi-preview-panel','tag-roi-crop-img','tag-ai-class-badge','tag-identity-candidates','btn-tag-discourage','modal-tag-close','modal-tag-cancel','modal-tag-submit'];
ids.forEach(id => __els.set(id, __makeEl(id)));
window.fetch = async () => ({ ok: true, json: async () => ({ ok: true }) });
InteractiveCanvas.initTagModal(() => 'cam_01');
InteractiveCanvas.openTagModal({ id: 4, entity_id: 12, entity_name: 'Bob', bbox: [1, 2, 10, 10] }, { skipRecognition: true });
const knownSubmit = __els.get('modal-tag-submit').textContent;
const knownDisc = __els.get('btn-tag-discourage').textContent;
__els.get('tag-name-input').value = '';
__els.get('tag-name-input').dispatchEvent({ type: 'input' });
const newSubmit = __els.get('modal-tag-submit').textContent;
const newDiscDisp = __els.get('btn-tag-discourage').style.display;
const chip = __makeEl('chip');
__els.get('tag-entity-id').value = '12';
await TagFeedbackActions.discourageCandidate({ entity_id: 12, name: 'Bob' }, () => 'cam_01', chip);
console.log(JSON.stringify({ knownSubmit, knownDisc, newSubmit, newDiscDisp, modalDisp: __els.get('modal-tag-entity').style.display, eidAfter: __els.get('tag-entity-id').value }));
""")
        self.assertEqual(res["knownSubmit"], "✅ Confirm Match")
        self.assertEqual(res["knownDisc"], "🚫 Not Bob / False Positive")
        self.assertEqual(res["newSubmit"], "💾 Enroll to Gallery")
        self.assertEqual(res["newDiscDisp"], "none")
        self.assertEqual(res["modalDisp"], "flex")
        self.assertEqual(res["eidAfter"], "")

    def test_overlay_layers_force_invalidates_stream_cache_and_drawer_routes(self) -> None:
        res = _run_node([STATIC_DIR / "js" / "overlay_layers.js", STATIC_DIR / "js" / "app_ui_helpers.js"], """
['overlay-layer-toolbar','drawer-btn-enroll','drawer-btn-cameras','drawer-btn-backup','mobile-nav-drawer','mobile-drawer-backdrop'].forEach(id => __els.set(id, __makeEl(id)));
let detCalls = 0, enrollOpens = 0, camOpens = 0;
window.ScrubberOverlay = { PALETTES: [{ name: 'Cyan', stroke: '#06b6d4' }], setLayer() {}, removeLayer() {} };
window.UniversalEnrollment = { openModal: () => { enrollOpens += 1; } };
window.CameraManager = { openModal: () => { camOpens += 1; } };
window.fetch = async (url) => {
  if (url.includes('/reports/') && url.includes('/detections')) { detCalls += 1; return { ok: true, json: async () => ({ frame_detections: [{ frame: detCalls }] }) }; }
  return { ok: true, json: async () => [{ run_id: 'r1', label: 'Run 1', status: 'completed' }] };
};
await OverlayLayers.ensureLoaded('clip.mp4', { activateRunId: 'r1' });
await new Promise(r => setTimeout(r, 10));
await OverlayLayers.ensureLoaded('clip.mp4', { activateRunId: 'r1' });
await new Promise(r => setTimeout(r, 10));
await OverlayLayers.ensureLoaded('clip.mp4', { force: true, activateRunId: 'r1' });
await new Promise(r => setTimeout(r, 10));
AppUIHelpers.bindDrawerActionButtons(() => {});
__els.get('drawer-btn-enroll').dispatchEvent({ type: 'click' });
__els.get('drawer-btn-cameras').dispatchEvent({ type: 'click' });
console.log(JSON.stringify({ detCalls, enrollOpens, camOpens }));
""")
        self.assertEqual(res["detCalls"], 2)
        self.assertEqual(res["enrollOpens"], 1)
        self.assertEqual(res["camOpens"], 1)

    def test_media_empty_state_and_no_duplicate_studio_attach(self) -> None:
        res = _run_node([STATIC_DIR / "js" / "media_empty_state.js", STATIC_DIR / "js" / "live_player.js"], """
const parent = __makeEl('wrap');
['studio-live-img','static-heatmap-img','tag-roi-crop-img','snapshot-modal-img','enroll-crop-preview-img','test-preview-img','live-stream-img','studio-camera-select'].forEach(id => {
  const el = __makeEl(id, { parentElement: parent });
  __els.set(id, el);
});
MediaEmptyState.bindAll();
const studioImg = __els.get('studio-live-img');
const coldDisp = studioImg.style.display;
MediaEmptyState.setSource(studioImg, '');
const emptyAfterBlank = studioImg.style.display;
let attachCount = 0;
window.StudioCanvas = { attachStudioMedia: () => { attachCount += 1; } };
LivePlayer.syncTabStreams('tab-live', 'tab-studio');
console.log(JSON.stringify({ coldDisp, emptyAfterBlank, attachCount }));
""")
        self.assertEqual(res["coldDisp"], "none")
        self.assertEqual(res["emptyAfterBlank"], "none")
        self.assertEqual(res["attachCount"], 0)
