#!/usr/bin/env python3
"""Diagnostic Probe: spa_nine_tab_cdp_probe.

Boots an isolated ephemeral FastAPI server (port=0, TemporaryDirectory) and runs
headless Chrome CDP (--capture-runtime --audit-layout --stability-ms 2000) across
all 9 SPA tabs, 1x1 vs 2x2 multiview grid, short vs long camera title switches,
and modals to assert 0 HTTP>=400, 0 missing assets, 0 JS exceptions, 0 CLS shifts,
0 <4px sibling gaps, 0 dead/duplicate buttons, and 0 layout overflows.
"""

import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import uvicorn

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DIAGNOSE_PY = Path.home() / ".gemini/config/skills/system-diagnostics/scripts/diagnose.py"
SWEEP_JS_PATH = Path(__file__).with_name("spa_nine_tab_sweep.js")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])

def _write_synth_mp4(path: Path) -> bytes:
    import cv2
    import numpy as np
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (320, 240))  # type: ignore[attr-defined]
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    cv2.rectangle(frame, (40, 40), (140, 180), (60, 180, 220), -1)
    try:
        for _ in range(5):
            writer.write(frame)
    finally:
        writer.release()
    return cv2.imencode(".jpg", frame)[1].tobytes()


def _seed_spa_env(tmp: Path) -> tuple[str, str, str, Path, bytes]:
    from intelligent_tracker.database import TrackerDB
    vdir = tmp / "videos"
    vdir.mkdir(parents=True, exist_ok=True)
    rec_mp4 = vdir / "recorded_clip.mp4"
    jpeg_bytes = _write_synth_mp4(rec_mp4)
    cfg_path = tmp / "cameras.json"
    cfg_path.write_text(json.dumps([
        {"id": "cam_short", "name": "Cam1", "source": str(rec_mp4), "enabled": True},
        {"id": "cam_long", "name": "Warehouse North-East Loading Dock Entrance Camera 02", "source": "1", "enabled": False},
        {"id": "usb_2", "name": "USB Cam 2", "source": "2", "enabled": False},
    ]), encoding="utf-8")
    scen_path = tmp / "scenarios.yaml"
    scen_path.write_text("zones: {}\ntripwires: {}\n", encoding="utf-8")
    db_path = tmp / "tracker.db"
    db = TrackerDB(str(db_path))
    db.save_video_run(video_filename="recorded_clip.mp4", report={"entities": [], "alerts": []}, frame_detections=[], source_fps=10.0)
    db.add_review_item(
        camera_id="cam_short", track_id=1, crop_path="", similarity=0.58,
        video_filename="recorded_clip.mp4", media_offset_sec=0.5,
        bbox=[40, 40, 100, 140], frame_width=320, frame_height=240,
    )
    db.close()
    return str(cfg_path), str(db_path), str(scen_path), vdir, jpeg_bytes


def _make_isolated_init(cfg: str, db_p: str, scen: str, jpeg_bytes: bytes, refs: dict[str, Any]) -> Any:
    import cv2
    import numpy as np
    from dashboard.camera_pool import CameraPool
    from dashboard.dependencies import bind_app_state
    from intelligent_tracker.database import TrackerDB
    from intelligent_tracker.lifecycle import StreamLifecycleManager
    from intelligent_tracker.scenarios import ScenarioManager

    def _isolated_init(application: Any) -> tuple[Any, Any, Any, Any]:
        pool = CameraPool(config_file=cfg, db_path=db_p, autostart=False)
        if mgr := pool.get_stream("cam_short"):
            mgr._running = True
            mgr._latest_raw_frame = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
            mgr._latest_raw_jpeg = mgr._latest_jpeg = jpeg_bytes
        db = TrackerDB(db_p)
        lm = StreamLifecycleManager(db=db, camera_pool=pool)
        refs.update(pool=pool, db=db)
        bind_app_state(application, camera_pool=pool, stream_manager=pool.primary_stream, scenario_manager=ScenarioManager(config_path=scen), lifecycle_manager=lm, db=db)
        return pool, pool.primary_stream, lm, None
    return _isolated_init


