#!/usr/bin/env python3
"""Diagnostic Probe: cold_boot_world_probe.

Boots create_app() against an isolated TemporaryDirectory DB/config/scenarios
to assert cold-start WorldGraph sync & reactive events, shared ConfidenceEngine,
TRC-017 cameras.json list resilience, stream restart scenario preservation,
and ProcessingModeService <-> StreamRecordingController lock-order safety.
"""

import json
import os
import sys
import tempfile
import threading
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
    cfg_path.write_text(json.dumps({"cameras": {}}), encoding="utf-8")
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


def _check_app_boot_contracts(app: Any, client: Any, failures: list[str], checks: dict[str, Any]) -> None:
    """Assert WorldGraph cold-start zones/tripwires, app.state bindings, /entities, and OpenAPI."""
    scen_mgr = getattr(app.state, "scenario_manager", None)
    wg = getattr(app.state, "world_graph", None) or getattr(scen_mgr, "world_graph", None)
    snap = wg.snapshot() if wg and hasattr(wg, "snapshot") else {}
    zones_in_wg, tw_in_wg = len(snap.get("zones", {})), len(snap.get("tripwires", {}))
    checks.update(world_graph_zones=zones_in_wg, world_graph_tripwires=tw_in_wg)
    if zones_in_wg == 0 or tw_in_wg == 0:
        failures.append(
            f"WorldGraph missing cold-boot zones/tripwires (zones={zones_in_wg}, tripwires={tw_in_wg})"
        )

    has_conf = getattr(app.state, "confidence_engine", None) is not None
    has_wqe = getattr(app.state, "world_query_engine", None) is not None
    checks.update(app_state_confidence_engine=has_conf, app_state_world_query_engine=has_wqe)
    if not has_conf or not has_wqe:
        failures.append(
            f"app.state missing bindings (confidence_engine={has_conf}, world_query_engine={has_wqe})"
        )

    r_ent = client.get("/entities")
    ent_count = len(r_ent.json()) if r_ent.status_code == 200 and isinstance(r_ent.json(), list) else 0
    checks.update(get_entities_status=r_ent.status_code, get_entities_count=ent_count)
    if r_ent.status_code != 200 or ent_count == 0:
        failures.append(
            f"GET /entities failed in zero-stream mode (status={r_ent.status_code}, count={ent_count})"
        )

    op_ids = [
        op["operationId"]
        for methods in app.openapi().get("paths", {}).values()
        for op in methods.values()
        if isinstance(op, dict) and "operationId" in op
    ]
    dups = sorted({oid for oid in op_ids if op_ids.count(oid) > 1})
    checks["duplicate_operation_ids"] = dups
    if dups:
        failures.append(f"Duplicate OpenAPI operationIds: {dups}")


def _check_world_reactive_events(app: Any, failures: list[str], checks: dict[str, Any]) -> None:
    """Assert WorldGraph emits reactive events onto EventBus upon mutation (P0-5)."""
    from intelligent_tracker.world.nodes import ZoneNode

    wg = getattr(app.state, "world_graph", None)
    bus = getattr(wg, "_event_bus", None) if wg is not None else None
    checks["world_graph_has_event_bus"] = bus is not None
    if wg is None or bus is None:
        failures.append("P0-5: WorldGraph._event_bus is None on cold boot (reactive events disabled)")
        return
    received: list[Any] = []
    arrived = threading.Event()
    bus.subscribe(lambda ev: (received.append(ev), arrived.set()))
    wg.register_zone(
        ZoneNode(
            zone_id="z_probe", camera_id="cam_test", name="ProbeZone", points=[(0, 0), (10, 0), (10, 10)]
        )
    )
    arrived.wait(timeout=1.0)
    checks["world_graph_reactive_events"] = len(received)
    if not received:
        failures.append("P0-5: WorldGraph.register_zone() emitted 0 reactive events to EventBus")


def _check_cameras_list_and_shared_confidence(tmp: Path, failures: list[str], checks: dict[str, Any]) -> None:
    """Assert TRC-017 cameras.json list resilience and multi-cam shared ConfidenceEngine (P0-5)."""
    from dashboard.camera_pool import CameraPool
    from dashboard.services.camera_config_store import CameraConfigStore

    list_cfg = tmp / "cameras_list.json"
    list_cfg.write_text(
        json.dumps({"cameras": [{"id": "cam_list_1", "name": "ListCam", "source": "0", "enabled": False}]}),
        encoding="utf-8",
    )
    loaded, _ = CameraConfigStore(str(list_cfg)).load_cameras()
    trc_ok = "cam_list_1" in loaded and "cameras" not in loaded
    checks["trc_017_cameras_list_resilience"] = trc_ok
    if not trc_ok:
        failures.append(
            f"TRC-017: CameraConfigStore failed on {{'cameras': [...]}}: keys={list(loaded.keys())}"
        )

    multi_cfg = tmp / "cameras_multi.json"
    multi_cfg.write_text(
        json.dumps(
            [
                {"id": "cam_a", "name": "CamA", "source": "0", "enabled": False},
                {"id": "cam_b", "name": "CamB", "source": "1", "enabled": False},
            ]
        ),
        encoding="utf-8",
    )
    pool = CameraPool(config_file=str(multi_cfg), db_path=str(tmp / "pool.db"), autostart=False)
    try:
        pool_ce = getattr(pool, "_confidence_engine", None)
        checks["camera_pool_owns_shared_confidence_engine"] = pool_ce is not None
        if pool_ce is None:
            failures.append("P0-5: CameraPool does not own a shared _confidence_engine across cameras")
    finally:
        pool.stop_all()


