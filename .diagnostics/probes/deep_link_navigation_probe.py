#!/usr/bin/env python3
"""Diagnostic Probe: deep_link_navigation_probe.

Verifies App.navigate(tab, SourceRef) handlers and cross-tab jump target IDs
across dashboard/static/ HTML and JS modules.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = REPO_ROOT / "dashboard" / "static"


def run_probe() -> dict[str, Any]:
    """Check App.navigate() targets against HTML tab IDs and SourceRef handlers."""
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

    status = "error" if failures else "ok"
    summary = f"Deep-link navigation probe: {len(failures)} failure(s)" if failures else f"Deep-link navigation probe passed ({checked} call sites)."
    return {"status": status, "summary": summary, "details": {"checked_calls": checked, "failures": failures}}


if __name__ == "__main__":
    res = run_probe()
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["status"] == "ok" else 1)
