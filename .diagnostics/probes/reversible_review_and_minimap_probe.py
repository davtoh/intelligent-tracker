#!/usr/bin/env python3
"""Diagnostic Probe: reversible_review_and_minimap_probe.

Verifies SQLite v5 review_decisions confirm/reassign/enroll-new/dismiss -> undo
state restoration, recurring unknown queueing (sim < 0.45, dwell >= 3.0s),
timeline report-wrong, and WorldTacticalMinimap / Studio 4-pt BEV quad parity.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _check_review_actions_undo(tmp: Path, db: Any, failures: list[str], checks: dict[str, Any]) -> int:
    """Verify v5 schema and confirm/reassign/enroll-new/dismiss -> undo restoration."""
    import cv2
    from dashboard.services.reversible_review_service import execute_review_action_with_audit, undo_review_decision
    from intelligent_tracker.active_learning import ActiveLearningManager

    ver = db._conn.execute("PRAGMA user_version").fetchone()[0]
    checks["schema_v5"] = ver == 5
    if ver != 5:
        failures.append(f"Expected PRAGMA user_version=5, got {ver}")

    e1, e2 = db.add_entity("Alice", category="person"), db.add_entity("Bob", category="person")
    crop_path = tmp / "probe_crop.jpg"
    cv2.imwrite(str(crop_path), np.full((64, 32, 3), 140, dtype=np.uint8))
    al_mgr = ActiveLearningManager(db=db, crops_dir=str(tmp / "crops"))

    for action, target_id in (("confirm", e1), ("reassign", e2), ("enroll_new", None), ("dismiss", e1)):
        rid = db.add_review_item(
            camera_id="cam_01", track_id=11, crop_path=str(crop_path),
            suggested_entity_id=e1, similarity=0.52, bbox=[10, 10, 50, 80],
        )
        res = execute_review_action_with_audit(
            db, al_mgr, action=action, item_id=rid, target_entity_id=target_id,
            name="NewPerson" if action == "enroll_new" else "", category="person",
        )
        dec_id = res.get("decision_id")
        if not dec_id:
            failures.append(f"Missing decision_id for action={action}: {res}")
            continue
        undo_res = undo_review_decision(db, decision_id=int(dec_id))
        item = db.get_review_item(rid)
        if undo_res.get("status") != "undone" or not item or item.get("status") != "pending":
            failures.append(f"Undo failed for action={action}: undo={undo_res}, item={item}")
    checks["review_actions_undo_ok"] = not any("Undo failed" in f for f in failures)
    return e1


def _check_report_wrong_and_unknowns(tmp: Path, db: Any, entity_id: int, failures: list[str], checks: dict[str, Any]) -> None:
    """Verify timeline report-wrong -> undo and recurring unknown dwell >= 3.0s queueing."""
    from dashboard.services.reversible_review_service import report_wrong_sighting, undo_review_decision
    from intelligent_tracker.active_learning_triage import ActiveLearningTriage
    from intelligent_tracker.tracker.track import Track

    sid = db.add_sighting(entity_id=entity_id, track_id=9, source="cam_01", timestamp=time.time(), bbox=[5, 5, 30, 60])
    rw = report_wrong_sighting(db, sighting_id=sid, notes="wrong_id")
    if not rw.get("decision_id"):
        failures.append(f"report_wrong_sighting missing decision_id: {rw}")
    else:
        rw_undo = undo_review_decision(db, decision_id=int(rw["decision_id"]))
        if rw_undo.get("status") != "undone":
            failures.append(f"report_wrong undo failed: {rw_undo}")
    checks["report_wrong_undo_ok"] = not any("report_wrong" in f for f in failures)

    triage = ActiveLearningTriage(db=db, min_confidence=0.45, unknown_min_dwell_sec=3.0, crops_dir=str(tmp / "crops"))
    frame = np.full((120, 160, 3), 100, dtype=np.uint8)
    trk_short = Track(track_id=21, bbox=(10, 10, 50, 80), class_id=0, label="person", confidence=0.9)
    trk_long = Track(track_id=22, bbox=(20, 15, 60, 90), class_id=0, label="person", confidence=0.9)
    q_short = triage.consider_candidate(track=trk_short, frame=frame, similarity=0.22, camera_id="cam_01", track_dwell_sec=1.0)
    q_long = triage.consider_candidate(track=trk_long, frame=frame, similarity=0.22, camera_id="cam_01", track_dwell_sec=3.5)
    q_item = db.get_review_item(q_long) if q_long else None
    ok_unk = (q_short is None) and bool(q_long) and q_item is not None and q_item.get("suggested_entity_id") is None
    checks["recurring_unknown_queued"] = ok_unk
    if not ok_unk:
        failures.append(f"Recurring unknown check failed: short={q_short}, long={q_long}, item={q_item}")


def _check_review_undo_and_unknowns(tmp: Path, failures: list[str], checks: dict[str, Any]) -> None:
    """Verify v5 review_decisions confirm/reassign/enroll-new/dismiss -> undo and recurring unknowns."""
    from intelligent_tracker.database import TrackerDB

    db = TrackerDB(str(tmp / "probe_v5.db"))
    try:
        e1 = _check_review_actions_undo(tmp, db, failures, checks)
        _check_report_wrong_and_unknowns(tmp, db, e1, failures, checks)
    finally:
        db.close()


def _check_studio_and_minimap_contracts(failures: list[str], checks: dict[str, Any]) -> None:
    """Verify studio_canvas.js < 260L budget, BEV quad symbols, and WorldTacticalMinimap zoom/BEV."""
    canvas_js = REPO_ROOT / "dashboard" / "static" / "js" / "studio_canvas.js"
    minimap_js = REPO_ROOT / "dashboard" / "static" / "js" / "world_minimap.js"
    canvas_lines = len(canvas_js.read_text(encoding="utf-8").splitlines())
    canvas_src = canvas_js.read_text(encoding="utf-8")
    minimap_src = minimap_js.read_text(encoding="utf-8")

    checks["studio_canvas_lines"] = canvas_lines
    if canvas_lines >= 260:
        failures.append(f"studio_canvas.js exceeds 260L cap: {canvas_lines}L")
    if "src_points" not in canvas_src or "bevQuadMode" not in canvas_src:
        failures.append("studio_canvas.js missing 4-point BEV quad (src_points / bevQuadMode) rendering")
    for sym in ("setZoom", "fitToBounds", "panBy", "viewMode", "toCanvasXY", "toWorldXY"):
        if sym not in minimap_src:
            failures.append(f"world_minimap.js missing {sym}")

    node = shutil.which("node")
    if node:
        vm_code = (
            "const fs=require('fs'),vm=require('vm');"
            "const ctx={window:{},document:{},console};ctx.window=ctx;"
            "vm.runInNewContext(fs.readFileSync('dashboard/static/js/world_minimap.js','utf8'),ctx);"
            "const M=ctx.WorldTacticalMinimapView;"
            "if(!M||typeof M.toCanvasXY!=='function')throw new Error('missing WorldTacticalMinimapView');"
            "const b={min_x:0,max_x:10,min_y:0,max_y:10};"
            "const p1=M.toCanvasXY(1,2,b,200,200,10);M.setZoom(2);"
            "const p2=M.toCanvasXY(1,2,b,200,200,10);"
            "if(!Array.isArray(p1)||!Array.isArray(p2)||p1[0]===p2[0])throw new Error('toCanvasXY zoom failed');"
        )
        proc = subprocess.run([node, "-e", vm_code], cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=15)
        checks["minimap_node_vm_ok"] = proc.returncode == 0
        if proc.returncode != 0:
            failures.append(f"world_minimap.js Node VM check failed: {proc.stderr.strip()}")


def run_probe() -> dict[str, Any]:
    """Run Step 4 reversible review & minimap seam probe."""
    failures: list[str] = []
    checks: dict[str, Any] = {}
    with tempfile.TemporaryDirectory() as tmpdir:
        _check_review_undo_and_unknowns(Path(tmpdir), failures, checks)
    _check_studio_and_minimap_contracts(failures, checks)
    status = "error" if failures else "ok"
    summary = (
        f"Reversible review & minimap probe: {len(failures)} failure(s)"
        if failures
        else "Reversible review & minimap probe passed."
    )
    return {"status": status, "summary": summary, "details": {"checks": checks, "failures": failures}}


if __name__ == "__main__":
    res = run_probe()
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["status"] == "ok" else 1)
