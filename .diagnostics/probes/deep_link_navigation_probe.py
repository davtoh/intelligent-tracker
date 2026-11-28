#!/usr/bin/env python3
"""Diagnostic Probe: deep_link_navigation_probe.

Verifies App.navigate(tab, SourceRef) handlers and cross-tab jump target IDs
across dashboard/static/ HTML and JS modules.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = REPO_ROOT / "dashboard" / "static"


def _verify_live_to_studio_nav_click() -> list[str]:
    """Simulate reloading on #live, clicking the #studio .nav-tab, and asserting Studio media attaches."""
    if not shutil.which("node"):
        return ["Node.js not found; cannot execute #live -> #studio .nav-tab DOM click verification"]
    js_dir = STATIC_DIR / "js"
    script = (
        "const fs = require('fs'), vm = require('vm');\n"
        f"const hCode = fs.readFileSync({json.dumps(str(js_dir / 'app_ui_helpers.js'))}, 'utf8');\n"
        f"const aCode = fs.readFileSync({json.dumps(str(STATIC_DIR / 'app.js'))}, 'utf8');\n"
        f"const nCode = fs.readFileSync({json.dumps(str(js_dir / 'nav_tabs_manager.js'))}, 'utf8');\n"
        f"const mCode = fs.readFileSync({json.dumps(str(js_dir / 'studio_media.js'))}, 'utf8');\n"
        f"const sCode = fs.readFileSync({json.dumps(str(STATIC_DIR / 'studio.js'))}, 'utf8');\n"
        "const listeners = {}, drawCalls = [];\n"
        "const mkCls = (init = []) => { const s = new Set(init); return { add: (c) => s.add(c), remove: (c) => s.delete(c), toggle: (c, v) => v ? s.add(c) : s.delete(c), contains: (c) => s.has(c) }; };\n"
        "const mkTab = (id, active) => { const fns = []; return { id, getAttribute: (k) => k === 'data-tab' ? id : null, classList: mkCls(active ? ['active'] : []), addEventListener: (e, cb) => fns.push(cb), click: () => fns.forEach((f) => f()) }; };\n"
        "const tLive = mkTab('tab-live', true), tStudio = mkTab('tab-studio', false);\n"
        "const pLive = mkTab('tab-live', true), pStudio = mkTab('tab-studio', false);\n"
        "const studioImg = { id: 'studio-live-img', src: '', hidden: true, style: { display: 'none' }, dataset: {}, removeAttribute: (a) => { if (a === 'hidden') studioImg.hidden = false; if (a === 'src') studioImg.src = ''; }, addEventListener: (e, cb) => { (listeners['img:' + e] ||= []).push(cb); } };\n"
        "const studioCanvas = { id: 'studio-canvas', width: 640, height: 360, style: {}, getContext: () => ({ clearRect: () => { drawCalls.push('clear'); } }) };\n"
        "const studioSel = { id: 'studio-camera-select', value: 'cam_01', innerHTML: '', options: [{ value: 'cam_01', parentElement: { label: 'Live Cameras' } }], selectedOptions: [{ parentElement: { label: 'Live Cameras' } }], addEventListener: () => {}, appendChild: () => {} };\n"
        "const els = { 'tab-live': pLive, 'tab-studio': pStudio, 'studio-live-img': studioImg, 'studio-canvas': studioCanvas, 'studio-camera-select': studioSel };\n"
        "const doc = { readyState: 'complete', hidden: false, getElementById: (id) => els[id] || null, querySelector: () => null, querySelectorAll: (s) => s === '.nav-tab' ? [tLive, tStudio] : (s === '.tab-pane' ? [pLive, pStudio] : []), createElement: () => ({ style: {}, dataset: {}, classList: mkCls(), appendChild: () => {} }), addEventListener: (e, cb) => { (listeners[e] ||= []).push(cb); } };\n"
        "const win = { location: { hash: '#live' }, scrollX: 0, scrollTo: () => {}, history: { pushState: () => {} }, addEventListener: (e, cb) => { (listeners[e] ||= []).push(cb); }, dispatchEvent: (ev) => { (listeners[ev.type] || []).forEach((f) => f(ev)); }, StudioCanvas: { drawOverlay: () => drawCalls.push('overlay'), initEvents: () => {}, attachStudioMedia: (...args) => win.StudioMedia.attachStudioMedia(...args) } };\n"
        "class CustomEvent { constructor(t, o) { this.type = t; this.detail = o?.detail; } }\n"
        "const fakeFetch = async (url) => ({ ok: true, json: async () => url.includes('/api/cameras') ? { cameras: [{ id: 'cam_01', name: 'Cam 1', status: 'online' }] } : { videos: [], zones: [], tripwires: [], links: [] } });\n"
        "const sb = { window: win, document: doc, history: win.history, CustomEvent, fetch: fakeFetch, console, Math, Number, String, Boolean, Array, Object, JSON, Promise, setTimeout, clearTimeout, setInterval: () => 1, clearInterval: () => {} };\n"
        "vm.runInNewContext(hCode, sb); vm.runInNewContext(aCode, sb); vm.runInNewContext(mCode, sb); vm.runInNewContext(sCode, sb);\n"
        "(async () => {\n"
        "  (listeners.DOMContentLoaded || []).forEach((f) => f());\n"
        "  vm.runInNewContext(nCode, sb);\n"
        "  await new Promise((r) => setTimeout(r, 20));\n"
        "  tStudio.click();\n"
        "  (listeners['img:load'] || []).forEach((f) => f());\n"
        "  process.stdout.write(JSON.stringify({ src: studioImg.src, display: studioImg.style.display, hidden: studioImg.hidden, drawCount: drawCalls.length }));\n"
        "})();\n"
    )
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False, timeout=20)
    if proc.returncode != 0:
        return [f"Live->Studio nav click check crashed: {proc.stderr.strip()}"]
    data = json.loads(proc.stdout.strip())
    errs: list[str] = []
    if not str(data.get("src", "")).startswith("/stream/cam_01") or "annotated=false" not in str(data.get("src", "")):
        errs.append(f"Studio media did not attach clean ?annotated=false live stream on .nav-tab click: src={data.get('src')!r}")
    if data.get("display") != "block" or data.get("hidden"):
        errs.append(f"Studio media remained hidden on .nav-tab click: display={data.get('display')!r}, hidden={data.get('hidden')!r}")
    if int(data.get("drawCount", 0)) < 1:
        errs.append("Studio canvas did not redraw after .nav-tab click and image load")
    return errs


