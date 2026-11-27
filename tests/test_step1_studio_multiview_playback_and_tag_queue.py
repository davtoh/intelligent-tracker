"""Step 1 unit and Node VM tests for Studio lifecycle, multiview wake, 4x/8x playback, TagTrackQueue, and clock hygiene."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from dashboard.services.async_inference_worker import build_live_step_result
from dashboard.services.diagnostic_bridge import DiagnosticTraceMiddleware, StaticNoCacheMiddleware
from dashboard.services.processing_mode_service import ProcessingModeService
from dashboard.stream_manager import StreamManager

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / "dashboard" / "static"
JS = STATIC / "js"


def _run_node(script: str) -> dict:
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False, timeout=20)
    if proc.returncode != 0:
        raise AssertionError(f"Node VM failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return json.loads(proc.stdout.strip())


class TestStep1BackendInvariants(unittest.TestCase):
    """Backend invariants for multiview wake, ASGI range bypass, and clock hygiene."""

    def test_resume_video_source_clears_hibernation_synchronously(self) -> None:
        from dashboard.services.stream_subscribers import StreamSubscriberRegistry

        mgr = StreamManager.__new__(StreamManager)
        mgr.camera_id = "cam_02"
        mgr._lock = __import__("threading").Lock()
        mgr._latest_telemetry = {"camera_id": "cam_02", "status": "hibernating"}
        mgr._processing_mode_service = ProcessingModeService(mode="focus_only")
        mgr._in_camera_pool = True
        mgr._subscriber_registry = StreamSubscriberRegistry(resume_callback=mgr._resume_video_source)
        mgr._subscriber_registry.is_hibernating = True
        mgr.video_source = MagicMock()
        mgr._recording_ctrl = MagicMock(is_recording=False)
        mgr.is_armed = False
        mgr._subscriber_registry.add_subscriber("mv_1")
        self.assertFalse(mgr._subscriber_registry.is_hibernating)
        self.assertEqual(mgr._latest_telemetry["status"], "online")
        mgr.video_source.resume.assert_called_once()

    def test_middlewares_are_pure_asgi_not_base_http_middleware(self) -> None:
        from starlette.middleware.base import BaseHTTPMiddleware

        self.assertFalse(issubclass(DiagnosticTraceMiddleware, BaseHTTPMiddleware))
        self.assertFalse(issubclass(StaticNoCacheMiddleware, BaseHTTPMiddleware))

    def test_build_live_step_result_uses_wall_clock_when_monotonic_now_passed(self) -> None:
        worker = MagicMock()
        worker.get_latest_result.return_value = None
        frame = np.zeros((32, 32, 3), dtype=np.uint8)
        res = build_live_step_result(worker, frame, now=12.5, frame_seq=3, run_vision=False)
        self.assertGreater(res.timestamp, 1_000_000_000.0)
        res_explicit = build_live_step_result(worker, frame, now=12.5, wall_now=1_700_000_000.0, frame_seq=4, run_vision=False)
        self.assertEqual(res_explicit.timestamp, 1_700_000_000.0)


@unittest.skipUnless(shutil.which("node"), "Node.js required for JS VM tests")
class TestStep1FrontendContracts(unittest.TestCase):
    """Node VM tests for OBS-014, OBS-002, OBS-001, and OBS-019."""

    def test_app_js_budget_and_nav_tab_click_emits_tab_changed(self) -> None:
        app_lines = len((STATIC / "app.js").read_text(encoding="utf-8").splitlines())
        self.assertLessEqual(app_lines, 340)
        script = (
            "const fs = require('fs'), vm = require('vm');\n"
            f"const hCode = fs.readFileSync({json.dumps(str(JS / 'app_ui_helpers.js'))}, 'utf8');\n"
            f"const aCode = fs.readFileSync({json.dumps(str(STATIC / 'app.js'))}, 'utf8');\n"
            f"const nCode = fs.readFileSync({json.dumps(str(JS / 'nav_tabs_manager.js'))}, 'utf8');\n"
            "const listeners = {}, studioCalls = [], events = [];\n"
            "const mkTab = (id, active) => { const cls = new Set(active ? ['active'] : []); const fn = []; return { getAttribute: (k) => k === 'data-tab' ? id : null, classList: { add: (c) => cls.add(c), remove: (c) => cls.delete(c), toggle: (c, v) => v ? cls.add(c) : cls.delete(c), contains: (c) => cls.has(c) }, addEventListener: (e, cb) => fn.push(cb), click: () => fn.forEach((f) => f()) }; };\n"
            "const tLive = mkTab('tab-live', true), tStudio = mkTab('tab-studio', false);\n"
            "const pLive = mkTab('tab-live', true), pStudio = mkTab('tab-studio', false);\n"
            "const els = { 'tab-live': pLive, 'tab-studio': pStudio };\n"
            "const doc = { readyState: 'complete', hidden: false, getElementById: (id) => els[id] || null, querySelector: () => null, querySelectorAll: (s) => s === '.nav-tab' ? [tLive, tStudio] : (s === '.tab-pane' ? [pLive, pStudio] : []), addEventListener: (e, cb) => { (listeners[e] ||= []).push(cb); } };\n"
            "const win = { location: { hash: '' }, scrollX: 0, scrollTo: () => {}, history: { pushState: () => {} }, addEventListener: (e, cb) => { (listeners[e] ||= []).push(cb); }, dispatchEvent: (ev) => { events.push(ev.type + ':' + ev.detail?.activeTab); }, Studio: { syncStudioTabState: (v) => studioCalls.push(v), renderBEV: () => {} } };\n"
            "class CustomEvent { constructor(t, o) { this.type = t; this.detail = o?.detail; } }\n"
            "const sb = { window: win, document: doc, history: win.history, CustomEvent, console, Math, Number, String, Boolean, Array, Object, JSON, Promise, setTimeout, clearTimeout };\n"
            "vm.runInNewContext(hCode, sb); vm.runInNewContext(aCode, sb); (listeners.DOMContentLoaded || []).forEach((f) => f());\n"
            "vm.runInNewContext(nCode, sb);\n"
            "tStudio.click();\n"
            "process.stdout.write(JSON.stringify({ studioCalls, events }));\n"
        )
        out = _run_node(script)
        self.assertIn(True, out["studioCalls"])
        self.assertIn("tab-changed:tab-studio", out["events"])

    def test_multiview_frame_and_telemetry_transition_badge_to_online(self) -> None:
        script = (
            "const fs = require('fs'), vm = require('vm');\n"
            f"const fCode = fs.readFileSync({json.dumps(str(JS / 'multiview' / 'frame_surface.js'))}, 'utf8');\n"
            f"const gCode = fs.readFileSync({json.dumps(str(JS / 'multiview' / 'grid_tile_overlay.js'))}, 'utf8');\n"
            "const badge = { className: 'tile-status-badge hibernating', textContent: 'HIBERNATING' };\n"
            "const tile = { getAttribute: (k) => k === 'data-id' ? 'cam_02' : null, querySelector: (s) => s === '.tile-status-badge' ? badge : null };\n"
            "const canvas = { width: 320, height: 180, dataset: {}, getContext: () => ({ drawImage: () => {}, fillRect: () => {}, fillText: () => {} }), closest: () => tile };\n"
            "const grid = { querySelectorAll: () => [tile] };\n"
            "const win = {}; const doc = { getElementById: () => grid };\n"
            "const sb = { window: win, document: doc, console, Math, Number, String, Boolean, Array, Object, WeakMap, Map };\n"
            "vm.runInNewContext(fCode, sb); vm.runInNewContext(gCode, sb);\n"
            "(async () => {\n"
            "  const s = new win.FrameSurface(canvas, { cameraId: 'cam_02', decodeBitmap: async () => ({ width: 320, height: 180, close: () => {} }) });\n"
            "  await s.pushFrame(new Uint8Array([1, 2]), 1, 1000);\n"
            "  const afterFrame = badge.textContent;\n"
            "  badge.className = 'tile-status-badge hibernating'; badge.textContent = 'HIBERNATING';\n"
            "  win.GridTileOverlay.handleTelemetry({ camera_id: 'cam_02', fps: 12.0, tracks: [] }, grid);\n"
            "  process.stdout.write(JSON.stringify({ afterFrame, afterTel: badge.textContent, cls: badge.className }));\n"
            "})();\n"
        )
        out = _run_node(script)
        self.assertEqual(out["afterFrame"], "ONLINE")
        self.assertEqual(out["afterTel"], "ONLINE")
        self.assertIn("online", out["cls"])

    def test_scrubber_playback_state_debounces_local_storage_and_flushes(self) -> None:
        script = (
            "const fs = require('fs'), vm = require('vm');\n"
            f"const pCode = fs.readFileSync({json.dumps(str(JS / 'scrubber_playback_state.js'))}, 'utf8');\n"
            "let writes = 0, timers = [];\n"
            "const store = {};\n"
            "const win = { localStorage: { getItem: (k) => store[k] || null, setItem: (k, v) => { writes += 1; store[k] = v; } }, addEventListener: () => {} };\n"
            "const fakeSetTimeout = (fn, ms) => { const id = timers.length + 1; timers.push({ id, fn, ms, cleared: false }); return id; };\n"
            "const fakeClearTimeout = (id) => { const t = timers.find((x) => x.id === id); if (t) t.cleared = true; };\n"
            "const sb = { window: win, localStorage: win.localStorage, setTimeout: fakeSetTimeout, clearTimeout: fakeClearTimeout, console, Math, Number, String, Boolean, Array, Object, JSON, Map };\n"
            "vm.runInNewContext(pCode, sb);\n"
            "const player = { currentTime: 1.0, duration: 10.0, paused: false, error: null };\n"
            "for (let i = 1; i <= 5; i++) { player.currentTime = i; win.ScrubberPlaybackState.saveFromPlayer(player, 'clip.mp4', true); }\n"
            "const writesBeforeFlush = writes;\n"
            "win.ScrubberPlaybackState.flushPendingPersist();\n"
            "process.stdout.write(JSON.stringify({ writesBeforeFlush, writesAfterFlush: writes, debounceMs: win.ScrubberPlaybackState.PERSIST_DEBOUNCE_MS }));\n"
        )
        out = _run_node(script)
        self.assertEqual(out["writesBeforeFlush"], 0)
        self.assertEqual(out["writesAfterFlush"], 1)
        self.assertGreaterEqual(out["debounceMs"], 500)

    def test_tag_track_queue_retains_crop_and_suppressions_on_next_prev(self) -> None:
        script = (
            "const fs = require('fs'), vm = require('vm');\n"
            f"const qCode = fs.readFileSync({json.dumps(str(JS / 'tag_track_queue.js'))}, 'utf8');\n"
            "const mkEl = (v = '') => ({ value: v, style: {}, innerHTML: '', dataset: {}, classList: { add: () => {} }, appendChild: () => {}, addEventListener: () => {} });\n"
            "const els = { 'tag-track-picker-strip': mkEl(), 'tag-crop-base64': mkEl('data:image/jpeg;base64,AAA'), 'tag-entity-id': mkEl('42'), 'tag-notes-input': mkEl('keep note') };\n"
            "const doc = { getElementById: (id) => els[id] || null, createElement: () => mkEl() };\n"
            "const win = {};\n"
            "const sb = { window: win, document: doc, console, Math, Number, String, Boolean, Array, Object, Set };\n"
            "vm.runInNewContext(qCode, sb);\n"
            "const selected = [];\n"
            "win.TagTrackQueue.init([{ id: 1, bbox: [10, 10, 20, 20] }, { id: 2, bbox: [50, 50, 20, 20] }], { onSelect: (t, ctx) => selected.push({ id: t.id, ctx }) });\n"
            "win.TagTrackQueue.updateActiveItem({ frozenCropBase64: 'data:image/jpeg;base64,FROZEN1', cachedCandidates: [{ entity_id: 7, name: 'Bob' }, { entity_id: 8, name: 'Alice' }] });\n"
            "win.TagTrackQueue.recordSuppressedEntity(7);\n"
            "win.TagTrackQueue.select(1);\n"
            "els['tag-crop-base64'].value = ''; els['tag-notes-input'].value = '';\n"
            "win.TagTrackQueue.select(0);\n"
            "const back = selected[selected.length - 1];\n"
            "process.stdout.write(JSON.stringify({ crop: back.ctx.cropBase64, suppressed: back.ctx.queueItemState.suppressedEntityIds, notes: back.ctx.queueItemState.notes, candIds: back.ctx.queueItemState.cachedCandidates.map((c) => c.entity_id) }));\n"
        )
        out = _run_node(script)
        self.assertEqual(out["crop"], "data:image/jpeg;base64,FROZEN1")
        self.assertEqual(out["suppressed"], ["7"])
        self.assertEqual(out["notes"], "keep note")
        self.assertEqual(out["candIds"], [8])


if __name__ == "__main__":
    unittest.main()
