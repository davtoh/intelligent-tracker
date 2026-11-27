# Follow-Up Plan: Interactive User Debug Mode (Click Breadcrumbs & Observations HUD)

**Goal**: Extend the `IT_DEBUG_MODE=1` runtime in `dashboard/services/debug_session.py` (`f3b8a56`) so users navigating the dashboard page-by-page can automatically record click/route/fetch breadcrumbs and submit timestamped qualitative observations into `data/debug_session/events.jsonl`, correlated directly by `scripts/debug_inspect.py` and a workspace `diagnose.py probe`.

---

## Scenario Combinations Matrix

| Scenario | Mode (`IT_DEBUG_MODE`) | Expected Behavior | Verification |
|---|---|---|---|
| **Normal Production Run** | Unset / `0` | Debug HUD hidden; zero click/fetch overhead; `POST /api/system/debug/observation` returns `403` or `404` | `tests/test_debug_observation_mode.py` |
| **Debug Session Navigation** | `IT_DEBUG_MODE=1` | Client ring buffer (`<= 30` entries) captures tab switches, clicked selector/id/label, and failed `fetch()`/`window.onerror` events | `tests/test_debug_observation_mode.py` (Node VM) |
| **User Logs Observation** | `IT_DEBUG_MODE=1` | Clicking **Log Observation** sends `{note, tab, url, breadcrumbs, viewport}` to `POST /api/system/debug/observation` -> appended to `events.jsonl` | `tests/test_debug_observation_mode.py` |
| **Agent Audit Correlation** | Post-session | `scripts/debug_inspect.py --observations` and `diagnose.py probe run debug_session` output user observations alongside correlated backend tracebacks | `tests/test_debug_observation_mode.py` |

---

## Milestone 1: Backend Observation Endpoint & `debug_triage.py` Correlation

- [x] **dashboard/services/debug_session.py**: Add `record_user_observation(note, tab, url, breadcrumbs, viewport, debug_dir=None)` writing a structured `level="OBSERVATION"` event into `events.jsonl` (bounded breadcrumbs `<= 30`, sanitized note length).
- [x] **dashboard/services/debug_triage.py**: Update `summarize_debug_session()` to separate/surface recent `observations` alongside deduplicated `issues` so `WARNING`/`ERROR` counts remain unpolluted while exposing correlated time windows.
- [x] **dashboard/routers/system.py**: Add `POST /api/system/debug/observation` (guarded by `is_debug_mode()`) and expose `"debug_mode": is_debug_mode()` on `GET /api/system/debug/summary` (or `/status`).
- [x] **tests/test_debug_observation_mode.py**: Add FastAPI `TestClient` + temp `TRACKER_DEBUG_DIR` tests for enabled/disabled mode gating and `events.jsonl` persistence.
- [x] **Verification**: Run `python -m unittest tests/test_debug_session.py tests/test_debug_observation_mode.py` and `diagnose.py audit --path dashboard/services/debug_session.py dashboard/services/debug_triage.py dashboard/routers/system.py`.

## Milestone 2: Frontend `IT_DEBUG_MODE` Click Breadcrumbs & Observation HUD

- [x] **dashboard/static/js/debug_observation_hud.js** & **dashboard/static/index.html**: Create a lightweight `< 150L` self-initializing HUD module that probes `/api/system/debug/summary` (no-op when disabled), captures `click`, `hashchange`, `window.onerror`, and failed `fetch()` breadcrumbs in a `30`-item ring buffer, and renders a collapsible floating **Log Observation** pill.
- [x] **tests/test_debug_observation_mode.py**: Add Node.js `vm.runInNewContext` tests verifying ring-buffer cap, click/fetch breadcrumb capture, and `POST /api/system/debug/observation` payload.
- [x] **Verification**: Run `python -m unittest tests/test_debug_observation_mode.py` and `diagnose.py surface --verify --strict`.

## Milestone 3: CLI Inspector, Workspace Probe & Documentation

- [x] **scripts/debug_inspect.py** & **.diagnostics/probes/debug_session.py**: Add `--observations` view in `debug_inspect.py` and register a reusable `.diagnostics/probes/debug_session.py` probe (`diagnose.py probe run debug_session`) for `/app-debugger` sessions.
- [x] **documentation/dashboard.rst**: Document interactive Debug Observation Mode workflow (`scripts/server_debug` -> click & log observation -> `scripts/debug_inspect.py` / `diagnose.py probe run debug_session`).
- [x] **Verification**: Run `python -m unittest tests/test_debug_session.py tests/test_debug_observation_mode.py`, `diagnose.py probe list`, and `python -m sphinx -W --keep-going documentation/ documentation/_build/html/`.
