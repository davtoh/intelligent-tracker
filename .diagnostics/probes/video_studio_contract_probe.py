#!/usr/bin/env python3
"""Diagnostic Probe: video_studio_contract_probe.

Verifies VideoIndexer -> TrackerDB (wall-clock, media_offset_sec, WorldQueryEngine
citations, per-video report isolation), RoiRecognitionService (locked anchor &
ConfidenceEngine wiring), and backend-to-JS JSON payload key parity.
"""

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _write_clip(path: Path, frames: int = 8) -> None:
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")  # type: ignore[attr-defined]
    writer = cv2.VideoWriter(str(path), fourcc, 10.0, (320, 240))
    try:
        for i in range(frames):
            img = np.zeros((240, 320, 3), dtype=np.uint8)
            cv2.rectangle(img, (40 + i * 5, 40), (120 + i * 5, 160), (200, 180, 50), -1)
            writer.write(img)
    finally:
        writer.release()


def _check_indexer_and_citations(tmp: Path, failures: list[str], checks: dict[str, Any]) -> None:
    """Verify VideoIndexer hooks, timeline media offsets, and WorldQueryEngine citations (P0-1, P1-11)."""
    from intelligent_tracker.batch import VideoIndexer
    from intelligent_tracker.database import TrackerDB
    from intelligent_tracker.memory.query_engine import WorldQueryEngine

    db = TrackerDB(str(tmp / "studio.db"))
    try:
        indexer = VideoIndexer(db=db, detector_name="mock", reid_name="color", sample_rate=4, video_filename="clip.mp4")
        proc = indexer._build_frame_processor("clip.mp4", video_filename="clip.mp4")
        has_wg = getattr(proc.bundle, "world_graph", None) is not None
        has_ce = getattr(proc.bundle, "confidence_engine", None) is not None
        checks.update(indexer_has_world_graph=has_wg, indexer_has_confidence_engine=has_ce)
        if not has_wg or not has_ce:
            failures.append(f"VideoIndexer missing hooks (world_graph={has_wg}, confidence_engine={has_ce})")
        db.index_timeline_event(
            summary="Studio dwell event", event_type="zone_dwell", camera_id="clip.mp4",
            metadata={"video_filename": "clip.mp4", "media_offset_sec": 3.5},
        )
        rows = db._conn.execute("SELECT video_filename, media_offset_sec FROM world_timeline_events LIMIT 5").fetchall()
        has_offset = bool(rows and rows[0][0] == "clip.mp4" and rows[0][1] == 3.5)
        checks["timeline_persists_video_offset"] = has_offset
        if not has_offset:
            failures.append("world_timeline_events dropped video_filename or media_offset_sec")
        cites = WorldQueryEngine(db).ask("Studio dwell", limit=5).citations
        cite_has_media = bool(cites and "video_filename" in cites[0] and "media_offset_sec" in cites[0])
        checks["wqe_citation_has_video_offset"] = cite_has_media
        if not cite_has_media:
            failures.append("P1-11: WorldQueryEngine._format_citation() dropped video_filename/media_offset_sec")
    finally:
        db.close()


