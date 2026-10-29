#!/usr/bin/env python3
"""
Frontier Architect - Cross-Platform, Project-Agnostic CDP Browser Inspector.
Supports Windows, macOS, and Linux across any web application.

Connection Cascade:
1. Attaches to the user's LIVE running Chrome/Chromium instance via `DevToolsActivePort`
   (enabled at `chrome://inspect/#remote-debugging` on Windows, macOS, or Linux).
2. Or connects to an existing `--remote-debugging-port` HTTP endpoint.
3. Or launches an isolated, auto-cleaned temporary headless Chrome instance (`--headless`).

Generic Capabilities:
  --list-tabs                  List open tabs in live Chrome
  --audit-layout               Generic DOM/viewport overflow scan + all <video>, <img>, <canvas> states
  --selectors "#app,.card"     Inspect specific CSS selectors (bounding boxes, styles, media state)
  --click "#submit-btn"        Click an element before auditing/evaluating
  --eval "document.title"      Evaluate arbitrary JS expression and print JSON result
  --screenshot out.jpg         Capture JPEG screenshot of the viewport
"""

import argparse
import asyncio
import base64
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

# Ensure UTF-8 output across Windows, macOS, and Linux terminals
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def find_chrome_executable() -> str:
    """Locate Chrome/Chromium binary across Windows, macOS, and Linux."""
    env_bin = os.environ.get("CHROME_BIN") or os.environ.get("CHROME_PATH")
    if env_bin and os.path.exists(env_bin):
        return env_bin

    system = platform.system().lower()
    candidates = []
    if system == "windows":
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        ]
    elif system == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    else:  # Linux / BSD
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            found = shutil.which(name)
            if found:
                return found

    for c in candidates:
        if os.path.exists(c):
            return c

    return shutil.which("chrome") or shutil.which("google-chrome") or "google-chrome"


def find_devtools_active_port() -> tuple[int, str] | None:
    """Locate Chrome's DevToolsActivePort file across Windows, macOS, and Linux."""
    system = platform.system().lower()
    home = Path.home()
    candidates: list[Path] = []

    if system == "windows":
        local_app_data = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        candidates = [
            local_app_data / "Google" / "Chrome" / "User Data" / "DevToolsActivePort",
            local_app_data / "Google" / "Chrome SxS" / "User Data" / "DevToolsActivePort",
            local_app_data / "Chromium" / "User Data" / "DevToolsActivePort",
        ]
    elif system == "darwin":
        app_support = home / "Library" / "Application Support"
        candidates = [
            app_support / "Google" / "Chrome" / "DevToolsActivePort",
            app_support / "Google" / "Chrome Canary" / "DevToolsActivePort",
            app_support / "Chromium" / "DevToolsActivePort",
        ]
    else:  # Linux
        config_dir = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
        candidates = [
            config_dir / "google-chrome" / "DevToolsActivePort",
            config_dir / "google-chrome-beta" / "DevToolsActivePort",
            config_dir / "chromium" / "DevToolsActivePort",
            home / "snap" / "chromium" / "common" / "chromium" / "DevToolsActivePort",
        ]

    for path in candidates:
        if path.exists():
            try:
                lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
                if len(lines) >= 2:
                    return int(lines[0]), lines[1]
            except Exception:
                pass
    return None


class CDPSession:
    def __init__(self, ws):
        self.ws = ws
        self.msg_id = 0

    async def send(self, method: str, params: dict | None = None, session_id: str | None = None, timeout: float = 15.0) -> dict:
        self.msg_id += 1
        call_id = self.msg_id
        payload = {"id": call_id, "method": method, "params": params or {}}
        if session_id:
            payload["sessionId"] = session_id
        await self.ws.send(json.dumps(payload))

        deadline = time.time() + timeout
        while True:
            remaining = max(0.1, deadline - time.time())
            raw = await asyncio.wait_for(self.ws.recv(), timeout=remaining)
            msg = json.loads(raw)
            if msg.get("id") == call_id:
                if "error" in msg:
                    raise RuntimeError(f"CDP error in {method}: {msg['error']}")
                return msg.get("result", {})


