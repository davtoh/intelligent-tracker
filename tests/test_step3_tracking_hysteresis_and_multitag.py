"""Tests for Step 3 Milestone 2: Identity Hysteresis Lock & Avatar/Name Canvas Rendering."""

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

import cv2
import numpy as np

from dashboard.services.entity_tagger import EntityTaggerService
from dashboard.services.roi_recognition_service import RoiRecognitionService
from dashboard.services.stream_telemetry import _extract_track_telemetry
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.matching import GalleryMatcher
from intelligent_tracker.matching.identity_hysteresis import IdentityHysteresisTracker
from intelligent_tracker.pipeline.bundle import build_reid
from intelligent_tracker.pipeline.config import PipelineConfig
from intelligent_tracker.tracker.track import Track
from intelligent_tracker.world import CameraNode, WorldEntityBridge, WorldGraph

REPO_ROOT = Path(__file__).resolve().parent.parent
AVATAR_CACHE_JS = REPO_ROOT / "dashboard" / "static" / "js" / "overlay_avatar_cache.js"
OVERLAY_JS = REPO_ROOT / "dashboard" / "static" / "js" / "unified_canvas_overlay.js"


class _SwitchableExtractor:
    """Deterministic test extractor returning programmable unit vectors."""

    embedding_dim = 8

    def __init__(self, initial: np.ndarray) -> None:
        self.current = initial.astype(np.float32)

    def extract(self, frame: np.ndarray, bbox: tuple[int, int, int, int]) -> np.ndarray:
        return self.current.copy()

    def extract_crop(self, crop: np.ndarray) -> np.ndarray:
        return self.current.copy()


def _unit_vec(axis: int, dim: int = 8) -> np.ndarray:
    """Create a 1-hot unit vector along ``axis``."""
    vec = np.zeros(dim, dtype=np.float32)
    vec[axis] = 1.0
    return vec


_NODE_AVATAR_PREAMBLE = """
const imageSpecs = {};
class MockImage {
  constructor() { this.complete = false; this.naturalWidth = 0; this.naturalHeight = 0; }
  set src(val) {
    this._src = val;
    const spec = imageSpecs[val] || { ok: true, w: 48, h: 48 };
    if (spec.ok) {
      this.naturalWidth = spec.w; this.naturalHeight = spec.h; this.complete = true;
      if (typeof this.onload === 'function') this.onload();
    } else if (typeof this.onerror === 'function') {
      this.onerror(new Error('load failed'));
    }
  }
}
function makeCtx() {
  const calls = [];
  const rec = (n) => (...a) => calls.push([n, ...a]);
  return {
    calls, canvas: { width: 800, height: 600 },
    save: rec('save'), restore: rec('restore'), clearRect: rec('clearRect'),
    fillRect: rec('fillRect'), strokeRect: rec('strokeRect'), fillText: rec('fillText'),
    beginPath: rec('beginPath'), closePath: rec('closePath'), arc: rec('arc'),
    clip: rec('clip'), drawImage: rec('drawImage'), stroke: rec('stroke'),
    setTransform: rec('setTransform'), setLineDash: rec('setLineDash'),
    measureText: (t) => ({ width: String(t).length * 6 }),
  };
}
"""


def _run_node_avatar_vm(test_body: str) -> dict:
    """Execute ``overlay_avatar_cache.js`` + ``unified_canvas_overlay.js`` in an isolated Node VM."""
    if not shutil.which("node"):
        raise unittest.SkipTest("Node.js required for canvas VM verification")
    wrapped_body = json.dumps(f"(() => {{ {test_body} }})()")
    harness = f"""
const fs = require('fs');
const vm = require('vm');
const ctx = vm.createContext({{ console, JSON, Math, Number, String, Array, Object, Boolean, Map, Error, devicePixelRatio: 1 }});
ctx.window = ctx;
ctx.globalThis = ctx;
vm.runInContext({json.dumps(_NODE_AVATAR_PREAMBLE)}, ctx);
ctx.Image = vm.runInContext('MockImage', ctx);
vm.runInContext(fs.readFileSync({json.dumps(str(AVATAR_CACHE_JS))}, 'utf8'), ctx);
vm.runInContext(fs.readFileSync({json.dumps(str(OVERLAY_JS))}, 'utf8'), ctx);
const res = vm.runInContext({wrapped_body}, ctx);
process.stdout.write(JSON.stringify(res));
"""
    proc = subprocess.run(["node", "-e", harness], capture_output=True, text=True, check=True)
    return json.loads(proc.stdout.strip())