def _check_report_isolation(tmp: Path, failures: list[str], checks: dict[str, Any]) -> None:
    """Verify per-video video_runs and occurrence report isolation in TrackerDB (P1-11)."""
    from intelligent_tracker.batch import VideoIndexer
    from intelligent_tracker.database import TrackerDB

    db = TrackerDB(str(tmp / "iso.db"))
    try:
        db.save_video_run(video_filename="clip_a.mp4", report={"entities": [{"id": 1}], "alerts": []}, frame_detections=[], source_fps=10.0)
        db.save_video_run(video_filename="clip_b.mp4", report={"entities": [{"id": 2}], "alerts": []}, frame_detections=[], source_fps=10.0)
        runs_a = db.list_video_runs("clip_a.mp4")
        eid_a, eid_b = db.add_entity("PersonA", "person"), db.add_entity("PersonB", "person")
        db.add_sighting(entity_id=eid_a, track_id=1, source="clip_a.mp4", video_filename="clip_a.mp4", media_offset_sec=1.0)
        db.add_sighting(entity_id=eid_b, track_id=2, source="clip_b.mp4", video_filename="clip_b.mp4", media_offset_sec=2.0)
        with VideoIndexer(db=db, detector_name="mock", video_filename="clip_a.mp4") as idx:
            rep_a = idx.generate_occurrence_report()
        rep_ok = rep_a.get("total_sightings") == 1 and len(rep_a.get("entities", [])) == 1 and rep_a["entities"][0]["entity"]["id"] == eid_a
        isolated = len(runs_a) == 1 and runs_a[0].get("filename") == "clip_a.mp4" and rep_ok
        checks["per_video_report_isolated"] = isolated
        if not isolated:
            failures.append(f"P1-11: per-video isolation failed (runs={len(runs_a)}, rep_ok={rep_ok})")
    finally:
        db.close()


def _check_roi_and_confidence(tmp: Path, vid: Path, failures: list[str], checks: dict[str, Any]) -> None:
    """Verify ROI tagging media_offset_sec, locked anchor, descriptor version, FTS, and seek error (P1-12)."""
    from dashboard.services.roi_recognition_service import RoiRecognitionService, RoiUnavailableError
    from intelligent_tracker.database import TrackerDB
    from intelligent_tracker.memory.fts_index import EventFTSIndex

    db = TrackerDB(str(tmp / "roi.db"))
    fts = EventFTSIndex(db=db, auto_attach=False)
    try:
        svc = RoiRecognitionService(db=db, videos_dir=str(tmp), crops_dir=str(tmp / "crops"), fts_index=fts)
        res = svc.commit_roi_tag(entity_name="StudioTag", category="person", video_filename=vid.name, timestamp_sec=0.4, bbox=[40, 40, 120, 160])
        sightings = db.get_sightings(entity_id=res["entity_id"], limit=5)
        sig = db._conn.execute("SELECT is_anchor, locked FROM entity_signatures WHERE entity_id = ? LIMIT 1", (res["entity_id"],)).fetchone()
        vers = db.get_descriptor_versions(res["entity_id"])
        fts_hits = db.search_timeline_events("StudioTag", limit=5)
        seek_err = False
        try:
            svc._read_video_frame(vid.name, 999.0)
        except RoiUnavailableError:
            seek_err = True
        checks.update(
            roi_tag_persists_media_offset=bool(sightings and sightings[0].get("media_offset_sec") == 0.4),
            roi_locked_anchor=bool(sig and sig[0] == 1 and sig[1] == 1),
            roi_has_confidence_engine=getattr(svc, "confidence_engine", None) is not None,
            roi_descriptor_version=bool(vers and vers[0].get("is_anchor") == 1),
            roi_fts_indexed=bool(fts_hits),
            roi_seek_error=seek_err,
        )
        for key in ("roi_tag_persists_media_offset", "roi_locked_anchor", "roi_has_confidence_engine", "roi_descriptor_version", "roi_fts_indexed", "roi_seek_error"):
            if not checks[key]:
                failures.append(f"P1-12 check '{key}' failed")
    finally:
        fts.stop()
        db.close()


