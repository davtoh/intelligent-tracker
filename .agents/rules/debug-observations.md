---
trigger: model_decision
description: Apply when enabling FRONTIER_DEBUG_OBSERVATIONS, running diagnose.py observations or brief commands, debugging with the dev HUD overlay, or triaging OBS-XXX items during audits.
---

# Debug Observation Connector & Local Privacy Rules

## 1. Enabling the Connector (Local Dev Only)
- Enable the Wire Contract v1 routes (`/api/diagnostics/*`) and dev-only HUD overlay (`/api/diagnostics/hud.js`) strictly in local development by setting:
  - PowerShell: `$env:FRONTIER_DEBUG_OBSERVATIONS = "1"`
  - Bash: `FRONTIER_DEBUG_OBSERVATIONS=1`
- **Never** set `FRONTIER_DEBUG_OBSERVATIONS=1` in production configs, Docker production images, or CI defaults. When unset, all `/api/diagnostics/*` routes return `404` and `dashboard/static/index.html` injects nothing.
- **Known v1 Limits**: The HUD records clicks, navigation, console/JS errors, and `fetch`/XHR calls (attaching `X-Debug-Recording-Id` for `DiagnosticTraceMiddleware` trace correlation). WebSocket frames and WebSocket-handler exceptions (`dashboard/routers/multiview.py`) are not captured or stamped in v1.

## 2. Standard Observation & Audit Commands
- **List active observations**: `diagnose.py observations list` (or `--json`, `--kind idea`)
- **Inspect one observation + correlated traces**: `diagnose.py observations show <OBS-ID>`
- **Pull from a running local app**: `diagnose.py observations pull --url http://127.0.0.1:<port>`
- **Single-command audit brief (probes + traces + observations)**: `diagnose.py brief --run-probes --pull http://127.0.0.1:<port>`
- **Verify connector conformance**: `diagnose.py observations verify-connector --url http://127.0.0.1:<port>`
- **Triage & resolve**:
  - `diagnose.py observations triage --id <OBS-ID> --root-cause "..." --missed-by tests,surface --guard "<upgrade>"`
  - `diagnose.py observations resolve --id <OBS-ID> --resolution "..." --commit <sha>`
- **Migrate legacy debug-session notes**: `python scripts/debug_inspect.py --migrate-observations`

## 3. Privacy & Local-Only Invariant
- **Observations never leave the machine**: `.diagnostics/observations.jsonl` and `.diagnostics/observation_catalog.json` are gitignored via `.diagnostics/.gitignore`; never commit observation files or paste sensitive user data into tracked docs/PRs.
- **Loopback & Redaction**: Routes accept loopback clients (`127.0.0.1`, `::1`) only (`403` otherwise), cap payloads at 64 KB, never store request/response bodies, and redact `value`, `password`, `authorization`, and `cookie` keys server-side at any depth.