def _check_restart_preserves_scenario(tmp: Path, failures: list[str], checks: dict[str, Any]) -> None:
    """Assert stream restart preserves ScenarioManager zones/homography (P1-8)."""
    import cv2
    import numpy as np
    from dashboard.camera_pool import CameraPool
    from intelligent_tracker.scenarios import ScenarioManager

    vid = tmp / "restart.mp4"
    writer = cv2.VideoWriter(str(vid), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (320, 240))  # type: ignore[attr-defined]
    try:
        writer.write(np.zeros((240, 320, 3), dtype=np.uint8))
    finally:
        writer.release()

    cfg = tmp / "restart_cams.json"
    cam_cfg = {"id": "cam_r", "name": "RestartCam", "source": str(vid), "enabled": False}
    cfg.write_text(json.dumps([cam_cfg]), encoding="utf-8")
    pool = CameraPool(config_file=str(cfg), db_path=str(tmp / "restart.db"), autostart=False)
    try:
        active_cfg = {**cam_cfg, "enabled": True}
        sm = pool._coordinator.create_and_register_stream("cam_r", active_cfg, start=False)
        scen = ScenarioManager(config_path=str(tmp / "scen_r.yaml"))
        scen.save_zone("cam_r", "z_r", [[0, 0], [100, 0], [100, 100], [0, 100]])
        scen.save_homography("cam_r", [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)])
        scen.apply_to_stream_manager(sm)
        pool._coordinator.restart_stream("cam_r", active_cfg)
        new_sm = pool.streams.get("cam_r")
        preserved = bool(
            new_sm and getattr(new_sm, "homography", None) is not None and len(new_sm.analytics.zones) > 0
        )
        checks["restart_preserves_scenario_homography"] = preserved
        if not preserved:
            failures.append("P1-8: restart_stream() dropped ScenarioManager zones/homography")
    finally:
        pool.stop_all()


def _check_restart_and_lock_order(tmp: Path, failures: list[str], checks: dict[str, Any]) -> None:
    """Assert stream restart scenario preservation (P1-8) and ProcessingModeService<->Recording lock order (P0-2)."""
    from types import SimpleNamespace
    import numpy as np
    from dashboard.services.processing_mode_service import ProcessingModeService
    from dashboard.services.stream_recording import StreamRecordingController

    _check_restart_preserves_scenario(tmp, failures, checks)
    svc = ProcessingModeService(mode="full_realtime")

    class _NoopWriter:
        is_open = True
        def write(self, _frame: Any) -> bool: return True
        def release(self) -> None: self.is_open = False
        def snapshot(self) -> dict[str, Any]: return {"frames_written": 1, "width": 64, "height": 64, "fps": 10.0}

    rec = StreamRecordingController("cam_lock", output_dir=str(tmp / "rec"), writer_factory=lambda *a, **k: _NoopWriter(), mode_service_getter=lambda: svc)
    class _StreamStub:
        is_running, is_armed, subscriber_count, _is_hibernating = True, False, 0, False
        @property
        def is_recording(self) -> bool: return rec.is_recording
    pool_stub = SimpleNamespace(streams={"cam_lock": _StreamStub()}, _lock=threading.RLock())
    stop = threading.Event()
    frame = np.zeros((64, 64, 3), dtype=np.uint8)

    def _rec_loop() -> None:
        for i in range(40):
            if stop.is_set():
                break
            rec.start(filename=f"lock_{i}.mp4")
            rec.write_frame(frame)
            rec.stop()

    t1 = threading.Thread(target=lambda: [svc.get_state(pool_stub) for _ in range(80) if not stop.is_set()], daemon=True)
    t2 = threading.Thread(target=_rec_loop, daemon=True)
    t1.start(); t2.start()
    t1.join(timeout=3.0); t2.join(timeout=3.0)
    stop.set()
    rec.finalize_if_active()
    checks["lock_order_stress_alive"] = t1.is_alive() or t2.is_alive()
    if t1.is_alive() or t2.is_alive():
        failures.append("P0-2: ProcessingModeService<->StreamRecordingController lock-order stress timed out")


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
                _check_app_boot_contracts(app, client, failures, checks)
                _check_world_reactive_events(app, failures, checks)
        _check_cameras_list_and_shared_confidence(tmp, failures, checks)
        _check_restart_and_lock_order(tmp, failures, checks)

    status = "error" if failures else "ok"
    summary = (
        f"Cold-boot probe: {len(failures)} failure(s)" if failures else "Cold-boot probe passed all checks."
    )
    return {"status": status, "summary": summary, "details": {"checks": checks, "failures": failures}}


if __name__ == "__main__":
    res = run_probe()
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["status"] == "ok" else 1)
