"""Headless Chrome CDP E2E test for Multiview WS, pagination, 1x1 restore, and fallback."""

import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest

import uvicorn
import websockets

import dashboard.app as app_module
from dashboard.camera_pool import CameraPool
from dashboard.dependencies import bind_app_state, clear_app_state, set_shutting_down
from intelligent_tracker.lifecycle import StreamLifecycleManager
from intelligent_tracker.scenarios import ScenarioManager
from scripts.cdp_inspect import find_chrome_executable

E2E_JS_PATH = Path(__file__).resolve().parent / "helpers" / "multiview_e2e.js"
CHROME_EXE = find_chrome_executable()
HAS_CHROME = bool(CHROME_EXE and (os.path.exists(CHROME_EXE) or shutil.which(CHROME_EXE)))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _seed_isolated_configs(tmp_dir: str) -> tuple[str, str, str]:
    cfg = os.path.join(tmp_dir, "cameras.json")
    db_p = os.path.join(tmp_dir, "e2e_tracker.db")
    scen = os.path.join(tmp_dir, "scenarios.json")
    cams = [
        {"id": f"cam_0{i}", "name": f"Gate {i}", "source": "synthetic", "type": "synthetic",
         "detector": "mock", "tracker": "centroid", "enabled": True}
        for i in range(1, 7)
    ]
    Path(cfg).write_bytes(json.dumps(cams).encode("utf-8"))
    Path(scen).write_bytes(b"{}")
    return cfg, db_p, scen


def _wait_port_file(profile_dir: Path, timeout_s: float = 10.0) -> tuple[int, str]:
    port_file = profile_dir / "DevToolsActivePort"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if port_file.is_file():
            lines = [ln.strip() for ln in port_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
            if len(lines) >= 2:
                return int(lines[0]), lines[1]
        time.sleep(0.1)
    raise TimeoutError("Headless Chrome did not publish DevToolsActivePort")


async def _run_cdp_eval(url: str, js_code: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="it_cdp_", ignore_cleanup_errors=True) as prof:
        cmd = [
            CHROME_EXE, "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={prof}",
            "--window-size=1440,900", "--autoplay-policy=no-user-gesture-required",
            "--disable-gpu", "--no-sandbox", "--no-first-run", "--no-default-browser-check", url,
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            port, ws_path = _wait_port_file(Path(prof))
            async with websockets.connect(f"ws://127.0.0.1:{port}{ws_path}", max_size=20 * 1024 * 1024) as ws:
                return await _eval_on_first_page(ws, js_code)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()


async def _eval_on_first_page(ws, js_code: str) -> dict:
    async def send(msg_id: int, method: str, params: dict | None = None, sid: str | None = None):
        payload = {"id": msg_id, "method": method, "params": params or {}}
        if sid:
            payload["sessionId"] = sid
        await ws.send(json.dumps(payload))
        exceptions = []
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("method") == "Runtime.exceptionThrown":
                exceptions.append(msg.get("params", {}))
            if msg.get("id") == msg_id:
                return msg.get("result", {}), exceptions

    targets, _ = await send(1, "Target.getTargets")
    page = next(t for t in targets["targetInfos"] if t.get("type") == "page" and not t.get("url", "").startswith("about:"))
    sid = (await send(2, "Target.attachToTarget", {"targetId": page["targetId"], "flatten": True}))[0]["sessionId"]
    await send(3, "Runtime.enable", sid=sid)
    await asyncio.sleep(0.5)
    res, excs = await send(4, "Runtime.evaluate", {"expression": js_code, "returnByValue": True, "awaitPromise": True}, sid=sid)
    return {"value": res.get("result", {}).get("value"), "exception": res.get("exceptionDetails"), "runtime_exceptions": excs}


def _start_isolated_server(tmp_dir: str) -> tuple[uvicorn.Server, threading.Thread, int, dict[str, object], object]:
    cfg, db_p, scen = _seed_isolated_configs(tmp_dir)
    refs: dict[str, object] = {}
    orig_init = app_module._init_runtime_services

    def _isolated_init(application):
        pool = CameraPool(config_file=cfg, db_path=db_p, autostart=True)
        sm = pool.primary_stream
        db = sm.db if sm else None
        lm = StreamLifecycleManager(db=db, camera_pool=pool)
        refs.update(pool=pool, db=db)
        bind_app_state(application, camera_pool=pool, stream_manager=sm,
                       scenario_manager=ScenarioManager(config_path=scen), lifecycle_manager=lm, db=db)
        return pool, sm, lm, None

    app_module._init_runtime_services = _isolated_init
    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(app_module.app, host="127.0.0.1", port=port, log_level="error"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    deadline = time.monotonic() + 10.0
    while not srv.started and time.monotonic() < deadline:
        time.sleep(0.05)
    return srv, th, port, refs, orig_init


def _stop_isolated_server(srv: uvicorn.Server, th: threading.Thread, refs: dict[str, object], orig_init: object) -> None:
    srv.should_exit = True
    th.join(timeout=5.0)
    app_module._init_runtime_services = orig_init
    if pool := refs.get("pool"):
        pool.stop_all()
    if db := refs.get("db"):
        db.close()
    clear_app_state(app_module.app)
    set_shutting_down(False)


@unittest.skipUnless(HAS_CHROME, "Chrome/Edge binary required for headless CDP E2E")
class TestMultiviewE2ECDP(unittest.TestCase):
    """End-to-end multiview WebSocket, pagination, 1x1 recovery, and MJPEG fallback check."""

    def test_multiview_lifecycle_and_fallback_in_headless_chrome(self) -> None:
        set_shutting_down(False)
        tmp = tempfile.TemporaryDirectory(prefix="it_mv_e2e_")
        self.addCleanup(tmp.cleanup)
        srv, th, port, refs, orig_init = _start_isolated_server(tmp.name)
        try:
            out = asyncio.run(_run_cdp_eval(f"http://127.0.0.1:{port}/", E2E_JS_PATH.read_text(encoding="utf-8")))
            self.assertIsNone(out["exception"], f"JS exception: {out['exception']}")
            self.assertEqual(out["runtime_exceptions"], [], f"Runtime exceptions: {out['runtime_exceptions']}")
            val = out["value"] or {}
            self.assertTrue(val.get("ok"), f"Unexpected E2E result: {val}")
            self.assertEqual(val.get("fallbackImgCount"), 4)
            self.assertGreater(val.get("initialDims", {}).get("w", 0), 0)
            self.assertGreater(val.get("restoredDims", {}).get("w", 0), 0)
        finally:
            _stop_isolated_server(srv, th, refs, orig_init)
