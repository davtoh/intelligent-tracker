"""Unit tests for Step 3 Milestone 3: Video Studio, ROI Anchors, Backup & Persistence."""

import os
import stat
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from dashboard.services.entity_tagger import EntityTaggerService
from dashboard.services.roi_recognition_service import RoiRecognitionService, RoiUnavailableError
from intelligent_tracker.backup import BackupManager
from intelligent_tracker.batch import VideoIndexer
from intelligent_tracker.database import TrackerDB
from intelligent_tracker.events.types import EntityIdentifiedEvent, RestrictedEntityAlert
from intelligent_tracker.memory.fts_index import EventFTSIndex
from intelligent_tracker.memory.query_engine import WorldQueryEngine
from intelligent_tracker.pipeline.post_detection_governance import publish_id_events
from intelligent_tracker.scenarios import ScenarioManager
from intelligent_tracker.tracker.sort import SortTracker
from intelligent_tracker.tracker.track import Track
from intelligent_tracker.video.capture_guard import CaptureReadGuard
from intelligent_tracker.video.lifecycle import CaptureLifecycleMixin
from intelligent_tracker.world.graph import WorldGraph
from intelligent_tracker.world.minimap import WorldTacticalMinimap
from intelligent_tracker.world.nodes import CameraNode, ZoneNode


def _make_test_mp4(path: Path, frames: int = 6) -> None:
    """Create a tiny synthetic MP4 fixture for seek/decode tests."""
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (160, 120))
    try:
        for i in range(frames):
            img = np.full((120, 160, 3), 40 + i * 20, dtype=np.uint8)
            writer.write(img)
    finally:
        writer.release()