class TestIdentityHysteresisAndCanvasAvatars(unittest.TestCase):
    """Verify K=3 hysteresis lock, M=5 contradiction unbind, force_bind, and canvas avatar badges."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = TrackerDB(os.path.join(self.tmp.name, "test_m2.db"))
        self.addCleanup(self.db.close)

    def test_default_hysteresis_parameters_and_live_bundle_wiring(self) -> None:
        hyst = IdentityHysteresisTracker()
        self.assertEqual((hyst.confirm_k, hyst.confirm_threshold, hyst.contradict_m), (3, 0.65, 5))
        cfg = PipelineConfig.from_dict({"reid": {"model": "color", "threshold": 0.65}})
        _, matcher = build_reid(cfg, self.db)
        self.assertIsNotNone(matcher)
        assert matcher is not None
        self.assertEqual(matcher.hysteresis.confirm_k, 3)
        self.assertEqual(matcher.hysteresis.contradict_m, 5)

    def test_gallery_k3_lock_class_flip_and_single_frame_noise_retention(self) -> None:
        alice_vec, bob_vec = _unit_vec(0), _unit_vec(1)
        alice_id = self.db.add_entity("Alice", category="vip")
        bob_id = self.db.add_entity("Bob", category="visitor")
        self.db.add_signature(alice_id, alice_vec, crop_path="data/crops/alice.jpg", is_anchor=1)
        self.db.add_signature(bob_id, bob_vec, crop_path="data/crops/bob.jpg", is_anchor=1)

        ext = _SwitchableExtractor(alice_vec)
        matcher = GalleryMatcher(
            db=self.db, extractor=ext, reid_threshold=0.65,
            feature_history_len=1, min_track_hits=1, hysteresis_k=3,
        )
        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        trk = Track(track_id=7, bbox=(10, 10, 30, 40), label="person", timestamp=10.0)
        trk.hits = 3

        for ts in (10.0, 10.2):
            evs = matcher.match_tracks({7: trk}, frame, source="cam_01", timestamp=ts)
            self.assertEqual(evs, [])
            self.assertFalse(hasattr(trk, "entity_id"))

        evs_3 = matcher.match_tracks({7: trk}, frame, source="cam_01", timestamp=10.4)
        self.assertEqual(len(evs_3), 1)
        self.assertEqual((trk.entity_id, trk.entity_name, trk.avatar_url), (alice_id, "Alice", "/crops/alice.jpg"))

        trk.label = "chair"
        matcher.match_tracks({7: trk}, frame, source="cam_01", timestamp=10.6)
        self.assertEqual(trk.entity_id, alice_id)

        trk.label = "person"
        ext.current = bob_vec
        evs_noise = matcher.match_tracks({7: trk}, frame, source="cam_01", timestamp=10.8)
        self.assertEqual(evs_noise, [])
        self.assertEqual((trk.entity_id, trk.entity_name), (alice_id, "Alice"))
        self.assertNotEqual(trk.entity_id, bob_id)

    def test_m5_consecutive_contradictions_unbind_and_world_bridge_detach(self) -> None:
        alice_vec, bob_vec = _unit_vec(0), _unit_vec(1)
        alice_id = self.db.add_entity("Alice", category="staff")
        bob_id = self.db.add_entity("Bob", category="visitor")
        self.db.add_signature(alice_id, alice_vec, crop_path="data/crops/alice.jpg", is_anchor=1)
        self.db.add_signature(bob_id, bob_vec, is_anchor=1)

        graph = WorldGraph()
        graph.register_camera(CameraNode(camera_id="cam_01", name="Lobby"))
        bridge = WorldEntityBridge(graph)
        ext = _SwitchableExtractor(alice_vec)
        matcher = GalleryMatcher(
            db=self.db, extractor=ext, reid_threshold=0.65, feature_history_len=1,
            min_track_hits=1, hysteresis_k=3, world_bridge=bridge, camera_id="cam_01",
        )
        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        trk = Track(track_id=9, bbox=(10, 10, 30, 40), label="person", timestamp=1.0)
        trk.hits = 3
        for step in range(3):
            matcher.match_tracks({9: trk}, frame, source="cam_01", timestamp=1.0 + step * 0.1)
        self.assertEqual(trk.entity_id, alice_id)

        ext.current = bob_vec
        for step in range(4):
            matcher.match_tracks({9: trk}, frame, source="cam_01", timestamp=2.0 + step * 0.1)
            self.assertEqual(trk.entity_id, alice_id)

        matcher.match_tracks({9: trk}, frame, source="cam_01", timestamp=2.5)
        self.assertFalse(hasattr(trk, "entity_id"))
        self.assertIsNone(trk.entity_name)
        alice_node = graph.get_node(f"entity:{alice_id}", node_type="entity")
        self.assertNotIn("cam_01", getattr(alice_node, "camera_tracks", {}))
        self.assertNotEqual(getattr(trk, "entity_id", None), bob_id)

        matcher.match_tracks({}, frame, source="cam_01", timestamp=10.0)
        self.assertIsNone(matcher.hysteresis.get_locked(9))

    def test_manual_force_bind_overrides_hysteresis_in_tagger_and_roi_commit(self) -> None:
        alice_vec, charlie_vec = _unit_vec(0), _unit_vec(2)
        alice_id = self.db.add_entity("Alice", category="staff")
        self.db.add_signature(alice_id, alice_vec, is_anchor=1)
        ext = _SwitchableExtractor(alice_vec)
        matcher = GalleryMatcher(
            db=self.db, extractor=ext, reid_threshold=0.65,
            feature_history_len=1, min_track_hits=1, hysteresis_k=3,
        )
        trk = Track(track_id=12, bbox=(5, 5, 30, 30), label="person", timestamp=1.0)
        trk.hits = 3
        matcher.hysteresis.force_bind(12, alice_id, "Alice", "staff", track=trk)

        tracker_stub = SimpleNamespace(tracks={12: trk})
        EntityTaggerService._update_live_track_identity(
            tracker_stub, 12, "ManualVIP", "vip", matcher,
            entity_id=99, camera_id="cam_01", avatar_url="/crops/vip.jpg",
        )
        locked = matcher.hysteresis.get_locked(12)
        self.assertIsNotNone(locked)
        assert locked is not None
        self.assertEqual((locked.entity_id, locked.entity_name, trk.avatar_url), (99, "ManualVIP", "/crops/vip.jpg"))

        crop_img = np.full((24, 24, 3), 180, dtype=np.uint8)
        ok, enc = cv2.imencode(".jpg", crop_img)
        self.assertTrue(ok)
        b64_crop = base64.b64encode(enc.tobytes()).decode("ascii")
        mgr_stub = SimpleNamespace(
            tracker=tracker_stub, gallery_matcher=matcher, reid_extractor=_SwitchableExtractor(charlie_vec),
            world_bridge=None, detector=MagicMock(),
        )
        roi_svc = RoiRecognitionService(
            db=self.db, stream_manager=mgr_stub, crops_dir=os.path.join(self.tmp.name, "crops"),
        )
        committed = roi_svc.commit_roi_tag("Charlie", category="contractor", crop_base64=b64_crop, track_id=12, camera_id="cam_01")
        locked_after = matcher.hysteresis.get_locked(12)
        assert locked_after is not None
        self.assertEqual((locked_after.entity_id, trk.entity_name), (committed["entity_id"], "Charlie"))
        self.assertTrue(str(getattr(trk, "avatar_url", "")).startswith("/crops/"))

    def test_track_to_dict_and_stream_telemetry_avatar_and_category_parity(self) -> None:
        raw_trk = Track(track_id=1, bbox=(10, 20, 30, 40), label="person")
        self.assertFalse(hasattr(raw_trk, "entity_id"))
        self.assertIsNone(raw_trk.to_dict()["avatar_url"])
        self.assertIsNone(raw_trk.to_dict()["learned_class"])

        bound_trk = Track(
            track_id=2, bbox=(10, 20, 30, 40), label="person",
            entity_id=7, entity_category="vip", avatar_url="/crops/alice.jpg", learned_class="badge_holder",
        )
        bound_trk.entity_name = "Alice"
        d = bound_trk.to_dict()
        self.assertEqual((d["entity_id"], d["category"], d["avatar_url"], d["learned_class"]), (7, "vip", "/crops/alice.jpg", "badge_holder"))

        homography = SimpleNamespace(track_to_ground=lambda bbox: (1.5, 2.5))
        telem = _extract_track_telemetry({2: bound_trk}, homography)[0]
        self.assertEqual((telem["entity_id"], telem["entity_category"], telem["category"]), (7, "vip", "vip"))
        self.assertEqual((telem["avatar_url"], telem["learned_class"]), ("/crops/alice.jpg", "badge_holder"))

    def test_node_overlay_avatar_cache_and_canvas_pill_rendering(self) -> None:
        out = _run_node_avatar_vm("""
