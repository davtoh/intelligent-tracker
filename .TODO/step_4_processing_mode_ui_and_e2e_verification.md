# Step 4 Implementation Plan: Top-Bar Processing Mode Selector UI, Tab Visibility Auto-Sync & E2E Benchmark

> **Parent Master Plan**: `.TODO/performance_and_processing_modes_master_roadmap.md` (Step 4)
> **Architecture Blueprint**: `docs/architecture/IDEAL_WORLD_ARCHITECTURE.md`
> **Execution Scope**: Execute **one milestone per turn**. **Milestone 1** is the *Active Execution Target*; **Milestone 2** is *Deferred to the Next Turn*.

---

## 1. Pre-Plan Diagnostic Baseline (`diagnose.py arch-map` & `diagnose.py audit`)

Measured against workspace baseline before edits (`308` files, `56,573` lines, `110` FastAPI routes):
- `dashboard/static/index.html`: `178` lines (`OK < 180L` strict budget in `tests/test_step3_architecture_budgets.py`, `0` defects). Adding `<link rel="stylesheet" href="/static/css/processing_mode.css">`, `#processing-mode-pill` in `.header-right`, and `<script src="/static/js/processing_mode.js"></script>` requires removing redundant blank lines around `<header>`/`<main>`/`<aside>` so `index.html` stays at `~176` lines (`< 180L`).
- `dashboard/static/js/nav_tabs_manager.js`: `275` lines (`OK < 350L`, `0` defects). `emitTabLifecycle(prevTab, tabId)` (lines 51–58) already dispatches `CustomEvent('tab-changed')` and notifies `window.LivePlayer?.syncTabStreams?.(prevTab, tabId)`.
- `dashboard/static/js/live_player.js`: `175` lines (`OK < 350L`, `0` defects). `attachLiveStream(videoImg, activeCameraId, forceReconnect)` (lines 38–52) and `syncTabStreams(prevTab, activeTab)` (lines 84–108) manage active camera stream binding.
- `dashboard/routers/processing_mode.py` (`48L`) & `dashboard/services/processing_mode_service.py` (`197L`): Already expose `GET /api/system/processing-mode` and `POST /api/system/processing-mode` accepting `{ mode, focused_camera_id, active_tab }` and returning `ProcessingModeStatusResponse` (`mode`, `focused_camera_id`, `active_tab`, `valid_modes`, `deferred_jobs`, `camera_states`, `updated_at`).
- `dashboard/services/stream_worker.py`: `272` lines (`OK < 350L`). `diagnose.py arch-map` notes 5 re-exported helper imports from `dashboard.services.stream_telemetry`; declaring `__all__` in `stream_worker.py` during Milestone 2 clears the unused-import notice while preserving backward compatibility for Step 1 unit tests.

---

## 2. Public Surface Invariants & Modularity Budgets

### Public Contracts & DOM Surface
- **Header Selector Pill (`dashboard/static/index.html`)**:
  - Container `#processing-mode-pill.processing-mode-pill` placed inside `.header-right` immediately before `.telemetry-pill`.
  - Contains status indicator dot `#processing-mode-dot.processing-mode-dot`, accessible label, `<select id="processing-mode-select" class="processing-mode-select" aria-label="Processing Mode">` with 4 options (`focus_only` = `Focus Only`, `full_realtime` = `Full Real-Time`, `capture_only` = `Capture-Only`, `paused` = `Paused`), and deferred queue badge `#processing-mode-deferred-badge`.
- **Frontend Controller (`dashboard/static/js/processing_mode.js`)**:
  - Exposes `window.ProcessingModeUI` with `init()`, `setMode(mode, options)`, `syncTabChange(activeTab)`, `syncCameraFocus(cameraId)`, `fetchStatus()`, and `getState()`.
  - Persists operator-selected mode in `localStorage` under key `it_processing_mode` (defaulting to `'focus_only'`).
  - Synchronizes `mode`, `focused_camera_id`, and `active_tab` (`'live'`, `'studio'`, `'videos'`, etc., or `'background'` when `document.hidden === true`) to `POST /api/system/processing-mode`.
- **CSS & Layout Invariants (`dashboard/static/css/processing_mode.css`)**:
  - Zero `!important` declarations (`AGENTS.md` Rule 5).
  - WCAG AA touch target (`min-height: 32px`) on `#processing-mode-select`, explicit `gap: 8px` inside `.processing-mode-pill`, and defensive overflow containment (`min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap`).

### Modularity Guardrails
- `dashboard/static/index.html` MUST stay strictly `< 180` lines (`tests/test_step3_architecture_budgets.py`).
- `dashboard/static/js/processing_mode.js` MUST stay `< 220` lines with all functions `<= 35` lines.
- `dashboard/static/css/processing_mode.css` MUST stay `< 140` lines with zero `!important`.
- `dashboard/static/js/nav_tabs_manager.js` MUST stay `< 290` lines and `dashboard/static/js/live_player.js` MUST stay `< 195` lines, with all functions `<= 40` lines.
- Every unit test method MUST stay `<= 40` lines (`AGENTS.md` Rule 3).

