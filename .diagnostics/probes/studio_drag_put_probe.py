#!/usr/bin/env python3
"""Diagnostic Probe: studio_drag_put_probe.

Verifies PUT /api/scenarios/zones/{camera_id}/{zone_id} and tripwires PUT
persistence against an isolated TrackerDB/ScenarioManager without touching live data.
"""

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def run_probe() -> dict[str, Any]:
    """Verify Studio zone/tripwire PUT persistence in an isolated workspace."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from dashboard.routers.scenarios import router as scenarios_router
    from intelligent_tracker.database import TrackerDB
    from intelligent_tracker.scenarios import ScenarioManager

    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        db = TrackerDB(str(tmp / "tracker.db"))
        try:
            scen_path = tmp / "scenarios.yaml"
            scen_path.write_text("zones: {}\ntripwires: {}\n", encoding="utf-8")
            sm = ScenarioManager(config_path=str(scen_path))
            sm.save_zone("cam_studio", "zone_1", [[10, 10], [100, 10], [100, 100], [10, 100]])
            sm.save_tripwire("cam_studio", "tw_1", [[10, 50], [210, 50]])
            app = FastAPI()
            app.include_router(scenarios_router)
            app.state.db = db
            app.state.scenario_manager = sm

            client = TestClient(app)
            new_poly = [[20, 20], [120, 20], [120, 120], [20, 120]]
            z_resp = client.put(
                "/api/scenarios/zones/cam_studio/zone_1",
                json={"polygon": new_poly},
            )
            if z_resp.status_code != 200:
                failures.append(f"PUT zone failed: {z_resp.status_code} {z_resp.text}")
            elif z_resp.json().get("zone", {}).get("polygon") != new_poly:
                failures.append(f"PUT zone did not update polygon: {z_resp.json()}")

            flipped_seg = [[210, 50], [10, 50]]
            tw_resp = client.put(
                "/api/scenarios/tripwires/cam_studio/tw_1",
                json={"line_segment": flipped_seg},
            )
            if tw_resp.status_code != 200:
                failures.append(f"PUT tripwire flip failed: {tw_resp.status_code} {tw_resp.text}")
            else:
                saved_tw = sm.cameras.get("cam_studio", {}).get("tripwires", {}).get("tw_1")
                saved_seg = [list(saved_tw.pt1), list(saved_tw.pt2)] if saved_tw else None
                if saved_seg != flipped_seg:
                    failures.append(f"PUT tripwire flip did not persist swapped coords: {saved_seg}")
        finally:
            db.close()

    status = "error" if failures else "ok"
    summary = f"Studio drag/PUT probe: {len(failures)} failure(s)" if failures else "Studio drag/PUT persistence probe passed."
    return {"status": status, "summary": summary, "details": {"failures": failures}}


if __name__ == "__main__":
    res = run_probe()
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["status"] == "ok" else 1)
