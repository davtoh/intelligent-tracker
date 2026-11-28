#!/usr/bin/env python3
"""Diagnostic Probe: tracking_coasting_and_uniqueness_probe.

Verifies 8 FPS synthetic P1 tracking (1 visible box + K=3 identity lock)
and 2-box concurrent 1-to-1 entity exclusion on a single camera.
"""

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class _ProbeHomography:
    def track_to_ground(self, bbox: Any) -> tuple[float, float]:
        return (float(bbox[0]), float(bbox[1]))


class _ProbeExtractor:
    def __init__(self, vec_by_x: dict[int, np.ndarray], default_vec: np.ndarray):
        self.embedding_dim = int(default_vec.shape[0])
        self._vec_by_x = vec_by_x
        self._default_vec = default_vec

    def extract(self, frame: np.ndarray, bbox: Any = None) -> np.ndarray:
        if bbox is not None:
            bx = int(bbox[0])
            for key, vec in self._vec_by_x.items():
                if abs(bx - key) <= 30:
                    return vec
        return self._default_vec

    def extract_crop(self, crop: np.ndarray) -> np.ndarray:
        return self._default_vec


def _check_8fps_p1_tracking(db: Any, failures: list[str], checks: dict[str, Any]) -> None:
    """Verify 8 FPS fast-moving P1 keeps 1 visible telemetry box and locks at K=3."""
    from dashboard.services.stream_telemetry import _extract_track_telemetry
    from intelligent_tracker.matching.gallery import GalleryMatcher
    from intelligent_tracker.tracker.sort import SortTracker

    eid = db.add_entity("P1_Target", "person")
    vec = np.zeros(16, dtype=np.float32)
    vec[0] = 1.0
    db.add_signature(eid, vec)
    tracker = SortTracker(min_hits=1, iou_threshold=0.3, coast_frames=2, coast_seconds=0.5)
    matcher = GalleryMatcher(db=db, extractor=_ProbeExtractor({}, vec), reid_threshold=0.65, min_track_hits=1, hysteresis_k=3)
    frame = np.zeros((240, 640, 3), dtype=np.uint8)
    seen_tids: set[int] = set()
    max_visible = 0
    locked_eid = None
    for step in range(5):
        det = [(40 + step * 75, 60, 48, 96, 0, 0.92, "person")]
        ts = 1000.0 + step * 0.125
        tracks = tracker.update(det, timestamp=ts)
        matcher.match_tracks(tracks, frame, source="cam_p1", timestamp=ts)
        visible = _extract_track_telemetry(tracks, _ProbeHomography())
        max_visible = max(max_visible, len(visible))
        seen_tids.update(item["id"] for item in visible)
        if tracks:
            locked_eid = getattr(next(iter(tracks.values())), "entity_id", None)
    checks["p1_unique_track_ids"] = len(seen_tids)
    checks["p1_max_visible_boxes"] = max_visible
    checks["p1_k3_locked"] = locked_eid == eid
    if len(seen_tids) != 1 or max_visible != 1 or locked_eid != eid:
        failures.append(f"8 FPS P1 failed: tids={seen_tids}, max_visible={max_visible}, locked_eid={locked_eid}")


def _check_two_box_uniqueness(db: Any, failures: list[str], checks: dict[str, Any]) -> None:
    """Verify two concurrent tracks cannot both bind 'Samir' on the same camera."""
    from intelligent_tracker.matching.gallery import GalleryMatcher
    from intelligent_tracker.tracker.track import Track

    eid = db.add_entity("Samir", "person")
    base = np.zeros(16, dtype=np.float32)
    base[2] = 1.0
    db.add_signature(eid, base)
    weaker = np.zeros(16, dtype=np.float32)
    weaker[2], weaker[3] = 0.85, 0.52
    weaker /= np.linalg.norm(weaker)
    matcher = GalleryMatcher(
        db=db, extractor=_ProbeExtractor({20: base, 220: weaker}, base),
        reid_threshold=0.65, min_track_hits=1, hysteresis_k=1,
    )
    t1 = Track(track_id=10, bbox=(20, 20, 48, 96), label="person")
    t2 = Track(track_id=11, bbox=(220, 20, 48, 96), label="person")
    t1.state = t2.state = "confirmed"
    matcher.match_tracks({10: t1, 11: t2}, np.zeros((240, 320, 3), dtype=np.uint8), source="cam_01", timestamp=200.0)
    bound = [tid for tid, trk in ((10, t1), (11, t2)) if getattr(trk, "entity_id", None) == eid]
    checks["samir_bound_tracks"] = bound
    if bound != [10]:
        failures.append(f"1-to-1 exclusion failed for Samir: bound={bound}")


def run_probe() -> dict[str, Any]:
    """Run 8 FPS P1 tracking stability and 2-box 1-to-1 entity exclusion checks."""
    from intelligent_tracker.database import TrackerDB

    checks: dict[str, Any] = {}
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        db = TrackerDB(str(Path(tmpdir) / "probe.db"))
        try:
            _check_8fps_p1_tracking(db, failures, checks)
            _check_two_box_uniqueness(db, failures, checks)
        finally:
            db.close()

    status = "error" if failures else "ok"
    summary = (
        f"Tracking coasting & uniqueness probe: {len(failures)} failure(s)"
        if failures
        else "Tracking coasting & 1-to-1 uniqueness probe passed."
    )
    return {"status": status, "summary": summary, "details": {"checks": checks, "failures": failures}}


if __name__ == "__main__":
    res = run_probe()
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["status"] == "ok" else 1)
