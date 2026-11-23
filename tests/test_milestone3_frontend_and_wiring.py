#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Regression tests for Milestone 3 frontend contracts, armed propagation, and boot gating."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np

from dashboard.services.async_inference_worker import AsyncInferenceWorker
from dashboard.stream_manager import StreamManager
from intelligent_tracker.video.writers import PipelineVideoWriter

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_node(script: str) -> dict:
    proc = subprocess.run(
        ["node", "-e", script],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    if proc.returncode != 0:
        raise AssertionError(f"Node VM failed ({proc.returncode}): {proc.stderr}\n{proc.stdout}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


@unittest.skipUnless(shutil.which("node"), "Node.js required for JS VM tests")
class TestMilestone3FrontendContracts(unittest.TestCase):
    """Verify Milestone 3 JS contracts, telemetry wiring, and boot stream gating."""

    def test_video_timeline_links_extracts_entities_and_alerts(self) -> None:
        script = (
            "const fs = require('fs'), vm = require('vm');\n"
            "const sb = { window: {}, document: { getElementById: () => null } };\n"
            "vm.runInNewContext(fs.readFileSync('dashboard/static/js/video_timeline_links.js', 'utf8'), sb);\n"
            "const evs = sb.window.VideoTimelineLinks.extractEventsFromReport({\n"
            "  entities: [{ entity: { id: 1, name: 'Alice' }, timeline: [{ media_offset_sec: 4.5 }] }],\n"
            "  alerts: [{ media_offset_sec: 12.0, event_type: 'zone_dwell' }],\n"
            "});\n"
            "process.stdout.write(JSON.stringify({ evs }));\n"
        )
        out = _run_node(script)
        self.assertEqual(len(out["evs"]), 2)
        self.assertEqual(out["evs"][0], {"offset_sec": 4.5, "kind": "sighting", "label": "Alice"})
        self.assertEqual(out["evs"][1], {"offset_sec": 12.0, "kind": "alert", "label": "zone_dwell"})

    def test_scrubber_bridge_uses_plural_reports_and_videos_route(self) -> None:
        script = (
            "const fs = require('fs'), vm = require('vm');\n"
            "const fetched = [], loaded = [], rendered = [];\n"
            "const sb = {\n"
            "  window: { VideoTimelineLinks: {\n"
            "    extractEventsFromReport: (r) => [{ offset_sec: 3, kind: 'alert', label: r.run_id }],\n"
            "    renderTimelineTicks: (evs, dur) => rendered.push({ evs, dur }),\n"
            "  } },\n"
            "  CSS: { escape: (s) => s }, document: { querySelector: () => null },\n"
            "  encodeURIComponent, console,\n"
            "  fetch: async (u) => { fetched.push(u); return { ok: true, json: async () => ([{ report: { run_id: 'r1' } }]) }; },\n"
            "};\n"
            "vm.runInNewContext(fs.readFileSync('dashboard/static/js/scrubber_library_bridge.js', 'utf8'), sb);\n"
            "(async () => {\n"
            "  await sb.window.ScrubberLibraryBridge.refreshTimelineTicks('clip.mp4', 60);\n"
            "  sb.window.ScrubberLibraryBridge.handleSeekRequest({ detail: { filename: 'clip.mp4', offsetSec: 5 } }, { loadVideoIntoPlayer: (u) => loaded.push(u) });\n"
            "  process.stdout.write(JSON.stringify({ fetched, loaded, rendered }));\n"
            "})();\n"
        )
        out = _run_node(script)
        self.assertEqual(out["fetched"], ["/api/videos/clip.mp4/reports"])
        self.assertEqual(out["loaded"], ["/videos/clip.mp4"])
        self.assertEqual(out["rendered"][0]["evs"][0]["label"], "r1")

    def test_studio_recorded_video_clears_img_and_skips_overlays(self) -> None:
        script = (
            "const fs = require('fs'), vm = require('vm');\n"
            "const overlayCalls = []; const listeners = {};\n"
            "const img = { id: 'studio-live-img', src: '/stream/cam_01', dataset: { activeStreamSrc: '/stream/cam_01' }, removeAttribute: (k) => { if (k === 'src') img.src = ''; } };\n"
            "const sel = { id: 'studio-camera-select', value: 'demo.mp4', options: [], innerHTML: '', selectedOptions: [{ parentElement: { label: 'Recorded Videos' } }], addEventListener: (e, fn) => { listeners[e] = fn; } };\n"
            "const els = { 'studio-live-img': img, 'studio-camera-select': sel, 'tab-studio': { classList: { contains: () => true } } };\n"
            "const sb = { window: null, document: { getElementById: (id) => els[id] || null, querySelectorAll: () => [], addEventListener: () => {} },\n"
            "  StudioOverlays: { init: () => {}, bindOverlayToolbar: () => {}, loadCameraOverlays: (id) => overlayCalls.push(id) },\n"
            "  JourneySearch: { bind: () => {} }, ScenarioModals: { init: () => {} }, BEVMinimap: { render: () => {} },\n"
            "  fetch: async () => ({ ok: false, json: async () => ({}) }), setInterval: () => 1, clearInterval: () => {}, encodeURIComponent, Date, Math, console };\n"
            "sb.window = sb; sb.addEventListener = () => {};\n"
            "vm.runInNewContext(fs.readFileSync('dashboard/static/studio.js', 'utf8'), sb);\n"
            "sb.window.Studio.init();\n"
            "listeners.change({ target: sel });\n"
            "process.stdout.write(JSON.stringify({ src: img.src, activeSrc: img.dataset.activeStreamSrc || null, overlayCalls }));\n"
        )
        out = _run_node(script)
        self.assertEqual(out["src"], "")
        self.assertIsNone(out["activeSrc"])
        self.assertEqual(out["overlayCalls"], [])

    def test_bev_minimap_renders_latest_telemetry_tracks_without_cam01(self) -> None:
        script = (
            "const fs = require('fs'), vm = require('vm');\n"
            "const texts = [];\n"
            "const ctx = { clearRect: () => {}, fillRect: () => {}, strokeRect: () => {}, beginPath: () => {}, moveTo: () => {}, lineTo: () => {}, closePath: () => {}, stroke: () => {}, fill: () => {}, arc: () => {}, fillText: (t) => texts.push(t) };\n"
            "const canvas = { width: 300, height: 300, getContext: () => ctx };\n"
            "const sb = { window: { latestTelemetry: { active_tracks: [{ id: 7, bbox: [10, 20, 30, 40], entity_name: 'Bob' }] } }, Math };\n"
            "vm.runInNewContext(fs.readFileSync('dashboard/static/js/bev_minimap.js', 'utf8'), sb);\n"
            "sb.window.BEVMinimap.render(canvas, null, [], null);\n"
            "process.stdout.write(JSON.stringify({ texts }));\n"
        )
        out = _run_node(script)
        self.assertIn("Bob", out["texts"])
        self.assertTrue(any("BEV: N/A" in t for t in out["texts"]))
        self.assertFalse(any("cam_01" in t for t in out["texts"]))

    def test_boot_attach_live_stream_gated_when_tab_live_inactive(self) -> None:
        script = (
            "const fs = require('fs'), vm = require('vm');\n"
            "const img = { src: '', dataset: {} };\n"
            "const els = { 'live-stream-img': img, 'tab-live': { classList: { contains: () => false } } };\n"
            "const doc = { getElementById: (id) => els[id] || null, querySelectorAll: () => [], addEventListener: () => {} };\n"
            "const win = { localStorage: { getItem: () => null }, App: { getActiveCameraId: () => null, switchCamera: () => {} } };\n"
            "const sb = { window: win, document: doc, fetch: async () => ({ ok: false }), encodeURIComponent, Date, Math, Array, String, setTimeout, clearTimeout, console };\n"
            "vm.runInNewContext(fs.readFileSync('dashboard/static/js/live_player.js', 'utf8'), sb);\n"
            "vm.runInNewContext(fs.readFileSync('dashboard/static/js/camera_ai_config.js', 'utf8'), sb);\n"
            "win.CameraAIConfig.resolveInitialCameraId([{ id: 'cam_09', name: 'Nine', enabled: true }], null);\n"
            "const srcWhenHidden = img.src; const cachedSrc = img.dataset.activeStreamSrc;\n"
            "els['tab-live'].classList.contains = () => true;\n"
            "win.LivePlayer.attachLiveStream(img, 'cam_09', false);\n"
            "process.stdout.write(JSON.stringify({ srcWhenHidden, cachedSrc, srcWhenActive: img.src }));\n"
        )
        out = _run_node(script)
        self.assertEqual(out["srcWhenHidden"], "")
        self.assertEqual(out["cachedSrc"], "/stream/cam_09")
        self.assertTrue(out["srcWhenActive"].startswith("/stream/cam_09?annotated=false"))

    def test_camera_ai_config_armed_checkbox_roundtrip(self) -> None:
        script = (
            "const fs = require('fs'), vm = require('vm');\n"
            "const cb = { checked: false };\n"
            "const doc = { getElementById: (id) => (id === 'cam-armed-checkbox' ? cb : null), querySelectorAll: () => [], addEventListener: () => {} };\n"
            "const sb = { window: {}, document: doc, fetch: async () => ({ ok: false }), parseFloat, isNaN, Math, Array, String, console };\n"
            "vm.runInNewContext(fs.readFileSync('dashboard/static/js/camera_ai_config.js', 'utf8'), sb);\n"
            "sb.window.CameraAIConfig.setValues({ armed: true, confidence: 0.5 });\n"
            "const afterSet = sb.window.CameraAIConfig.getValues().armed;\n"
            "sb.window.CameraAIConfig.resetValues();\n"
            "const afterReset = sb.window.CameraAIConfig.getValues().armed;\n"
            "process.stdout.write(JSON.stringify({ afterSet, afterReset }));\n"
        )
        out = _run_node(script)
        self.assertTrue(out["afterSet"])
        self.assertFalse(out["afterReset"])


class TestMilestone3BackendWiring(unittest.TestCase):
    """Verify dynamic armed propagation and PipelineVideoWriter clock hygiene."""

    def test_async_inference_worker_and_stream_manager_propagate_armed(self) -> None:
        proc = MagicMock()
        proc.step.return_value = SimpleNamespace(tracks={1: object()}, analytics={})
        scheduler = MagicMock()
        mgr = SimpleNamespace(camera_id="cam_arm", is_armed=False)
        worker = AsyncInferenceWorker(
            proc,
            scheduler=scheduler,
            camera_id="cam_arm",
            is_armed=False,
            is_armed_getter=lambda: bool(getattr(mgr, "is_armed", False)),
        )
        self.assertFalse(worker.is_armed)
        mgr.is_armed = True
        self.assertTrue(worker.is_armed)

        dummy = StreamManager.__new__(StreamManager)
        dummy.is_armed = False
        dummy._worker = SimpleNamespace(_async_worker=worker)
        dummy.set_armed(True)
        self.assertTrue(dummy.is_armed)
        dummy.set_armed(False)
        self.assertFalse(worker._is_armed)

    def test_pipeline_video_writer_preserves_wall_and_elapsed_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "out.mp4")
            writer = PipelineVideoWriter(out_path, fps=10.0, resolution=(64, 64))
            self.addCleanup(writer.release)
            writer.write(np.zeros((64, 64, 3), dtype=np.uint8))
            writer.release()
            snap = writer.snapshot()
            self.assertIsInstance(writer.started_at, float)
            self.assertIsInstance(writer.stopped_at, float)
            self.assertEqual(snap["frames_written"], 1)
            self.assertGreaterEqual(snap["elapsed_s"], 0.0)


if __name__ == "__main__":
    unittest.main()
