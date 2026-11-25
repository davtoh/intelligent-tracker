#!/usr/bin/env python3
"""Diagnostic Probe: effective_config_probe.

Verifies deep_merge(default.yaml, override) with explicit null clearing classes,
ReidProfile SSOT resolution, and opt-in demo config isolation.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def run_probe() -> dict[str, Any]:
    """Verify effective config merge, ReidProfile SSOT, and demo config opt-in."""
    from dashboard.services.base_config_resolver import DEFAULT_CONFIG_PATH, DEMO_CONFIG_PATH, resolve_base_config_path
    from intelligent_tracker.config_merge import deep_merge
    from intelligent_tracker.reid.profile import CANONICAL_REID_DIM, CANONICAL_REID_MODEL, resolve_reid_profile

    failures: list[str] = []
    merged = deep_merge({"tracker": {"classes": [0, 2], "conf": 0.5}}, {"tracker": {"classes": None}})
    if merged.get("tracker", {}).get("classes") is not None or merged.get("tracker", {}).get("conf") != 0.5:
        failures.append(f"deep_merge failed to clear classes with null: {merged}")

    prof = resolve_reid_profile({"reid": {"model": "osnet"}})
    if prof.model_name != CANONICAL_REID_MODEL or prof.expected_dim != CANONICAL_REID_DIM or not prof.is_canonical:
        failures.append(f"ReidProfile SSOT mismatch: {prof}")

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("IT_LOAD_DEMO_SCENARIOS", None)
        os.environ.pop("TRACKER_CONFIG", None)
        if resolve_base_config_path() != DEFAULT_CONFIG_PATH:
            failures.append("Default config path did not resolve to configs/default.yaml")
        os.environ["IT_LOAD_DEMO_SCENARIOS"] = "1"
        if resolve_base_config_path() != DEMO_CONFIG_PATH:
            failures.append("Opt-in demo config path did not resolve to configs/alert_demo.yaml")

    status = "error" if failures else "ok"
    summary = f"Effective config probe: {len(failures)} failure(s)" if failures else "Effective config & ReidProfile SSOT passed."
    return {"status": status, "summary": summary, "details": {"failures": failures}}


if __name__ == "__main__":
    res = run_probe()
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["status"] == "ok" else 1)
