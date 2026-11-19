"""Node VM unit tests for multiview/protocol.js and multiview/frame_surface.js."""

import base64
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from dashboard.services.multiview.protocol import pack_frame

MV_JS = Path(__file__).resolve().parents[1] / "dashboard" / "static" / "js" / "multiview"
PROTOCOL_JS = MV_JS / "protocol.js"
SURFACE_JS = MV_JS / "frame_surface.js"


def _run_node(script: str) -> dict:
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(proc.stdout)


def _vm_prelude() -> str:
    return (
        "const fs = require('fs'), vm = require('vm');\n"
        f"const protoCode = fs.readFileSync({json.dumps(str(PROTOCOL_JS))}, 'utf8');\n"
        f"const surfCode = fs.readFileSync({json.dumps(str(SURFACE_JS))}, 'utf8');\n"
        "const win = { devicePixelRatio: 1 };\n"
        "const sb = { window: win, TextDecoder, Buffer, DataView, ArrayBuffer, Uint8Array, Math, Number, String, Array, Object, Error, Promise, console };\n"
        "vm.runInNewContext(protoCode, sb);\n"
        "vm.runInNewContext(surfCode, sb);\n"
    )


@unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
class TestMultiviewProtocolAndFrameSurface(unittest.TestCase):
    """Verify binary frame unpacking, wrap-aware seq gating, bitmap cleanup, and ResizeObserver."""

    def test_protocol_unpacks_python_packed_frame_and_wrap_seq(self) -> None:
        packed_b64 = base64.b64encode(
            pack_frame("cam_ü1", 42, 1700000000123, b"\xff\xd8\xff\xd9")
        ).decode("ascii")
        script = _vm_prelude() + (
            f"const u8 = new Uint8Array(Buffer.from({json.dumps(packed_b64)}, 'base64'));\n"
            "const f = win.MultiviewProtocol.parseBinaryFrame(u8);\n"
            "const P = win.MultiviewProtocol;\n"
            "process.stdout.write(JSON.stringify({\n"
            "  v: f.version, k: f.kind, id: f.cameraId, seq: f.seq, ts: f.captureTsMs,\n"
            "  bytes: Array.from(f.payload),\n"
            "  w0: P.isNewerSeq(5, null), w1: P.isNewerSeq(6, 5), w2: P.isNewerSeq(5, 5),\n"
            "  w3: P.isNewerSeq(4, 5), w4: P.isNewerSeq(0, 0xFFFFFFFF), w5: P.isNewerSeq(0xFFFFFFFF, 0),\n"
            "}));\n"
        )
        out = _run_node(script)
        self.assertEqual(out["id"], "cam_ü1")
        self.assertEqual(out["seq"], 42)
        self.assertEqual(out["ts"], 1700000000123)
        self.assertEqual(out["bytes"], [255, 216, 255, 217])
        self.assertEqual([out["w0"], out["w1"], out["w2"], out["w3"], out["w4"], out["w5"]], [True, True, False, False, True, False])

    def test_protocol_rejects_malformed_frames(self) -> None:
        script = _vm_prelude() + (
            "const P = win.MultiviewProtocol;\n"
            "const errs = [];\n"
            "for (const arr of [new Uint8Array(4), new Uint8Array([2,1,0,1,0,0,0,1,0,0,0,0,0,0,0,0,65]), new Uint8Array([1,1,0,10,0,0,0,1,0,0,0,0,0,0,0,0,65])]) {\n"
            "  try { P.parseBinaryFrame(arr); errs.push(false); } catch (_) { errs.push(true); }\n"
            "}\n"
            "process.stdout.write(JSON.stringify({ errs }));\n"
        )
        out = _run_node(script)
        self.assertEqual(out["errs"], [True, True, True])

    def test_frame_surface_drops_stale_async_decode_and_closes_bitmaps(self) -> None:
        script = _vm_prelude() + (
            "const closed = [], drawn = []; let throwDraw = false;\n"
            "const ctx = { fillStyle: '', font: '', textAlign: '', textBaseline: '', fillRect: () => {}, fillText: () => {}, drawImage: (b) => { if (throwDraw) throw new Error('boom'); drawn.push(b.id); } };\n"
            "const canvas = { width: 0, height: 0, clientWidth: 320, clientHeight: 180, getContext: () => ctx };\n"
            "const pending = {};\n"
            "const surf = new win.FrameSurface(canvas, { decodeBitmap: (b) => new Promise((res) => { pending[b[0]] = res; }) });\n"
            "(async () => {\n"
            "  const p1 = surf.pushFrame(new Uint8Array([1]), 1, 100);\n"
            "  const p2 = surf.pushFrame(new Uint8Array([2]), 2, 200);\n"
            "  pending[2]({ id: 'b2', width: 320, height: 180, close: () => closed.push('b2') });\n"
            "  const r2 = await p2;\n"
            "  pending[1]({ id: 'b1', width: 320, height: 180, close: () => closed.push('b1') });\n"
            "  const r1 = await p1;\n"
            "  throwDraw = true;\n"
            "  const p3 = surf.pushFrame(new Uint8Array([3]), 3, 300);\n"
            "  pending[3]({ id: 'b3', width: 320, height: 180, close: () => closed.push('b3') });\n"
            "  const r3 = await p3;\n"
            "  process.stdout.write(JSON.stringify({ r1, r2, r3, drawn, closed, seq: surf.lastDrawnSeq }));\n"
            "})();\n"
        )
        out = _run_node(script)
        self.assertTrue(out["r2"])
        self.assertFalse(out["r1"])
        self.assertFalse(out["r3"])
        self.assertEqual(out["drawn"], ["b2"])
        self.assertEqual(out["closed"], ["b2", "b1", "b3"])
        self.assertEqual(out["seq"], 2)

    def test_frame_surface_dpr_resize_observer_and_status_posters(self) -> None:
        script = _vm_prelude() + (
            "const texts = []; let roCb = null, disconnected = false;\n"
            "sb.ResizeObserver = class { constructor(cb) { roCb = cb; } observe() {} disconnect() { disconnected = true; } };\n"
            "const ctx = { fillStyle: '', font: '', textAlign: '', textBaseline: '', fillRect: () => {}, fillText: (t) => texts.push(t), drawImage: () => {} };\n"
            "let rect = { width: 160, height: 90 };\n"
            "const canvas = { width: 0, height: 0, parentElement: {}, getBoundingClientRect: () => rect, getContext: () => ctx };\n"
            "win.devicePixelRatio = 2;\n"
            "const surf = new win.FrameSurface(canvas, { initialStatus: 'hibernating', decodeBitmap: async () => ({ width: 10, height: 10, close: () => {} }) });\n"
            "rect = { width: 200, height: 100 }; roCb();\n"
            "surf.setStatus('reconnecting', 'retry 1');\n"
            "surf.destroy();\n"
            "(async () => {\n"
            "  const after = await surf.pushFrame(new Uint8Array([1]), 1, 10);\n"
            "  process.stdout.write(JSON.stringify({ w: canvas.width, h: canvas.height, disconnected, after, texts }));\n"
            "})();\n"
        )
        out = _run_node(script)
        self.assertEqual((out["w"], out["h"]), (400, 200))
        self.assertTrue(out["disconnected"])
        self.assertFalse(out["after"])
        self.assertIn("RECONNECTING", out["texts"])
        self.assertIn("retry 1", out["texts"])
