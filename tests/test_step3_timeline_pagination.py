#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tests for Step 3 Milestone 1: #timeline pagination, source filtering & Live/Studio links."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.dependencies import bind_app_state, clear_app_state, set_shutting_down
from intelligent_tracker.database import TrackerDB

REPO_ROOT = Path(__file__).resolve().parent.parent

_VM_PRELUDE = r"""
const fs = require('fs'), vm = require('vm');
function makeEl(id = '', initialValue = '') {
  const listeners = {};
  return {
    id, value: initialValue, textContent: '', innerHTML: '', disabled: false, style: {},
    addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
    click() { (listeners.click || []).forEach((f) => f()); },
    dispatch(ev) { (listeners[ev] || []).forEach((f) => f()); },
  };
}
function runTimelineVm(els, fetchImpl) {
  const switchedTabs = [], switchedCameras = [], events = [];
  const doc = {
    getElementById: (id) => els[id] || null,
    querySelector: () => null,
    querySelectorAll: () => [],
  };
  const win = {
    Date, Math, Number, String, Array, Object, JSON, encodeURIComponent,
    CustomEvent: function (name, init) { this.type = name; this.detail = init?.detail || {}; },
    dispatchEvent: (ev) => { events.push({ type: ev.type, detail: ev.detail }); },
    switchTab: (tabId) => { switchedTabs.push(tabId); },
    App: { switchCamera: (camId) => { switchedCameras.push(camId); } },
  };
  win.window = win;
  const ctx = vm.createContext({ window: win, document: doc, fetch: fetchImpl, console, ...win });
  vm.runInContext(fs.readFileSync('dashboard/static/js/video_timeline_links.js', 'utf8'), ctx);
  vm.runInContext(fs.readFileSync('dashboard/static/js/gallery_timeline.js', 'utf8'), ctx);
  return { win, els, switchedTabs, switchedCameras, events };
}
"""