def build_generic_audit_js(custom_selectors: list[str]) -> str:
    selectors_json = json.dumps(custom_selectors)
    return f"""
(() => {{
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const docScrollH = document.documentElement.scrollHeight;
  const docScrollW = document.documentElement.scrollWidth;

  function describeEl(el) {{
    const r = el.getBoundingClientRect();
    const cs = window.getComputedStyle(el);
    const parent = el.parentElement;
    const pr = parent ? parent.getBoundingClientRect() : null;
    const overflowsParent = pr ? (
      Math.round(r.right) > Math.round(pr.right) + 2 ||
      Math.round(r.bottom) > Math.round(pr.bottom) + 2 ||
      Math.round(r.left) < Math.round(pr.left) - 2 ||
      Math.round(r.top) < Math.round(pr.top) - 2
    ) : false;

    const info = {{
      tag: el.tagName.toLowerCase(),
      id: el.id || undefined,
      className: typeof el.className === 'string' && el.className ? el.className.trim().split(/\\s+/).slice(0, 4).join('.') : undefined,
      rect: {{ x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height), bottom: Math.round(r.bottom) }},
      overflowsParent,
      visible: r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden',
      style: {{ display: cs.display, position: cs.position, overflow: cs.overflow, maxHeight: cs.maxHeight, aspectRatio: cs.aspectRatio, objectFit: cs.objectFit }},
    }};
    if (el.tagName === 'VIDEO') {{
      info.video = {{
        src: el.currentSrc || el.src,
        paused: el.paused,
        ended: el.ended,
        currentTime: Number(el.currentTime.toFixed(2)),
        duration: Number((el.duration || 0).toFixed(2)),
        videoWidth: el.videoWidth,
        videoHeight: el.videoHeight,
        readyState: el.readyState,
        error: el.error ? el.error.code : null
      }};
    }} else if (el.tagName === 'IMG') {{
      info.img = {{
        src: el.currentSrc || el.src,
        naturalWidth: el.naturalWidth,
        naturalHeight: el.naturalHeight,
        complete: el.complete
      }};
    }} else if (el.tagName === 'BUTTON' || el.tagName.startsWith('H') || el.tagName === 'SPAN') {{
      info.text = el.textContent.trim().slice(0, 80);
    }}
    return info;
  }}

  const mediaElements = Array.from(document.querySelectorAll('video, img, canvas')).map(describeEl);

  const customSelectors = {selectors_json};
  const queriedSelectors = {{}};
  for (const sel of customSelectors) {{
    const el = document.querySelector(sel);
    queriedSelectors[sel] = el ? describeEl(el) : null;
  }}

  // Automatically detect visible containers that overflow the viewport or clip children
  const layoutOverflowWarnings = [];
  for (const el of document.querySelectorAll('main, section, article, div, aside')) {{
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const cs = window.getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    if (r.right > vw + 4 || (el.scrollHeight > el.clientHeight + 4 && cs.overflowY === 'hidden')) {{
      layoutOverflowWarnings.push({{
        selector: (el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (typeof el.className === 'string' && el.className ? '.' + el.className.trim().split(/\\s+/)[0] : '')),
        rect: {{ width: Math.round(r.width), height: Math.round(r.height), right: Math.round(r.right), bottom: Math.round(r.bottom) }},
        scrollHeight: el.scrollHeight,
        clientHeight: el.clientHeight,
        overflowY: cs.overflowY
      }});
      if (layoutOverflowWarnings.length >= 15) break;
    }}
  }}

  return {{
    title: document.title,
    url: window.location.href,
    viewport: {{
      width: vw,
      height: vh,
      scrollWidth: docScrollW,
      scrollHeight: docScrollH,
      hasVerticalScrollbar: docScrollH > vh,
      hasHorizontalScrollbar: docScrollW > vw
    }},
    mediaElements,
    queriedSelectors: customSelectors.length ? queriedSelectors : undefined,
    layoutOverflowWarnings
  }};
}})()
"""


