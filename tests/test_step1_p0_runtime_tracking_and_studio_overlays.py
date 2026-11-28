"""Step 1 P0 tests: runtime crashes, tracking stability, Re-ID uniqueness, studio overlays, timeline reset."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import cv2
import numpy as np

from dashboard.services.stream_telemetry import _extract_track_telemetry
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.matching.gallery import GalleryMatcher
from intelligent_tracker.pipeline.post_detection_governance import handle_zone_exits
from intelligent_tracker.reid.gallery_reembed import reembed_mismatched_signatures
from intelligent_tracker.reid.profile import CANONICAL_REID_DIM, resolve_canonical_reid_dim, resolve_reid_profile
from intelligent_tracker.repositories.sightings_query_helpers import build_sightings_where_clause
from intelligent_tracker.tracker.sort import SortTracker
from intelligent_tracker.tracker.track import Track
from intelligent_tracker.world.graph import WorldGraph
from intelligent_tracker.world.handoff import MultiCameraHandoffCoordinator

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = REPO_ROOT / "dashboard" / "static"


class _StubHomography:
    def track_to_ground(self, bbox):
        return (float(bbox[0]), float(bbox[1]))


class _StubExtractor:
    def __init__(self, dim: int = 2560, vecs: dict[int, np.ndarray] | None = None):
        self.embedding_dim = dim
        self._vecs = vecs or {}

    def extract(self, frame, bbox=None):
        if bbox is not None and int(bbox[0]) in self._vecs:
            return self._vecs[int(bbox[0])]
        v = np.zeros(self.embedding_dim, dtype=np.float32)
        v[0] = 1.0
        return v

    def extract_crop(self, crop):
        return self.extract(crop)


def _run_node(script: str) -> dict:
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False, timeout=20)
    if proc.returncode != 0:
        raise AssertionError(f"Node script failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout.strip())


class TestStep1P0Backend(unittest.TestCase):
    """Backend tests for handoff, 2560D Re-ID, 8 FPS tracking, 1-to-1 uniqueness, and float-epoch SQL."""

    def test_handoff_record_zone_exit_accepts_track_id_without_typeerror(self):
        class _FakeTopo:
            def __init__(self):
                self.calls = []

            def record_zone_exit(self, camera_id, zone_name, **kwargs):
                self.calls.append((camera_id, zone_name, kwargs))
                return ["prior_1"]

        class _Bundle:
            analytics = type("A", (), {"camera_id": "cam_01"})()
            config = None
            gallery_matcher = None

        topo = _FakeTopo()
        coord = MultiCameraHandoffCoordinator(WorldGraph(), topology=topo)
        bridge = type("B", (), {"handoff_coordinator": coord})()
        trk = Track(track_id=42, bbox=(10, 10, 40, 80), label="person", entity_id=7)
        handle_zone_exits(
            _Bundle(),
            {"new_events": [{"action": "exit", "track_id": 42, "zone_id": "entry"}]},
            {42: trk},
            1700000000.0,
            topology=topo,
            world_bridge=bridge,
        )
        self.assertEqual(len(topo.calls), 2)
        self.assertEqual(topo.calls[1][2]["metadata"].get("track_id"), 42)

    def test_canonical_reid_dim_2560_and_reembed_passes_cleanly(self):
        self.assertEqual(CANONICAL_REID_DIM, 2560)
        self.assertEqual(resolve_reid_profile().expected_dim, 2560)
        self.assertEqual(resolve_canonical_reid_dim(_StubExtractor(dim=2560)), 2560)
        with tempfile.TemporaryDirectory() as tmpdir:
            db = TrackerDB(str(Path(tmpdir) / "t.db"))
            try:
                eid = db.add_entity("Samir", "person")
                crop = Path(tmpdir) / "crop.jpg"
                cv2.imwrite(str(crop), np.full((64, 64, 3), 120, dtype=np.uint8))
                vec = np.zeros(2560, dtype=np.float32)
                vec[0] = 1.0
                db.add_signature(eid, vec, crop_path=str(crop))
                res = reembed_mismatched_signatures(db, extractor=_StubExtractor(dim=2560))
                self.assertEqual(res["mismatched"], 0)
                self.assertEqual(res["failed"], 0)
                self.assertEqual(res["expected_dim"], 2560)
            finally:
                db.close()

    def test_sort_centroid_fallback_at_8fps_and_telemetry_ghost_filter(self):
        tracker = SortTracker(min_hits=1, iou_threshold=0.3, coast_frames=3, coast_seconds=0.5)
        t0 = 1000.0
        tids = []
        for idx in range(5):
            # Move 70px per 0.125s step (0 IoU on 50x90 box, within bounded centroid fallback)
            det = [(100 + idx * 70, 120, 50, 90, 0, 0.9, "person")]
            active = tracker.update(det, timestamp=t0 + idx * 0.125)
            tids.append(sorted(active.keys()))
        self.assertEqual(len(set(tids[0])), 1)
        for frame_tids in tids[1:]:
            self.assertEqual(frame_tids, tids[0])

        confirmed = Track(track_id=1, bbox=(100, 100, 50, 90), label="person")
        confirmed.state, confirmed.hits, confirmed.missed_frames = "confirmed", 4, 0
        ghost = Track(track_id=2, bbox=(40, 100, 50, 90), label="person")
        ghost.state, ghost.hits, ghost.missed_frames = "coasting", 3, 2
        tentative = Track(track_id=3, bbox=(200, 100, 50, 90), label="person")
        tentative.state, tentative.hits, tentative.missed_frames = "tentative", 1, 0
        emitted = _extract_track_telemetry({1: confirmed, 2: ghost, 3: tentative}, _StubHomography())
        self.assertEqual([item["id"] for item in emitted], [1])

    def test_gallery_matcher_enforces_1_to_1_entity_uniqueness(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = TrackerDB(str(Path(tmpdir) / "u.db"))
            try:
                eid = db.add_entity("Samir", "person")
                base = np.zeros(16, dtype=np.float32)
                base[0] = 1.0
                db.add_signature(eid, base)
                strong = base.copy()
                weaker = np.zeros(16, dtype=np.float32)
                weaker[0], weaker[1] = 0.85, 0.52
                weaker /= np.linalg.norm(weaker)
                ext = _StubExtractor(dim=16, vecs={10: strong, 200: weaker})
                matcher = GalleryMatcher(db=db, extractor=ext, reid_threshold=0.65, min_track_hits=1, hysteresis_k=1)
                t1 = Track(track_id=1, bbox=(10, 10, 40, 80), label="person")
                t2 = Track(track_id=2, bbox=(200, 10, 40, 80), label="person")
                t1.state = t2.state = "confirmed"
                frame = np.zeros((160, 320, 3), dtype=np.uint8)
                events = matcher.match_tracks({1: t1, 2: t2}, frame, source="cam_01", timestamp=100.0)
                bound = [tid for tid, trk in ((1, t1), (2, t2)) if getattr(trk, "entity_id", None) == eid]
                self.assertEqual(bound, [1])
                self.assertIsNone(getattr(t2, "entity_id", None))
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0].track_id, 1)
            finally:
                db.close()

    def test_sightings_where_clause_normalizes_float_unix_epoch_bounds(self):
        where_sql, params = build_sightings_where_clause(start_time="1735689600.25", end_time=1735693200.0)
        self.assertIn("s.timestamp >= ?", where_sql)
        self.assertIn("s.timestamp <= ?", where_sql)
        self.assertEqual(params, ["2025-01-01 00:00:00", "2025-01-01 01:00:00"])


@unittest.skipUnless(shutil.which("node"), "Node.js required for frontend VM checks")
class TestStep1P0Frontend(unittest.TestCase):
    """Node VM tests for CameraAIConfig chips, Studio ?annotated=false, ScrubberOverlay, and Timeline Reset."""

    def test_camera_ai_config_excludes_category_and_gallery_chips(self):
        js_path = STATIC_DIR / "js" / "camera_ai_config.js"
        script = (
            f"const fs=require('fs'), vm=require('vm'); const code=fs.readFileSync({json.dumps(str(js_path))},'utf8');\n"
            "const mkCls=()=>{const s=new Set(); return {add:c=>s.add(c),remove:c=>s.delete(c),toggle:(c,v)=>v?s.add(c):s.delete(c),has:c=>s.has(c)};};\n"
            "const mkBtn=(cls,dc='')=>({classList:mkCls(),_cls:cls,getAttribute:k=>k==='data-classes'?dc:null,addEventListener:()=>{}});\n"
            "const allBtn=mkBtn('btn-tag-preset',''), catChip=mkBtn('btn-tag-preset btn-cat-chip',''), galChip=mkBtn('btn-tag-preset btn-gallery-ent-chip','');\n"
            "const buttons=[allBtn,catChip,galChip];\n"
            "const matchSel=(sel)=>buttons.filter(b=>{\n"
            "  if(sel.includes(':not(.btn-cat-chip)') && b._cls.includes('btn-cat-chip')) return false;\n"
            "  if(sel.includes(':not(.btn-gallery-ent-chip)') && b._cls.includes('btn-gallery-ent-chip')) return false;\n"
            "  return true;\n"
            "});\n"
            "const els={'modal-camera-manager':{},'cam-classes-input':{value:'',addEventListener:()=>{}},'cam-conf-input':{value:'0.40',addEventListener:()=>{}}};\n"
            "const doc={readyState:'complete',getElementById:id=>els[id]||null,querySelectorAll:sel=>matchSel(sel),addEventListener:()=>{}};\n"
            "const win={addEventListener:()=>{}}; const sb={window:win,document:doc,fetch:async()=>({ok:false}),console,Math,Number,String,Boolean,Array,Object,JSON};\n"
            "vm.runInNewContext(code,sb); win.CameraAIConfig.setValues({detector:'yolov8',classes:[]});\n"
            "process.stdout.write(JSON.stringify({all:allBtn.classList.has('active'),cat:catChip.classList.has('active'),gal:galChip.classList.has('active')}));\n"
        )
        res = _run_node(script)
        self.assertTrue(res["all"])
        self.assertFalse(res["cat"])
        self.assertFalse(res["gal"])

    def test_studio_media_annotated_false_telemetry_redraw_and_scrubber_get_current_tracks(self):
        sm_path = STATIC_DIR / "js" / "studio_media.js"
        asc_path = STATIC_DIR / "js" / "active_source_context.js"
        scr_path = STATIC_DIR / "js" / "scrubber_overlay.js"
        script = (
            f"const fs=require('fs'), vm=require('vm');\n"
            f"const sm=fs.readFileSync({json.dumps(str(sm_path))},'utf8');\n"
            f"const asc=fs.readFileSync({json.dumps(str(asc_path))},'utf8');\n"
            f"const scr=fs.readFileSync({json.dumps(str(scr_path))},'utf8');\n"
            "const listeners={}; let draws=0;\n"
            "const img={id:'studio-live-img',src:'',style:{},dataset:{},removeAttribute:()=>{},addEventListener:()=>{}};\n"
            "const tabStudio={classList:{contains:c=>c==='active'}};\n"
            "const vid={currentTime:1.0,videoWidth:640,videoHeight:360,paused:true,getBoundingClientRect:()=>({width:640,height:360})};\n"
            "const canvas={width:640,height:360,style:{},parentElement:{getBoundingClientRect:()=>({width:640,height:360})},getContext:()=>({save:()=>{},restore:()=>{},clearRect:()=>{},scale:()=>{}})};\n"
            "const els={'studio-live-img':img,'tab-studio':tabStudio,'scrubber-video-player':vid,'scrubber-overlay-canvas':canvas};\n"
            "const doc={readyState:'complete',getElementById:id=>els[id]||null,addEventListener:()=>{}};\n"
            "const win={addEventListener:(e,cb)=>{(listeners[e]||=[]).push(cb);},dispatchEvent:ev=>(listeners[ev.type]||[]).forEach(f=>f(ev)),Studio:{drawOverlay:()=>{draws++;}},ScrubberOverlayRenderer:{findClosestDetections:(fd)=>fd[0],computeVideoRenderBox:()=>({offsetX:0,offsetY:0,renderW:640,renderH:360}),resolveScaleFactors:()=>({scaleX:1,scaleY:1}),renderLayerRecord:()=>{}}};\n"
            "const sb={window:win,document:doc,console,Date,Math,Number,String,Boolean,Array,Object,JSON,Map,Set,encodeURIComponent};\n"
            "vm.runInNewContext(asc,sb); vm.runInNewContext(sm,sb); vm.runInNewContext(scr,sb);\n"
            "win.StudioMedia.attachStudioMedia('cam_01', false, true);\n"
            "const src1=img.src;\n"
            "win.dispatchEvent({type:'telemetry-updated'});\n"
            "const ctrl=win.ActiveSourceContext.bindFreezeToggle({img, getCameraId:()=>'cam_01'}); ctrl.resume();\n"
            "const src2=img.src;\n"
            "win.ScrubberOverlay.setDetections([{time:1.0,tracks:[{id:9,bbox:[1,2,3,4]}]}],[640,360]);\n"
            "const trks=win.ScrubberOverlay.getCurrentTracks();\n"
            "process.stdout.write(JSON.stringify({src1,src2,draws,trksLen:trks.length,tid:trks[0]?.id}));\n"
        )
        res = _run_node(script)
        self.assertIn("annotated=false", res["src1"])
        self.assertIn("annotated=false", res["src2"])
        self.assertGreaterEqual(res["draws"], 1)
        self.assertEqual(res["trksLen"], 1)
        self.assertEqual(res["tid"], 9)

    def test_timeline_reset_clears_window_chip_filters_and_hash(self):
        tf_path = STATIC_DIR / "js" / "timeline_filter_helpers.js"
        gt_path = STATIC_DIR / "js" / "gallery_timeline.js"
        script = (
            f"const fs=require('fs'), vm=require('vm');\n"
            f"const tf=fs.readFileSync({json.dumps(str(tf_path))},'utf8');\n"
            f"const gt=fs.readFileSync({json.dumps(str(gt_path))},'utf8');\n"
            "const fetched=[]; let replacedUrl='';\n"
            "const mkEl=(val='')=>({value:val,textContent:'',innerHTML:'',style:{display:'none'},disabled:false,listeners:{},addEventListener(e,cb){(this.listeners[e]||=[]).push(cb);}});\n"
            "const els={'timeline-entity-select':mkEl('5'),'timeline-zone-select':mkEl('z1'),'timeline-source-select':mkEl('cam_1'),'timeline-limit-select':mkEl('25'),'sightings-timeline-list':mkEl(),'timeline-active-window-chip':mkEl(),'btn-reset-timeline-filters':mkEl(),'btn-filter-sightings':mkEl()};\n"
            "const doc={readyState:'complete',getElementById:id=>els[id]||null,querySelectorAll:()=>[]};\n"
            "const win={location:{pathname:'/',search:'',hash:'#tab-timeline?from=1735689600&to=1735693200'},history:{replaceState:(_s,_t,u)=>{replacedUrl=u;}}};\n"
            "const fakeFetch=async(u)=>{fetched.push(u); return {ok:true,json:async()=>({items:[],total:0,has_more:false})};};\n"
            "const sb={window:win,document:doc,fetch:fakeFetch,console,Date,Math,Number,String,Boolean,Array,Object,JSON,encodeURIComponent};\n"
            "vm.runInNewContext(tf,sb); vm.runInNewContext(gt,sb); win.GalleryTimeline.bindTimelineEvents();\n"
            "(async()=>{\n"
            "  await win.TimelineView.applyFilter({entityId:'5',startTime:'1735689600',endTime:'1735693200',videoFilename:'clip.mp4'});\n"
            "  const chipBefore=els['timeline-active-window-chip'].textContent;\n"
            "  await els['btn-reset-timeline-filters'].listeners.click[0]();\n"
            "  process.stdout.write(JSON.stringify({chipBefore,chipAfter:els['timeline-active-window-chip'].textContent,chipDisp:els['timeline-active-window-chip'].style.display,replacedUrl,lastUrl:fetched[fetched.length-1]}));\n"
            "})();\n"
        )
        res = _run_node(script)
        self.assertIn("2025-01-01", res["chipBefore"])
        self.assertEqual(res["chipAfter"], "")
        self.assertEqual(res["chipDisp"], "none")
        self.assertEqual(res["replacedUrl"], "/#tab-timeline")
        self.assertNotIn("start_time=", res["lastUrl"])
        self.assertNotIn("end_time=", res["lastUrl"])
        self.assertNotIn("video_filename=", res["lastUrl"])


if __name__ == "__main__":
    unittest.main()
