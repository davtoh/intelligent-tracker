"""Node VM frontend tests for Step 3 Milestone 2: #alerts Clip @ MM:SS deep-links & H.264 pairing."""

import json
from pathlib import Path
import subprocess
import unittest

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
        raise AssertionError(f"Node script failed ({proc.returncode}): {proc.stderr}")
    return json.loads(proc.stdout.strip())


class TestStep3AlertsClipDeepLinksFrontend(unittest.TestCase):
    """Node VM tests verifying Clip @ MM:SS rendering and _h264.mp4 pair resolution."""

    def test_clip_button_renders_mmss_and_resolves_paired_h264(self) -> None:
        """buildSeekInStudioButtonHtml renders '▶ Clip @ MM:SS' and resolves paired H.264 clips."""
        script = r"""
const fs = require('fs');
const vm = require('vm');
let switched = null;
let dispatched = null;
const pairs = { 'live_clip.mp4': { convertedFilename: 'live_clip_h264.mp4' } };
const sandbox = {
  window: {
    switchTab: (t) => { switched = t; },
    dispatchEvent: (ev) => { dispatched = ev; },
    VideoLibrary: { getPairedH264: (fn) => pairs[fn] || null },
  },
  CustomEvent: class { constructor(t, i) { this.type = t; this.detail = i?.detail; } },
  document: { getElementById: () => null },
};
vm.runInNewContext(fs.readFileSync('dashboard/static/js/video_timeline_links.js', 'utf8'), sandbox);
const html = sandbox.window.VideoTimelineLinks.buildSeekInStudioButtonHtml('live_clip.mp4', 75.4);
const ok = sandbox.window.VideoTimelineLinks.seekToVideoTimestamp('live_clip.mp4', 75.4);
const plainHtml = sandbox.window.VideoTimelineLinks.buildSeekInStudioButtonHtml('native.mp4', 5);
process.stdout.write(JSON.stringify({ html, plainHtml, ok, switched, detail: dispatched?.detail }));
"""
        res = _run_node(script)
        self.assertTrue(res["ok"])
        self.assertIn("▶ Clip @ 01:15", res["html"])
        self.assertIn('class="btn btn-xs btn-outline btn-seek-studio"', res["html"])
        self.assertIn('data-video-filename="live_clip_h264.mp4"', res["html"])
        self.assertIn('data-offset-sec="75.40"', res["html"])
        self.assertIn("▶ Clip @ 00:05", res["plainHtml"])
        self.assertEqual(res["switched"], "tab-videos")
        self.assertEqual(res["detail"], {"filename": "live_clip_h264.mp4", "offsetSec": 75.4})

    def test_alerts_view_renders_clip_jump_for_recorded_live_alert(self) -> None:
        """AlertsView renders '▶ Clip @ MM:SS' with paired H.264 resolution for recorded alerts."""
        script = r"""
const fs = require('fs');
const vm = require('vm');
const tbody = { innerHTML: '' };
const payload = {
  items: [
    { id: 1, timestamp: 1700000100, event_type: 'zone_enter', severity: 'warning', camera_id: 'cam_01',
      zone_id: 'vault', entity_name: 'Alice', message: 'Entered vault',
      video_filename: 'cam01_rec.mp4', media_offset_sec: 12.5, is_read: false, metadata: {} },
    { id: 2, timestamp: 1700000105, event_type: 'zone_exit', severity: 'info', camera_id: 'cam_01',
      zone_id: 'vault', entity_name: 'Bob', message: 'Exited vault', is_read: true, metadata: {} },
  ],
  total: 2, has_more: false, unread_alert_count: 1,
};
const sandbox = {
  window: { VideoLibrary: { getPairedH264: (fn) => (fn === 'cam01_rec.mp4' ? { convertedFilename: 'cam01_rec_h264.mp4' } : null) } },
  document: { getElementById: (id) => (id === 'alerts-table-body' ? tbody : null) },
  fetch: async () => ({ ok: true, json: async () => payload }),
  URLSearchParams, console,
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('dashboard/static/js/video_timeline_links.js', 'utf8'), sandbox);
vm.runInContext(fs.readFileSync('dashboard/static/js/alerts_view.js', 'utf8'), sandbox);
(async () => {
  await vm.runInContext('window.AlertsView.loadAlerts({ filters: {} })', sandbox);
  process.stdout.write(JSON.stringify({ html: tbody.innerHTML }));
})();
"""
        html = _run_node(script)["html"]
        self.assertIn("▶ Clip @ 00:12", html)
        self.assertIn('data-video-filename="cam01_rec_h264.mp4"', html)
        self.assertIn('data-offset-sec="12.50"', html)
        self.assertEqual(html.count("btn-seek-studio"), 1)


if __name__ == "__main__":
    unittest.main()
