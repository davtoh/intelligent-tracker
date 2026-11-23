"""Unit & JS VM tests for view-aware focus_only hibernation and 2x2/3x3 CameraGrid streaming."""

import json
import pathlib
import shutil
import subprocess
import unittest

from dashboard.services.processing_mode_service import ProcessingModeService

CAMERA_GRID_JS = pathlib.Path("dashboard/static/js/camera_grid.js")


def _run_node(script: str) -> dict:
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(proc.stdout.strip())


class TestViewAwareFocusOnlyPolicy(unittest.TestCase):
    """Verify view-aware focus_only keeps subscribed grid cameras awake in capture-only mode."""

    def test_default_focused_camera_id_is_none(self) -> None:
        svc = ProcessingModeService()
        self.assertIsNone(svc.focused_camera_id)
        self.assertFalse(svc.should_hibernate_camera("vid_01", subscriber_count=0))
        self.assertTrue(svc.should_run_vision_step("vid_01"))

    def test_focus_only_keeps_subscribed_unfocused_cameras_awake_without_vision(self) -> None:
        svc = ProcessingModeService(mode="focus_only", focused_camera_id="cam_01", active_tab="live")
        self.assertFalse(svc.should_hibernate_camera("cam_02", subscriber_count=1))
        self.assertFalse(svc.should_run_vision_step("cam_02"))
        self.assertFalse(svc.should_hibernate_camera("cam_01", subscriber_count=0))
        self.assertTrue(svc.should_run_vision_step("cam_01"))

    def test_focus_only_hibernates_unsubscribed_unfocused_and_background_tabs(self) -> None:
        svc = ProcessingModeService(mode="focus_only", focused_camera_id="cam_01", active_tab="live")
        self.assertTrue(svc.should_hibernate_camera("cam_02", subscriber_count=0))
        self.assertFalse(svc.should_hibernate_camera("cam_02", subscriber_count=0, is_recording=True))

        svc.update(active_tab="studio")
        self.assertTrue(svc.should_hibernate_camera("cam_01", subscriber_count=0))
        self.assertFalse(svc.should_hibernate_camera("cam_01", subscriber_count=1))


