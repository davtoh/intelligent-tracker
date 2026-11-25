#!/usr/bin/env python3
"""Diagnostic Probe: sightings_provenance_probe.

Verifies sightings.camera_id and sightings.run_id persistence and retrieval
in an isolated TemporaryDirectory TrackerDB.
"""

import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def run_probe() -> dict[str, Any]:
    """Verify sightings camera_id and run_id provenance persistence."""
    from intelligent_tracker.database import TrackerDB

    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        db = TrackerDB(str(Path(tmpdir) / "tracker.db"))
        try:
            ent_id = db.add_entity("ProvPerson", category="person")
            db.add_sighting(
                entity_id=ent_id,
                track_id=7,
                source="cam_prov",
                timestamp=time.time(),
                zone_id="zone_prov",
                bbox=[10, 20, 50, 80],
                confidence=0.91,
                video_filename="clip.mp4",
                media_offset_sec=1.5,
                camera_id="cam_prov",
                run_id="run_abc123",
            )
            rows = db.get_sightings(entity_id=ent_id)
            if len(rows) != 1:
                failures.append(f"Expected 1 sighting, got {len(rows)}")
            else:
                row = rows[0]
                if row.get("camera_id") != "cam_prov" or row.get("run_id") != "run_abc123":
                    failures.append(f"Provenance mismatch: camera_id={row.get('camera_id')} run_id={row.get('run_id')}")
        finally:
            db.close()

    status = "error" if failures else "ok"
    summary = f"Sightings provenance probe: {len(failures)} failure(s)" if failures else "Sightings camera_id/run_id provenance probe passed."
    return {"status": status, "summary": summary, "details": {"failures": failures}}


if __name__ == "__main__":
    res = run_probe()
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["status"] == "ok" else 1)
