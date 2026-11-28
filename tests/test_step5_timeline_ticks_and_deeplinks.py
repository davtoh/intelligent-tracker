import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from intelligent_tracker.database import TrackerDB
from intelligent_tracker.journey import TrajectoryJourneySearcher

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_node(script: str) -> dict:
    proc = subprocess.run(
        ["node", "-e", script],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0:
        raise AssertionError(f"Node script failed ({proc.returncode}): {proc.stderr}")
    return json.loads(proc.stdout.strip())


class TestStep5TimelineTicksAndDeeplinks(unittest.TestCase):
    def test_journey_hop_preserves_video_filename_and_offset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = TrackerDB(db_path=os.path.join(tmpdir, "tracker.db"))
            try:
                eid = db.add_entity(name="Alice", category="person")
                db.add_sighting(
                    entity_id=eid,
                    track_id=7,
                    source="cam_vid",
                    timestamp=1700000010.0,
                    zone_id="entry",
                    bbox=[10, 20, 50, 80],
                    confidence=0.91,
                    video_filename="mall_entry.mp4",
                    media_offset_sec=14.5,
                )
                journey = TrajectoryJourneySearcher(db).search_journey(entity_id=eid)
                self.assertEqual(len(journey.hops), 1)
                self.assertEqual(journey.hops[0].video_filename, "mall_entry.mp4")
                self.assertAlmostEqual(journey.hops[0].media_offset_sec, 14.5)
                serialized = journey.to_dict()
                self.assertEqual(serialized["hops"][0]["video_filename"], "mall_entry.mp4")
                self.assertAlmostEqual(serialized["hops"][0]["media_offset_sec"], 14.5)
            finally:
                db.close()

    def test_timeline_ticks_render_and_click_to_seek(self) -> None:
        script = r"""
const fs = require('fs');
const vm = require('vm');
const ticks = [];
const player = { currentTime: 0, duration: 100 };
const container = {
  innerHTML: '',
  querySelectorAll: () => ticks,
};
const sandbox = {
  window: { dispatchEvent: () => {}, VideoScrubber: { renderOverlay: () => {} } },
  CustomEvent: class { constructor(t, i) { this.type = t; this.detail = i?.detail; } },
  document: { getElementById: (id) => (id === 'scrubber-timeline-ticks' ? container : player) },
};
vm.runInNewContext(fs.readFileSync('dashboard/static/js/video_timeline_links.js', 'utf8'), sandbox);
const out = sandbox.window.VideoTimelineLinks.renderTimelineTicks([
  { offset_sec: 10, kind: 'sighting', label: 'Alice' },
  { offset_sec: 30, kind: 'alert', label: 'RSAC Intrusion' },
], 100, container);
let clickFn = null;
ticks.push({ getAttribute: () => '30', addEventListener: (_, fn) => { clickFn = fn; } });
sandbox.window.VideoTimelineLinks.renderTimelineTicks([{ offset_sec: 30, kind: 'alert' }], 100, container);
clickFn({ stopPropagation: () => {} });
process.stdout.write(JSON.stringify({ count: out.length, pct0: out[0].pct, kind1: out[1].kind, seeked: player.currentTime, html: container.innerHTML }));
"""
        res = _run_node(script)
        self.assertEqual(res["count"], 2)
        self.assertAlmostEqual(res["pct0"], 10.0)
        self.assertEqual(res["kind1"], "alert")
        self.assertEqual(res["seeked"], 30)
        self.assertIn("scrubber-tick-alert", res["html"])

    def test_seek_in_studio_button_and_tab_dispatch(self) -> None:
        script = r"""
const fs = require('fs');
const vm = require('vm');
let switched = null;
let dispatched = null;
const sandbox = {
  window: {
    switchTab: (t) => { switched = t; },
    dispatchEvent: (ev) => { dispatched = ev; },
  },
  CustomEvent: class { constructor(t, i) { this.type = t; this.detail = i?.detail; } },
  document: { getElementById: () => null },
};
vm.runInNewContext(fs.readFileSync('dashboard/static/js/video_timeline_links.js', 'utf8'), sandbox);
const emptyBtn = sandbox.window.VideoTimelineLinks.buildSeekInStudioButtonHtml('', 5);
const btnHtml = sandbox.window.VideoTimelineLinks.buildSeekInStudioButtonHtml('clip.mp4', 12.5);
sandbox.window.VideoTimelineLinks.seekToVideoTimestamp('clip.mp4', 12.5);
process.stdout.write(JSON.stringify({ emptyBtn, btnHtml, switched, type: dispatched?.type, detail: dispatched?.detail }));
"""
        res = _run_node(script)
        self.assertEqual(res["emptyBtn"], "")
        self.assertIn("▶ Clip @ 00:12", res["btnHtml"])
        self.assertIn("btn-seek-studio", res["btnHtml"])
        self.assertEqual(res["switched"], "tab-videos")
        self.assertEqual(res["type"], "video-seek-request")
        self.assertEqual(res["detail"], {"filename": "clip.mp4", "offsetSec": 12.5})

    def test_scrubber_library_bridge_handles_immediate_and_pending_seek(self) -> None:
        script = r"""
const fs = require('fs');
const vm = require('vm');
let metaCb = null;
let currentFile = 'a.mp4';
const player = { currentTime: 0, duration: 120, addEventListener: (ev, cb) => { if (ev === 'loadedmetadata') metaCb = cb; } };
const sandbox = {
  window: { ScrubberOverlay: { render: () => {} } },
  CSS: { escape: (s) => s },
  document: { querySelector: () => null },
  fetch: async () => ({ ok: false }),
};
vm.runInNewContext(fs.readFileSync('dashboard/static/js/scrubber_library_bridge.js', 'utf8'), sandbox);
const ctx = { getCurrentFilename: () => currentFile, videoPlayer: player, loadVideoIntoPlayer: () => { currentFile = 'b.mp4'; }, updateTimeline: () => {} };
sandbox.window.ScrubberLibraryBridge.handleSeekRequest({ detail: { filename: 'a.mp4', offsetSec: 22 } }, ctx);
const immediate = player.currentTime;
sandbox.window.ScrubberLibraryBridge.handleSeekRequest({ detail: { filename: 'b.mp4', offsetSec: 45 } }, ctx);
metaCb();
process.stdout.write(JSON.stringify({ immediate, pendingApplied: player.currentTime }));
"""
        res = _run_node(script)
        self.assertEqual(res["immediate"], 22)
        self.assertEqual(res["pendingApplied"], 45)

    def test_deeplink_wiring_present_across_tab_modules_and_html(self) -> None:
        for rel in [
            "dashboard/static/js/gallery_timeline.js",
            "dashboard/static/js/analytics_view.js",
            "dashboard/static/js/journey_search.js",
            "dashboard/static/review_and_rsac.js",
        ]:
            content = (REPO_ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("buildSeekInStudioButtonHtml", content, f"Missing deep-link hook in {rel}")
        videos_html = (REPO_ROOT / "dashboard/static/partials/tabs/videos.html").read_text(encoding="utf-8")
        index_html = (REPO_ROOT / "dashboard/static/index.html").read_text(encoding="utf-8")
        self.assertIn('id="scrubber-timeline-ticks"', videos_html)
        self.assertIn("/static/js/video_timeline_links.js", index_html)
