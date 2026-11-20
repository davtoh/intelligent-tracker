#!/usr/bin/env python3
"""Diagnostic Probe: video_studio_contract_probe.

Verifies VideoIndexer -> TrackerDB (world_timeline_events video_filename/media_offset_sec),
Video Studio ROI tagging media offsets, and frontend JS contract parity.
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
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (320, 240))
    try:
        for i in range(frames):
            img = np.zeros((240, 320, 3), dtype=np.uint8)
            cv2.rectangle(img, (40 + i * 5, 40), (120 + i * 5, 160), (200, 180, 50), -1)
            writer.write(img)
    finally:
        writer.release()


def _check_indexer_and_timeline(tmp: Path, vid: Path, failures: list[str], checks: dict[str, Any]) -> None:
    """Verify VideoIndexer WorldGraph/ConfidenceEngine wiring and timeline media offsets."""
    from intelligent_tracker.batch import VideoIndexer
    from intelligent_tracker.database import TrackerDB

    db = TrackerDB(str(tmp / "studio.db"))
    try:
        indexer = VideoIndexer(db=db, detector_name="mock", reid_name="color", sample_rate=4, video_filename="clip.mp4")
        proc = indexer._build_frame_processor("clip.mp4", video_filename="clip.mp4")
        has_wg = getattr(proc.bundle, "world_graph", None) is not None
        has_ce = getattr(proc.bundle, "confidence_engine", None) is not None
        checks["indexer_has_world_graph"] = has_wg
        checks["indexer_has_confidence_engine"] = has_ce
        if not has_wg or not has_ce:
            failures.append(f"VideoIndexer missing hooks (world_graph={has_wg}, confidence_engine={has_ce})")

        db.index_timeline_event(
            summary="Test event", event_type="zone_dwell", camera_id="clip.mp4",
            metadata={"video_filename": "clip.mp4", "media_offset_sec": 3.5},
        )
        rows = db._conn.execute("SELECT video_filename, media_offset_sec FROM world_timeline_events LIMIT 5").fetchall()
        has_offset = bool(rows and rows[0][0] == "clip.mp4" and rows[0][1] == 3.5)
        checks["timeline_persists_video_offset"] = has_offset
        if not has_offset:
            failures.append("world_timeline_events dropped video_filename or media_offset_sec")
    finally:
        db.close()


def _check_roi_and_js_contracts(tmp: Path, vid: Path, failures: list[str], checks: dict[str, Any]) -> None:
    """Verify ROI tagging media offset persistence and JS scrubber/studio contracts."""
    from dashboard.services.roi_recognition_service import RoiRecognitionService
    from intelligent_tracker.database import TrackerDB

    db = TrackerDB(str(tmp / "roi.db"))
    try:
        svc = RoiRecognitionService(db=db, videos_dir=str(tmp), crops_dir=str(tmp / "crops"))
        res = svc.commit_roi_tag(
            entity_name="StudioTag", category="person",
            video_filename=vid.name, timestamp_sec=0.4, bbox=[40, 40, 120, 160],
        )
        sightings = db.get_sightings(entity_id=res["entity_id"], limit=5)
        has_media_off = bool(sightings and sightings[0].get("media_offset_sec") == 0.4)
        checks["roi_tag_persists_media_offset"] = has_media_off
        if not has_media_off:
            failures.append("RoiRecognitionService.tag_roi() dropped media_offset_sec in sightings")
    finally:
        db.close()

    bridge_js = (REPO_ROOT / "dashboard/static/js/scrubber_library_bridge.js").read_text(encoding="utf-8")
    links_js = (REPO_ROOT / "dashboard/static/js/video_timeline_links.js").read_text(encoding="utf-8")
    checks["bridge_uses_singular_report_404"] = "/report`" in bridge_js or "/report'" in bridge_js
    checks["links_reads_occurrences"] = ".occurrences" in links_js
    if checks["bridge_uses_singular_report_404"]:
        failures.append("scrubber_library_bridge.js fetches singular /api/videos/{fn}/report (404)")
    if checks["links_reads_occurrences"]:
        failures.append("video_timeline_links.js reads non-existent report.occurrences")


def run_probe() -> dict[str, Any]:
    """Execute Video Studio contract assertions."""
    checks: dict[str, Any] = {}
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        vid = tmp / "clip.mp4"
        _write_clip(vid)
        _check_indexer_and_timeline(tmp, vid, failures, checks)
        _check_roi_and_js_contracts(tmp, vid, failures, checks)

    status = "error" if failures else "ok"
    summary = f"Video Studio contract probe: {len(failures)} failure(s)" if failures else "Video Studio contract probe passed."
    return {"status": status, "summary": summary, "details": {"checks": checks, "failures": failures}}


if __name__ == "__main__":
    res = run_probe()
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["status"] == "ok" else 1)
