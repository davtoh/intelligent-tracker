#!/usr/bin/env python3
"""Diagnostic Probe: cold_boot_world_probe.

Boots create_app() against an isolated TemporaryDirectory DB/config/scenarios
(including zero-stream DB routes and DB/YAML zones/tripwires) to assert
cold-start WorldGraph sync, app.state bindings, and /api/* health.
"""

import json
import os
import sys
import tempfile
import unittest.mock
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _seed_isolated_env(tmp: Path) -> tuple[Path, Path, Path]:
    """Create isolated cameras.json, scenarios.yaml, and seeded tracker.db."""
    from intelligent_tracker.database import TrackerDB

    cfg_path = tmp / "cameras.json"
    cfg_path.write_text(json.dumps({"cameras": []}), encoding="utf-8")
    scen_path = tmp / "scenarios.yaml"
    scen_path.write_text("zones: {}\ntripwires: {}\n", encoding="utf-8")
    db_path = tmp / "tracker.db"
    db = TrackerDB(str(db_path))
    try:
        db.save_zone("cam_test", "Boot Zone", [[0, 0], [100, 0], [100, 100], [0, 100]])
        db.save_tripwire("cam_test", "Boot Tripwire", [[0, 50], [100, 50]])
        db.add_entity("BootPerson", category="person")
    finally:
        db.close()
    return cfg_path, scen_path, db_path


def run_probe() -> dict[str, Any]:
    """Execute cold-boot lifecycle assertions against an isolated FastAPI app."""
    checks: dict[str, Any] = {}
    failures: list[str] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        cfg_path, scen_path, db_path = _seed_isolated_env(tmp)
        env_patch = {
            "TRACKER_DB_PATH": str(db_path),
            "CAMERAS_CONFIG_PATH": str(cfg_path),
            "SCENARIOS_CONFIG_PATH": str(scen_path),
        }
        with unittest.mock.patch.dict(os.environ, env_patch, clear=False):
            from fastapi.testclient import TestClient
            from dashboard.app import create_app

            app = create_app()
            with TestClient(app) as client:
                # 1. Check WorldGraph cold-start zone/tripwire sync (Bug #6)
                scen_mgr = getattr(app.state, "scenario_manager", None)
                wg = getattr(app.state, "world_graph", None)
                if scen_mgr is not None and wg is None:
                    wg = getattr(scen_mgr, "world_graph", None)
                zones_in_wg = len(getattr(wg, "zones", {}) or {}) if wg else 0
                tw_in_wg = len(getattr(wg, "tripwires", {}) or {}) if wg else 0
                checks["world_graph_zones"] = zones_in_wg
                checks["world_graph_tripwires"] = tw_in_wg
                if zones_in_wg == 0 or tw_in_wg == 0:
                    failures.append(f"WorldGraph missing cold-boot zones/tripwires (zones={zones_in_wg}, tripwires={tw_in_wg})")

                # 2. Check app.state ConfidenceEngine / WorldQueryEngine bindings (Bug #9)
                has_conf = getattr(app.state, "confidence_engine", None) is not None
                has_wqe = getattr(app.state, "world_query_engine", None) is not None
                checks["app_state_confidence_engine"] = has_conf
                checks["app_state_world_query_engine"] = has_wqe
                if not has_conf or not has_wqe:
                    failures.append(f"app.state missing bindings (confidence_engine={has_conf}, world_query_engine={has_wqe})")

                # 3. Check zero-stream DB route GET /entities (Bug #9)
                r_ent = client.get("/entities")
                checks["get_entities_status"] = r_ent.status_code
                ent_count = len(r_ent.json()) if r_ent.status_code == 200 and isinstance(r_ent.json(), list) else 0
                checks["get_entities_count"] = ent_count
                if r_ent.status_code != 200 or ent_count == 0:
                    failures.append(f"GET /entities failed in zero-stream mode (status={r_ent.status_code}, count={ent_count})")

                # 4. Check OpenAPI duplicate operation_ids (Bug #9)
                spec = app.openapi()
                op_ids: list[str] = []
                for methods in spec.get("paths", {}).values():
                    for op in methods.values():
                        if isinstance(op, dict) and "operationId" in op:
                            op_ids.append(op["operationId"])
                dups = sorted({oid for oid in op_ids if op_ids.count(oid) > 1})
                checks["duplicate_operation_ids"] = dups
                if dups:
                    failures.append(f"Duplicate OpenAPI operationIds: {dups}")

    status = "error" if failures else "ok"
    summary = f"Cold-boot probe: {len(failures)} failure(s)" if failures else "Cold-boot probe passed all checks."
    return {"status": status, "summary": summary, "details": {"checks": checks, "failures": failures}}


if __name__ == "__main__":
    res = run_probe()
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["status"] == "ok" else 1)