class TestStep3VideoStudioRoiAndPersistence(unittest.TestCase):
    """Verify P1-11, P1-12, P1-13, and TRC-018 contracts."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_video_indexer_fts_wiring_and_report_isolation(self) -> None:
        """VideoIndexer wires fts_index and isolates occurrence reports by video_filename."""
        db = TrackerDB(str(self.root / "studio.db"))
        self.addCleanup(db.close)
        fts = EventFTSIndex(db=db, auto_attach=False)
        self.addCleanup(fts.stop)

        with VideoIndexer(db=db, detector_name="mock", video_filename="a.mp4", fts_index=fts) as idx:
            self.assertIs(idx.matcher.fts_index, fts)
            proc = idx._build_frame_processor("a.mp4", "a.mp4")
            self.assertIs(proc.bundle.event_fts_index, fts)

        e1 = db.add_entity("Alice", "person")
        e2 = db.add_entity("Bob", "person")
        db.add_sighting(entity_id=e1, track_id=1, source="a.mp4", video_filename="a.mp4", media_offset_sec=1.5)
        db.add_sighting(entity_id=e2, track_id=2, source="b.mp4", video_filename="b.mp4", media_offset_sec=2.5)

        rep_a = VideoIndexer(db=db, detector_name="mock", video_filename="a.mp4").generate_occurrence_report()
        self.assertEqual(rep_a["total_sightings"], 1)
        self.assertEqual([e["entity"]["id"] for e in rep_a["entities"]], [e1])

    def test_wqe_citation_and_governance_zone_id(self) -> None:
        """WorldQueryEngine citations include media fields and governance forwards zone_id."""
        db = TrackerDB(str(self.root / "wqe.db"))
        self.addCleanup(db.close)
        db.index_timeline_event(
            summary="Gate entry", event_type="sighting", camera_id="cam_1", zone_id="lobby",
            metadata={"video_filename": "gate.mp4", "media_offset_sec": 4.2},
        )
        cites = WorldQueryEngine(db).ask("Gate entry", limit=5).citations
        self.assertEqual(cites[0]["video_filename"], "gate.mp4")
        self.assertEqual(cites[0]["media_offset_sec"], 4.2)

        published = []
        bundle = MagicMock()
        bundle.config.camera_id = "cam_1"
        bundle.event_bus.publish.side_effect = published.append
        trk = Track(track_id=3, bbox=(10, 10, 40, 80), class_id=0, label="person", confidence=0.9)
        ev = MagicMock(track_id=3, entity_id=9, name="Intruder", category="restricted", similarity=0.95, zone_id="vault", snapshot_base64="abc")
        publish_id_events(bundle, np.zeros((100, 100, 3), dtype=np.uint8), {3: trk}, [ev], 1000.0)
        self.assertTrue(any(isinstance(e, EntityIdentifiedEvent) and e.zone_id == "vault" for e in published))
        self.assertTrue(any(isinstance(e, RestrictedEntityAlert) and e.zone_id == "vault" for e in published))

    def test_roi_seek_error_and_locked_anchor_commit(self) -> None:
        """RoiRecognitionService raises RoiUnavailableError on bad seek and commits locked anchor."""
        db = TrackerDB(str(self.root / "roi.db"))
        self.addCleanup(db.close)
        fts = EventFTSIndex(db=db, auto_attach=False)
        self.addCleanup(fts.stop)
        vid = self.root / "clip.mp4"
        _make_test_mp4(vid, frames=5)

        svc = RoiRecognitionService(db=db, videos_dir=str(self.root), crops_dir=str(self.root / "crops"), fts_index=fts)
        with self.assertRaises(RoiUnavailableError):
            svc._read_video_frame("clip.mp4", 999.0)

        res = svc.commit_roi_tag(entity_name="AnchorOne", category="staff", video_filename="clip.mp4", timestamp_sec=0.2, bbox=[10, 10, 40, 60])
        row = db._conn.execute("SELECT is_anchor, locked FROM entity_signatures WHERE entity_id = ?", (res["entity_id"],)).fetchone()
        self.assertEqual((row[0], row[1]), (1, 1))
        self.assertEqual(db.get_descriptor_versions(res["entity_id"])[0]["is_anchor"], 1)
        self.assertTrue(db.search_timeline_events("AnchorOne", limit=5))

    def test_entity_tagger_syncs_track_matcher_and_bridge(self) -> None:
        """EntityTaggerService sets locked anchor and updates Track, GalleryMatcher, and WorldEntityBridge."""
        db = TrackerDB(str(self.root / "tagger.db"))
        self.addCleanup(db.close)
        frame = np.full((120, 160, 3), 100, dtype=np.uint8)
        trk = Track(track_id=5, bbox=(10, 10, 50, 80), class_id=0, label="person", confidence=0.88)
        tracker = MagicMock(tracks={5: trk})
        matcher = MagicMock(_identified_tracks={})
        bridge = MagicMock()

        with patch("dashboard.services.entity_tagger.CROPS_DIR", str(self.root / "crops")):
            res = EntityTaggerService.tag_entity(
                raw_frame=frame, db=db, entity_name="BobTag", category="vip",
                track_id=5, bbox=[10, 10, 50, 80], camera_id="cam_2",
                tracker=tracker, gallery_matcher=matcher, world_bridge=bridge,
            )
        self.assertEqual(trk.entity_id, res["entity_id"])
        self.assertEqual(trk.identity_label, "BobTag")
        self.assertEqual(trk.reid_score, 1.0)
        self.assertIn(5, matcher._identified_tracks)
        bridge.reassign_track.assert_called_once()

    def test_backup_rejects_symlinks_cleans_wal_and_hot_reloads(self) -> None:
        """BackupManager rejects symlink entries, removes WAL/SHM sidecars, and invokes hot_reload."""
        db_path = str(self.root / "tracker.db")
        crops_dir, cfg_dir = str(self.root / "crops"), str(self.root / "configs")
        db = TrackerDB(db_path)
        db.add_entity("Persisted", "person")
        db.close()

        reloaded = []
        mgr = BackupManager(db_path=db_path, crops_dir=crops_dir, configs_dir=cfg_dir, hot_reload_callbacks=[lambda: reloaded.append(True)])
        zip_path = mgr.create_backup(output_path=str(self.root / "snap.zip"), include_crops=False)

        with zipfile.ZipFile(zip_path, "a") as zf:
            zi = zipfile.ZipInfo("configs/evil_link")
            zi.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(zi, "/etc/passwd")
            zf.writestr("../escape.txt", "bad")

        for suffix in ("-wal", "-shm"):
            Path(f"{db_path}{suffix}").write_text("stale", encoding="utf-8")

        res = mgr.restore_backup(zip_path, hot_reload=True)
        self.assertEqual(res["hot_reloaded"], 1)
        self.assertTrue(reloaded)
        self.assertFalse(os.path.exists(f"{db_path}-wal"))
        self.assertFalse(os.path.exists(f"{db_path}-shm"))
        self.assertFalse((self.root / "configs" / "evil_link").exists())

    def test_scenario_manager_and_repo_guards(self) -> None:
        """ScenarioManager closes owned DB on exit/init-failure and repos guard closed _conn."""
        db_path = str(self.root / "scen.db")
        with ScenarioManager(config_path=str(self.root / "scen.yaml"), db_path=db_path) as sm:
            self.assertTrue(sm._owns_db)
            self.assertIsNotNone(sm.db._conn)
        self.assertIsNone(sm.db)

        db = TrackerDB(str(self.root / "closed.db"))
        db.close()
        self.assertEqual(db.list_entities(), [])
        with self.assertRaises(RuntimeError):
            db.add_entity("FailAfterClose")

    def test_capture_guard_lifecycle_sort_and_minimap(self) -> None:
        """CaptureReadGuard, CaptureLifecycleMixin, SortTracker.tracks, and Minimap calibration gate."""
        guard = CaptureReadGuard(timeout=0.5)
        self.addCleanup(guard.stop)
        self.assertTrue(guard.is_healthy)

        class _DummyCap(CaptureLifecycleMixin):
            def __init__(self) -> None:
                self.source = "dummy"
                self.auto_reconnect = True
                self._cap = None
                self._thread = None
                self._running = False
                self._is_paused = False
                self._stop_event = threading.Event()
                self._pause_event = threading.Event()
                self._ready_event = threading.Event()
                self._first_frame_read = False
                self._lock = threading.Lock()
                self._queue = __import__("queue").Queue()
                self._is_connected = False
                self._start_time = None
                self.lock_held_in_open = False

            def _open_capture(self) -> bool:
                self.lock_held_in_open = self._lock.locked()
                return True

            def _capture_worker(self) -> None:
                self._ready_event.set()
                self._stop_event.wait(0.2)

        dc = _DummyCap()
        self.addCleanup(dc.stop)
        dc.start(wait_for_ready=False)
        self.assertFalse(dc.lock_held_in_open)

        tracker = SortTracker(min_hits=1)
        tracker.update([(10, 10, 40, 80)], timestamp=time.time())
        self.assertEqual(len(tracker.tracks), 1)

        wg = WorldGraph()
        wg.register_camera(CameraNode(camera_id="cam_uncal", name="Uncal"))
        wg.register_zone(ZoneNode(camera_id="cam_uncal", zone_id="z1", name="z1", points=[(100.0, 100.0), (200.0, 100.0), (200.0, 200.0)]))
        mm = WorldTacticalMinimap(wg)
        telem = mm.build_world_minimap_telemetry()
        self.assertEqual(telem["zones"][0]["global_polygon"], [])