async def run_against_target(cdp: CDPSession, session_id: str | None, args) -> int:
    await cdp.send("Page.enable", session_id=session_id)
    await cdp.send("Runtime.enable", session_id=session_id)

    if args.navigate:
        await cdp.send("Page.navigate", {"url": args.url}, session_id=session_id)
        await asyncio.sleep(args.wait)
    elif args.wait > 0:
        await asyncio.sleep(args.wait)

    if args.click:
        click_js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(args.click)});
            if (!el) return {{ clicked: false, reason: 'Selector not found' }};
            el.click();
            return {{ clicked: true, text: el.textContent?.trim() }};
        }})()
        """
        res = await cdp.send(
            "Runtime.evaluate",
            {"expression": click_js, "returnByValue": True, "awaitPromise": True},
            session_id=session_id,
        )
        print(json.dumps({"click": res.get("result", {}).get("value")}, indent=2, ensure_ascii=False))
        await asyncio.sleep(0.5)

    custom_sels = [s.strip() for s in args.selectors.split(",") if s.strip()] if args.selectors else []
    if args.audit_layout or custom_sels:
        res = await cdp.send(
            "Runtime.evaluate",
            {"expression": build_generic_audit_js(custom_sels), "returnByValue": True, "awaitPromise": True},
            session_id=session_id,
        )
        print(json.dumps(res.get("result", {}).get("value"), indent=2, ensure_ascii=False))

    if args.eval:
        res = await cdp.send(
            "Runtime.evaluate",
            {"expression": args.eval, "returnByValue": True, "awaitPromise": True},
            session_id=session_id,
        )
        val = res.get("result", {}).get("value", res.get("result"))
        print(json.dumps(val, indent=2, ensure_ascii=False))

    if args.screenshot:
        shot = await cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 85}, session_id=session_id)
        data = shot.get("data")
        if data:
            out_path = Path(args.screenshot)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(base64.b64decode(data))
            print(f"[CDP] Saved screenshot to {out_path.resolve()}")

    return 0


async def main_async(args) -> int:
    try:
        import websockets
    except ImportError:
        print(
            "Error: Python 'websockets' package not installed in active interpreter. "
            "Run `pip install websockets` or invoke with your project's virtualenv Python.",
            file=sys.stderr,
        )
        return 1

    # 1. Try connecting to user's live Chrome via DevToolsActivePort (unless --headless forced)
    if not args.headless:
        active_port = find_devtools_active_port()
        if active_port:
            port, ws_path = active_port
            browser_ws_url = f"ws://127.0.0.1:{port}{ws_path}"
            try:
                print(f"[CDP] Connecting to live Chrome via DevToolsActivePort ({browser_ws_url})...", file=sys.stderr)
                print("[CDP] Note: If Chrome shows an 'Allow remote debugging?' prompt, click 'Allow'.", file=sys.stderr)
                async with websockets.connect(browser_ws_url, max_size=50 * 1024 * 1024, open_timeout=10) as ws:
                    cdp = CDPSession(ws)
                    targets_res = await cdp.send("Target.getTargets", timeout=15.0)
                    pages = [t for t in targets_res.get("targetInfos", []) if t.get("type") == "page"]

                    if args.list_tabs:
                        print(json.dumps(pages, indent=2, ensure_ascii=False))
                        return 0

                    target = None
                    for p in pages:
                        if args.url and args.url.rstrip("/") in p.get("url", ""):
                            target = p
                            break
                    if not target and pages:
                        non_chrome = [p for p in pages if not p.get("url", "").startswith(("chrome://", "devtools://"))]
                        target = non_chrome[0] if non_chrome else pages[0]

                    if not target:
                        create_res = await cdp.send("Target.createTarget", {"url": args.url})
                        target_id = create_res["targetId"]
                    else:
                        target_id = target["targetId"]
                        print(f"[CDP] Attached to live tab: {target.get('title')} ({target.get('url')})", file=sys.stderr)

                    attach_res = await cdp.send("Target.attachToTarget", {"targetId": target_id, "flatten": True})
                    session_id = attach_res["sessionId"]
                    return await run_against_target(cdp, session_id, args)
            except Exception as e:
                print(
                    f"[CDP] Live Chrome connection failed ({e}). "
                    "Ensure 'chrome://inspect/#remote-debugging' -> 'Enable remote debugging' is checked, "
                    "or pass --headless to use an isolated headless browser.",
                    file=sys.stderr,
                )
                if not args.fallback_headless:
                    return 2

    # 2. Headless Chrome with auto-cleaned TemporaryDirectory (zero workspace clutter!)
    chrome_exe = find_chrome_executable()
    port = args.port
    with tempfile.TemporaryDirectory(prefix="agy_cdp_") as tmp_profile:
        width, height = (int(x) for x in args.window_size.lower().split("x"))
        cmd = [
            chrome_exe,
            "--headless=new",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={tmp_profile}",
            f"--window-size={width},{height}",
            "--autoplay-policy=no-user-gesture-required",
            "--disable-gpu",
            "--no-sandbox",
            args.url,
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            ws_url = None
            for _ in range(25):
                await asyncio.sleep(0.3)
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1.0) as resp:
                        tabs = json.loads(resp.read().decode("utf-8"))
                        for t in tabs:
                            if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                                ws_url = t["webSocketDebuggerUrl"]
                                break
                        if ws_url:
                            break
                except Exception:
                    pass

            if not ws_url:
                print("[CDP] Error: Headless Chrome failed to expose debugging WebSocket.", file=sys.stderr)
                return 1

            async with websockets.connect(ws_url, max_size=50 * 1024 * 1024) as ws:
                cdp = CDPSession(ws)
                await cdp.send(
                    "Emulation.setDeviceMetricsOverride",
                    {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False},
                )
                return await run_against_target(cdp, None, args)
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass


def main():
    parser = argparse.ArgumentParser(description="Frontier Architect Cross-Platform CDP Browser Inspector")
    parser.add_argument("--url", default="http://localhost:8000", help="Target URL to match or open")
    parser.add_argument("--list-tabs", action="store_true", help="List open tabs in live Chrome")
    parser.add_argument("--audit-layout", action="store_true", help="Run generic DOM/viewport overflow and media element audit")
    parser.add_argument("--selectors", default=None, help="Comma-separated CSS selectors to inspect (e.g. '#app,.player,video')")
    parser.add_argument("--eval", default=None, help="JavaScript expression to evaluate in target page")
    parser.add_argument("--click", default=None, help="CSS selector to click before auditing/evaluating")
    parser.add_argument("--screenshot", default=None, help="Path to save JPEG screenshot")
    parser.add_argument("--navigate", action="store_true", help="Force navigation to --url even on existing tab")
    parser.add_argument("--wait", type=float, default=1.5, help="Seconds to wait before inspection")
    parser.add_argument("--headless", action="store_true", help="Use isolated auto-cleaned headless Chrome instead of live Chrome")
    parser.add_argument("--no-fallback-headless", dest="fallback_headless", action="store_false", help="Fail instead of falling back to headless if live Chrome is unreachable")
    parser.set_defaults(fallback_headless=True)
    parser.add_argument("--window-size", default="1440x900", help="Window size for headless mode (default: 1440x900)")
    parser.add_argument("--port", type=int, default=9229, help="Port for temporary headless Chrome (default: 9229)")
    args = parser.parse_args()
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