---

## 3. Phased Implementation Milestones

### Milestone 1: Header Processing Mode Selector Pill, `localStorage` Persistence & Tab/Camera Focus Auto-Sync
- [x] **dashboard/static/css/processing_mode.css**: Create component stylesheet (`< 140L`, zero `!important`) styling `.processing-mode-pill`, `.processing-mode-dot` (`mode-focus_only`, `mode-full_realtime`, `mode-capture_only`, `mode-paused`), `.processing-mode-select` (`min-height: 32px`, `min-width: 0`, `text-overflow: ellipsis`), and `.processing-mode-deferred-badge`, and register `@import url("css/processing_mode.css");` in `dashboard/static/styles.css`.
- [x] **dashboard/static/js/processing_mode.js**: Create `window.ProcessingModeUI` (`< 220L`, functions `<= 35L`) managing `#processing-mode-select`, `localStorage` persistence (`it_processing_mode`), `GET`/`POST /api/system/processing-mode` synchronization, `tab-changed` and `visibilitychange` listeners, `#active-camera-select` focus listeners, and deferred indexing badge updates.
- [x] **dashboard/static/index.html**: Add `<link rel="stylesheet" href="/static/css/processing_mode.css">`, mount `#processing-mode-pill` inside `.header-right`, add `<script src="/static/js/processing_mode.js"></script>`, and compact blank lines so `index.html` remains strictly `< 180` lines (`~176L`).
- [x] **dashboard/static/js/nav_tabs_manager.js**: Notify `window.ProcessingModeUI?.syncTabChange?.(tabId.replace(/^tab-/, ''))` inside `emitTabLifecycle` (`< 290L`, functions `<= 35L`).
- [x] **dashboard/static/js/live_player.js**: Notify `window.ProcessingModeUI?.syncCameraFocus?.(camId)` inside `attachLiveStream` when the active camera changes (`< 195L`, functions `<= 35L`).
- [x] **tests/test_step4_processing_mode_ui.py**: Add unit, Node VM, and FastAPI `TestClient` tests (`<= 40L` per test method) verifying `ProcessingModeUI` initialization, `localStorage` persistence, `POST /api/system/processing-mode` sync on mode/tab/visibility/camera transitions, deferred badge rendering, static asset HTTP 200 delivery, zero `!important`, and `index.html < 180L`.
- [x] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 1 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step4_processing_mode_ui.py"
```

---

### Milestone 2: End-to-End Responsiveness, `arch-map` Clean-Up & Master Roadmap Sign-Off *(Deferred)*
- [x] **dashboard/services/stream_worker.py**: Define explicit `__all__` exporting `StreamWorker`, `build_stream_telemetry`, and re-exported telemetry helpers so `diagnose.py arch-map --path .` reports zero unused imports (`< 285L`, functions `<= 40L`).
- [x] **tests/test_step4_e2e_performance_and_modes.py**: Add end-to-end integration and budget verification tests (`<= 40L` per test method) verifying full mode lifecycle (`focus_only` -> `full_realtime` -> `capture_only` -> `paused`), `CameraPool` worker hibernation/vision state parity, `capture_only` deferred `VideoIndexer` job badge propagation, `< 200ms` control-plane latency, and strict Step 1–4 file/function modularity budgets.
- [x] **CHANGELOG.md**: Record milestone completion via 'python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" changelog add'

**Milestone 2 Verification Command**:
```bash
python -m unittest discover -s tests -p "test_step4_*.py"
```

---

## 4. Scenario Combinations Matrix

| Real-World Scenario / Objective | Mode / Inputs | Key Parameters | Exact Runnable Command |
| :--- | :--- | :--- | :--- |
| **Verify Header Processing Mode UI & Node VM Sync** | Milestone 1 Unit Tests | `test_step4_processing_mode_ui.py` | `python -m unittest discover -s tests -p "test_step4_processing_mode_ui.py"` |
| **Verify E2E Processing Modes & Performance Budgets** | Milestone 2 Integration Tests | `test_step4_e2e_performance_and_modes.py` | `python -m unittest discover -s tests -p "test_step4_e2e_performance_and_modes.py"` |
| **Verify All Step 4 Suites** | Full Step 4 Regression | `test_step4_*.py` | `python -m unittest discover -s tests -p "test_step4_*.py"` |
| **Audit Step 4 Files Against Modularity Budgets** | Static Auditor | `--max-lines 350 --max-fn-lines 40` | `python "<config_dir>/skills/system-diagnostics/scripts/diagnose.py" audit --path dashboard/static/index.html dashboard/static/js/processing_mode.js dashboard/static/css/processing_mode.css dashboard/static/js/nav_tabs_manager.js dashboard/static/js/live_player.js` |
| **Full Headless Regression Suite** | Unittest Runner | `MPLBACKEND=Agg` | `python -m unittest discover tests` |
| **Sphinx Documentation Build Check** | Documentation Verifier | `-W --keep-going` | `python -m sphinx -W --keep-going documentation/ documentation/_build/html/` |