def _run_node(js_body: str) -> dict:
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node runtime not found")
    proc = subprocess.run(
        [node, "-e", _VM_PRELUDE + "\n(async () => {\n" + js_body + "\n})();"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"Node VM failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


class TestTimelinePaginationRepoAndApi(unittest.TestCase):
    """Isolated TrackerDB and FastAPI TestClient checks for /sightings pagination & sources."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="step3_m1_")
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, "tracker.db")
        self.db = TrackerDB(db_path=self.db_path)
        self.addCleanup(self.db.close)
        set_shutting_down(False)
        clear_app_state(app)
        bind_app_state(app, db=self.db)
        self.addCleanup(lambda: clear_app_state(app))
        from unittest.mock import patch
        p_vid = patch("dashboard.dependencies.VIDEOS_DIR", self._tmp.name)
        p_vid.start()
        self.addCleanup(p_vid.stop)
        self.client = TestClient(app)

    def _seed_sightings(self) -> int:
        eid = self.db.add_entity("Alice", "person")
        for idx in range(5):
            self.db.add_sighting(
                entity_id=eid,
                track_id=10 + idx,
                source="cam_front" if idx < 3 else "cam_yard",
                timestamp=f"2026-11-23 10:00:0{idx}",
                zone_id="entry" if idx % 2 == 0 else "yard",
                confidence=0.9,
                video_filename="clip_yard.mp4" if idx >= 3 else "",
                media_offset_sec=float(idx * 4.5) if idx >= 3 else 0.0,
            )
        return eid

    def test_repo_offset_count_and_sources(self):
        eid = self._seed_sightings()
        page1 = self.db.get_sightings(entity_id=eid, limit=2, offset=0)
        page2 = self.db.get_sightings(entity_id=eid, limit=2, offset=2)
        self.assertEqual(len(page1), 2)
        self.assertEqual(len(page2), 2)
        self.assertNotEqual(page1[0]["id"], page2[0]["id"])
        self.assertEqual(self.db.count_sightings(source="cam_front"), 3)
        self.assertEqual(self.db.count_sightings(video_filename="clip_yard.mp4"), 2)
        sources = self.db.list_sighting_sources()
        self.assertEqual([s["source"] for s in sources], ["cam_front", "cam_yard"])
        self.assertFalse(sources[0]["has_video"])
        self.assertTrue(sources[1]["has_video"])

    def test_api_legacy_flat_list_and_paginated_envelope(self):
        self._seed_sightings()
        flat_resp = self.client.get("/sightings?limit=2")
        self.assertEqual(flat_resp.status_code, 200)
        self.assertIsInstance(flat_resp.json(), list)
        self.assertEqual(len(flat_resp.json()), 2)

        page_resp = self.client.get("/sightings?paginated=true&limit=2&offset=2")
        self.assertEqual(page_resp.status_code, 200)
        body = page_resp.json()
        self.assertEqual(body["total"], 5)
        self.assertEqual(body["offset"], 2)
        self.assertEqual(body["limit"], 2)
        self.assertTrue(body["has_more"])
        self.assertEqual(len(body["items"]), 2)

    def test_api_source_video_filter_and_sources_endpoint(self):
        self._seed_sightings()
        filtered = self.client.get("/sightings?paginated=true&source=cam_front").json()
        self.assertEqual(filtered["total"], 3)
        self.assertTrue(all(item["source"] == "cam_front" for item in filtered["items"]))

        vid_filtered = self.client.get("/sightings?paginated=true&video_filename=clip_yard.mp4").json()
        self.assertEqual(vid_filtered["total"], 2)

        sources_resp = self.client.get("/sightings/sources")
        self.assertEqual(sources_resp.status_code, 200)
        self.assertEqual(len(sources_resp.json()), 2)


_TIMELINE_VM_SCRIPT = r"""
const els = {
  'timeline-entity-select': makeEl('timeline-entity-select', ''),
  'timeline-zone-select': makeEl('timeline-zone-select', ''),
  'timeline-source-select': makeEl('timeline-source-select', ''),
  'timeline-limit-select': makeEl('timeline-limit-select', '2'),
  'sightings-timeline-list': makeEl('sightings-timeline-list'),
  'timeline-prev-btn': makeEl('timeline-prev-btn'),
  'timeline-next-btn': makeEl('timeline-next-btn'),
  'timeline-page-info': makeEl('timeline-page-info'),
  'btn-filter-sightings': makeEl('btn-filter-sightings'),
};
const urls = [];
const fetchImpl = async (url) => {
  urls.push(url);
  if (url === '/entities') return { ok: true, json: async () => [{ id: 1, name: 'Alice', category: 'person' }] };
  if (url === '/zones') return { ok: true, json: async () => [{ name: 'entry' }] };
  if (url === '/sightings/sources') return { ok: true, json: async () => [{ source: 'cam_front', count: 3 }] };
  if (url.includes('offset=2')) {
    return {
      ok: true,
      json: async () => ({
        items: [{ id: 1, entity_name: 'Alice', source: 'cam_yard', video_filename: 'clip.mp4', media_offset_sec: 12.5, track_id: 2, confidence: 0.9 }],
        total: 3, offset: 2, limit: 2, has_more: false,
      }),
    };
  }
  return {
    ok: true,
    json: async () => ({
      items: [{ id: 2, entity_name: 'Alice', source: 'cam_front', video_filename: '', media_offset_sec: 0, track_id: 1, confidence: 0.95 }],
      total: 3, offset: 0, limit: 2, has_more: true,
    }),
  };
};
const { win, switchedTabs, switchedCameras, events } = runTimelineVm(els, fetchImpl);
win.GalleryTimeline.bindTimelineEvents();
await win.GalleryTimeline.loadTimelineFilters();
await win.TimelineView.applyFilter({ source: 'cam_front' });
const page1Info = els['timeline-page-info'].textContent;
const page1PrevDisabled = els['timeline-prev-btn'].disabled;
const page1NextDisabled = els['timeline-next-btn'].disabled;
const page1Html = els['sightings-timeline-list'].innerHTML;
els['timeline-next-btn'].click();
await new Promise((r) => setTimeout(r, 0));
const page2Info = els['timeline-page-info'].textContent;
const page2Html = els['sightings-timeline-list'].innerHTML;
win.TimelineView.jumpToLiveSource('cam_front');
win.VideoTimelineLinks.seekToVideoTimestamp('clip.mp4', 12.5);
console.log(JSON.stringify({
  urls, sourceOptions: els['timeline-source-select'].innerHTML,
  page1Info, page1PrevDisabled, page1NextDisabled, page1Html,
  page2Info, page2Html, switchedTabs, switchedCameras, events,
}));
"""


class TestTimelineFrontendVm(unittest.TestCase):
    """Node VM tests for timeline pagination, source filters, and Live/Studio jumps."""

    def test_filters_pagination_and_jump_actions(self):
        out = _run_node(_TIMELINE_VM_SCRIPT)
        self.assertIn("cam_front (3)", out["sourceOptions"])
        self.assertEqual(out["page1Info"], "Page 1 of 2 (3 total)")
        self.assertTrue(out["page1PrevDisabled"])
        self.assertFalse(out["page1NextDisabled"])
        self.assertIn("btn-jump-live", out["page1Html"])
        self.assertIn("timeline-source-badge", out["page1Html"])
        self.assertEqual(out["page2Info"], "Page 2 of 2 (3 total)")
        self.assertIn("btn-seek-studio", out["page2Html"])
        self.assertEqual(out["switchedTabs"], ["tab-live", "tab-videos"])
        self.assertEqual(out["switchedCameras"], ["cam_front"])
        self.assertEqual(out["events"][0]["type"], "video-seek-request")
        self.assertEqual(out["events"][0]["detail"]["filename"], "clip.mp4")


if __name__ == "__main__":
    unittest.main()
