"""Node VM unit & integration tests for MultiviewWsClient, CameraGrid WS/fallback, and armed-paused UI."""

import json
from pathlib import Path
import shutil
import subprocess
import unittest

STATIC_JS = Path(__file__).resolve().parents[1] / "dashboard" / "static" / "js"
MV_JS = STATIC_JS / "multiview"


def _run_node(script: str) -> dict:
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(proc.stdout)


def _client_vm_prelude() -> str:
    return (
        "const fs = require('fs'), vm = require('vm');\n"
        "const timers = new Map(); let nextTid = 1; const sockets = [];\n"
        "const setTimer = (fn, ms) => { const id = nextTid++; timers.set(id, { id, ms, fn: () => { timers.delete(id); fn(); } }); return id; };\n"
        "const clearTimer = (id) => { timers.delete(id); };\n"
        "const docListeners = {}, winListeners = {};\n"
        "const doc = { hidden: false, addEventListener: (t, fn) => { (docListeners[t] ||= []).push(fn); } };\n"
        "const win = { location: { protocol: 'http:', host: 'edge.local' }, addEventListener: (t, fn) => { (winListeners[t] ||= []).push(fn); } };\n"
        "function wsFactory(url) {\n"
        "  const ws = { url, readyState: 0, sent: [], closedWith: null,\n"
        "    send: (m) => ws.sent.push(JSON.parse(m)),\n"
        "    close: (c, r) => { ws.readyState = 3; ws.closedWith = { c, r }; } };\n"
        "  sockets.push(ws); return ws;\n"
        "}\n"
        "const sb = { window: win, document: doc, setTimeout: setTimer, clearTimeout: clearTimer, encodeURIComponent, TextDecoder, DataView, ArrayBuffer, Uint8Array, Math, Number, String, Array, Object, Error, JSON, Promise, console };\n"
        f"vm.runInNewContext(fs.readFileSync({json.dumps(str(MV_JS / 'protocol.js'))}, 'utf8'), sb);\n"
        f"vm.runInNewContext(fs.readFileSync({json.dumps(str(MV_JS / 'multiview_client.js'))}, 'utf8'), sb);\n"
    )


def _grid_ws_vm_prelude() -> str:
    files = [
        STATIC_JS / "grid_pagination.js",
        MV_JS / "protocol.js",
        MV_JS / "frame_surface.js",
        MV_JS / "multiview_client.js",
        STATIC_JS / "live_player.js",
        STATIC_JS / "camera_grid.js",
    ]
    loads = "\n".join(f"vm.runInNewContext(fs.readFileSync({json.dumps(str(p))}, 'utf8'), sb);" for p in files)
    return (
        "const fs = require('fs'), vm = require('vm');\n"
        "const timers = new Map(); let nextTid = 1; const sockets = [];\n"
        "let gridHtml = ''; const ctx = { fillStyle:'', font:'', textAlign:'', textBaseline:'', fillRect:()=>{}, fillText:()=>{}, drawImage:()=>{} };\n"
        "const mkCanvas = (cid) => ({ width:0, height:0, clientWidth:320, clientHeight:180, getAttribute:(k)=>(k==='data-camera-id'?cid:''), getContext:()=>ctx });\n"
        "const multiGrid = { style:{}, className:'', get innerHTML(){return gridHtml;}, set innerHTML(v){gridHtml=v;},\n"
        "  querySelectorAll:(s)=> s==='canvas.tile-canvas' ? [...gridHtml.matchAll(/data-camera-id=\"([^\"]+)\"/g)].map(m=>mkCanvas(m[1])) : (s==='img' ? [...gridHtml.matchAll(/<img /g)].map(()=>({src:'/stream/x',dataset:{}})) : []) };\n"
        "const liveImg = { src:'', dataset:{} }, bar = { hidden:true }, degBadge = { hidden:true }, ind = { textContent:'' }, btnP = { disabled:false, dataset:{}, addEventListener:()=>{} }, btnN = { disabled:false, dataset:{}, addEventListener:()=>{} };\n"
        "const elems = { 'multi-grid-container':multiGrid, 'video-wrapper':{style:{}}, 'live-stream-img':liveImg, 'grid-pagination-bar':bar, 'grid-degraded-badge':degBadge, 'grid-page-indicator':ind, 'btn-grid-prev':btnP, 'btn-grid-next':btnN };\n"
        "const doc = { hidden:false, getElementById:(id)=>elems[id]||null, querySelectorAll:()=>[], addEventListener:()=>{} };\n"
        "function FakeWS(url){ this.url=url; this.readyState=0; this.sent=[]; this.send=(m)=>this.sent.push(JSON.parse(m)); this.close=()=>{this.readyState=3;}; sockets.push(this); }\n"
        "const win = { location:{protocol:'http:',host:'edge.local'}, devicePixelRatio:1, WebSocket:FakeWS, dispatchEvent:()=>{}, addEventListener:()=>{}, App:{getActiveCameraId:()=>'c0'} };\n"
        "const setT=(fn,ms)=>{const id=nextTid++; timers.set(id,{id,ms,fn:()=>{timers.delete(id);fn();}}); return id;}; const clrT=(id)=>timers.delete(id);\n"
        "const sb = { window:win, document:doc, WebSocket:FakeWS, Event:function(t){this.type=t;}, setTimeout:setT, clearTimeout:clrT, Date, encodeURIComponent, TextDecoder, DataView, ArrayBuffer, Uint8Array, Math, Number, String, Array, Object, Error, JSON, Promise, console };\n"
        + loads + "\n"
    )


