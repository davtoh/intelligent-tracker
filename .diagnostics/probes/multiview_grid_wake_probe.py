#!/usr/bin/env python3
"""Diagnostic Probe: multiview_grid_wake_probe.

Boots an isolated CameraPool in focus_only mode, subscribes a MultiviewSession
for a 2x2 grid, and asserts the woken stream immediately clears _is_hibernating
and emits source_status == 'online' (OBS-002).
"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class _CaptureWebSocket:
    """Minimal in-memory WebSocket stub capturing JSON/binary frames sent by MultiviewSession."""

    def __init__(self) -> None:
        self.json_messages: list[dict[str, Any]] = []
        self.binary_frames: list[bytes] = []

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.json_messages.append(payload)

    async def send_text(self, text: str) -> None:
        self.json_messages.append(json.loads(text))

    async def send_bytes(self, data: bytes) -> None:
        self.binary_frames.append(data)

    async def close(self, code: int = 1000) -> None:
        return None


def _write_synth_mp4(path: Path) -> bytes:
    import cv2
    import numpy as np

    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (320, 240))  # type: ignore[attr-defined]
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    cv2.rectangle(frame, (30, 30), (140, 180), (40, 200, 120), -1)
    try:
        for _ in range(5):
            writer.write(frame)
    finally:
        writer.release()
    return cv2.imencode(".jpg", frame)[1].tobytes()


async def _run_multiview_wake(pool: Any, jpeg_bytes: bytes) -> dict[str, Any]:
    from dashboard.services.multiview.session import MultiviewSession

    ws = _CaptureWebSocket()
    session = MultiviewSession(ws, pool)
    try:
        for cid in ("cam_01", "cam_02"):
            mgr = pool.get_stream(cid)
            if mgr is not None:
                mgr._running = True
                mgr._latest_raw_jpeg = jpeg_bytes
                mgr._latest_jpeg = jpeg_bytes
        cam2 = pool.get_stream("cam_02")
        assert cam2 is not None
        cam2._is_hibernating = True
        with cam2._lock:
            cam2._latest_telemetry["status"] = "hibernating"

        await session._handle_control({
            "action": "subscribe",
            "layout": "2x2",
            "cameras": ["cam_01", "cam_02"],
            "max_fps": 10,
            "max_width": 640,
        })
        mgr, tier = session._active["cam_02"]
        await session._flush_camera("cam_02", mgr, tier)

        queued = list(getattr(session._sender, "_json_msgs", [])) + list(getattr(session._sender, "_json_queue", [])) + ws.json_messages
        statuses = [
            m.get("status")
            for m in queued
            if isinstance(m, dict) and m.get("type") == "source_status" and m.get("camera_id") == "cam_02"
        ]
        if not statuses and session._last_status.get("cam_02"):
            statuses.append(session._last_status["cam_02"])
        return {
            "cam2_is_hibernating": bool(cam2.is_hibernating),
            "cam2_telemetry_status": cam2._latest_telemetry.get("status"),
            "cam2_last_status": session._last_status.get("cam_02"),
            "cam2_source_statuses": statuses,
        }
    finally:
        session._stopped = True
        session._release_all_leases()


def run_probe() -> dict[str, Any]:
    """Boot isolated CameraPool in focus_only and verify 2x2 MultiviewSession wake."""
    from dashboard.camera_pool import CameraPool
    from dashboard.services.processing_mode_service import ProcessingModeService

    failures: list[str] = []
    details: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="it_mv_wake_") as tmp_str:
        tmp = Path(tmp_str)
        mp4 = tmp / "synth.mp4"
        jpeg_bytes = _write_synth_mp4(mp4)
        cfg_path = tmp / "cameras.json"
        cfg_path.write_text(json.dumps([
            {"id": "cam_01", "name": "Cam 1", "source": str(mp4), "enabled": True},
            {"id": "cam_02", "name": "Cam 2", "source": str(mp4), "enabled": True},
        ]), encoding="utf-8")
        db_path = tmp / "tracker.db"
        mode_svc = ProcessingModeService(mode="focus_only", focused_camera_id="cam_01")
        pool = CameraPool(
            config_file=str(cfg_path),
            db_path=str(db_path),
            autostart=False,
        )
        for cid in ("cam_01", "cam_02"):
            stream = pool.get_stream(cid)
            if stream is not None:
                stream._processing_mode_service = mode_svc
        try:
            details = asyncio.run(_run_multiview_wake(pool, jpeg_bytes))
            if details.get("cam2_is_hibernating"):
                failures.append("cam_02 remained _is_hibernating=True after MultiviewSession 2x2 subscribe")
            if details.get("cam2_telemetry_status") != "online":
                failures.append(f"Expected cam_02 telemetry status 'online', got {details.get('cam2_telemetry_status')!r}")
            if "online" not in (details.get("cam2_source_statuses") or []):
                failures.append(f"MultiviewSession did not emit source_status=='online' for cam_02: {details.get('cam2_source_statuses')}")
        finally:
            pool.stop_all()
            if getattr(pool, "_db", None) is not None:
                pool._db.close()

    status = "error" if failures else "ok"
    summary = (
        f"Multiview grid wake probe failed ({len(failures)} issue(s))"
        if failures
        else "Multiview grid wake probe passed (focus_only -> 2x2 cleared hibernation & emitted online)."
    )
    return {"status": status, "summary": summary, "details": {**details, "failures": failures}}


if __name__ == "__main__":
    res = run_probe()
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["status"] == "ok" else 1)