def _check_entity_tagger_sync(tmp: Path, failures: list[str], checks: dict[str, Any]) -> None:
    """Verify EntityTaggerService locked anchor, Track identity fields, and WorldEntityBridge sync (P1-12)."""
    from unittest.mock import MagicMock
    from dashboard.services.entity_tagger import EntityTaggerService
    from intelligent_tracker.database import TrackerDB
    from intelligent_tracker.tracker.track import Track

    db = TrackerDB(str(tmp / "tagger.db"))
    try:
        frame = np.full((240, 320, 3), 120, dtype=np.uint8)
        trk = Track(track_id=7, bbox=(20, 20, 80, 120), class_id=0, label="person", confidence=0.9)
        tracker = MagicMock(tracks={7: trk})
        matcher = MagicMock(_identified_tracks={})
        bridge = MagicMock()
        res = EntityTaggerService.tag_entity(
            raw_frame=frame, db=db, entity_name="AliceSync", category="staff",
            track_id=7, bbox=[20, 20, 80, 120], camera_id="cam_01",
            tracker=tracker, gallery_matcher=matcher, world_bridge=bridge,
        )
        ok = (
            getattr(trk, "entity_id", None) == res["entity_id"]
            and getattr(trk, "identity_label", None) == "AliceSync"
            and 7 in matcher._identified_tracks
            and bridge.reassign_track.called
        )
        checks["entity_tagger_live_sync"] = ok
        if not ok:
            failures.append("P1-12: EntityTaggerService live track / WorldEntityBridge sync failed")
    finally:
        db.close()


def _check_js_payload_parity(failures: list[str], checks: dict[str, Any]) -> None:
    """Verify frontend JS payload keys match backend contracts (review_queue, events, detections)."""
    bridge_js = (REPO_ROOT / "dashboard/static/js/scrubber_library_bridge.js").read_text(encoding="utf-8")
    links_js = (REPO_ROOT / "dashboard/static/js/video_timeline_links.js").read_text(encoding="utf-8")
    rsac_js = (REPO_ROOT / "dashboard/static/review_and_rsac.js").read_text(encoding="utf-8")
    analytics_js = (REPO_ROOT / "dashboard/static/js/analytics_view.js").read_text(encoding="utf-8")
    scrubber_js = (REPO_ROOT / "dashboard/static/js/scrubber_overlay.js").read_text(encoding="utf-8")

    checks["bridge_uses_singular_report_404"] = "/report`" in bridge_js or "/report'" in bridge_js
    checks["links_reads_occurrences"] = ".occurrences" in links_js
    if checks["bridge_uses_singular_report_404"]:
        failures.append("scrubber_library_bridge.js fetches singular /api/videos/{fn}/report (404)")
    if checks["links_reads_occurrences"]:
        failures.append("video_timeline_links.js reads non-existent report.occurrences")

    missing_rq = [k for k in ("similarity", "suggested_name", "timestamp") if f"item.{k}" not in rsac_js]
    checks["review_queue_js_key_mismatches"] = missing_rq
    if missing_rq:
        failures.append(
            f"review_and_rsac.js missing canonical review_queue keys {missing_rq}"
        )

    events_ok = all(
        k in analytics_js for k in ("event_type", "timestamp", "video_filename", "media_offset_sec")
    )
    det_ok = all(k in scrubber_js for k in ("frame_detections", "source_resolution", "next_index"))
    checks.update(events_js_keys_ok=events_ok, detections_js_keys_ok=det_ok)
    if not events_ok or not det_ok:
        failures.append(f"JS payload key parity failed (events={events_ok}, detections={det_ok})")


def run_probe() -> dict[str, Any]:
    """Execute Video Studio contract assertions."""
    checks: dict[str, Any] = {}
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        vid = tmp / "clip.mp4"
        _write_clip(vid)
        _check_indexer_and_citations(tmp, failures, checks)
        _check_report_isolation(tmp, failures, checks)
        _check_roi_and_confidence(tmp, vid, failures, checks)
        _check_entity_tagger_sync(tmp, failures, checks)
        _check_js_payload_parity(failures, checks)

    status = "error" if failures else "ok"
    summary = (
        f"Video Studio contract probe: {len(failures)} failure(s)"
        if failures
        else "Video Studio contract probe passed."
    )
    return {"status": status, "summary": summary, "details": {"checks": checks, "failures": failures}}


if __name__ == "__main__":
    res = run_probe()
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["status"] == "ok" else 1)