@unittest.skipUnless(shutil.which("node"), "Node.js is required for JS VM verification")
class TestMultiviewClientAndGridIntegration(unittest.TestCase):
    """Verify MultiviewWsClient lifecycle, fallback/restore, grid wiring, and armed-paused UI."""

    def test_lazy_connect_replace_set_subscribe_and_idle_close(self) -> None:
        script = _client_vm_prelude() + (
            "const client = new win.MultiviewWsClientClass({ url: 'ws://x/ws/multiview', wsFactory, win, doc, setTimer, clearTimer });\n"
            "const lazyCount = sockets.length;\n"
            "client.subscribe(['c1', 'c2'], '2x2');\n"
            "sockets[0].readyState = 1; sockets[0].onopen();\n"
            "client.subscribe(['c3'], '3x3');\n"
            "client.unsubscribeAll();\n"
            "const idleT = Array.from(timers.values())[0];\n"
            "idleT.fn();\n"
            "process.stdout.write(JSON.stringify({ lazyCount, sockCount: sockets.length, sent: sockets[0].sent, idleMs: idleT.ms, closed: sockets[0].closedWith }));\n"
        )
        out = _run_node(script)
        self.assertEqual(out["lazyCount"], 0)
        self.assertEqual(out["sockCount"], 1)
        self.assertEqual([m["action"] for m in out["sent"]], ["subscribe", "subscribe", "unsubscribe_all"])
        self.assertEqual(out["sent"][1]["cameras"], ["c3"])
        self.assertEqual(out["idleMs"], 30000)
        self.assertEqual(out["closed"], {"c": 1000, "r": "idle"})

    def test_visibility_pause_resume_and_pagehide_close(self) -> None:
        script = _client_vm_prelude() + (
            "const client = new win.MultiviewWsClientClass({ url: 'ws://x/ws/multiview', wsFactory, win, doc, setTimer, clearTimer });\n"
            "client.subscribe(['c1'], '2x2');\n"
            "sockets[0].readyState = 1; sockets[0].onopen();\n"
            "doc.hidden = true; docListeners.visibilitychange.forEach(fn => fn());\n"
            "doc.hidden = false; docListeners.visibilitychange.forEach(fn => fn());\n"
            "winListeners.pagehide.forEach(fn => fn());\n"
            "process.stdout.write(JSON.stringify({ sent: sockets[0].sent.map(m => m.action), closed: sockets[0].closedWith, pendingTimers: timers.size }));\n"
        )
        out = _run_node(script)
        self.assertEqual(out["sent"], ["subscribe", "pause", "resume"])
        self.assertEqual(out["closed"], {"c": 1000, "r": "pagehide"})
        self.assertEqual(out["pendingTimers"], 0)

    def test_three_failure_fallback_backoff_and_auto_restore(self) -> None:
        script = _client_vm_prelude() + (
            "const changes = [], delays = [];\n"
            "const client = new win.MultiviewWsClientClass({ url: 'ws://x/ws/multiview', wsFactory, win, doc, setTimer, clearTimer, onTransportChange: (m) => changes.push(m) });\n"
            "client.subscribe(['c1', 'c2'], '3x3');\n"
            "for (let i = 0; i < 3; i++) {\n"
            "  sockets[i].onclose({ code: 1006 });\n"
            "  const t = Array.from(timers.values()).pop(); delays.push(t.ms); t.fn();\n"
            "}\n"
            "const degAfter3 = client.isDegraded();\n"
            "sockets[3].readyState = 1; sockets[3].onopen();\n"
            "process.stdout.write(JSON.stringify({ degAfter3, degNow: client.isDegraded(), changes, delays, restoredSent: sockets[3].sent }));\n"
        )
        out = _run_node(script)
        self.assertTrue(out["degAfter3"])
        self.assertFalse(out["degNow"])
        self.assertEqual(out["changes"], ["mjpeg-fallback", "ws"])
        self.assertEqual(out["delays"], [1000, 2000, 4000])
        self.assertEqual(out["restoredSent"][0]["cameras"], ["c1", "c2"])

    def test_close_1013_retryable_no_immediate_fallback(self) -> None:
        script = _client_vm_prelude() + (
            "const client = new win.MultiviewWsClientClass({ url: 'ws://x/ws/multiview', wsFactory, win, doc, setTimer, clearTimer });\n"
            "client.subscribe(['c1'], '2x2');\n"
            "sockets[0].onclose({ code: 1013 }); const d1 = client.isDegraded();\n"
            "Array.from(timers.values())[0].fn(); sockets[1].onclose({ code: 1013 }); const d2 = client.isDegraded();\n"
            "Array.from(timers.values())[0].fn(); sockets[2].onclose({ code: 1013 }); const d3 = client.isDegraded();\n"
            "process.stdout.write(JSON.stringify({ d1, d2, d3, timers: timers.size }));\n"
        )
        out = _run_node(script)
        self.assertFalse(out["d1"])
        self.assertFalse(out["d2"])
        self.assertTrue(out["d3"])
        self.assertEqual(out["timers"], 1)

    def test_camera_grid_ws_canvas_fallback_restore_and_tab_unsubscribe(self) -> None:
        script = _grid_ws_vm_prelude() + (
            "const cams = Array.from({length:6}, (_,i)=>({id:'c'+i, name:'C'+i, status:'online'}));\n"
            "win.CameraGrid.setGridMode('3x3', cams, 'c0', ()=>{});\n"
            "const wsC = (gridHtml.match(/<canvas /g)||[]).length, wsI = (gridHtml.match(/<img /g)||[]).length, b1 = degBadge.hidden;\n"
            "for (let i=0; i<3; i++) { sockets[i].onclose({code:1006}); Array.from(timers.values()).pop().fn(); }\n"
            "const fbCls = multiGrid.className, fbI = (gridHtml.match(/<img /g)||[]).length, b2 = degBadge.hidden;\n"
            "sockets[3].readyState = 1; sockets[3].onopen();\n"
            "const rCls = multiGrid.className, rC = (gridHtml.match(/<canvas /g)||[]).length, b3 = degBadge.hidden;\n"
            "win.LivePlayer.syncTabStreams('tab-live', 'tab-videos');\n"
            "process.stdout.write(JSON.stringify({ wsC, wsI, b1, fbCls, fbI, b2, rCls, rC, b3, lastAct: sockets[3].sent.map(x=>x.action) }));\n"
        )
        out = _run_node(script)
        self.assertEqual((out["wsC"], out["wsI"], out["b1"]), (6, 0, True))
        self.assertIn("grid-2x2", out["fbCls"])
        self.assertEqual((out["fbI"], out["b2"]), (4, False))
        self.assertIn("grid-3x3", out["rCls"])
        self.assertEqual((out["rC"], out["b3"]), (6, True))
        self.assertEqual(out["lastAct"], ["subscribe", "unsubscribe_all"])

    def test_paused_overlay_shows_armed_cameras_paused(self) -> None:
        pm_js = STATIC_JS / "processing_mode.js"
        script = (
            "const fs = require('fs'), vm = require('vm');\n"
            "const els = { 'live-paused-overlay': { hidden: true }, 'live-paused-subtitle': { textContent: '' } };\n"
            "const doc = { readyState: 'complete', hidden: false, getElementById: (id) => els[id] || null, addEventListener: () => {} };\n"
            "const win = { addEventListener: () => {}, localStorage: { getItem: () => null, setItem: () => {} } };\n"
            "const fakeFetch = async () => ({ ok: true, json: async () => ({ mode: 'paused', cameras: { a: { is_armed: true, should_hibernate: true }, b: { is_armed: true, should_hibernate: true }, c: { is_armed: false, should_hibernate: true } } }) });\n"
            "vm.runInNewContext(fs.readFileSync(" + json.dumps(str(pm_js)) + ", 'utf8'), { window: win, document: doc, fetch: fakeFetch, Set, Array, Object, String, Number, Boolean, JSON, Promise, console });\n"
            "(async () => { for (let i=0; i<6; i++) await Promise.resolve(); process.stdout.write(JSON.stringify({ h: els['live-paused-overlay'].hidden, sub: els['live-paused-subtitle'].textContent })); })();\n"
        )
        out = _run_node(script)
        self.assertFalse(out["h"])
        self.assertIn("2 armed cameras paused", out["sub"])

    def test_default_timers_avoid_webidl_illegal_invocation(self) -> None:
        script = (
            "const fs = require('fs'), vm = require('vm');\n"
            "const calls = []; const sockets = [];\n"
            "function strictSet(fn, ms) { 'use strict'; if (this !== undefined && this !== sb) throw new TypeError('Illegal invocation'); calls.push('set:' + ms); return 99; }\n"
            "function strictClr(id) { 'use strict'; if (this !== undefined && this !== sb) throw new TypeError('Illegal invocation'); calls.push('clr:' + id); }\n"
            "const win = { location: { protocol: 'http:', host: 'edge.local' }, addEventListener: () => {} };\n"
            "const doc = { hidden: false, addEventListener: () => {} };\n"
            "function wsFactory(u) { const w = { url: u, readyState: 1, send: () => {}, close: () => {} }; sockets.push(w); return w; }\n"
            "const sb = { window: win, document: doc, setTimeout: strictSet, clearTimeout: strictClr, TypeError, encodeURIComponent, TextDecoder, DataView, ArrayBuffer, Uint8Array, Math, Number, String, Array, Object, Error, JSON, Promise, console };\n"
            f"vm.runInNewContext(fs.readFileSync({json.dumps(str(MV_JS / 'protocol.js'))}, 'utf8'), sb);\n"
            f"vm.runInNewContext(fs.readFileSync({json.dumps(str(MV_JS / 'multiview_client.js'))}, 'utf8'), sb);\n"
            "const c = new win.MultiviewWsClientClass({ url: 'ws://x/ws/multiview', wsFactory, win, doc });\n"
            "c.subscribe(['c1'], '2x2'); c.unsubscribeAll(); c.close();\n"
            "process.stdout.write(JSON.stringify({ calls }));\n"
        )
        out = _run_node(script)
        self.assertEqual(out["calls"], ["set:30000", "clr:99"])
