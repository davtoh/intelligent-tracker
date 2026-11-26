# Intelligent Tracker: Adopt Universal Debug Observation Connector & `FOR AUDITS` Auto-Ingestion

Adopts the standardized `system-diagnostics` Observation Connector, DevTools HUD (Pick Element + Record/Stop + Soft Pause), and `OBS-001` triage lifecycle inside `intelligent_tracker`, migrates the 7 existing observations from `data/debug_session/events.jsonl`, and upgrades `.TODO/Prompts` (`FOR AUDITS`) so agents ingest open observations automatically without manual copy-paste.

> **Prerequisite**: Complete `universal_debug_observation_connector_plan` in `skills/` first.

## Scenario Combinations Matrix

| Scenario | Command / Trigger | Expected Result |
| :--- | :--- | :--- |
| **Local Debug Session with DevTools HUD** | `python scripts/run_dashboard.py --local --debug` | Serves standardized DevTools HUD (`Pick Element`, `Record/Stop`, `Pause`, `Log Observation`) and isolates debug stored recordings. |
| **Migrate Existing 7 Observations** | `python scripts/debug_inspect.py --migrate-observations` | Imports existing `data/debug_session/events.jsonl` observations into `.diagnostics/observation_catalog.json` as `OBS-001..OBS-007` (`open`). |
| **Workspace Probe Open-Obs Alert** | `diagnose.py probe run debug_session` | Surfaces `open_observations_count` and reports non-silent attention status when open observations exist. |
| **Zero-Copy-Paste `FOR AUDITS` Run** | Prompt `FOR AUDITS` in `.TODO/Prompts` | Automatically reads `diagnose.py observations list --status open` and triages/links observations to plans. |

---

## Milestone 1: Adopt Shared Connector, Migrate 7 Observations & Isolate Debug Recordings
- [ ] **dashboard/services/debug_session.py**: Delegate observation persistence and catalog triage to `system-diagnostics`'s `observation_store.py` (with graceful standalone fallback) and isolate `STORED_RECORDINGS` directory under `data/debug_session/recordings/` when `IT_DEBUG_MODE=1` (resolving OBS #5).
- [ ] **dashboard/routers/system.py**: Wire `/api/system/debug/observation` and `/api/system/debug/hud.js` to the standardized connector & DevTools HUD asset (keeping routes `<= 25L`).
- [ ] **scripts/debug_inspect.py**: Add `--migrate-observations` one-shot import for existing `data/debug_session/events.jsonl` entries and default `--observations` to `open`/`triaged` items (`--all` for resolved).
- [ ] **tests/test_debug_observation_mode.py**: Verify connector delegation, debug recording isolation, migration idempotency, and open-only filtering using `tempfile.TemporaryDirectory()`.

**Verifier**: `python -m unittest tests/test_debug_session.py tests/test_debug_observation_mode.py`

---

## Milestone 2: Upgrade `debug_session` Probe & `.TODO/Prompts` (`FOR AUDITS`) *(Deferred to Next Turn / Milestone)*
- [ ] **.diagnostics/probes/debug_session.py**: Surface `open_observations_count` and return `status: "warn"` (with compact open `OBS-XXX` list) when open user observations exist so `FOR AUDITS` and `/app-debugger` never overlook them.
- [ ] **.TODO/Prompts**: Update `FOR AUDITS` to run `diagnose.py observations list --status open` in the parallel baseline batch, automatically populate User-Observed Findings from open `OBS-XXX` entries, and instruct agents to run `diagnose.py observations triage` / `resolve` when closing findings.
- [ ] **documentation/dashboard.rst**: Update Debug Mode docs with Pick Element, Record/Stop, Soft Pause, and `OBS-XXX` triage commands.

**Verifier**: `python -m unittest tests/test_debug_session.py tests/test_debug_observation_mode.py`