def run_probe() -> dict[str, Any]:
    """Check App.navigate() targets against HTML tab IDs, SourceRef handlers, and #live->#studio click."""
    failures: list[str] = []
    nav_js = (STATIC_DIR / "js" / "app_navigation.js").read_text(encoding="utf-8")
    for required_tab in ("tab-live", "tab-studio", "tab-analytics", "tab-videos", "tab-timeline", "tab-alerts"):
        if required_tab not in nav_js:
            failures.append(f"app_navigation.js missing SourceRef handler for {required_tab}")

    contracts = {
        "js/active_source_context.js": ["bindFreezeToggle", "checkAvailability", "showUnavailable"],
        "js/video_timeline_links.js": ["buildSourceJumpButtonsHtml", "handleSourceJumpClick"],
        "js/journey_search.js": ["buildSourceJumpButtonsHtml", "handleThumbError"],
        "review_and_rsac.js": ["buildSourceJumpButtonsHtml", "review-run-pill"],
        "partials/modals/entity_modals.html": ["btn-enroll-live-toggle"],
        "partials/tabs/studio.html": ["btn-studio-freeze-toggle"],
        "partials/tabs/analytics.html": ["analytics-source-select"],
    }
    for rel, tokens in contracts.items():
        text = (STATIC_DIR / rel).read_text(encoding="utf-8", errors="replace")
        for tok in tokens:
            if tok not in text:
                failures.append(f"{rel} missing required contract symbol/id '{tok}'")

    html_ids: set[str] = set()
    for hp in STATIC_DIR.rglob("*.html"):
        html_ids.update(re.findall(r"""\bid=["']([a-zA-Z0-9_\-]+)["']""", hp.read_text(encoding="utf-8", errors="replace")))

    nav_pat = re.compile(r"""\bApp\.navigate\s*\(\s*['"]([a-zA-Z0-9_\-]+)['"]""")
    checked = 0
    for jp in STATIC_DIR.rglob("*.js"):
        for target in nav_pat.findall(jp.read_text(encoding="utf-8", errors="replace")):
            checked += 1
            if target not in html_ids:
                failures.append(f"App.navigate('{target}') in {jp.name} targets missing HTML ID")

    if checked == 0:
        failures.append("No App.navigate(...) call sites discovered in dashboard/static/")

    failures.extend(_verify_live_to_studio_nav_click())

    status = "error" if failures else "ok"
    summary = f"Deep-link navigation probe: {len(failures)} failure(s)" if failures else f"Deep-link navigation probe passed ({checked} call sites + #live->#studio click)."
    return {"status": status, "summary": summary, "details": {"checked_calls": checked, "failures": failures}}


if __name__ == "__main__":
    res = run_probe()
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["status"] == "ok" else 1)