class TestCameraGridMultiStreamLifecycle(unittest.TestCase):
    """Verify CameraGrid detaches 1x1 on 2x2/3x3, preserves active tiles, and re-attaches on 1x1."""

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_grid_switch_detaches_1x1_and_reattaches_on_return(self) -> None:
        script = (
            "const fs = require('fs'), vm = require('vm');\n"
            f"const code = fs.readFileSync({json.dumps(str(CAMERA_GRID_JS))}, 'utf8');\n"
            "const liveImg = { src: '/stream/cam_01?annotated=false' };\n"
            "const multiGrid = { style: {}, innerHTML: '', className: '', querySelectorAll: () => [] };\n"
            "const singleWrap = { style: {} };\n"
            "const elems = { 'live-stream-img': liveImg, 'multi-grid-container': multiGrid, 'video-wrapper': singleWrap };\n"
            "const doc = { getElementById: (id) => elems[id] || null, querySelectorAll: () => [] };\n"
            "const events = [];\n"
            "const win = { dispatchEvent: () => {}, LivePlayer: { detachLiveStream: () => events.push('detach'), attachLiveStream: (_el, id) => events.push('attach:' + id) } };\n"
            "const sb = { window: win, document: doc, Event: function(t){ this.type = t; }, encodeURIComponent, String, Array, console };\n"
            "vm.runInNewContext(code, sb);\n"
            "const cams = [{ id: 'cam_01', name: 'Gate', status: 'online', fps: 30 }, { id: 'cam_02', name: 'Dock', status: 'online', fps: 25 }];\n"
            "win.CameraGrid.setGridMode('2x2', cams, 'cam_01', () => {});\n"
            "const hasLazy = multiGrid.innerHTML.includes('loading=\"lazy\"');\n"
            "win.CameraGrid.setGridMode('1x1', cams, 'cam_01', () => {});\n"
            "process.stdout.write(JSON.stringify({ events, hasLazy }));\n"
        )
        out = _run_node(script)
        self.assertFalse(out["hasLazy"])
        self.assertEqual(out["events"], ["detach", "attach:cam_01"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
    def test_grid_refresh_updates_existing_tiles_without_rebuilding_streams(self) -> None:
        script = (
            "const fs = require('fs'), vm = require('vm');\n"
            f"const code = fs.readFileSync({json.dumps(str(CAMERA_GRID_JS))}, 'utf8');\n"
            "const fpsEl = { textContent: '0 FPS' };\n"
            "const tile = { getAttribute: () => 'cam_01', classList: { toggle: () => {} }, querySelector: (s) => (s === '.tile-fps' ? fpsEl : null) };\n"
            "const multiGrid = { style: {}, innerHTML: 'EXISTING', className: '', querySelectorAll: (s) => (s === '.camera-grid-tile' ? [tile] : []) };\n"
            "const elems = { 'multi-grid-container': multiGrid, 'video-wrapper': { style: {} } };\n"
            "const doc = { getElementById: (id) => elems[id] || null, querySelectorAll: () => [] };\n"
            "const win = { dispatchEvent: () => {} };\n"
            "const sb = { window: win, document: doc, Event: function(t){ this.type = t; }, encodeURIComponent, String, Array, console };\n"
            "vm.runInNewContext(code, sb);\n"
            "win.CameraGrid.setGridMode('3x3', [{ id: 'cam_01', name: 'Gate', status: 'online', fps: 60 }], 'cam_01', () => {});\n"
            "process.stdout.write(JSON.stringify({ html: multiGrid.innerHTML, fps: fpsEl.textContent }));\n"
        )
        out = _run_node(script)
        self.assertEqual(out["html"], "EXISTING")
        self.assertEqual(out["fps"], "60 FPS")


class TestColdBootCoordinatorSSOT(unittest.TestCase):
    """Verify StreamPoolCoordinator seeds cold-boot focus and resolves get_stream(None) via SSOT."""

    def test_start_all_seeds_focused_camera_from_first_enabled_camera(self) -> None:
        from unittest.mock import MagicMock, patch
        from dashboard.services.stream_pool_coordinator import StreamPoolCoordinator

        pms = ProcessingModeService(mode="focus_only", focused_camera_id=None, active_tab="live")
        coord = StreamPoolCoordinator("data/test.db", "configs/alert_demo.yaml", MagicMock(), processing_mode_service=pms)
        coord.streams["vid_02"] = MagicMock(is_running=True)
        coord.streams["vid_03"] = MagicMock(is_running=True)
        configs = {
            "vid_01": {"enabled": False, "name": "Disabled", "source": "synthetic"},
            "vid_02": {"enabled": True, "name": "Front", "source": "synthetic"},
            "vid_03": {"enabled": True, "name": "Back", "source": "synthetic"},
        }
        with patch("dashboard.services.stream_pool_coordinator._start_stream_if_ready"):
            coord.start_all(configs)
        self.assertEqual(pms.focused_camera_id, "vid_02")
        self.assertFalse(pms.should_hibernate_camera("vid_02", subscriber_count=0))
        self.assertTrue(pms.should_hibernate_camera("vid_03", subscriber_count=0))
        self.assertFalse(pms.should_run_vision_step("vid_03"))

    def test_get_stream_fallback_prioritizes_focused_camera_over_cam_01(self) -> None:
        from unittest.mock import MagicMock
        from dashboard.services.stream_pool_coordinator import StreamPoolCoordinator

        pms = ProcessingModeService(mode="focus_only", focused_camera_id="vid_02", active_tab="live")
        coord = StreamPoolCoordinator("data/test.db", "configs/alert_demo.yaml", MagicMock(), processing_mode_service=pms)
        cam_01 = MagicMock(is_running=True)
        vid_02 = MagicMock(is_running=True)
        coord.streams = {"cam_01": cam_01, "vid_02": vid_02}
        self.assertIs(coord.get_stream(None), vid_02)
        self.assertIs(coord.get_stream("default"), vid_02)