Object.assign(imageSpecs, {
  '/api/crops/alice.jpg': { ok: true, w: 48, h: 48 },
  '/api/crops/broken.jpg': { ok: false, w: 0, h: 0 },
  '/api/crops/zero.jpg': { ok: true, w: 0, h: 0 },
});
const tf = { offsetX: 0, offsetY: 0, scaleX: 1, scaleY: 1, renderW: 800, renderH: 600 };
const ctxOk = makeCtx();
window.UnifiedCanvasOverlay.renderScene(ctxOk, {
  clearWidth: 800, clearHeight: 600, transform: tf,
  tracks: [{ id: 3, bbox: [40, 50, 50, 90], confidence: 0.94, entity_name: 'Alice', avatar_url: '/api/crops/alice.jpg' }],
});
const ctxErr = makeCtx();
window.UnifiedCanvasOverlay.renderScene(ctxErr, {
  clearWidth: 800, clearHeight: 600, transform: tf,
  tracks: [
    { id: 4, bbox: [100, 60, 40, 80], entity_name: 'Alice', avatar_url: '/api/crops/broken.jpg' },
    { id: 5, bbox: [200, 60, 40, 80], entity_name: 'ZeroImg', avatar_url: '/api/crops/zero.jpg' },
  ],
});
const statuses = [window.OverlayAvatarCache.getStatus('/api/crops/broken.jpg'), window.OverlayAvatarCache.getStatus('/api/crops/zero.jpg')];
window.OverlayAvatarCache.setMaxEntries(4);
for (let i = 0; i < 7; i += 1) window.OverlayAvatarCache.getAvatarImage(`/api/crops/u_${i}.jpg`);
return {
  okOps: ctxOk.calls.map(c => c[0]), okTexts: ctxOk.calls.filter(c => c[0] === 'fillText').map(c => c[1]),
  errOps: ctxErr.calls.map(c => c[0]), errTexts: ctxErr.calls.filter(c => c[0] === 'fillText').map(c => c[1]),
  statuses, lruSize: window.OverlayAvatarCache.size(),
};
""")
        for op in ("arc", "clip", "drawImage"):
            self.assertIn(op, out["okOps"])
        self.assertTrue(any("Alice" in t and "#3" in t for t in out["okTexts"]))
        self.assertNotIn("drawImage", out["errOps"])
        self.assertTrue(any("Alice" in t for t in out["errTexts"]))
        self.assertEqual((tuple(out["statuses"]), out["lruSize"]), (("error", "error"), 4))


if __name__ == "__main__":
    unittest.main()
