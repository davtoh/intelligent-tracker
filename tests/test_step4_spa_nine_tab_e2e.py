#!/usr/bin/env python3
"""Chrome-gated E2E test for 9-tab SPA, multiview 1x1<->2x2, Zero-CLS HUD, and modals."""

import importlib.util
import os
import shutil
import unittest
from pathlib import Path

from scripts.cdp_inspect import find_chrome_executable

REPO_ROOT = Path(__file__).resolve().parent.parent
PROBE_PATH = REPO_ROOT / ".diagnostics" / "probes" / "spa_nine_tab_cdp_probe.py"
CHROME_EXE = find_chrome_executable()
HAS_CHROME = bool(CHROME_EXE and (os.path.exists(CHROME_EXE) or shutil.which(CHROME_EXE)))


def _load_spa_probe():
    spec = importlib.util.spec_from_file_location("spa_nine_tab_cdp_probe", PROBE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(HAS_CHROME, "Chrome/Edge executable not found for headless CDP E2E")
class TestStep4SpaNineTabE2E(unittest.TestCase):
    """Verify 0 HTTP/JS errors, 0 CLS, 0 overflows, and interactive flows across 9 SPA tabs."""

    def test_spa_nine_tab_and_multiview_e2e(self) -> None:
        probe = _load_spa_probe()
        res = probe.run_probe()
        self.assertEqual(res["status"], "ok", msg=f"Failures: {res['details']['failures']}")
        checks = res["details"]["checks"]
        for key in (
            "http_errors",
            "js_errors",
            "overflows",
            "cls_shifts",
            "tight_gaps",
            "dead_buttons",
            "duplicate_buttons",
        ):
            self.assertEqual(checks[key], 0, msg=f"Expected 0 {key}, got {checks[key]}")
        sweep = checks["sweep"]
        self.assertEqual(len(sweep["tabs"]), 9)
        self.assertTrue(sweep["grid2x2Active"])
        self.assertEqual(len(set(sweep["titleHeights"])), 1)
        self.assertTrue(all(sweep["modals"].values()))


if __name__ == "__main__":
    unittest.main()