def _start_server(tmp: Path) -> tuple[uvicorn.Server, threading.Thread, int, dict[str, Any], Any]:
    import dashboard.app as app_module
    import dashboard.routers.videos as videos_router
    cfg, db_p, scen, vdir, jpeg_bytes = _seed_spa_env(tmp)
    refs: dict[str, Any] = {"orig_vdir": videos_router.VIDEOS_DIR}
    videos_router.VIDEOS_DIR = str(vdir)
    orig_init = app_module._init_runtime_services
    app_module._init_runtime_services = _make_isolated_init(cfg, db_p, scen, jpeg_bytes, refs)
    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(app_module.app, host="127.0.0.1", port=port, log_level="error"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    deadline = time.monotonic() + 10.0
    while not srv.started and time.monotonic() < deadline:
        time.sleep(0.05)
    return srv, th, port, refs, orig_init


def _stop_server(srv: uvicorn.Server, th: threading.Thread, refs: dict[str, Any], orig_init: Any) -> None:
    import dashboard.app as app_module
    import dashboard.routers.videos as videos_router
    from dashboard.dependencies import clear_app_state, set_shutting_down

    srv.should_exit = True
    th.join(timeout=5.0)
    app_module._init_runtime_services = orig_init
    if "orig_vdir" in refs:
        videos_router.VIDEOS_DIR = refs["orig_vdir"]
    if pool := refs.get("pool"):
        pool.stop_all()
    if db := refs.get("db"):
        db.close()
    clear_app_state(app_module.app)
    set_shutting_down(False)


def _evaluate_cdp_output(raw: dict[str, Any], failures: list[str], checks: dict[str, Any]) -> None:
    rt = raw.get("runtime", {})
    http_errs = rt.get("http_errors", []) or []
    js_excs = (rt.get("exceptions", []) or []) + (rt.get("console_errors", []) or [])
    layout = raw.get("layout", {})
    overflows = layout.get("overflows", []) or []
    cls_shifts = layout.get("stability_shifts", layout.get("cls_shifts", [])) or []
    tight_gaps = layout.get("sibling_gap_warnings", []) or []
    dead_btns = layout.get("dead_buttons", []) or []
    dup_btns = layout.get("duplicate_buttons", []) or []
    broken_imgs = layout.get("brokenImageWarnings", []) or []
    squeezed_ctrls = layout.get("squeezedControlWarnings", []) or []
    checks.update(
        http_errors=len(http_errs),
        js_errors=len(js_excs),
        overflows=len(overflows),
        cls_shifts=len(cls_shifts),
        tight_gaps=len(tight_gaps),
        dead_buttons=len(dead_btns),
        duplicate_buttons=len(dup_btns),
        broken_images=len(broken_imgs),
        squeezed_controls=len(squeezed_ctrls),
    )
    for label, items in [
        ("HTTP>=400", http_errs),
        ("JS errors", js_excs),
        ("overflows", overflows),
        ("CLS shifts", cls_shifts),
        ("<4px gaps", tight_gaps),
        ("dead buttons", dead_btns),
        ("duplicate buttons", dup_btns),
        ("broken images", broken_imgs),
        ("squeezed controls", squeezed_ctrls),
    ]:
        if items:
            failures.append(f"CDP {label} ({len(items)}): {items[:3]}")
    sweep = raw.get("sweep") or raw.get("eval", {}).get("value", {}) or {}
    checks["sweep"] = sweep
    _evaluate_sweep(sweep, failures)


def _evaluate_sweep(sweep: dict[str, Any], failures: list[str]) -> None:
    """Validate 9-tab activation, 2x2/3x3/4x4 grid overlay parity, media loads, and modals."""
    tabs = sweep.get("tabs") or {}
    if len(tabs) < 9:
        failures.append(f"Expected 9 SPA tabs in sweep, got {len(tabs)}")
    bad_tabs = [k for k, v in tabs.items() if not v.get("active") or v.get("overflowX")]
    if bad_tabs:
        failures.append(f"SPA tab failures: {bad_tabs}")
    gp = sweep.get("gridParity") or {}
    for mode in ("2x2", "3x3", "4x4"):
        entry = gp.get(mode) or {}
        if not entry.get("active") or not entry.get("overlayMatch"):
            failures.append(f"Multiview {mode} grid/overlay parity failed: {entry}")
    for key, msg in (
        ("heatmapLoaded", "#static-heatmap-img failed to load (naturalWidth==0)"),
        ("alertsReady", "#tab-alerts failed to activate"),
        ("journeyReady", "#tab-journey failed to activate"),
        ("reviewCardReady", "#tab-review card missing bbox/provenance context"),
        ("studioLiveLoaded", "#studio-live-img failed to load (naturalWidth==0)"),
        ("studioOfflineEmptyOk", "#studio offline camera did not show MediaEmptyState / hide broken img"),
        ("recordedSelected", "#studio Recorded Videos selection failed"),
        ("enrollChanged", "#enroll-camera-select change did not render freeze-frame"),
        ("camTableErgonomic", "#modal-camera-manager .data-table horizontally squeezed"),
        ("candidateXNonClosing", "#modal-tag-entity candidate X closed the modal"),
    ):
        if not sweep.get(key):
            failures.append(msg)
    heights = sweep.get("titleHeights") or []
    if len(heights) < 2 or min(heights) <= 0 or len(set(heights)) > 1:
        failures.append(f"Camera title height shift detected: {heights}")
    modals = sweep.get("modals") or {}
    closed_modals = [k for k, ok in modals.items() if not ok]
    if len(modals) < 2 or closed_modals:
        failures.append(f"Modal flow failures: {modals}")


def _parse_cdp_json(stdout: str) -> dict[str, Any]:
    dec = json.JSONDecoder()
    merged: dict[str, Any] = {}
    pos = 0
    while (idx := stdout.find("{", pos)) >= 0:
        obj, end = dec.raw_decode(stdout[idx:])
        if isinstance(obj, dict):
            if "tabs" in obj:
                merged["sweep"] = obj
            else:
                merged.update(obj)
        pos = idx + end
    if not merged:
        raise json.JSONDecodeError("No JSON object found", stdout, 0)
    return merged


def _run_cdp_subprocess(port: int, js_file: Path, failures: list[str], checks: dict[str, Any]) -> None:
    cmd = [
        sys.executable,
        str(DIAGNOSE_PY),
        "ui",
        "--url",
        f"http://127.0.0.1:{port}/",
        "--headless",
        "--capture-runtime",
        "--audit-layout",
        "--stability-ms",
        "2000",
        "--eval-file",
        str(js_file),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=90, check=False)
    checks["cdp_exit_code"] = proc.returncode
    try:
        _evaluate_cdp_output(_parse_cdp_json(proc.stdout or ""), failures, checks)
    except json.JSONDecodeError:
        failures.append(
            f"CDP output not JSON (rc={proc.returncode}): {proc.stdout[:200]} {proc.stderr[:200]}"
        )


def run_probe() -> dict[str, Any]:
    """Run headless Chrome CDP 9-tab + multiview + modal sweep on isolated server."""
    checks: dict[str, Any] = {}
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        js_file = tmp / "sweep.js"
        js_file.write_text(SWEEP_JS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        srv, th, port, refs, orig_init = _start_server(tmp)
        try:
            _run_cdp_subprocess(port, js_file, failures, checks)
        finally:
            _stop_server(srv, th, refs, orig_init)

    status = "error" if failures else "ok"
    summary = (
        f"SPA 9-tab CDP probe: {len(failures)} failure(s)"
        if failures
        else "SPA 9-tab CDP probe passed all checks."
    )
    return {"status": status, "summary": summary, "details": {"checks": checks, "failures": failures}}


if __name__ == "__main__":
    res = run_probe()
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["status"] == "ok" else 1)
